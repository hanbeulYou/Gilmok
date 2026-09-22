"""Publish and reread PR 6 raw snapshots before atomic aggregate loading."""

import argparse
import calendar
import hashlib
import json
import math
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pandas as pd

from ingest.commercial_trades import collect_months, months_between, normalize_trades
from ingest.common import ROOT, RawStore, Settings, StorageError
from ingest.database import connect_database
from ingest.legal_boundaries import prepare_legal_boundaries, raw_legal_boundaries
from ingest.rent_database import aggregate_trades, load_trade_snapshot
from ingest.seoul_transit import write_frame
from ingest.verify_commerce_education import POINTS

EXPECTED_LEGAL_DONGS = {"대치": "11680106", "학여울": "11680106", "한티": "11680118"}


def publish_verified(store, source, month, path, *, snapshot=None):
    """Publication is successful only after exact multiset comparison through storage."""
    path = Path(path)
    if snapshot is None:
        # Local storage's general publisher permits replacement; PR6 snapshots do not.
        if not store.settings.uses_r2:
            existing = Path(store.location(source, month))
            if existing.exists() and existing.read_bytes() != path.read_bytes():
                raise StorageError("Existing raw snapshot differs; use a revision")
        manifest = store.publish_file(source, month, path)
    else:
        manifest = store.publish_revision(source, month, snapshot, path)
    key = manifest["key"]
    location = (
        f"s3://{store.settings.r2_bucket}/{key}"
        if store.settings.uses_r2
        else str(store.settings.local_root / key)
    )
    with store.connection() as connection:
        connection.read_parquet(str(path)).create_view("original")
        connection.read_parquet(location).create_view("published")
        mismatch = connection.execute("""select count(*) from (
            (select * from original except all select * from published) union all
            (select * from published except all select * from original))""").fetchone()[0]
        if mismatch:
            raise ValueError("Published raw snapshot differs from input")
        rows = connection.execute("select count(*) from published").fetchone()[0]
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return manifest | {
        "location": location,
        "rows": rows,
        "reread_mismatches": mismatch,
        "sha256": digest,
        "bytes": path.stat().st_size,
    }


def read_published(store, manifests):
    with store.connection() as connection:
        frames = []
        for manifest in manifests:
            relation = connection.read_parquet(manifest["location"])
            # .df() converts DECIMAL to float64; keep provider monetary precision.
            frames.append(pd.DataFrame(relation.fetchall(), columns=relation.columns))
        return pd.concat(frames, ignore_index=True)


def database_sizes(connection):
    total = connection.execute("select pg_database_size(current_database())").fetchone()[0]
    rows = connection.execute("""select c.relname,pg_table_size(c.oid),pg_indexes_size(c.oid),
        pg_total_relation_size(c.oid) from pg_class c join pg_namespace n on n.oid=c.relnamespace
        where n.nspname='public' and c.relname in
        ('legal_dongs','commercial_trade_stats','rent_areas','rent_survey')""").fetchall()
    return {
        "database_bytes": total,
        "relations": [
            dict(zip(("table", "table_bytes", "index_bytes", "total_bytes"), row)) for row in rows
        ],
    }


def assert_trade_contract(payload):
    if payload["meta"]["legal_dong_code"] not in set(EXPECTED_LEGAL_DONGS.values()):
        raise ValueError("Validation coordinate has no verified legal dong")
    options = payload["trade_by_building_type"]
    if options:
        selected = sorted(options, key=lambda row: (-row["sample_count"], row["trade_kind"]))[0]
        if (
            payload["trade_building_type"] != selected["trade_kind"]
            or payload["trade_sample_count"] != selected["sample_count"]
        ):
            raise ValueError("Trade default did not select the largest sample")
        if selected["sample_count"] < 5 and payload["trade_median_per_m2"] is not None:
            raise ValueError("Under-five trade sample must return NULL")
        if selected["sample_count"] >= 5 and payload["trade_median_per_m2"] is None:
            raise ValueError("Eligible trade sample unexpectedly NULL")
    elif payload["trade_median_per_m2"] is not None:
        raise ValueError("Missing trade samples must return NULL")
    if payload["rent_level"] not in (None, "district", "region"):
        raise ValueError("Unexpected survey fallback level")


def measure(connection):
    query = (ROOT / "ingest/sql/rent_inputs.sql").read_text()
    records = []
    for name, lat, lng in POINTS:
        for radius in (500, 1000):
            for floor in (None, 2):
                parameters = (lng, lat, radius, floor, None)
                for _ in range(3):
                    connection.execute(query, parameters).fetchone()
                times = [
                    connection.execute(
                        "explain (analyze,format json) " + query, parameters
                    ).fetchone()[0][0]["Execution Time"]
                    for _ in range(30)
                ]
                payload = connection.execute(query, parameters).fetchone()[0]
                if payload["meta"]["legal_dong_code"] != EXPECTED_LEGAL_DONGS[name]:
                    raise ValueError("Landmark differs from its verified legal-dong boundary")
                assert_trade_contract(payload)
                p95 = sorted(times)[math.ceil(len(times) * 0.95) - 1]
                if p95 >= 1000:
                    raise ValueError("Rent RPC DB execution p95 exceeds 1000ms")
                records.append(
                    {
                        "name": name,
                        "lat": lat,
                        "lng": lng,
                        "radius": radius,
                        "floor": floor,
                        "warmups": 3,
                        "runs": 30,
                        "p95_ms": p95,
                        "result": payload,
                    }
                )
    return records


