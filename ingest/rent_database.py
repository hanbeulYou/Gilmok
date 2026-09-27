"""Atomic PR 6 summaries: no individual sales enter Postgres."""

from datetime import date

import duckdb
import pandas as pd
from psycopg import sql
from psycopg.types.json import Jsonb

from ingest.common import ROOT
from ingest.copy_batches import chunked_copy
from ingest.legal_boundaries import GANGNAM_DONGS

STAT_COLUMNS = (
    "legal_dong_code", "trade_kind", "aggregation_level", "floor",
    "median_price_per_m2", "sample_count", "unknown_floor_count", "area_basis",
)
SURVEY_COLUMNS = (
    "area_code", "building_class", "quarter", "rent_per_m2", "vacancy_rate",
    "rent_statbl_id", "rent_cls_id", "vacancy_statbl_id", "vacancy_cls_id",
    "source", "source_version",
)


def aggregate_trades(normalized_frame):
    if normalized_frame.empty:
        raise ValueError("A complete trade snapshot cannot be empty")
    if normalized_frame.loc[normalized_frame.eligible, "legal_dong_code"].isna().any():
        raise ValueError("Eligible trades must have verified legal-dong codes")
    with duckdb.connect() as connection:
        connection.register("normalized_trades", normalized_frame)
        result = connection.execute(
            (ROOT / "ingest/sql/commercial_trade_stats.sql").read_text()
        )
        return pd.DataFrame(result.fetchall(), columns=[c[0] for c in result.description])


def _copy(cursor, table, columns, frame):
    with chunked_copy(cursor, sql.SQL("copy {} ({}) from stdin").format(
        sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, columns))
    )) as stream:
        for row in frame.loc[:, list(columns)].itertuples(index=False, name=None):
            values = []
            for column, value in zip(columns, row):
                if pd.isna(value):
                    value = None
                elif column in {"floor", "sample_count", "unknown_floor_count"}:
                    if int(value) != value:
                        raise ValueError("Non-integral trade floor or sample count")
                    value = int(value)
                values.append(value)
            stream.write_row(tuple(values))


def load_trade_snapshot(connection, boundaries, stats, *, period_start, period_end,
                        source_version, report):
    """Replace the current Gangnam window in one transaction; preserve unrelated data."""
    start, end = date.fromisoformat(str(period_start)), date.fromisoformat(str(period_end))
    if end < start or not source_version:
        raise ValueError("Invalid trade period or source version")
    if (boundaries.empty or boundaries.code8.duplicated().any()
            or dict(zip(boundaries.code8, boundaries.name)) != GANGNAM_DONGS):
        raise ValueError("Expected the complete verified 14 legal-dong boundaries")
    if stats.empty or not set(stats.legal_dong_code) <= set(boundaries.code8):
        raise ValueError("Trade statistics need verified legal-dong boundaries and samples")
    keys = ["legal_dong_code", "trade_kind", "aggregation_level", "floor"]
    if stats.duplicated(keys).any():
        raise ValueError("Duplicate trade summary key")
    all_count = int(stats.loc[stats.aggregation_level == "all_floors", "sample_count"].sum())
    if "eligible_count" in report and all_count != report["eligible_count"]:
        raise ValueError("Summary sample counts differ from eligible raw records")
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("select pg_advisory_xact_lock(11680,6)")
        cursor.execute("""create temporary table gilmok_legal_stage (
            code8 text primary key,name text,wkt text,source text,source_version text
        ) on commit drop""")
        _copy(cursor, "gilmok_legal_stage",
              ("code8", "name", "wkt", "source", "source_version"), boundaries)
        cursor.execute("""insert into public.legal_dongs
            (code8,name,geom,source,source_version)
            select code8,name,extensions.st_multi(extensions.st_geomfromtext(wkt,4326)),
                source,source_version from gilmok_legal_stage
            on conflict(code8) do update set name=excluded.name,geom=excluded.geom,
                source=excluded.source,source_version=excluded.source_version,ingested_at=now()
        """)
        cursor.execute("""create temporary table gilmok_trade_stage (
            legal_dong_code text,trade_kind text,aggregation_level text,floor integer,
            median_price_per_m2 numeric,sample_count integer,unknown_floor_count integer,
            area_basis text) on commit drop""")
        _copy(cursor, "gilmok_trade_stage", STAT_COLUMNS, stats)
        cursor.execute("delete from public.commercial_trade_stats")
        cursor.execute("""insert into public.commercial_trade_stats
            (legal_dong_code,trade_kind,aggregation_level,floor,median_price_per_m2,
             sample_count,unknown_floor_count,area_basis,period_start,period_end,source,
             source_version)
            select legal_dong_code,trade_kind,aggregation_level,floor,median_price_per_m2,
                sample_count,unknown_floor_count,area_basis,%s,%s,'molit_commercial_trades',%s
            from gilmok_trade_stage""", (start, end, source_version))
        result = {**report, "summary_rows": len(stats), "eligible_count": all_count,
                  "legal_dongs": len(boundaries), "period_start": str(start),
                  "period_end": str(end), "source_version": source_version}
        _save_report(cursor, "commercial_trades", source_version, result)
        cursor.execute("drop table gilmok_legal_stage,gilmok_trade_stage")
        return result


