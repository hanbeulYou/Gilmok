"""Replay a frozen R2 manifest into an empty database; never collect provider APIs."""

import argparse
import json
import time
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
from psycopg import sql
from psycopg.types.json import Jsonb

from ingest import academies, schools, stores
from ingest.common import ROOT, RawStore, Settings
from ingest.database import load_boundaries
from ingest.refresh import maintain, target_database
from ingest.restore_manifest import cached_object, sha256
from ingest.restore_provenance import (
    DATA_TABLES,
    METADATA_TABLES,
    table_signature,
    verify_living_profile,
)
from ingest.score_reference import load_snapshot as load_reference
from ingest.seoul_transit import read_frame


class Replay:
    def __init__(self, manifest, directory, store):
        self.manifest, self.directory, self.store = manifest, directory, store
        self.entries = manifest["objects"] + manifest["supplements"]
        self.paths = {e["key"]: cached_object(store, e, directory) for e in self.entries}
        self.provenance = self.payload("restore_provenance")

    def objects(self, source):
        return [e for e in self.entries if e["key"].split("/")[1] == source]

    def path(self, source):
        entry, = self.objects(source)
        return self.paths[entry["key"]]

    def frame(self, source):
        # Monetary DECIMAL must not pass through DuckDB .df()'s float conversion.
        with duckdb.connect() as db:
            relation = db.read_parquet(str(self.path(source)))
            return pd.DataFrame(relation.fetchall(), columns=relation.columns)

    def payload(self, source):
        return json.loads(self.frame(source).iloc[0, 0])

    def version(self, table):
        values = {e["match"]["source_version"] for e in self.provenance["timestamps"][table]}
        version, = values
        return version

    def boundaries_population(self, db):
        from ingest.legal_boundaries import prepare_legal_boundaries
        from ingest.living_population import aggregate_window
        from ingest.population import normalize_residents
        from ingest.population_database import (
            load_living_population,
            load_population_cells,
            load_resident_snapshot,
        )
        from ingest.population_grid import grid_rows

        admin = self.frame("admin_boundaries")
        admin_rows = admin[["code", "name", "wkt"]].to_dict("records")
        load_boundaries(db, "admin_dongs", admin_rows, source=admin.source.iloc[0],
                        source_version=admin.source_version.iloc[0], srid=4326)
        raw_legal = self.frame("legal_boundaries")
        collection = json.loads(raw_legal.collection_metadata_json.iloc[0])
        collection["features"] = [json.loads(v) for v in raw_legal.feature_json]
        legal_file = self.directory / "legal-boundaries.geojson"
        legal_file.write_text(json.dumps(collection))
        self.legal = prepare_legal_boundaries(
            legal_file, source_version=self.version("legal_dongs"))
        for r in self.legal.itertuples():
            db.execute("""insert into public.legal_dongs(code8,name,geom,source,source_version)
                values(%s,%s,extensions.st_multi(extensions.st_geomfromtext(%s,4326)),%s,%s)""",
                (r.code8, r.name, r.wkt, r.source, r.source_version))
        living_path = self.directory / "living-profile.parquet"
        raw_paths = [self.paths[e["key"]] for e in self.objects("living_population")]
        aggregate_window(raw_paths, date(2026, 6, 1), date(2026, 8, 31), living_path)
        living = read_frame(living_path)
        baseline = read_frame(self.path("living_restore_baseline"))
        verify_living_profile(living, baseline)
        cells = grid_rows(self.path("population_grid"), set(living.cell_id))
        load_population_cells(db, cells, source="seoul_living_population_250m",
                              source_version=self.version("population_cells"))
        residents_file = self.directory / "residents.csv"
        self.frame("resident_population").to_csv(residents_file, encoding="cp949", index=False)
        residents = normalize_residents(residents_file, "2026-08")
        load_resident_snapshot(db, admin_rows, residents.to_dict("records"),
            boundary_source=admin.source.iloc[0], boundary_version=admin.source_version.iloc[0],
            source="mois_resident_population", source_version=self.version("population_age"))
        # Keep exact S1 float bits after validating every key, NULL and reaggregated value.
        load_living_population(db, baseline.astype(object).where(pd.notna(baseline), None)
            .to_dict("records"), source="seoul_living_population_250m",
            source_version=self.version("living_pop"))

    def transit(self, db):
        from ingest.transit_database import load_snapshot, seoul_stops
        from ingest.verify_transit import SOURCES, aggregate_months, coverage, require_coverage

        stops, counts, reports = [], [], {}
        for kind, (adapter, _, _) in SOURCES.items():
            all_stops = adapter.stops(self.frame(kind + "_stops"))
            scoped = seoul_stops(db, all_stops)
            normalized, monthly = [], {}
            for entry in self.objects(kind + "_boardings"):
                raw = read_frame(self.paths[entry["key"]])
                frame = adapter.normalize(raw, all_stops, Path(entry["key"]).stem)
                report = coverage(raw, frame, set(scoped.stop_id))
                require_coverage(report)
                monthly[Path(entry["key"]).stem] = report
                normalized.append(frame)
            aggregate = aggregate_months(normalized)
            stops.append(scoped)
            counts.append(aggregate[aggregate.stop_id.isin(set(scoped.stop_id))])
            reports[kind] = dict(coordinates=dict(retrieved_on=self.version("transit_stops")),
                                 months=monthly)
        load_snapshot(db, pd.concat(stops, ignore_index=True), pd.concat(counts, ignore_index=True),
                      reports, start=date(2026, 6, 1), end=date(2026, 8, 31),
                      coordinate_version=self.version("transit_stops"))

    def places(self, db):
        from ingest.commerce_education_database import attach_geocodes, load_snapshot

        # Only addresses occurring in the original public academy/school rows were exported.
        geocodes = self.payload("public_place_geocodes")
        db.execute("insert into public.geocode_cache select * from "
                   "jsonb_populate_recordset(null::public.geocode_cache,%s)", (Jsonb(geocodes),))
        for name, module in [("stores", stores), ("academies", academies), ("schools", schools)]:
            frame = module.normalize(self.path(name) if name == "stores" else self.frame(name))
            if name != "stores":
                frame = attach_geocodes(db, frame)
            original = next(e for e in self.provenance["metadata"]["place_snapshots"]
                            if e["target_table"] == name)
            load_snapshot(db, name, frame, source=original["source"],
                          version=original["source_version"], raw_key=original["raw_key"],
                          report=original["report"])

    def buildings(self, db):
        from ingest.building_footprints import normalize_shp, normalize_wfs
        from ingest.building_register import normalize_floors, normalize_titles
        from ingest.buildings_database import load_snapshot

        with duckdb.connect() as c:
            raw = c.execute("select * from read_parquet(?) where starts_with(A2,'11680')",
                            [str(self.path("gis_buildings_shp"))]).df()
        raw["source_geometry_wkb"] = raw.source_geometry_wkb.map(bytes)
        shp, _ = normalize_shp(raw)
        raw_wfs = self.frame("vworld_building_footprints")
        features = [dict(id=r["feature_id"], geometry=json.loads(r["geometry_json"]),
                         properties={k: v for k, v in r.items()
                                     if k not in ("feature_id", "geometry_json")})
                    for r in raw_wfs.to_dict("records")]
        original, = self.provenance["metadata"]["building_snapshots"]
        wfs, _ = normalize_wfs(features, set(shp.gis_id), original["snapshot_version"],
                               self.directory / "wfs-replay.parquet")
        load_snapshot(db, pd.concat([shp, wfs], ignore_index=True),
                      normalize_titles(self.frame("building_hub_titles")),
                      normalize_floors(self.frame("building_hub_floors")),
                      snapshot=original["snapshot_version"], raw_objects=original["raw_objects"])
        baseline = self.frame("building_geometry_baseline")
        db.execute("create temporary table restore_geometry (id text primary key, "
                   "geom extensions.geometry(MultiPolygon,4326) not null) on commit drop")
        with db.cursor().copy("copy restore_geometry(id,geom) from stdin") as copy:
            for row in baseline.itertuples(index=False, name=None):
                copy.write_row(row)
        if db.execute("""select count(*) from public.buildings b full join restore_geometry g
            using(id) where b.id is null or g.id is null or
            extensions.st_geometrytype(b.geom)<>extensions.st_geometrytype(g.geom)
            or extensions.st_npoints(b.geom)<>extensions.st_npoints(g.geom)""").fetchone()[0]:
            raise ValueError("Footprint identity/type/vertex count differs from baseline")
        missing, max_distance, changed = db.execute("""with a as (
            select id,(d).path path,(d).geom geom from public.buildings,
            lateral extensions.st_dumppoints(geom) d), b as (
            select id,(d).path path,(d).geom geom from restore_geometry,
            lateral extensions.st_dumppoints(geom) d)
            select count(*) filter(where a.id is null or b.id is null),
              max(extensions.st_distance(a.geom::extensions.geography,
                                         b.geom::extensions.geography)),
              count(*) filter(where extensions.st_asewkb(a.geom)<>extensions.st_asewkb(b.geom))
            from a full join b using(id,path)""").fetchone()
        if missing or max_distance is None or max_distance > 1e-6:
            raise ValueError("Footprint vertex position differs from baseline")
        self.geometry_proof = dict(max_vertex_distance_m=max_distance,
                                   tolerance_m=1e-6, changed_float_vertices=changed,
                                   restored_exact_baseline=True)
        db.execute("update public.buildings b set geom=g.geom from restore_geometry g "
                   "where b.id=g.id and extensions.st_asewkb(b.geom)<>extensions.st_asewkb(g.geom)")

    def rent(self, db):
        from ingest.commercial_trades import normalize_trades
        from ingest.rent_database import aggregate_trades, load_survey_snapshot, load_trade_snapshot
        from ingest.rent_survey import normalize_survey

        raw = pd.concat([read_frame(self.paths[e["key"]])
                         for e in self.objects("commercial_trades")], ignore_index=True)
        normalized = normalize_trades(raw, dict(zip(self.legal.name, self.legal.code8)))
        load_trade_snapshot(db, self.legal, aggregate_trades(normalized),
            period_start="2024-09-01", period_end="2026-08-31",
            source_version=self.version("commercial_trade_stats"), report={})
        evidence = json.loads(self.frame("rent_survey_scope").evidence_json.iloc[0])
        scopes = {(r["table"], r["cls_id"]): {k: v for k, v in r.items()
                  if k not in ("table", "cls_id")} for r in evidence["scopes"]}
        version = self.version("rent_survey")
        surveys = normalize_survey(self.frame("rent_survey"), scopes, source_version=version)
        load_survey_snapshot(db, pd.DataFrame(evidence["areas"]), surveys,
                             source_version=version, report={})

    def provenance_and_reference(self, db):
        for table, entries in self.provenance["timestamps"].items():
            if table not in DATA_TABLES:
                raise ValueError("Unexpected provenance table")
            for entry in entries:
                predicates = [sql.SQL("{} is not distinct from %s").format(sql.Identifier(c))
                              for c in entry["match"]]
                values = [entry["at"], *entry["match"].values()]
                if "ids" in entry:
                    predicates.append(sql.SQL("id=any(%s)"))
                    values.append(entry["ids"])
                db.execute(sql.SQL("update public.{} set ingested_at=%s where {}").format(
                    sql.Identifier(table), sql.SQL(" and ").join(predicates) if predicates
                    else sql.SQL("true")), values)
        for table in METADATA_TABLES:
            db.execute(sql.SQL("delete from ingest_private.{}").format(sql.Identifier(table)))
            db.execute(sql.SQL("insert into ingest_private.{} select * from "
                "jsonb_populate_recordset(null::ingest_private.{},%s)").format(
                    sql.Identifier(table), sql.Identifier(table)),
                (Jsonb(self.provenance["metadata"][table]),))
        load_reference(db, self.path("score_reference"), self.payload("score_reference_manifest"))


