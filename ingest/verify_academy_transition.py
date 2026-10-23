"""Isolated local G promotion, full-precision backups, spatial checks, and score inputs."""

import argparse
import gzip
import hashlib
import json
import math
import sqlite3
import time
from collections import Counter
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from statistics import median

import duckdb
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from ingest import academies, schools
from ingest.academy_display import load_display, prepare_display
from ingest.academy_layer_release import prepare_reviews, publish_layer_release
from ingest.academy_transition import local_connection, write_json
from ingest.commerce_education_database import load_snapshot
from ingest.common import ROOT, RawStore, Settings
from ingest.reference_release_guard import validate_reference_release
from ingest.refresh_monthly import execute_monthly
from ingest.score_reference import collect_inputs, fingerprint, publish_reference, source_state

BACKUP_TABLES = (
    "public.academies",
    "public.schools",
    "public.geocode_cache",
    "public.score_reference",
    "public.score_reference_sets",
    "ingest_private.place_snapshots",
    "ingest_private.refresh_snapshots",
    "ingest_private.ingest_runs",
    "app_private.academy_display",
    "app_private.academy_display_release",
    "app_private.academy_coordinate_reviews",
    "app_private.academy_layer_release",
)


@contextmanager
def isolated(url):
    if not conninfo_to_dict(url).get("dbname", "").startswith("gilmok_academy_transition_"):
        raise ValueError("Use a dedicated gilmok_academy_transition_ database")
    with local_connection(url) as db:
        yield db


def table_digest(db, table, destination=None):
    schema, name = table.split(".")
    query = sql.SQL(
        "copy (select * from {} t order by to_jsonb(t)::text) to stdout (format binary)"
    ).format(sql.Identifier(schema, name))
    digest = hashlib.sha256()
    size = 0
    stream_file = gzip.open(destination, "wb") if destination else None
    try:
        with db.cursor() as c, c.copy(query) as copy:
            for block in copy:
                digest.update(block)
                size += len(block)
                if stream_file:
                    stream_file.write(block)
    finally:
        if stream_file:
            stream_file.close()
    rows = db.execute(
        sql.SQL("select count(*) from {}").format(sql.Identifier(schema, name))
    ).fetchone()[0]
    return dict(table=table, rows=rows, binary_sha256=digest.hexdigest(), binary_bytes=size)


def backup(db, directory):
    folder = directory / "rollback"
    folder.mkdir(exist_ok=True)
    path = folder / "manifest.json"
    if path.exists():
        raise ValueError("Rollback manifest already exists; never overwrite baseline")
    report = dict(
        source_fingerprint=fingerprint(source_state(db)),
        tables=[],
        mode="local_only",
        cache_and_keys_deleted=False,
    )
    with db.transaction():
        for table in BACKUP_TABLES:
            file = folder / (table + ".bin.gz")
            row = table_digest(db, table, file)
            row.update(file=file.name, gzip_sha256=hashlib.sha256(file.read_bytes()).hexdigest())
            report["tables"].append(row)
    write_json(path, report)
    return report


def freeze_promotion(db, directory):
    """Freeze a canonical release, not an arbitrary rollback/test snapshot."""
    if db.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError("Promotion freeze needs its own read-only snapshot")
    with db.transaction():
        db.execute("set transaction isolation level repeatable read read only")
        verified = validate_reference_release(db)
        if verified["source_fingerprint"] != fingerprint(source_state(db)):
            raise ValueError("Reference release does not match current sources")
        report = backup(db, directory)
        report.update(purpose="promotion", reference_release=verified)
        write_json(directory / "rollback/manifest.json", report)
    return report


@contextmanager
def rollback_probe(db):
    """A local release probe can observe writes but may never leave test metadata."""
    if db.info.host not in {"127.0.0.1", "localhost", "::1"} or not db.info.dbname.startswith(
        "gilmok_academy_transition_"
    ):
        raise ValueError("Release probes require an isolated loopback transition database")
    if db.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError("Release probes require a fresh transaction")
    with db.transaction():
        before = {table: table_digest(db, table) for table in BACKUP_TABLES}
    try:
        with db.transaction(force_rollback=True):
            yield db
    finally:
        with db.transaction():
            after = {table: table_digest(db, table) for table in BACKUP_TABLES}
        if before != after:
            raise ValueError("Release probe left changes outside its rollback transaction")