def measure_http(measurements):
    status = subprocess.run(
        ["supabase", "status", "-o", "json"], capture_output=True, text=True, check=True
    )
    settings = json.loads(status.stdout)
    base = settings["API_URL"]
    if urlparse(base).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Rent performance verification is local-only")
    for item in measurements:
        parameters = {"lng": item["lng"], "lat": item["lat"], "radius_m": item["radius"],
                      "floor": item["floor"], "building_class": None}
        request = Request(base + "/rest/v1/rpc/rent_inputs",
                          data=json.dumps(parameters).encode(), headers={
                              "apikey": settings["ANON_KEY"],
                              "Authorization": "Bearer " + settings["ANON_KEY"],
                              "Content-Type": "application/json"})
        started = time.perf_counter()
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except Exception:
            raise RuntimeError("Anonymous rent HTTP request failed") from None
        item["http_roundtrip_ms"] = (time.perf_counter() - started) * 1000
        item["http_samples"] = 1
        if payload != item["result"]:
            raise ValueError("Anonymous HTTP rent RPC differs from database result")


def run_trades(args, *, store=None, database_factory=None):
    datetime.strptime(args.snapshot, "%Y%m%dT%H%M%SZ")
    store = store or RawStore(Settings.from_env())
    directory = Path(args.directory)
    output = directory / args.snapshot
    output.mkdir(parents=True, exist_ok=True)
    boundary_path = directory / "legal-dongs.geojson"
    boundaries = prepare_legal_boundaries(boundary_path, source_version=args.snapshot)
    raw = collect_months(args.start_month, args.end_month, directory)
    manifests = []
    for month in months_between(args.start_month, args.end_month):
        frame = raw.loc[raw.request_month == month].copy()
        # Collector raw data contains provider text and integer provenance only.
        for column in frame.columns.difference(["request_page", "request_row"]):
            if not frame[column].map(lambda value: isinstance(value, str)).all():
                raise ValueError("Raw transaction fields must remain strings")
        path = output / f"commercial-{month}.parquet"
        write_frame(frame, path)
        manifests.append(
            publish_verified(
                store,
                "commercial_trades",
                month[:4] + "-" + month[4:],
                path,
                snapshot=args.snapshot if args.revision else None,
            )
        )
    path = output / "legal-boundaries.parquet"
    write_frame(raw_legal_boundaries(boundary_path), path)
    boundary_manifest = publish_verified(
        store,
        "legal_boundaries",
        "2026-09",
        path,
        snapshot=args.snapshot if args.revision else None,
    )
    # DB summaries must derive from the just-reread storage objects exclusively.
    published = read_published(store, manifests)
    published_boundaries = read_published(store, [boundary_manifest])
    collection = json.loads(published_boundaries.iloc[0].collection_metadata_json)
    collection["features"] = [json.loads(value) for value in published_boundaries.feature_json]
    reread_path = output / "legal-dongs-reread.geojson"
    reread_path.write_text(json.dumps(collection), encoding="utf-8")
    boundaries = prepare_legal_boundaries(reread_path, source_version=args.snapshot)
    normalized = normalize_trades(published, dict(zip(boundaries.name, boundaries.code8)))
    stats = aggregate_trades(normalized)
    report = {
        "snapshot": args.snapshot,
        "raw_rows": len(published),
        "eligible_rows": int(normalized.eligible.sum()),
        "types": {str(k): int(v) for k, v in normalized.trade_kind.value_counts().items()},
        "exclusions": {
            str(k): int(v)
            for k, v in normalized.exclusion_reason.value_counts(dropna=False).items()
        },
        "objects": manifests + [boundary_manifest],
        "summary_rows": len(stats),
        "local_raw_bytes": sum(m["bytes"] for m in manifests + [boundary_manifest]),
        "local_temporary_bytes": reread_path.stat().st_size,
    }
    year, month = int(args.end_month[:4]), int(args.end_month[4:])
    period_end = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
    factory = database_factory or connect_database
    with factory() as connection:
        report["database_before"] = database_sizes(connection)
        load_trade_snapshot(
            connection,
            boundaries,
            stats,
            period_start=args.start_month[:4] + "-" + args.start_month[4:] + "-01",
            period_end=period_end,
            source_version=args.snapshot,
            report=report,
        )
        report["database_during_transaction"] = database_sizes(connection)
        report["rpc"] = measure(connection)
        connection.execute("notify pgrst, 'reload schema'")
    with factory() as connection:
        report["database_after_commit"] = database_sizes(connection)
    measure_http(report["rpc"])
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("trades", "verify"))
    parser.add_argument("--directory", type=Path, default=Path(".local/validation/pr6"))
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--start-month", default="202409")
    parser.add_argument("--end-month", default="202608")
    parser.add_argument("--revision", action="store_true")
    args = parser.parse_args()
    if args.command == "trades":
        report = run_trades(args)
        print(json.dumps({"raw_rows": report["raw_rows"], "summary_rows": report["summary_rows"]}))
    else:
        with connect_database() as connection:
            report = {"rpc": measure(connection), "sizes": database_sizes(connection)}
        measure_http(report["rpc"])
        path = args.directory / f"verification-{args.snapshot}.json"
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(f"Verified {len(report['rpc'])} RPC cases")


if __name__ == "__main__":
    main()
