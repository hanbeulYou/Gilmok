"""Atomic loading of normalized EPSG:4326 boundaries into Supabase."""

import os
from collections.abc import Iterable, Mapping
from contextlib import contextmanager

import psycopg
from dotenv import dotenv_values
from psycopg import sql

from ingest.common import ROOT

LOCAL_DB_URL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
BOUNDARIES = {"admin_dongs": "adm_cd", "census_blocks": "tot_reg_cd"}


@contextmanager
def connect_database():
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    url = env.get("SUPABASE_DB_URL") or LOCAL_DB_URL
    try:
        connection = psycopg.connect(url, connect_timeout=5)
    except psycopg.Error:
        message = "Cannot connect to Supabase; check service and SUPABASE_DB_URL"
        raise RuntimeError(message) from None
    with connection:
        yield connection


def load_boundaries(
    connection: psycopg.Connection,
    table: str,
    rows: Iterable[Mapping[str, str]],
    *,
    source: str,
    source_version: str,
    srid: int,
) -> int:
    """Replace one source snapshot atomically, including provenance and success audit.

    Inputs are normalized code/name/WKT records, not unverified external API schemas.
    Coordinate conversion belongs in the source adapter and must finish before this call.
    """
    if table not in BOUNDARIES:
        raise ValueError("Only admin_dongs and census_blocks are boundary load targets")
    if srid != 4326:
        raise ValueError("Boundaries must be transformed to EPSG:4326 before loading")
    if not source.strip() or not source_version.strip():
        raise ValueError("Source and source_version are required")
    identifier = sql.Identifier("public", table)
    code_column = sql.Identifier(BOUNDARIES[table])
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "create temporary table gilmok_boundary_stage "
            "(code text, name text, wkt text) on commit drop"
        )
        count = 0
        with cursor.copy("copy pg_temp.gilmok_boundary_stage (code, name, wkt) from stdin") as copy:
            for row in rows:
                copy.write_row((row["code"], row["name"], row["wkt"]))
                count += 1
        if count == 0:
            raise ValueError("Refusing to replace boundaries with an empty snapshot")
        cursor.execute(sql.SQL("delete from {} where source = %s").format(identifier), (source,))
        cursor.execute(
            sql.SQL(
                "insert into {} ({}, name, geom, source, source_version, estimated) "
                "select code, name, extensions.st_multi(extensions.st_geomfromtext(wkt, 4326)), "
                "%s, %s, false from pg_temp.gilmok_boundary_stage"
            ).format(identifier, code_column),
            (source, source_version),
        )
        cursor.execute(
            "insert into ingest_private.ingest_runs "
            "(source, source_version, target_table, row_count) values (%s, %s, %s, %s)",
            (source, source_version, table, count),
        )
        cursor.execute("drop table pg_temp.gilmok_boundary_stage")
    return count