def restore(db, directory):
    folder = directory / "rollback"
    manifest = json.loads((folder / "manifest.json").read_text())
    tables = {item["table"] for item in manifest["tables"]}
    if tables not in (set(BACKUP_TABLES), set(BACKUP_TABLES[:-2])):
        raise ValueError("Rollback table set differs from the fixed transition scope")
    for item in manifest["tables"]:
        if item["file"] != item["table"] + ".bin.gz":
            raise ValueError("Invalid rollback filename")
        if hashlib.sha256((folder / item["file"]).read_bytes()).hexdigest() != item["gzip_sha256"]:
            raise ValueError("Rollback artifact hash mismatch")
    with db.transaction():
        db.execute("set local lock_timeout='5s'")
        db.execute(
            sql.SQL("lock table {} in access exclusive mode").format(
                sql.SQL(",").join(sql.Identifier(*t.split(".")) for t in BACKUP_TABLES)
            )
        )
        # Legacy 10-table manifests predate the gate: restore sources with the gate closed.
        # New 12-table manifests restore exact release/review state as well.
        # Reference rows depend on the reference set. Existing sources are never dropped.
        for table in BACKUP_TABLES:
            db.execute(sql.SQL("delete from {}").format(sql.Identifier(*table.split("."))))
        order = sorted(manifest["tables"], key=lambda r: r["table"] == "public.score_reference")
        for item in order:
            with (
                db.cursor() as c,
                c.copy(
                    sql.SQL("copy {} from stdin (format binary)").format(
                        sql.Identifier(*item["table"].split("."))
                    )
                ) as copy,
            ):
                with gzip.open(folder / item["file"], "rb") as data:
                    while block := data.read(1024 * 1024):
                        copy.write(block)
        for item in manifest["tables"]:
            actual = table_digest(db, item["table"])
            if (actual["binary_sha256"], actual["rows"]) != (item["binary_sha256"], item["rows"]):
                raise ValueError("Rollback full-precision digest mismatch")
        if fingerprint(source_state(db)) != manifest["source_fingerprint"]:
            raise ValueError("Rollback source fingerprint mismatch")
    return dict(
        passed=True, table_count=len(order), source_fingerprint=manifest["source_fingerprint"]
    )


def prepare(directory, revision):
    inventory = json.loads((directory / "inventory.json").read_text())
    raw_manifest = {
        item["table"]: item for item in json.loads((directory / "raw-manifest.json").read_text())
    }
    with sqlite3.connect(f"file:{directory / 'journal.sqlite3'}?mode=ro", uri=True) as journal:
        outcomes = {
            address: json.loads(result)
            for address, result in journal.execute("select address,result from outcomes")
        }
    if set(inventory["addresses"]) != set(outcomes):
        raise ValueError("Recalculation incomplete; partial source promotion forbidden")
    result = {}
    for table, module in (("academies", academies), ("schools", schools)):
        raw_path = directory / "raw" / (table + ".parquet")
        if hashlib.sha256(raw_path.read_bytes()).hexdigest() != raw_manifest[table]["sha256"]:
            raise ValueError("Pinned raw file checksum mismatch")
        with duckdb.connect() as c:
            raw = c.read_parquet(str(raw_path)).df()
        frame = module.normalize(raw)
        if set(frame.id) != {r[0] for r in inventory["rows"][table]}:
            raise ValueError("Raw identities differ from pinned source inventory")
        version = {r[2] for r in inventory["rows"][table]}
        if len(version) != 1:
            raise ValueError("Mixed raw source versions require review")
        for key in ("lng", "lat", "geocode_reason"):
            frame[key] = None
        frame["geocode_provider"] = "juso"
        frame["geocode_failed"] = True
        for i, address in zip(frame.index, frame.address):
            value = outcomes[address]
            if value["status"] == "ready":
                frame.loc[i, ["lng", "lat", "geocode_failed"]] = [
                    value["location"]["lng"],
                    value["location"]["lat"],
                    False,
                ]
            else:
                frame.loc[i, "geocode_reason"] = value["status"]
        digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        result[table] = dict(
            frame=frame,
            version=version.pop(),
            raw_sha256=digest,
            source=module.SOURCE,
            display=prepare_display(raw, frame, revision, digest) if table == "academies" else None,
        )
    return result, outcomes


