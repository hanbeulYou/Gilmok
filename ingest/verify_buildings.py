"""Collect, preserve, load, and verify the approved Gangnam building snapshot."""

import argparse
import fcntl
import hashlib
import json
import math
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import boto3
import duckdb
import pandas as pd

from ingest.building_footprints import (
    WfsClient,
    normalize_shp,
    normalize_wfs,
    read_shp_zip,
)
from ingest.building_register import (
    atomic_json,
    download,
    normalize_floors,
    normalize_titles,
    pnu_parts,
)
from ingest.buildings_database import load_snapshot
from ingest.common import ROOT, RawStore, Settings
from ingest.database import connect_database
from ingest.seoul_transit import read_frame, write_frame
from ingest.verify_transit import publish_verified


def footprint_bbox(frame):
    with duckdb.connect() as c:
        c.execute("LOAD spatial")
        c.register("raw", frame)
        shape = c.execute("""
          select min(ST_XMin(g)),min(ST_YMin(g)),max(ST_XMax(g)),max(ST_YMax(g)) from (
            select ST_Transform(ST_GeomFromWKB(source_geometry_wkb),'EPSG:5186','EPSG:4326',
                                always_xy:=true) g from raw)
        """).fetchone()
    with connect_database(local_only=True) as db:
        boundary = db.execute("""
          select extensions.ST_XMin(g),extensions.ST_YMin(g),
                 extensions.ST_XMax(g),extensions.ST_YMax(g)
          from (select extensions.ST_Extent(geom) g from public.admin_dongs
                where left(adm_cd,5)='11680') b
        """).fetchone()
    if any(v is None for v in boundary):
        raise ValueError("Verified Gangnam administrative boundaries are required")
    return (
        min(shape[0], boundary[0]) - 0.00001,
        min(shape[1], boundary[1]) - 0.00001,
        max(shape[2], boundary[2]) + 0.00001,
        max(shape[3], boundary[3]) + 0.00001,
    )


def prepare(args):
    raw, raw_path, manifest = read_shp_zip(args.shp_zip, args.directory)
    shp, shp_report = normalize_shp(raw)
    bbox = footprint_bbox(raw)
    features, wfs_report = WfsClient(args.directory / "wfs-pages", args.snapshot).collect(bbox)
    wfs, wfs_normalization = normalize_wfs(
        features, set(shp.gis_id), args.snapshot, args.directory / "wfs-original.parquet"
    )
    footprints = pd.concat([shp, wfs], ignore_index=True)
    write_frame(footprints, args.directory / "footprints-normalized.parquet")
    group_keys = ("sigunguCd", "bjdongCd", "platGbCd")
    tuples = sorted({tuple(pnu_parts(pnu)[k] for k in group_keys) for pnu in raw.A2})
    groups = [dict(zip(group_keys, values, strict=True)) for values in tuples]
    register_manifest = args.directory / "register-manifest.json"
    if register_manifest.exists():
        collected = json.loads(register_manifest.read_text())
        if collected.get("snapshot") != args.snapshot or collected.get("groups") != groups:
            raise ValueError("Register manifest differs; use a new snapshot directory")
    else:
        collected = download(groups, args.directory, args.snapshot)
    titles = normalize_titles(read_frame(Path(collected["titles"]["path"])))
    floors = normalize_floors(read_frame(Path(collected["floors"]["path"])))
    report = {
        "snapshot": args.snapshot,
        "shp": manifest | shp_report,
        "wfs": wfs_report | wfs_normalization,
        "register_collection": collected,
        "scope": "Gangnam public DB; complete Seoul SHP original preserved",
        "source_decision": "primary SHP; spatially missing WFS supplements without registers",
    }
    paths = {
        "gis_buildings_shp": raw_path,
        "vworld_building_footprints": args.directory / "wfs-original.parquet",
        "building_hub_titles": Path(collected["titles"]["path"]),
        "building_hub_floors": Path(collected["floors"]["path"]),
    }
    return footprints, titles, floors, report, paths


def verify_archive(store, result):
    digest = hashlib.sha256()
    settings = store.settings
    if settings.uses_r2:
        try:
            client = boto3.client(
                "s3",
                endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=settings.r2_access_key_id,
                aws_secret_access_key=settings.r2_secret_access_key,
                region_name="auto",
            )
            with client.get_object(Bucket=settings.r2_bucket, Key=result["key"])["Body"] as body:
                for chunk in iter(lambda: body.read(4 * 1024 * 1024), b""):
                    digest.update(chunk)
        except Exception:
            raise RuntimeError("R2 archive reread failed") from None
    else:
        with (settings.local_root / result["key"]).open("rb") as body:
            digest = hashlib.file_digest(body, "sha256")
    if digest.hexdigest() != result["sha256"]:
        raise ValueError("Original ZIP differs after publication")
    return result | {"reread_sha256_matches": True}


