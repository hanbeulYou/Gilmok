"""Freeze R2 source bytes before any remote database write."""

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import boto3
import duckdb

from ingest.common import ROOT, RawStore, Settings
from ingest.refresh_sources import restore_object

SOURCES = {
    "admin_boundaries", "population_grid", "resident_population", "living_population",
    "legal_boundaries", "bus_stops", "bus_boardings", "subway_stops", "subway_boardings",
    "stores", "academies", "schools", "gis_buildings_shp", "vworld_building_footprints",
    "building_hub_titles", "building_hub_floors", "commercial_trades", "rent_survey",
    "rent_survey_scope", "score_reference", "score_reference_inputs", "score_reference_manifest",
}
REFERENCE_SNAPSHOT = "20260923T111436Z"


def sha256(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def selected(key):
    parts = key.split("/")
    return (len(parts) >= 3 and parts[0] == "raw" and parts[1] in SOURCES
            and key.endswith(".parquet") and ".." not in parts
            and (not parts[1].startswith("score_reference") or REFERENCE_SNAPSHOT in parts))


def cached_object(store, entry, directory):
    key = entry["key"]
    if not key.startswith("raw/") or ".." in key.split("/") or "\\" in key:
        raise ValueError("Invalid restore object key")
    path = directory / key
    if path.exists() and sha256(path) == entry["sha256"]:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".download")
    restore_object(store, key, temporary, entry["sha256"])
    temporary.replace(path)
    return path


def prepare(directory, store):
    if not store.settings.uses_r2:
        raise ValueError("Remote restore preparation requires R2 originals")
    s = store.settings
    client = boto3.client("s3", endpoint_url=f"https://{s.r2_account_id}.r2.cloudflarestorage.com",
                          aws_access_key_id=s.r2_access_key_id,
                          aws_secret_access_key=s.r2_secret_access_key)
    entries = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=s.r2_bucket, Prefix="raw/"):
        for obj in page.get("Contents", []):
            if selected(obj["Key"]):
                header = client.head_object(Bucket=s.r2_bucket, Key=obj["Key"])
                digest = header["Metadata"].get("sha256")
                if not digest or len(digest) != 64:
                    raise ValueError("R2 object missing publisher SHA256: " + obj["Key"])
                entries.append(dict(key=obj["Key"], bytes=obj["Size"], sha256=digest))
    if {e["key"].split("/")[1] for e in entries} != SOURCES:
        raise ValueError("Incomplete R2 source inventory")

    def inspect(entry):
        path = cached_object(store, entry, directory)
        with duckdb.connect() as db:
            relation = db.read_parquet(str(path))
            return {**entry, "rows": relation.count("*").fetchone()[0],
                    "columns": relation.columns}

    with ThreadPoolExecutor(max_workers=3) as pool:
        objects = list(pool.map(inspect, sorted(entries, key=lambda e: e["key"])))
    manifest = dict(version=1, prepared_at=datetime.now(UTC).isoformat(),
                    reference_snapshot=REFERENCE_SNAPSHOT, objects=objects,
                    source_bytes=sum(e["bytes"] for e in objects))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "source-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / ".local/restore/s3-1")
    parser.add_argument("--publish-supplements", action="store_true",
                        help="Publish public provenance and verified baselines to R2")
    args = parser.parse_args()
    store = RawStore(Settings.from_env())
    existing = args.directory / "restore-manifest.json"
    result = (json.loads(existing.read_text()) if existing.exists()
              else prepare(args.directory, store))
    if args.publish_supplements:
        from ingest.restore_provenance import (
            prepare_geometry_baseline,
            prepare_living_baseline,
            prepare_supplements,
        )

        result = prepare_supplements(args.directory, store, result)
        result = prepare_living_baseline(args.directory, store, result)
        result = prepare_geometry_baseline(args.directory, store, result)
    print(json.dumps(dict(objects=len(result["objects"]), source_bytes=result["source_bytes"])))
