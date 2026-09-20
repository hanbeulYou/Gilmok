"""Reproducible raw publication, compact place loading, quality and radius proofs."""

import argparse
import json
import math
from pathlib import Path

import pandas as pd
from psycopg import sql

from ingest import academies, schools, stores
from ingest.commerce_education_database import (
    TABLE_COLUMNS,
    attach_geocodes,
    load_snapshot,
    with_geometry,
)
from ingest.common import ROOT, RawStore, Settings, raw_key
from ingest.database import connect_database
from ingest.seoul_transit import read_frame, write_frame
from ingest.verify_transit import publish_verified

RADIUS_SQL = ROOT / "ingest/sql/commerce_education_radius.sql"
POINTS = [
    ("대치", 37.494612, 127.063642),
    ("학여울", 37.496663, 127.070594),
    ("한티", 37.496237, 127.052873),
]


def distribution(series):
    return {str(k): int(v) for k, v in series.value_counts(dropna=False).items()}


def prepare(args):
    directory = args.directory
    directory.mkdir(parents=True, exist_ok=True)
    paths = {"stores": stores.extract_raw(args.stores_zip, directory, args.stores_month)}
    for name, module, supplied in [
        ("academies", academies, args.academy_json),
        ("schools", schools, args.school_json),
    ]:
        if supplied:
            paths[name] = directory / f"{name}.parquet"
            if not paths[name].exists():
                write_frame(pd.DataFrame(json.loads(supplied.read_text())), paths[name])
        else:
            paths[name] = module.fetch(directory)
    raw_a, raw_s = read_frame(paths["academies"]), read_frame(paths["schools"])
    frames = {
        "stores": stores.normalize(paths["stores"]),
        "academies": academies.normalize(raw_a),
        "schools": schools.normalize(raw_s),
    }
    addresses = sorted((set(frames["academies"].address) | set(frames["schools"].address)) - {""})
    (directory / "addresses.json").write_text(json.dumps(addresses, ensure_ascii=False))
    report = {
        "source_version": args.education_version,
        "geocode_unique_addresses": len(addresses),
        "stores": {
            "rows": len(frames["stores"]),
            "classification_counts": {
                c: int(frames["stores"][c].nunique())
                for c in ["inds_lcls", "inds_mcls", "inds_scls"]
            },
            "missing_floor": int(frames["stores"].floor.isna().sum()),
        },
        "academies": {
            "raw_rows": len(raw_a),
            "active_rows": len(frames["academies"]),
            "status": distribution(raw_a.REG_STTS_NM),
            "field": distribution(raw_a.FLD_NM),
            "affiliation": distribution(raw_a.TRNG_AFLT_NM),
            "course": distribution(raw_a.TRNG_CRS_NM),
        },
        "schools": {
            "raw_rows": len(raw_s),
            "target_rows": len(frames["schools"]),
            "types": distribution(raw_s.SCHUL_KND_SC_NM),
        },
    }
    return paths, frames, report


def sample_storage(connection, frame):
    sample = with_geometry(frame.head(10000))
    columns = TABLE_COLUMNS["stores"]
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "create temporary table store_size_probe "
            "(like public.stores including all) on commit drop"
        )
        with cursor.copy("copy store_size_probe from stdin") as copy:
            for row in sample[columns].itertuples(index=False, name=None):
                copy.write_row(tuple(None if pd.isna(v) else v for v in row))
        size = cursor.execute("select pg_total_relation_size('store_size_probe')").fetchone()[0]
        cursor.execute("drop table store_size_probe")
    return {
        "sample_rows": len(sample),
        "sample_bytes_including_indexes": size,
        "projected_bytes": math.ceil(size * len(frame) / len(sample)),
    }


def compare_database(connection, table, frame):
    """Compare business fields, geometry and NULL to source, in both directions."""
    frame = with_geometry(frame)
    columns = [
        c for c in TABLE_COLUMNS[table] if c not in {"source", "source_version", "estimated"}
    ]
    identifiers = sql.SQL(",").join(map(sql.Identifier, columns))
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "create temporary table expected_places on commit drop as "
                "select {} from public.{} with no data"
            ).format(identifiers, sql.Identifier(table))
        )
        with cursor.copy(
            sql.SQL("copy expected_places ({}) from stdin").format(identifiers)
        ) as copy:
            for row in frame[columns].itertuples(index=False, name=None):
                copy.write_row(tuple(None if pd.isna(v) else v for v in row))
        count = cursor.execute(
            sql.SQL(
                "select count(*) from ((select {} from public.{} except all "
                "select {} from expected_places) union all (select {} from expected_places "
                "except all select {} from public.{})) d"
            ).format(
                identifiers,
                sql.Identifier(table),
                identifiers,
                identifiers,
                identifiers,
                sql.Identifier(table),
            )
        ).fetchone()[0]
        cursor.execute("drop table expected_places")
    if count:
        raise ValueError(f"{table} differs from source in {count} rows")
    return count


