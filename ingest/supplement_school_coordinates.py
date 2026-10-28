"""Approved #39 local school supplement; never replaces a located Juso point."""

import argparse
import hashlib
import json
import math
import re
import subprocess
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
from psycopg.types.json import Jsonb

from ingest.academy_layer_release import prepare_reviews, publish_layer_release
from ingest.academy_transition import write_json
from ingest.common import RawStore, Settings
from ingest.refresh_monthly import execute_monthly
from ingest.score_reference import collect_inputs, publish_reference
from ingest.verify_academy_transition import (
    backup,
    capture_scores,
    isolated,
    table_digest,
)

PROVIDER = "edu_facility_standard"
PENDING = "coordinate_verification_pending:"


def require_node_version(version):
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", version.strip())
    if not match or int(match[1]) != 22 or int(match[2]) < 12:
        raise ValueError("Use package.json Node >=22.12 <23 before rebuilding references")


def build_plan(rows):
    """Conservative name/level/address join from review_school_locations output."""
    ids = [r["neis_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate NEIS identity")
    fills, holds = [], []
    standard_ids = set()
    for row in rows:
        if row["status"] != "address_match":
            continue
        source = row["standard"]
        if source["SCHOOL_ID"] in standard_ids:
            raise ValueError("School crosswalk must be one-to-one")
        standard_ids.add(source["SCHOOL_ID"])
        lng, lat = float(source["LONGITUDE"]), float(source["LATITUDE"])
        if not (
            math.isfinite(lng) and math.isfinite(lat) and 124 <= lng <= 132 and 33 <= lat <= 39
        ):
            raise ValueError("Invalid degree coordinate")
        item = dict(
            id=row["neis_id"],
            name=row["name"],
            standard_id=source["SCHOOL_ID"],
            lng=lng,
            lat=lat,
            source_date=source["REFERENCE_DATE"],
        )
        if row["juso_status"] != "ready":
            if row.get("inside_seoul") is True:
                fills.append(item)
        elif row.get("inside_seoul") is False:
            holds.append(dict(item, reason=PENDING + "standard_outside_seoul"))
        elif row.get("distance_m", 0) > 500:
            holds.append(dict(item, reason=PENDING + "standard_juso_distance_gt_500m"))
    return dict(fills=fills, holds=holds)


def apply_plan(db, plan, report):
    """Existing provider/reason columns only; transaction belongs to monthly runner."""
    preserved = db.execute("""select id,encode(extensions.st_asewkb(geom),'hex')
        from public.schools where geocode_provider='juso' and geom is not null
        order by id""").fetchall()
    for item in plan["fills"]:
        row = db.execute(
            """select name,geom is null,geocode_provider,
            extensions.st_x(geom),extensions.st_y(geom) from public.schools
            where id=%s for update""",
            (item["id"],),
        ).fetchone()
        if row is None or row[0] != item["name"]:
            raise ValueError("School identity changed since review")
        if not row[1]:
            if row[2:] == (PROVIDER, item["lng"], item["lat"]):
                continue  # exact already-applied supplement only
            raise ValueError("Refusing to replace a located school")
        db.execute(
            """update public.schools set
            geom=extensions.st_setsrid(extensions.st_makepoint(%s,%s),4326),
            geocode_failed=false,geocode_provider=%s,geocode_reason=null,
            ingested_at=now() where id=%s""",
            (item["lng"], item["lat"], PROVIDER, item["id"]),
        )
    for item in plan["holds"]:
        row = db.execute(
            """select name,geocode_provider,geom is not null,geocode_reason
            from public.schools where id=%s for update""",
            (item["id"],),
        ).fetchone()
        if row is None or row[:3] != (item["name"], "juso", True):
            raise ValueError("Held school must retain its located Juso point")
        if row[3] not in (None, item["reason"]):
            raise ValueError("Do not overwrite another coordinate review reason")
        db.execute(
            """update public.schools set geocode_reason=%s
            where id=%s and geocode_reason is distinct from %s""",
            (item["reason"], item["id"], item["reason"]),
        )
    after = db.execute("""select id,encode(extensions.st_asewkb(geom),'hex')
        from public.schools where geocode_provider='juso' and geom is not null
        order by id""").fetchall()
    if after != preserved:
        raise ValueError("Juso coordinates changed")
    # Keep the NEIS roster raw_key/version; attach coordinate file provenance separately.
    db.execute(
        """update ingest_private.place_snapshots set
        located_count=(select count(*) from public.schools where geom is not null),
        report=report || jsonb_build_object('school_coordinate_supplement',%s::jsonb),
        ingested_at=now() where target_table='schools'""",
        (Jsonb(report),),
    )


def run(url, rows_path, raw_directory, output, revision, *, reviews_path, review_version):
    # The raw bridge calls node directly, outside pnpm's engines check.
    require_node_version(subprocess.check_output(["node", "--version"], text=True))
    # The only connection factory rejects remote hosts and non-isolated DB names.
    with isolated(url) as db:
        academy = db.execute(
            "select source_revision,raw_sha256 from app_private.academy_display_release"
            " where singleton"
        ).fetchone()
        school = db.execute(
            "select report from ingest_private.place_snapshots where target_table='schools'"
        ).fetchone()[0]
        if not academy:
            raise ValueError("G academy display release required")
        reviews = prepare_reviews(
            reviews_path,
            version=review_version,
            sources={"academies": academy, "schools": (school["snapshot"], school["raw_sha256"])},
        )
    if output.exists():
        raise ValueError("Use a fresh output directory; preserve previous manifests")
    rows = json.loads(rows_path.read_text())
    plan = build_plan(rows)
    if len(rows) != 1320 or len(plan["fills"]) != 73 or len(plan["holds"]) != 3:
        raise ValueError("Approved 1320 / 73 / 3 inventory changed; review first")
    output.mkdir(parents=True)
    files = [
        dict(file=p.name, sha256=hashlib.sha256(p.read_bytes()).hexdigest())
        for p in sorted(raw_directory.glob("standard-page-*.json"))
    ]
    if len(files) != 2:
        raise ValueError("Expected both official download pages")
    # Validate the review coordinates against those exact downloaded source rows.
    raw = {
        r["SCHOOL_ID"]: r
        for p in sorted(raw_directory.glob("standard-page-*.json"))
        for r in json.loads(p.read_text())
    }
    for item in plan["fills"] + plan["holds"]:
        source = raw[item["standard_id"]]
        if (float(source["LONGITUDE"]), float(source["LATITUDE"]), source["REFERENCE_DATE"]) != (
            item["lng"],
            item["lat"],
            item["source_date"],
        ):
            raise ValueError("Review differs from official download")
    report = dict(
        snapshot=revision,
        local_only=True,
        crs="EPSG:4326",
        crs_basis="user_approved_1229_school_comparison_not_metadata_declaration",
        provider=PROVIDER,
        files=files,
        plan=plan,
        academy_layer_review=dict(
            version=review_version,
            sha256=hashlib.sha256(reviews_path.read_bytes()).hexdigest(),
            rows=len(reviews),
        ),
    )
    write_json(output / "plan.json", report)
    before = output / "before"
    before.mkdir()
    with isolated(url) as db:
        counts = db.execute("""select count(*),count(geom),
            count(*) filter(where geocode_provider='juso' and geom is not null)
            from public.schools""").fetchone()
        if counts != (1320, 1241, 1241):
            raise ValueError("Start from approved Juso-only G baseline")
        backup(db, before)
        capture_scores(db, output, "before")

    def prepare(source, db):
        assert source == "schools"
        return date.today(), report, lambda connection: apply_plan(connection, plan, report)

    def fail_reference(db):
        raise RuntimeError("forced_reference_failure_after_school_updates")

    failure = execute_monthly(
        ("schools",),
        revision,
        lambda: isolated(url),
        prepare,
        fail_reference,
        maintenance=lambda *_: None,
        release_loader=lambda db: publish_layer_release(db, reviews, review_version=review_version),
    )
    write_json(output / "forced-failure.json", failure)
    if failure["committed"]:
        raise AssertionError("Forced reference failure committed")
    expected = json.loads((before / "rollback/manifest.json").read_text())
    with isolated(url) as db:
        for item in expected["tables"]:
            assert table_digest(db, item["table"])["binary_sha256"] == item["binary_sha256"]

    def reference(db):
        folder = output / "reference"
        folder.mkdir()
        collected = collect_inputs(db, folder, uncommitted_refresh=True)
        store = RawStore(Settings(local_root=(output / "objects").resolve()))
        return publish_reference(store, folder, revision, collected)

    result = execute_monthly(
        ("schools",),
        revision,
        lambda: isolated(url),
        prepare,
        reference,
        maintenance=lambda *_: None,
        release_loader=lambda db: publish_layer_release(db, reviews, review_version=review_version),
    )
    write_json(output / "promotion.json", result)
    if not result["committed"]:
        raise ValueError("School/source reference transaction failed; inspect report")
    after = output / "after"
    after.mkdir()
    with isolated(url) as db:
        backup(db, after)
        # Generic G's "after" label expects a root-level rollback folder. Here
        # before/after each own a manifest; cache preservation is checked by digest.
        capture_scores(db, output, "supplemented")
        (output / "supplemented-inputs.json.gz").rename(output / "after-inputs.json.gz")
        records = db.execute("""select to_jsonb(s)-'geom' || jsonb_build_object(
            'lng',extensions.st_x(geom),'lat',extensions.st_y(geom))
            from public.schools s order by id""").fetchall()
    frame = pd.DataFrame([r[0] for r in records])
    with duckdb.connect() as connection:
        connection.from_df(frame).write_parquet(str(output / "schools.parquet"))
    write_json(
        output / "snapshot.json",
        dict(
            report,
            raw_school_snapshot=dict(
                file="schools.parquet",
                rows=len(frame),
                sha256=hashlib.sha256((output / "schools.parquet").read_bytes()).hexdigest(),
            ),
            rollback_before="before/rollback/manifest.json",
            rollback_after="after/rollback/manifest.json",
        ),
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--raw-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--review-version", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.database_url,
                args.rows,
                args.raw_directory,
                args.output,
                args.revision,
                reviews_path=args.reviews,
                review_version=args.review_version,
            ),
            ensure_ascii=False,
            default=str,
        )
    )