def _save_report(cursor, source, source_version, report):
    cursor.execute("""insert into ingest_private.rent_snapshots(source,source_version,report)
        values(%s,%s,%s) on conflict(source) do update set
        source_version=excluded.source_version,report=excluded.report,ingested_at=now()
    """, (source, source_version, Jsonb(report)))


def load_survey_snapshot(connection, areas, surveys, *, source_version, report):
    """Load evidenced areas; region coverage must follow its official survey definition."""
    area_columns = ("area_code", "area_name", "level", "gu_code", "wkt", "valid_from",
                    "valid_to", "mapping_verified", "mapping_evidence", "source",
                    "source_version")
    if areas.empty or surveys.empty or areas.area_code.duplicated().any():
        raise ValueError("Survey load requires nonempty, distinct evidenced areas")
    if not set(surveys.area_code) <= set(areas.area_code):
        raise ValueError("Survey has an unmapped area")
    if (areas.mapping_evidence.isna().any()
            or not areas.mapping_evidence.str.strip().astype(bool).all()):
        raise ValueError("Survey mappings need evidence or a missing-definition reason")
    if areas.loc[areas.mapping_verified.eq(True), "wkt"].isna().any():
        raise ValueError("Verified spatial mappings require geometry")
    if not set(areas.level) <= {"district", "region"}:
        raise ValueError("Only verified district or region survey levels are supported")
    if surveys.duplicated(["area_code", "building_class", "quarter"]).any():
        raise ValueError("Duplicate survey summary key")
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("select pg_advisory_xact_lock(11680,6)")
        cursor.execute("""create temporary table gilmok_rent_area_stage (
            area_code text,area_name text,level text,gu_code text,wkt text,valid_from date,
            valid_to date,mapping_verified boolean,mapping_evidence text,source text,
            source_version text) on commit drop""")
        _copy(cursor, "gilmok_rent_area_stage", area_columns, areas)
        cursor.execute("""insert into public.rent_areas
            (area_code,area_name,level,gu_code,geom,valid_from,valid_to,mapping_verified,
             mapping_evidence,source,source_version)
            select area_code,area_name,level,gu_code,
                extensions.st_multi(extensions.st_geomfromtext(wkt,4326)),valid_from,valid_to,
                mapping_verified,mapping_evidence,source,source_version
            from gilmok_rent_area_stage on conflict(area_code) do update set
                area_name=excluded.area_name,level=excluded.level,gu_code=excluded.gu_code,
                geom=excluded.geom,valid_from=excluded.valid_from,valid_to=excluded.valid_to,
                mapping_verified=excluded.mapping_verified,mapping_evidence=excluded.mapping_evidence,
                source=excluded.source,source_version=excluded.source_version,ingested_at=now()
        """)
        cursor.execute("""create temporary table gilmok_survey_stage
            (like public.rent_survey including defaults) on commit drop""")
        _copy(cursor, "gilmok_survey_stage", SURVEY_COLUMNS, surveys)
        # This loader receives a complete source snapshot (all requested types/metrics).
        # Replacing just incoming keys would retain provider-deleted rows and stale quarters.
        cursor.execute("""delete from public.rent_survey
            where source in (select distinct source from gilmok_survey_stage)""")
        cursor.execute(sql.SQL("insert into public.rent_survey ({0}) select {0} "
                               "from gilmok_survey_stage").format(
            sql.SQL(",").join(map(sql.Identifier, SURVEY_COLUMNS))))
        result = {**report, "survey_rows": len(surveys), "mapped_areas": len(areas)}
        _save_report(cursor, "rent_survey", source_version, result)
        cursor.execute("drop table gilmok_rent_area_stage,gilmok_survey_stage")
        return result