def load_cache(db, outcomes):
    """Replace only Juso rows in an isolated DB; existing Kakao/Vworld rows survive."""
    for address, value in outcomes.items():
        location = value.get("location", {})
        ready = value["status"] == "ready"
        db.execute(
            """insert into public.geocode_cache
            (address,provider,geom,geocode_failed,failure_reason,source,source_version,provenance)
            values(%s,'juso',case when %s then extensions.st_setsrid(
              extensions.st_makepoint(%s,%s),4326) else null end,%s,%s,'juso_address',%s,%s)
            on conflict(address,provider) do update set geom=excluded.geom,
            geocode_failed=excluded.geocode_failed,failure_reason=excluded.failure_reason,
            source=excluded.source,source_version=excluded.source_version,provenance=excluded.provenance
            """,
            (
                address,
                ready,
                location.get("lng"),
                location.get("lat"),
                not ready,
                None if ready else value["status"],
                date.today().isoformat(),
                Jsonb(
                    dict(
                        coordinate_policy="juso_only",
                        selection=value.get("selection"),
                        location=location,
                        source="local_transition_journal",
                    )
                ),
            ),
        )


def promote_local(url, directory, revision, *, reviews_path=None, review_version=None):
    if reviews_path is None or not review_version:
        raise ValueError("G promotion requires a pinned quality review manifest/version")
    frames, outcomes = prepare(directory, revision)
    reviews = prepare_reviews(
        reviews_path,
        version=review_version,
        sources={table: (revision, data["raw_sha256"]) for table, data in frames.items()},
    )
    raw_manifest = {
        r["table"]: r for r in json.loads((directory / "raw-manifest.json").read_text())
    }

    def prepare_source(table, db):
        data = frames[table]
        manifest = dict(
            snapshot=revision, raw_sha256=data["raw_sha256"], provider="juso", local_only=True
        )
        manifest["academy_layer_review"] = dict(
            version=review_version,
            sha256=hashlib.sha256(reviews_path.read_bytes()).hexdigest(),
            rows=len(reviews),
        )

        def loader(db):
            if table == "academies":
                load_cache(db, outcomes)
            load_snapshot(
                db,
                table,
                data["frame"],
                source=data["source"],
                version=data["version"],
                raw_key=raw_manifest[table]["key"],
                report=manifest,
            )
            if table == "academies":
                load_display(
                    db,
                    data["display"],
                    revision=revision,
                    version=data["version"],
                    raw_sha256=data["raw_sha256"],
                )

        return date.today(), manifest, loader

    def reference(db):
        folder = directory / "reference"
        folder.mkdir(exist_ok=False)
        collected = collect_inputs(db, folder, uncommitted_refresh=True)
        store = RawStore(Settings(local_root=(directory / "objects").resolve()))
        return publish_reference(store, folder, revision, collected)

    report = execute_monthly(
        ("academies", "schools"),
        revision,
        lambda: isolated(url),
        prepare_source,
        reference,
        maintenance=lambda *_: None,
        release_loader=lambda db: publish_layer_release(db, reviews, review_version=review_version),
    )
    write_json(directory / "promotion.json", report)
    if not report.get("committed"):
        raise ValueError("Local source/display/reference promotion failed; inspect report")
    return report


def capture_scores(db, directory, label):
    if label == "after":
        verify_preserved_cache(db, directory)
    with gzip.open(ROOT / "tests/scoring/fixtures/v040-inputs.json.gz", "rt") as file:
        cases = json.load(file)["cases"]
    reference = db.execute(
        "select public.score_reference_distribution('academy_v0',800)"
    ).fetchone()[0]
    for case in cases:
        p = case["candidate"]
        args = (p["lat"], p["lng"], p["floor"], p.get("address"))
        for key, radius in (("primary", 800), ("school", 1000)):
            case[key] = db.execute(
                f"select public.score_inputs(%s,%s,{radius},%s,%s)", args
            ).fetchone()[0]
        case["scene"] = db.execute(
            "select public.exposure_inputs_v022(lat=>%s,lng=>%s)", args[:2]
        ).fetchone()[0] | {"floor": p["floor"]}
        case["reference"] = reference
    with gzip.open(directory / f"{label}-inputs.json.gz", "wt") as file:
        json.dump(cases, file, ensure_ascii=False)


def verify_preserved_cache(db, directory):
    """Compare non-Juso cache bytes with the immutable rollback copy before rollback."""
    db.execute("create temp table g_cache_before (like public.geocode_cache) on commit drop")
    with (
        db.cursor() as cursor,
        cursor.copy("copy g_cache_before from stdin (format binary)") as copy,
    ):
        with gzip.open(directory / "rollback/public.geocode_cache.bin.gz", "rb") as source:
            while block := source.read(1024 * 1024):
                copy.write(block)
    db.execute("""create temp view g_cache_kept_before as
        select * from g_cache_before where provider in ('kakao','vworld');
        create temp view g_cache_kept_after as
        select * from public.geocode_cache where provider in ('kakao','vworld')""")
    before = table_digest(db, "pg_temp.g_cache_kept_before")
    after = table_digest(db, "pg_temp.g_cache_kept_after")
    equal = before["rows"] == after["rows"] and before["binary_sha256"] == after["binary_sha256"]
    if not equal:
        raise ValueError("Existing Kakao/Vworld cache changed")
    write_json(directory / "preserved-cache.json", dict(passed=True, before=before, after=after))


