"""Public-source provenance/coordinates missing from the original R2 publications."""

import json
from datetime import UTC, datetime

import duckdb
import numpy as np
import pandas as pd
from psycopg import sql

from ingest import academies, schools
from ingest.database import connect_database
from ingest.living_population import POPULATION_COLUMNS
from ingest.restore_manifest import cached_object
from ingest.score_reference import source_state
from ingest.seoul_transit import write_frame
from ingest.verify_score_inputs import TABLES, cases, stable_payload

DATA_TABLES = (*TABLES, "score_reference", "score_reference_sets")
METADATA_TABLES = ("place_snapshots", "building_snapshots", "rent_snapshots",
                   "transit_coverage", "refresh_snapshots")


def columns(db, table):
    return [r[0] for r in db.execute("select column_name from information_schema.columns "
                                   "where table_schema='public' and table_name=%s "
                                   "order by ordinal_position", (table,))]


def table_signature(db, table):
    if table not in DATA_TABLES:
        raise ValueError("Not a public source table")
    geometry = (sql.SQL(" || jsonb_build_object('geom',encode(extensions.st_asewkb(geom),'hex'))")
                if "geom" in columns(db, table) else sql.SQL(""))
    count, digest = db.execute(sql.SQL("select count(*),md5(string_agg(h,'' order by h)) "
        "from (select md5((to_jsonb(t){} )::text) h from public.{} t) rows").format(
            geometry, sql.Identifier(table))).fetchone()
    return dict(rows=count, row_digest=digest)


def capture(db, addresses):
    timestamps = {}
    for table in DATA_TABLES:
        names = columns(db, table)
        if "ingested_at" not in names:
            continue
        match_columns = [c for c in ("source", "source_version") if c in names]
        fields = sql.SQL(",").join(map(sql.Identifier, [*match_columns, "ingested_at"]))
        groups = db.execute(sql.SQL("select {},count(*) from public.{} group by {} "
                                   "order by count(*) desc").format(
                                       fields, sql.Identifier(table), fields)).fetchall()
        seen, entries = set(), []
        for row in groups:
            match = dict(zip(match_columns, row[:len(match_columns)]))
            key = json.dumps(match, sort_keys=True)
            entry = dict(match=match, at=row[-2].isoformat())
            if key in seen:
                if "id" not in names:
                    raise ValueError("Ambiguous provenance requires a documented row identity")
                predicates = sql.SQL(" and ").join(
                    sql.SQL("{} is not distinct from %s").format(sql.Identifier(c))
                    for c in [*match_columns, "ingested_at"])
                entry["ids"] = [r[0] for r in db.execute(sql.SQL(
                    "select id from public.{} where {} order by id").format(
                        sql.Identifier(table), predicates), row[:-1])]
            seen.add(key)
            entries.append(entry)
        timestamps[table] = entries
    metadata = {t: db.execute(sql.SQL("select coalesce(jsonb_agg(to_jsonb(t)),'[]') "
                 "from ingest_private.{} t").format(sql.Identifier(t))).fetchone()[0]
                for t in METADATA_TABLES}
    geocodes = db.execute("""select to_jsonb(g) || jsonb_build_object('geom',
        encode(extensions.st_asewkb(geom),'hex')) from public.geocode_cache g
        where address=any(%s) order by address,provider""", (sorted(addresses),)).fetchall()
    baseline = []
    for case in cases():
        payload = db.execute("select public.score_inputs(%(lat)s,%(lng)s,%(radius_m)s,"
                             "%(floor)s)", case).fetchone()[0]
        baseline.append(dict(case=case, result=stable_payload(payload)))
    signatures = {}
    for table in DATA_TABLES:
        signatures[table] = table_signature(db, table)
        print("baseline " + table, flush=True)
    return dict(timestamps=timestamps, metadata=metadata, tables=signatures,
                source_state=source_state(db), cases=baseline), [r[0] for r in geocodes]


