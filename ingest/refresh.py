"""Scheduled/manual refresh; immutable preparation, atomic promotion, separate maintenance."""

import argparse
import calendar
import hashlib
import json
import os
import re
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

from dotenv import dotenv_values
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from ingest.common import ROOT, RawStore, Settings
from ingest.database import connect_database

AUTO = ("living", "transit", "academies", "schools", "population", "trades")
MANUAL = ("stores", "buildings", "rent")
TABLES = {
    "score_reference": ("score_reference", "score_reference_sets"),
    "living": ("living_pop",),
    "transit": ("transit_stops", "transit_boardings"),
    "academies": ("academies",),
    "schools": ("schools",),
    "population": ("population_age",),
    "trades": ("legal_dongs", "commercial_trade_stats"),
    "stores": ("stores",),
    "buildings": ("buildings", "building_registers", "building_floors"),
    "rent": ("rent_areas", "rent_survey"),
}


def month_window(end_month, count):
    end = datetime.strptime(end_month, "%Y-%m").date()
    if end.strftime("%Y-%m") != end_month:
        raise ValueError("Expected YYYY-MM")
    last = end.year * 12 + end.month - 1
    return [f"{n // 12:04d}-{n % 12 + 1:02d}" for n in range(last - count + 1, last + 1)]


def month_end(month):
    d = datetime.strptime(month, "%Y-%m").date()
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def last_complete_month(today=None):
    today = today or date.today()
    return month_window(today.strftime("%Y-%m"), 2)[0]


@contextmanager
def target_database(target="local"):
    if target not in ("local", "remote"):
        raise ValueError("Explicit local or remote target required")
    if target == "remote":
        env = {**dotenv_values(ROOT / ".env"), **os.environ}
        if env.get("INGEST_REMOTE_ENABLED") != "true" or not env.get("SUPABASE_DB_URL"):
            raise ValueError("Remote ingest requires explicit activation and DB URL")
        info = conninfo_to_dict(env["SUPABASE_DB_URL"])
        ref = env.get("SUPABASE_PROJECT_REF", "")
        host, user = info.get("host", ""), info.get("user", "")
        direct = host == f"db.{ref}.supabase.co"
        pool = host.endswith(".pooler.supabase.com") and user == f"postgres.{ref}"
        if not re.fullmatch(r"[a-z0-9]{20}", ref) or not (direct or pool):
            raise ValueError("Remote DB must match the configured project")
        if info.get("sslmode") not in ("require", "verify-ca", "verify-full"):
            raise ValueError("Remote ingest requires TLS")
        if pool and info.get("port", "5432") != "5432":
            raise ValueError("Use session pooler, not transaction pooler")
    with connect_database(local_only=target == "local") as db:
        yield db


def maintain(factory, tables):
    # A failed VACUUM cannot roll back an already committed refresh.
    with factory() as db:
        db.autocommit = True
        db.execute("set lock_timeout='5s'")
        db.execute("set statement_timeout='15min'")
        for table in tables:
            db.execute(sql.SQL("vacuum (analyze) public.{}").format(sql.Identifier(table)))


