"""Isolated local G promotion, full-precision backups, spatial checks, and score inputs."""

import argparse
import gzip
import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import duckdb
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from ingest import academies, schools
from ingest.academy_display import load_display, prepare_display
from ingest.academy_transition import local_connection, write_json
from ingest.commerce_education_database import load_snapshot
from ingest.common import ROOT, RawStore, Settings
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


def restore(db, directory):
    folder = directory / "rollback"
    manifest = json.loads((folder / "manifest.json").read_text())
    if {item["table"] for item in manifest["tables"]} != set(BACKUP_TABLES):
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


def promote_local(url, directory, revision):
    frames, outcomes = prepare(directory, revision)
    raw_manifest = {
        r["table"]: r for r in json.loads((directory / "raw-manifest.json").read_text())
    }

    def prepare_source(table, db):
        data = frames[table]
        manifest = dict(
            snapshot=revision, raw_sha256=data["raw_sha256"], provider="juso", local_only=True
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
    )
    write_json(directory / "promotion.json", report)
    if not report.get("committed"):
        raise ValueError("Local source/display/reference promotion failed; inspect report")
    return report


def capture_scores(db, directory, label):
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
            footprint_available=sum(r["footprint_available"] for r in ready),
            inside_pnu_footprint=sum(r["inside_pnu_footprint"] is True for r in ready),
            outside_pnu_footprint=sum(r["inside_pnu_footprint"] is False for r in ready),
            outside_seoul=sum(not r["inside_seoul"] for r in ready),
            move_m_max=max(distances, default=None),
            move_m_median=distances[len(distances) // 2] if distances else None,
            move_over_50m=sum(d > 50 for d in distances),
            move_over_100m=sum(d > 100 for d in distances),
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
        "stage", choices=("backup", "before", "spatial", "promote", "after", "rollback")
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--revision", default="20261012T150643Z")
    args = parser.parse_args()
    if args.stage == "promote":
        report = promote_local(args.database_url, args.directory, args.revision)
    else:
        with isolated(args.database_url) as db:
            if args.stage in ("before", "after"):
                capture_scores(db, args.directory, args.stage)
                report = dict(stage=args.stage, cases=10)
            elif args.stage == "backup":
                report = backup(db, args.directory)
            elif args.stage == "spatial":
                report = spatial(db, args.directory)
            else:
                report = restore(db, args.directory)
                write_json(args.directory / "rollback-result.json", report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
