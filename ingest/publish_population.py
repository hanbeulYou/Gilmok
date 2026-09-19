"""Publish PR 2 resident/boundary snapshots, verify readback, then load local DB."""

import argparse
import json
from pathlib import Path

import duckdb
import pandas as pd

from ingest.admin_boundaries import (
    BOUNDARY_SOURCE,
    BOUNDARY_VERSION,
    prepare_admin_boundaries,
)
from ingest.common import RawStore, Settings
from ingest.database import connect_database
from ingest.population import normalize_residents
from ingest.population_database import load_resident_snapshot
from ingest.population_grid import grid_rows
from ingest.verify_population_storage import read_back


def publish_supporting(residents: Path, boundary: Path, grid: Path, month: str,
                       directory: Path, store: RawStore) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    normalized = normalize_residents(residents, month)
    admin = prepare_admin_boundaries(boundary, set(normalized.adm_cd))
    grid_rows(grid, set())  # Verify the actual CRS and every ID/geometry before labeling raw data.
    local = RawStore(Settings(directory / "staging"))
    frames = {"resident_population": pd.read_csv(
        residents, encoding="cp949", dtype=str, keep_default_na=False
    ), "admin_boundaries": admin}
    with duckdb.connect() as connection:
        connection.execute("LOAD spatial")
        frames["population_grid"] = connection.execute(
            "select * exclude(geom),ST_AsWKB(geom) as geometry_wkb,5179 as srid,"
            "'Seoul Open Data Plaza' as attribution from ST_Read(?)", [str(grid)]
        ).df()
    reports = []
    for source, frame in frames.items():
        # Boundary keys use the associated population snapshot month. Actual
        # boundary version remains in provenance, not inferred from this key.
        path = Path(local.write_parquet(source, month, frame))
        publication = store.publish_file(source, month, path)
        readback = directory / f"{source}.parquet"
        read_report = read_back(store, source, month, readback)
        with duckdb.connect() as connection:
            connection.read_parquet(str(path)).create_view("original")
            connection.read_parquet(str(readback)).create_view("readback")
            differences = connection.execute(
                "select count(*) from ((select * from original except all select * from readback) "
                "union all (select * from readback except all select * from original))"
            ).fetchone()[0]
        if differences:
            raise ValueError(f"Published {source} rows do not match")
        reports.append({**publication, **read_report, "different_rows": differences})
    with connect_database(local_only=True) as connection:
        loaded = load_resident_snapshot(
            connection, admin.to_dict("records"), normalized.to_dict("records"),
            boundary_source=BOUNDARY_SOURCE, boundary_version=BOUNDARY_VERSION,
            source="mois_resident_population", source_version=month,
        )
        totals = connection.execute(
            "select age_band,sum(population),count(*) from public.population_age "
            "where source='mois_resident_population' group by age_band order by age_band"
        ).fetchall()
        sizes = connection.execute(
            "select pg_total_relation_size('public.admin_dongs'),"
            "pg_total_relation_size('public.population_age'),pg_database_size(current_database())"
        ).fetchone()
    report = {"publications": reports, "loaded": loaded, "resident_totals": totals,
              "sizes": dict(zip(["admin_dongs_bytes", "population_age_bytes", "database_bytes"],
                                sizes))}
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("residents", "boundary", "grid", "directory"):
        parser.add_argument(f"--{option}", type=Path, required=True)
    parser.add_argument("--month", required=True)
    args = parser.parse_args()
    print(json.dumps(publish_supporting(args.residents, args.boundary, args.grid, args.month,
                                       args.directory, RawStore(Settings.from_env())), indent=2))