def measure(connection):
    query = RADIUS_SQL.read_text()
    records = []
    for name, lat, lng in POINTS:
        for radius in (500, 1000):
            parameters = {"lat": lat, "lng": lng, "radius": radius}
            for _ in range(3):
                connection.execute(query, parameters).fetchone()
            times = [
                connection.execute("explain (analyze,format json) " + query, parameters).fetchone()[
                    0
                ][0]["Execution Time"]
                for _ in range(30)
            ]
            values = connection.execute(query, parameters).fetchone()[0]
            records.append(
                {
                    "name": name,
                    **parameters,
                    "values": values,
                    "db_p95_ms": sorted(times)[math.ceil(len(times) * 0.95) - 1],
                    "repetitions": 30,
                    "warmup": 3,
                }
            )
    if any(r["db_p95_ms"] >= 1000 for r in records):
        raise ValueError("Place SQL p95 exceeds 1000ms (not the whole score_inputs RPC)")
    return records


def run(args):
    paths, frames, report = prepare(args)
    store = RawStore(Settings.from_env())
    months = {
        "stores": args.stores_month,
        "academies": args.education_version[:7],
        "schools": args.education_version[:7],
    }
    report["publications"] = {
        name: publish_verified(store, name, months[name], path) for name, path in paths.items()
    }
    # Normalize actual remote raw snapshots as well; source-only local processing is insufficient.
    with store.connection() as duck:
        duck.read_parquet(store.location("stores", months["stores"])).create_view("store_raw")
        for original, normalized in [
            ("상권업종대분류코드", "inds_lcls"),
            ("상권업종중분류코드", "inds_mcls"),
            ("상권업종소분류코드", "inds_scls"),
        ]:
            remote_counts = dict(
                duck.execute(
                    f'SELECT "{original}",count(*) FROM store_raw GROUP BY "{original}"'
                ).fetchall()
            )
            if remote_counts != distribution(frames["stores"][normalized]):
                raise ValueError("Remote raw store aggregation differs")
        report["stores"]["remote_classification_mismatches"] = 0
        for name in ("academies", "schools"):
            raw = duck.read_parquet(store.location(name, months[name])).df()
            normalized = (academies if name == "academies" else schools).normalize(raw)
            pd.testing.assert_frame_equal(
                normalized.reset_index(drop=True), frames[name].reset_index(drop=True)
            )
    if args.load:
        with connect_database(local_only=True) as connection:
            baseline = connection.execute("select pg_database_size(current_database())").fetchone()[
                0
            ]
            report["store_sample"] = sample_storage(connection, frames["stores"])
            print("store_sample", json.dumps(report["store_sample"]), flush=True)
            if baseline + report["store_sample"]["projected_bytes"] > 500_000_000:
                raise ValueError("Projected DB over 500MB; report before full store load")
            for name in ("academies", "schools"):
                frames[name] = attach_geocodes(connection, frames[name])
                report[name]["unlocated_rows"] = int(frames[name].geocode_failed.sum())
            sources = {
                "stores": "semas_stores",
                "academies": academies.SOURCE,
                "schools": schools.SOURCE,
            }
            # All three source snapshots become visible together, or all roll back.
            for name, frame in frames.items():
                version = args.stores_month if name == "stores" else args.education_version
                load_snapshot(
                    connection,
                    name,
                    frame,
                    source=sources[name],
                    version=version,
                    raw_key=raw_key(name, months[name]),
                    report=report[name],
                )
                report[name]["db_mismatches"] = compare_database(connection, name, frame)
                print("loaded", name, len(frame), flush=True)
            for name in frames:
                connection.execute(sql.SQL("analyze public.{}").format(sql.Identifier(name)))
            report["radius_queries"] = measure(connection)
            report["storage"] = {
                "database_before_bytes": baseline,
                "database_during_transaction_bytes": connection.execute(
                    "select pg_database_size(current_database())"
                ).fetchone()[0],
                "tables": {
                    name: connection.execute(
                        "select pg_total_relation_size(%s)", ("public." + name,)
                    ).fetchone()[0]
                    for name in frames
                },
            }
            if report["storage"]["database_during_transaction_bytes"] > 500_000_000:
                raise ValueError("Actual DB exceeds 500MB; rolling back place snapshot")
        # Dropped temporary relation files are released only at transaction commit.
        with connect_database(local_only=True) as connection:
            report["storage"]["database_after_bytes"] = connection.execute(
                "select pg_database_size(current_database())"
            ).fetchone()[0]
    target = args.directory / "report.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("report", target, flush=True)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stores-zip", type=Path, required=True)
    parser.add_argument("--stores-month", required=True)
    parser.add_argument(
        "--education-version", required=True, help="Source retrieval date YYYY-MM-DD"
    )
    parser.add_argument("--academy-json", type=Path)
    parser.add_argument("--school-json", type=Path)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--load", action="store_true")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