def promote(db, source, period_end, snapshot, manifest, loader):
    with db.transaction():
        lock = int.from_bytes(hashlib.sha256(source.encode()).digest()[:4], "big") % 2**31
        db.execute("select pg_advisory_xact_lock(7412808,%s)", (lock,))
        previous = db.execute(
            "select period_end,snapshot from ingest_private.refresh_snapshots "
            "where source=%s for update",
            (source,),
        ).fetchone()
        if previous and (period_end, snapshot) < previous:
            raise ValueError("Stale refresh cannot replace a newer snapshot")
        if previous == (period_end, snapshot):
            return False
        baseline_sql = {
            "living": "select max(period_end) from public.living_pop",
            "transit": "select max(period_end) from public.transit_boardings",
            "population": "select max(ref_month) from public.population_age",
            "trades": "select max(period_end) from public.commercial_trade_stats",
        }
        if source in baseline_sql:
            baseline = db.execute(baseline_sql[source]).fetchone()[0]
            if baseline and period_end < baseline:
                raise ValueError("Refresh predates the existing S1 data")
        if source in ("stores", "academies", "schools"):
            row = db.execute(
                "select source_version from ingest_private.place_snapshots where target_table=%s",
                (source,),
            ).fetchone()
            if row:
                version = row[0]
                baseline = date.fromisoformat(version if len(version) == 10 else version + "-01")
                if period_end < baseline:
                    raise ValueError("Refresh predates the existing place snapshot")
        if source == "rent":
            quarter = db.execute("select max(quarter) from public.rent_survey").fetchone()[0]
            if quarter:
                from ingest.publish_rent_survey import quarter_dates

                if period_end < quarter_dates(quarter)[1]:
                    raise ValueError("Refresh predates the existing survey quarter")
        if source == "buildings":
            row = db.execute(
                "select max(snapshot_version) from ingest_private.building_snapshots"
            ).fetchone()
            if row[0] and period_end < date.fromisoformat(row[0]):
                raise ValueError("Refresh predates existing building snapshot")
        loader(db)
        db.execute(
            """insert into ingest_private.refresh_snapshots
            (source,period_end,snapshot,manifest) values(%s,%s,%s,%s)
            on conflict(source) do update set period_end=excluded.period_end,
            snapshot=excluded.snapshot,manifest=excluded.manifest,committed_at=now()""",
            (source, period_end, snapshot, Jsonb(manifest)),
        )
    return True


def execute_refresh(source, snapshot, factory, prepare, *, maintenance=maintain):
    report = dict(source=source, snapshot=snapshot, status="preparing", committed=False)
    # Session lock covers downloads and promotion as well as maintenance; no cancellation mid-load.
    lock = int.from_bytes(hashlib.sha256(source.encode()).digest()[:4], "big") % 2**31
    try:
        with factory() as db:
            db.autocommit = True
            if not db.execute("select pg_try_advisory_lock(7412808,%s)", (lock,)).fetchone()[0]:
                return report | dict(status="busy")
            try:
                period_end, manifest, loader = prepare(db)
                changed = promote(db, source, period_end, snapshot, manifest, loader)
                report.update(committed=True, changed=changed, manifest=manifest)
                try:
                    maintenance(factory, TABLES[source])
                    report["status"] = "complete" if changed else "already_current"
                except Exception as error:
                    report.update(status="maintenance_failed", error_type=type(error).__name__)
            finally:
                db.execute("select pg_advisory_unlock(7412808,%s)", (lock,))
    except Exception as error:
        report.update(status="refresh_failed", error_type=type(error).__name__)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=AUTO + MANUAL, required=True)
    parser.add_argument("--target", choices=("local", "remote"), default="local")
    parser.add_argument("--end-month", default=last_complete_month())
    parser.add_argument("--quarter")
    parser.add_argument("--snapshot", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--directory", type=Path, default=ROOT / ".local/refresh")
    parser.add_argument("--asset-manifest", type=Path)
    parser.add_argument("--asset-manifest-key")
    args = parser.parse_args()
    datetime.strptime(args.snapshot, "%Y%m%dT%H%M%SZ")
    month_window(args.end_month, 1)
    if month_end(args.end_month) >= date.today().replace(day=1):
        parser.error("Only complete calendar months may be refreshed")
    args.directory = args.directory / args.source / args.snapshot
    args.directory.mkdir(parents=True, exist_ok=True)
    from ingest.refresh_sources import prepare_source

    store = RawStore(Settings.from_env())
    if args.target == "remote" and not store.settings.uses_r2:
        raise ValueError("Remote refresh requires persistent R2 storage")
    report = execute_refresh(
        args.source,
        args.snapshot,
        lambda: target_database(args.target),
        lambda db: prepare_source(args, store, db),
    )
    (args.directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "manifest"}))
    if report["status"] in ("refresh_failed", "maintenance_failed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
