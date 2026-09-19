"""Atomic loading of verified grid boundaries; source validation is in population_grid."""

from collections.abc import Iterable, Mapping

import psycopg
from psycopg import sql

from ingest.database import load_boundaries
from ingest.living_population import POPULATION_COLUMNS


def load_resident_snapshot(connection: psycopg.Connection, boundaries: Iterable[Mapping],
                           residents: Iterable[Mapping], *, boundary_source: str,
                           boundary_version: str, source: str, source_version: str) -> dict:
    """Commit matching current boundaries and all three resident bands atomically."""
    if not source.strip() or not source_version.strip():
        raise ValueError("Source and source_version are required")
    boundaries, residents = list(boundaries), list(residents)
    codes = {row["code"] for row in boundaries}
    expected = {(code, band) for code in codes for band in ("5_9", "10_14", "15_18")}
    actual = [(row["adm_cd"], row["age_band"]) for row in residents]
    if not expected or set(actual) != expected or len(actual) != len(expected):
        raise ValueError("Exactly three resident bands per boundary are required")
    if len({str(row["ref_month"]) for row in residents}) != 1:
        raise ValueError("A resident snapshot must have one month")
    with connection.transaction(), connection.cursor() as cursor:
        count = load_boundaries(connection, "admin_dongs", boundaries,
                                source=boundary_source, source_version=boundary_version, srid=4326)
        cursor.execute("delete from public.population_age where source=%s", (source,))
        with cursor.copy(
            "copy public.population_age "
            "(adm_cd,age_band,population,ref_month,source,source_version) from stdin"
        ) as copy:
            for row in residents:
                copy.write_row((row["adm_cd"], row["age_band"], row["population"],
                                row["ref_month"], source, source_version))
        cursor.execute("set constraints public.population_age_dong_fkey immediate")
        cursor.execute("set constraints public.population_age_dong_fkey deferred")
        cursor.execute(
            "insert into ingest_private.ingest_runs "
            "(source,source_version,target_table,row_count) values (%s,%s,%s,%s)",
            (source, source_version, "population_age", len(residents)),
        )
    return {"boundaries": count, "residents": len(residents)}


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


def load_living_population(
    connection: psycopg.Connection,
    rows: Iterable[Mapping],
    *,
    source: str,
    source_version: str,
    resolution_m: int = 250,
) -> int:
    """Atomically replace one source/resolution profile, including its success audit."""
    if not source.strip() or not source_version.strip():
        raise ValueError("Source and source_version are required")
    if resolution_m != 250:
        raise ValueError("Only the verified 250m source is supported by this loader")
    fields = ["cell_id", "dow_type", "hour", *POPULATION_COLUMNS,
              "sample_days", "period_start", "period_end"]
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "create temporary table gilmok_living_stage "
            "(like public.living_pop including defaults) on commit drop"
        )
        columns = ["resolution_m", *fields, "source", "source_version"]
        count = 0
        with cursor.copy(sql.SQL("copy pg_temp.gilmok_living_stage ({}) from stdin").format(
            sql.SQL(",").join(map(sql.Identifier, columns))
        )) as copy:
            for row in rows:
                copy.write_row((resolution_m, *(row[field] for field in fields),
                                source, source_version))
                count += 1
        if not count:
            raise ValueError("Refusing to replace living population with an empty snapshot")
        periods = cursor.execute(
            "select count(distinct (period_start,period_end)) from pg_temp.gilmok_living_stage"
        ).fetchone()[0]
        if periods != 1:
            raise ValueError("A snapshot must have one common aggregation period")
        # A valid-date count must also fit its own weekday/weekend calendar, not only
        # the total period. Calculate the two limits once per snapshot.
        invalid = cursor.execute(
            "with period as (select distinct period_start,period_end "
            "from pg_temp.gilmok_living_stage), calendar as ("
            "select case when extract(isodow from d) in (6,7) then 'weekend' "
            "else 'weekday' end as dow_type,count(*) as days from period, "
            "generate_series(period_start::timestamp,period_end::timestamp,interval '1 day') d "
            "group by 1) select count(*) from pg_temp.gilmok_living_stage s "
            "left join calendar c using(dow_type) where s.sample_days>coalesce(c.days,0)"
        ).fetchone()[0]
        if invalid:
            raise ValueError("sample_days exceeds its weekday/weekend calendar")
        cursor.execute(
            "delete from public.living_pop where source=%s and resolution_m=%s",
            (source, resolution_m),
        )
        cursor.execute("insert into public.living_pop select * from pg_temp.gilmok_living_stage")
        # Check at this savepoint too, so unknown cells cannot produce a success audit.
        cursor.execute("set constraints public.living_pop_cell_fkey immediate")
        cursor.execute("set constraints public.living_pop_cell_fkey deferred")
        cursor.execute(
            "insert into ingest_private.ingest_runs "
            "(source,source_version,target_table,row_count) values (%s,%s,%s,%s)",
            (source, source_version, "living_pop", count),
        )
        cursor.execute("drop table pg_temp.gilmok_living_stage")
    return count