def verify_tables(db, expected):
    actual = {table: table_signature(db, table) for table in DATA_TABLES}
    mismatches = [t for t in DATA_TABLES if actual[t] != expected[t]]
    if mismatches:
        raise ValueError("Restored row/geometry/provenance mismatch: " + ",".join(mismatches))
    return actual


def run(manifest_path, directory, target, approved_manifest_sha256=None):
    digest = sha256(manifest_path)
    if target == "remote" and digest != approved_manifest_sha256:
        raise ValueError("Remote restore requires the explicitly approved manifest SHA256")
    manifest = json.loads(manifest_path.read_text())
    replay = Replay(manifest, directory, RawStore(Settings.from_env()))
    report = dict(manifest_sha256=digest, target=target, stages=[])
    started = time.monotonic()
    def factory():
        return target_database(target)
    with factory() as db:
        if target == "local" and db.info.dbname == "postgres":
            raise ValueError("Local replay requires an isolated database")
        db.execute("select pg_advisory_xact_lock(7412809)")
        occupied = any(db.execute(sql.SQL("select exists(select 1 from public.{})").format(
                       sql.Identifier(t))).fetchone()[0] for t in DATA_TABLES)
        if occupied:
            report["tables"] = verify_tables(db, manifest["expected_tables"])
            report["already_restored"] = True
            return report
        report["before_bytes"] = db.execute(
            "select pg_database_size(current_database())").fetchone()[0]
        for name in ("boundaries_population", "transit", "places", "buildings", "rent",
                     "provenance_and_reference"):
            start = time.monotonic()
            getattr(replay, name)(db)
            report["stages"].append(dict(name=name, seconds=round(time.monotonic()-start, 3)))
            print(json.dumps(report["stages"][-1]), flush=True)
        report["tables"] = verify_tables(db, manifest["expected_tables"])
        report["geometry_proof"] = replay.geometry_proof
        # Entire replay commits together; any failed stage/check leaves the target empty.
    maintain(factory, DATA_TABLES)
    with factory() as db:
        report["after_bytes"] = db.execute(
            "select pg_database_size(current_database())").fetchone()[0]
        report["relations"] = db.execute("""select jsonb_agg(jsonb_build_object(
            'table',relname,'table_bytes',pg_table_size(relid),
            'index_bytes',pg_indexes_size(relid))) from pg_stat_user_tables
            where schemaname='public'""").fetchone()[0]
    report["seconds"] = round(time.monotonic()-started, 3)
    (directory / (target + "-restore-report.json")).write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--directory", type=Path, default=ROOT / ".local/restore/s3-1")
    parser.add_argument("--target", choices=("local", "remote"), required=True)
    parser.add_argument("--approved-manifest-sha256")
    args = parser.parse_args()
    run(args.manifest, args.directory, args.target, args.approved_manifest_sha256)
