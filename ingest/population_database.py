"""Atomic loading of verified grid boundaries; source validation is in population_grid."""

from collections.abc import Iterable, Mapping

import psycopg


def load_population_cells(
    connection: psycopg.Connection,
    rows: Iterable[Mapping],
    *,
    source: str,
    source_version: str,
    resolution_m: int = 250,
) -> int:
    """Replace one source/resolution snapshot and audit it in the same transaction.

    Callers supply WGS84 polygons validated by the source adapter. Failures preserve
    the previous snapshot. No conversion, boundary interpolation, or API calls here.
    """
    if not source.strip() or not source_version.strip():
        raise ValueError("Source and source_version are required")
    if resolution_m != 250:
        raise ValueError("Only the verified 250m source is supported by this loader")
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "create temporary table gilmok_cell_stage "
            "(cell_id text, wkt text, boundary_generated boolean) on commit drop"
        )
        count = 0
        with cursor.copy("copy pg_temp.gilmok_cell_stage from stdin") as copy:
            for row in rows:
                if not isinstance(row["boundary_generated"], bool):
                    raise ValueError("boundary_generated must be boolean")
                copy.write_row((row["cell_id"], row["wkt"], row["boundary_generated"]))
                count += 1
        if not count:
            raise ValueError("Refusing to replace cells with an empty snapshot")
        cursor.execute(
            "delete from public.population_cells where source=%s and resolution_m=%s",
            (source, resolution_m),
        )
        cursor.execute(
            "insert into public.population_cells "
            "(resolution_m, cell_id, geom, boundary_generated, source, source_version) "
            "select %s, cell_id, extensions.st_geomfromtext(wkt,4326), "
            "boundary_generated, %s, %s from pg_temp.gilmok_cell_stage",
            (resolution_m, source, source_version),
        )
        cursor.execute(
            "insert into ingest_private.ingest_runs "
            "(source, source_version, target_table, row_count) values (%s,%s,%s,%s)",
            (source, source_version, "population_cells", count),
        )
        cursor.execute("drop table pg_temp.gilmok_cell_stage")
    return count