def spatial(db, directory):
    """Read-only spatial comparison against pinned old rows, not modified display coordinates."""
    inventory = json.loads((directory / "inventory.json").read_text())
    _, outcomes = prepare(directory, "spatial-verification")
    rows = []
    start = time.monotonic()
    for table, originals in inventory["rows"].items():
        for identity, address, _version, _provider, _failed, old_lng, old_lat in originals:
            value = outcomes[address]
            record = dict(table=table, id=identity, status=value["status"])
            if value["status"] == "ready":
                location = value["location"]
                result = db.execute(
                    """with point as (select extensions.st_setsrid(
                    extensions.st_makepoint(%s,%s),4326) p), footprint as
                    (select extensions.st_unaryunion(extensions.st_collect(geom)) g
                     from public.buildings where pnu=%s)
                    select case when %s::float8 is null then null else extensions.st_distance(
                      p::extensions.geography,extensions.st_setsrid(
                      extensions.st_makepoint(%s,%s),4326)::extensions.geography) end,
                    g is not null, case when g is null then null else extensions.st_covers(g,p) end,
                    case when g is null then null else extensions.st_distance(
                      g::extensions.geography,p::extensions.geography) end,
                    exists(select 1 from public.admin_dongs where extensions.st_covers(geom,p))
                    from point,footprint""",
                    (
                        location["lng"],
                        location["lat"],
                        value["selection"]["pnu"],
                        old_lng,
                        old_lng,
                        old_lat,
                    ),
                ).fetchone()
                record.update(
                    move_m=result[0],
                    footprint_available=result[1],
                    inside_pnu_footprint=result[2],
                    footprint_distance_m=result[3],
                    inside_seoul=result[4],
                )
            rows.append(record)
    with gzip.open(directory / "spatial-rows.json.gz", "wt") as file:
        json.dump(rows, file)
    summary = {}
    for table in ("academies", "schools"):
        items = [r for r in rows if r["table"] == table]
        ready = [r for r in items if r["status"] == "ready"]
        distances = sorted(r["move_m"] for r in ready if r["move_m"] is not None)
        summary[table] = dict(
            total=len(items),
            ready=len(ready),
            unlocated=len(items) - len(ready),
            statuses=dict(Counter(r["status"] for r in items)),
            footprint_available=sum(r["footprint_available"] for r in ready),
            inside_pnu_footprint=sum(r["inside_pnu_footprint"] is True for r in ready),
            outside_pnu_footprint=sum(r["inside_pnu_footprint"] is False for r in ready),
            footprint_unavailable=sum(not r["footprint_available"] for r in ready),
            outside_seoul=sum(not r["inside_seoul"] for r in ready),
            move_m_max=max(distances, default=None),
            move_m_median=median(distances) if distances else None,
            move_m_p95=distances[math.ceil(len(distances) * 0.95) - 1] if distances else None,
            move_not_comparable=len(ready) - len(distances),
            move_over_50m=sum(d > 50 for d in distances),
            move_over_100m=sum(d > 100 for d in distances),
            move_over_500m=sum(d > 500 for d in distances),
        )
    report = dict(
        tables=summary,
        seconds=round(time.monotonic() - start, 3),
        outside_footprint_policy="review_only_no_snapping_local_impact_uses_provider_point",
    )
    write_json(directory / "spatial-summary.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage", choices=("backup", "freeze", "before", "spatial", "promote", "after", "rollback")
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--revision", default="20261012T150643Z")
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--review-version")
    args = parser.parse_args()
    if args.stage == "promote":
        report = promote_local(
            args.database_url,
            args.directory,
            args.revision,
            reviews_path=args.reviews,
            review_version=args.review_version,
        )
    else:
        with isolated(args.database_url) as db:
            if args.stage in ("before", "after"):
                capture_scores(db, args.directory, args.stage)
                report = dict(stage=args.stage, cases=10)
            elif args.stage == "backup":
                report = backup(db, args.directory)
            elif args.stage == "freeze":
                report = freeze_promotion(db, args.directory)
            elif args.stage == "spatial":
                report = spatial(db, args.directory)
            else:
                report = restore(db, args.directory)
                write_json(args.directory / "rollback-result.json", report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