def measure(db):
    coordinates = db.execute("""
      select s.name,extensions.st_x(s.geom),extensions.st_y(s.geom)
      from public.transit_stops s where s.name in ('대치','한티','학여울') and exists (
        select 1 from public.admin_dongs d where d.name like '%%대치%%'
        and extensions.st_covers(d.geom,s.geom)) order by s.name
    """).fetchall()
    if len(coordinates) != 3:
        raise ValueError("Expected the three existing Daechi validation coordinates")
    query = (ROOT / "ingest/sql/buildings_radius.sql").read_text()
    result = {
        "warmups": 3,
        "repeats": 30,
        "measurements": [],
        "limitation": "Buildings RPC only; not the complete S1 score_inputs RPC",
        "postgres": db.execute("select version()").fetchone()[0],
        "postgis": db.execute("select extensions.postgis_full_version()").fetchone()[0],
    }
    for name, lng, lat in coordinates:
        for radius in (500, 1000):
            parameters = (lng, lat, radius)
            for _ in range(result["warmups"]):
                db.execute(query, parameters).fetchone()
            elapsed = []
            for _ in range(result["repeats"]):
                plan = db.execute("explain(analyze,format json) " + query, parameters).fetchone()[0]
                elapsed.append(plan[0]["Execution Time"])
            payload = db.execute(query, parameters).fetchone()[0]
            p95 = sorted(elapsed)[math.ceil(len(elapsed) * 0.95) - 1]
            if p95 >= 1000:
                raise ValueError("Buildings RPC DB p95 exceeds 1000ms")
            validate_payload(payload)
            result["measurements"].append(
                {
                    "name": name,
                    "lng": lng,
                    "lat": lat,
                    "radius_m": radius,
                    "db_p95_ms": p95,
                    "meta": payload["meta"],
                    "registry": payload["registry"],
                }
            )
    return result


def validate_payload(payload):
    props = [f["properties"] for f in payload["features"]]
    meta = payload["meta"]
    unknown = [p for p in props if p["height_source"] == "unknown"]
    if (
        len(props) != meta["total_buildings"]
        or len(unknown) != meta["unknown_buildings"]
        or any(p["height_m"] is not None or p["render_height_m"] != 4 for p in unknown)
        or any(not p["occlusion_included"] for p in props)
        or any(p["occlusion_height_m"] != p["render_height_m"] for p in props)
    ):
        raise ValueError("Building height/unknown/occlusion response contract differs")
    ratio = len(unknown) / len(props) if props else None
    if meta["unknown_ratio"] != ratio and (
        ratio is None or abs(meta["unknown_ratio"] - ratio) > 1e-12
    ):
        raise ValueError("Unknown confidence denominator differs from all occluders")
    if any(p["register_pk"] is not None for p in props if p["source"] == "vworld_wfs_supplement"):
        raise ValueError("Supplement leaked into the register join")


def measure_http(measurements):
    # CLI secrets stay in memory and are never written to reports or a second credential file.
    status = subprocess.run(
        ["supabase", "status", "-o", "json"], capture_output=True, text=True, check=True
    )
    settings = json.loads(status.stdout)
    base = settings["API_URL"]
    if urlparse(base).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Performance verification is local-only")
    for item in measurements:
        parameters = {k: item[k] for k in ("lng", "lat", "radius_m")}
        request = Request(
            base + "/rest/v1/rpc/buildings_in_radius",
            data=json.dumps(parameters).encode(),
            headers={
                "apikey": settings["ANON_KEY"],
                "Authorization": "Bearer " + settings["ANON_KEY"],
                "Content-Type": "application/json",
            },
        )
        started = time.perf_counter()
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
        item["http_roundtrip_ms"] = (time.perf_counter() - started) * 1000
        item["http_samples"] = 1
        validate_payload(payload)
        if payload["meta"] != item["meta"] or payload["registry"] != item["registry"]:
            raise ValueError("Anonymous HTTP RPC differs from verified SQL")


def storage(db):
    return dict(
        db.execute("""
      select 'database_bytes',pg_database_size(current_database()) union all
      select relname||'_total_bytes',pg_total_relation_size(oid)
        from pg_class where oid in ('public.buildings'::regclass,
          'public.building_registers'::regclass,'public.building_floors'::regclass) union all
      select relname||'_index_bytes',pg_indexes_size(oid)
        from pg_class where oid in ('public.buildings'::regclass,
          'public.building_registers'::regclass,'public.building_floors'::regclass)
    """).fetchall()
    )


def run(args):
    footprints, titles, floors, report, paths = prepare(args)
    with connect_database(local_only=True) as db:
        report["storage_before"] = storage(db)
    if args.load:
        store = RawStore(Settings.from_env())
        month = args.snapshot[:7]
        report["raw_store"] = "r2" if store.settings.uses_r2 else "local"
        report["publication"] = {
            name: publish_verified(store, name, month, path) for name, path in paths.items()
        }
        archive = store.publish_archive("gis_buildings_shp", month, args.shp_zip)
        report["publication"]["original_zip"] = verify_archive(store, archive)
        with connect_database(local_only=True) as db:
            report["database"] = load_snapshot(
                db,
                footprints,
                titles,
                floors,
                snapshot=args.snapshot,
                raw_objects=report["publication"],
            )
            for table in ("buildings", "building_registers", "building_floors"):
                db.execute(f"analyze public.{table}")
            report["queries"] = measure(db)
        with connect_database(local_only=True) as db:
            report["storage_after_commit"] = storage(db)
        measure_http(report["queries"]["measurements"])
    else:
        with connect_database(local_only=True) as db:
            report["quality"] = load_snapshot(
                db, footprints, titles, floors, snapshot=args.snapshot, raw_objects={}, load=False
            )
    report["local_artifact_bytes"] = sum(
        p.stat().st_size for p in args.directory.rglob("*") if p.is_file()
    )
    atomic_json(args.directory / "validation.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shp-zip", type=Path, required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--load", action="store_true", help="Publish originals and load local DB")
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    with (args.directory / "ingest.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run(args)
    print(
        json.dumps(
            {
                "report": str(args.directory / "validation.json"),
                "loaded": args.load,
                "source_rows": result["shp"]["original_rows"],
            }
        )
    )


if __name__ == "__main__":
    main()
