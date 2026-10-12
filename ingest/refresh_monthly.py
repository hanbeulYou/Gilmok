"""Publish monthly sources and their reference in one PostgreSQL commit."""

import argparse
import hashlib
import json
import time
from datetime import UTC, date, datetime
from pathlib import Path

from psycopg import InterfaceError, OperationalError, sql

from ingest.common import ROOT, RawStore, Settings
from ingest.refresh import (
    AUTO,
    TABLES,
    last_complete_month,
    maintain,
    month_end,
    promote,
    target_database,
)
from ingest.refresh_sources import prepare_source
from ingest.score_reference import collect_inputs, fingerprint, publish_reference, source_state


def atomic_promote(db, prepared, snapshot, reference_builder, *, expected_state):
    """Readers see the old pair until commit; any failure rolls back every loader.

    External collection is already complete. Keep ordinary SELECT available; never
    TRUNCATE/swap tables. Lock both data and provenance against concurrent loaders.
    """
    tables = sorted({t for source in TABLES.values() for t in source})
    with db.transaction():
        db.execute("set transaction isolation level repeatable read")
        db.execute("set local lock_timeout='5s'")
        db.execute("set local statement_timeout='15min'")
        db.execute(
            sql.SQL("lock table {} in share row exclusive mode").format(
                sql.SQL(",").join(sql.Identifier("public", t) for t in tables)
            )
        )
        db.execute(
            "lock table ingest_private.refresh_snapshots, "
            "ingest_private.place_snapshots, ingest_private.transit_coverage, "
            "ingest_private.building_snapshots, ingest_private.rent_snapshots "
            "in share row exclusive mode"
        )
        if fingerprint(source_state(db)) != expected_state:
            raise ValueError("Sources changed during preparation; retry entire monthly release")
        stages = []
        for source, (period_end, manifest, loader) in prepared.items():
            start = time.monotonic()
            changed = promote(db, source, period_end, snapshot, manifest, loader)
            stages.append(
                dict(source=source, changed=changed, seconds=round(time.monotonic() - start, 3))
            )
        start = time.monotonic()
        period_end, manifest, loader = reference_builder(db)
        promote(db, "score_reference", period_end, snapshot, manifest, loader)
        stages.append(dict(source="score_reference", seconds=round(time.monotonic() - start, 3)))
    return stages, manifest


def execute_monthly(
    sources, snapshot, factory, prepare, reference_builder, *, maintenance=maintain
):
    report = dict(snapshot=snapshot, sources=list(sources), committed=False, status="preparing")
    locks = []
    started = time.monotonic()
    try:
        with factory() as db:
            db.autocommit = True
            try:
                # Share the single-source lock namespace; stable ordering prevents deadlocks.
                for source in sorted((*sources, "score_reference")):
                    lock = (
                        int.from_bytes(hashlib.sha256(source.encode()).digest()[:4], "big") % 2**31
                    )
                    if not db.execute(
                        "select pg_try_advisory_lock(7412808,%s)", (lock,)
                    ).fetchone()[0]:
                        raise RuntimeError("Refresh already running")
                    locks.append(lock)
                baseline = fingerprint(source_state(db))
                existing = dict(
                    db.execute(
                        "select source,snapshot from ingest_private.refresh_snapshots "
                        "where source=any(%s)",
                        (list(sources) + ["score_reference"],),
                    ).fetchall()
                )
                if all(existing.get(s) == snapshot for s in (*sources, "score_reference")):
                    active = db.execute(
                        "select source_fingerprint from public.score_reference_sets "
                        "where preset_id='academy_v0'"
                    ).fetchone()
                    if not active or active[0] != baseline:
                        raise ValueError(
                            "Completed release no longer matches sources; use new snapshot"
                        )
                    report.update(committed=True, status="already_current")
                else:
                    prepared = {}
                    for source in sources:
                        report["phase"] = "prepare:" + source
                        prepared[source] = prepare(source, db)
                    report["preparation_seconds"] = round(time.monotonic() - started, 3)
                    report["phase"] = "atomic_promotion"
                    stages, manifest = atomic_promote(
                        db, prepared, snapshot, reference_builder, expected_state=baseline
                    )
                    report.update(
                        committed=True,
                        status="complete",
                        stages=stages,
                        reference_manifest=manifest,
                    )
                try:
                    report["phase"] = "maintenance"
                    maintenance(
                        factory,
                        tuple(
                            dict.fromkeys(
                                t
                                for source in (*sources, "score_reference")
                                for t in TABLES[source]
                            )
                        ),
                    )
                except Exception as error:
                    report.update(status="maintenance_failed", error_type=type(error).__name__)
            finally:
                for lock in reversed(locks):
                    db.execute("select pg_advisory_unlock(7412808,%s)", (lock,))
    except Exception as error:
        status = "finalization_failed" if report["committed"] else "refresh_failed"
        if not report["committed"] and report.get("phase") == "atomic_promotion" and isinstance(
            error, (OperationalError, InterfaceError)
        ):
            # A lost COMMIT acknowledgement is not proof of rollback. Resolve via snapshots.
            report["committed"] = None
            status = "commit_unknown"
        report.update(status=status, error_type=type(error).__name__)
    report["seconds"] = round(time.monotonic() - started, 3)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("all", *AUTO), default="all")
    parser.add_argument("--target", choices=("local", "remote"), default="local")
    parser.add_argument("--end-month", default=last_complete_month())
    parser.add_argument("--snapshot", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--directory", type=Path, default=ROOT / ".local/monthly")
    args = parser.parse_args()
    datetime.strptime(args.snapshot, "%Y%m%dT%H%M%SZ")
    if month_end(args.end_month) >= date.today().replace(day=1):
        parser.error("Only completed months may be refreshed")
    directory = args.directory / args.snapshot
    directory.mkdir(parents=True, exist_ok=True)
    store = RawStore(Settings.from_env())
    if args.target == "remote" and not store.settings.uses_r2:
        raise ValueError("Remote refresh requires persistent R2 storage")

    def prepare(source, db):
        folder = directory / source
        folder.mkdir(exist_ok=True)
        return prepare_source(
            argparse.Namespace(
                **(
                    vars(args)
                    | dict(
                        source=source,
                        directory=folder,
                        asset_manifest=None,
                        asset_manifest_key=None,
                        quarter=None,
                    )
                )
            ),
            store,
            db,
        )

    def reference(db):
        folder = directory / "score_reference"
        folder.mkdir(exist_ok=True)
        collected = collect_inputs(db, folder, uncommitted_refresh=True)
        return publish_reference(store, folder, args.snapshot, collected)

    report = execute_monthly(
        AUTO if args.source == "all" else (args.source,),
        args.snapshot,
        target_database(args.target),
        prepare,
        reference,
    )
    (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "reference_manifest"}))
    if report["status"] not in ("complete", "already_current"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