def prepare_supplements(directory, store, manifest):
    if manifest.get("supplements"):
        for entry in manifest["supplements"]:
            cached_object(store, entry, directory)
        return manifest
    addresses = set()
    for module in (academies, schools):
        source = module.__name__.split(".")[-1]
        entry, = [e for e in manifest["objects"] if e["key"].split("/")[1] == source]
        with duckdb.connect() as db:
            raw = db.read_parquet(str(cached_object(store, entry, directory))).df()
        addresses.update(set(module.normalize(raw).address) - {""})
    with connect_database(local_only=True) as db:
        db.execute("set transaction isolation level repeatable read read only")
        provenance, geocodes = capture(db, addresses)
    snapshot = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    entries = []
    for source, value in [("restore_provenance", provenance),
                          ("public_place_geocodes", geocodes)]:
        path = directory / (source + ".parquet")
        write_frame(pd.DataFrame([{"payload_json": json.dumps(value, ensure_ascii=False)}]), path)
        result = store.publish_revision(source, "2026-09", snapshot, path)
        entry = dict(key=result["key"], sha256=result["sha256"], bytes=path.stat().st_size,
                     rows=len(value) if isinstance(value, list) else 1)
        cached_object(store, entry, directory)
        entries.append(entry)
    manifest["supplements"] = entries
    manifest["expected_tables"] = provenance["tables"]
    (directory / "restore-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def verify_living_profile(actual, expected):
    keys = ["cell_id", "dow_type", "hour"]
    a = actual.sort_values(keys).reset_index(drop=True)
    b = expected.sort_values(keys).reset_index(drop=True)
    if len(a) != len(b) or a.duplicated(keys).any() or b.duplicated(keys).any():
        raise ValueError("Living profile keys/rows differ")
    max_error = 0.0
    for col in [*keys, *POPULATION_COLUMNS, "sample_days", "period_start", "period_end"]:
        if not a[col].isna().equals(b[col].isna()):
            raise ValueError("Living profile NULL mask differs: " + col)
        if col in POPULATION_COLUMNS:
            x, y = a[col].astype(float), b[col].astype(float)
            if not np.isclose(x, y, rtol=1e-10, atol=1e-8, equal_nan=True).all():
                raise ValueError("Living profile values differ: " + col)
            maximum = (x-y).abs().max()
            if pd.notna(maximum):
                max_error = max(max_error, float(maximum))
        elif not a[col].astype(str).equals(b[col].astype(str)):
            raise ValueError("Living profile values differ: " + col)
    return dict(rows=len(a), max_abs_error=max_error, absolute_tolerance=1e-8,
                relative_tolerance=1e-10, null_masks_match=True)


def prepare_living_baseline(directory, store, manifest):
    """Preserve the S1 loaded float representation only after full R2 reaggregation proof."""
    from datetime import date

    from ingest.living_population import aggregate_window
    from ingest.seoul_transit import read_frame

    if any("/living_restore_baseline/" in e["key"] for e in manifest["supplements"]):
        return manifest
    entries = [e for e in manifest["objects"] if "/living_population/" in e["key"]]
    paths = [cached_object(store, e, directory) for e in entries]
    profile = directory / "living-profile.parquet"
    aggregate_window(paths, date(2026, 6, 1), date(2026, 8, 31), profile)
    fields = ["cell_id", "dow_type", "hour", *POPULATION_COLUMNS,
              "sample_days", "period_start", "period_end"]
    with connect_database(local_only=True) as db:
        db.execute("set transaction read only")
        rows = db.execute(sql.SQL("select {} from public.living_pop").format(
            sql.SQL(",").join(map(sql.Identifier, fields)))).fetchall()
    expected = pd.DataFrame(rows, columns=fields)
    proof = verify_living_profile(read_frame(profile), expected)
    path = directory / "living-restore-baseline.parquet"
    write_frame(expected, path)
    snapshot = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    result = store.publish_revision("living_restore_baseline", "2026-09", snapshot, path)
    entry = dict(key=result["key"], sha256=result["sha256"], bytes=result["bytes"],
                 rows=len(expected))
    cached_object(store, entry, directory)
    manifest["supplements"].append(entry)
    manifest["living_baseline_proof"] = proof
    (directory / "restore-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def prepare_geometry_baseline(directory, store, manifest):
    """Retain the published 4326 footprint representation across PROJ/platform rounding."""
    if any("/building_geometry_baseline/" in e["key"] for e in manifest["supplements"]):
        return manifest
    with connect_database(local_only=True) as db:
        db.execute("set transaction read only")
        rows = db.execute("select id,encode(extensions.st_asewkb(geom),'hex') "
                          "from public.buildings order by id").fetchall()
    path = directory / "building-geometry-baseline.parquet"
    write_frame(pd.DataFrame(rows, columns=["id", "geom"]), path)
    snapshot = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    result = store.publish_revision("building_geometry_baseline", "2026-09", snapshot, path)
    entry = dict(key=result["key"], sha256=result["sha256"], bytes=result["bytes"], rows=len(rows))
    cached_object(store, entry, directory)
    manifest["supplements"].append(entry)
    (directory / "restore-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest
