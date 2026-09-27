"""Snapshot reconciliation, minimal stores, and honest unlocated school/academy rows."""

import pandas as pd
from psycopg import sql
from psycopg.types.json import Jsonb

from ingest.copy_batches import chunked_copy

TABLE_COLUMNS = {
    "stores": ["store_id", "inds_lcls", "inds_mcls", "inds_scls", "floor", "geom"],
    "academies": [
        "id",
        "name",
        "institution_type",
        "registration_status",
        "field",
        "affiliation",
        "course_list",
        "course",
        "address",
        "geom",
        "geocode_failed",
        "geocode_provider",
        "geocode_reason",
        "source",
        "source_version",
        "estimated",
    ],
    "schools": [
        "id",
        "name",
        "level",
        "school_type",
        "address",
        "geom",
        "geocode_failed",
        "geocode_provider",
        "geocode_reason",
        "source",
        "source_version",
        "estimated",
    ],
}


def attach_geocodes(connection, frame):
    rows = connection.execute(
        "select address,provider,extensions.st_x(geom),extensions.st_y(geom),"
        "geocode_failed,failure_reason from public.geocode_cache "
        "order by address,geocode_failed,case provider when 'kakao' then 0 else 1 end"
    ).fetchall()
    cache = {}
    for address, provider, x, y, failed, reason in rows:
        cache.setdefault(address, (x, y, failed, provider, reason))
    resolved = []
    for address in frame.address:
        if not address:
            resolved.append((None, None, True, None, "empty_address"))
        elif address not in cache:
            raise ValueError("Unresolved address; complete geocoding before loading snapshot")
        else:
            resolved.append(cache[address])
    result = frame.copy()
    result[["lng", "lat", "geocode_failed", "geocode_provider", "geocode_reason"]] = resolved
    return result


def with_geometry(frame):
    result = frame.copy()
    x = pd.to_numeric(result.lng, errors="raise")
    y = pd.to_numeric(result.lat, errors="raise")
    present = x.notna() | y.notna()
    if not (x[present].between(124, 132) & y[present].between(33, 39)).all():
        raise ValueError("Invalid or incomplete EPSG:4326 coordinate")
    result["geom"] = [
        None if pd.isna(x) or pd.isna(y) else f"SRID=4326;POINT({x} {y})"
        for x, y in zip(result.lng, result.lat, strict=True)
    ]
    return result


def load_snapshot(connection, table, frame, *, source, version, raw_key, report):
    columns = TABLE_COLUMNS[table]
    identity = columns[0]
    if frame.empty or frame[identity].duplicated().any():
        raise ValueError("Refusing empty or duplicate snapshot")
    frame = with_geometry(frame)
    if table != "stores":
        frame = frame.assign(source=source, source_version=version, estimated=False)
    identifiers = sql.SQL(",").join(map(sql.Identifier, columns))
    target, stage = sql.Identifier("public", table), sql.Identifier("place_stage")
    values = columns[1:]
    assignments = sql.SQL(",").join(
        sql.SQL("{}=excluded.{}").format(sql.Identifier(c), sql.Identifier(c)) for c in values
    )
    if table != "stores":
        assignments += sql.SQL(",ingested_at=now()")
    old = sql.SQL(",").join(sql.SQL("t.{}").format(sql.Identifier(c)) for c in values)
    new = sql.SQL(",").join(sql.SQL("excluded.{}").format(sql.Identifier(c)) for c in values)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("select pg_advisory_xact_lock(7412402)")
        cursor.execute(
            sql.SQL(
                "create temporary table {} (like {} including defaults "
                "including constraints) on commit drop"
            ).format(stage, target)
        )
        cursor.execute(
            sql.SQL("alter table {} add primary key ({})").format(stage, sql.Identifier(identity))
        )
        with chunked_copy(
                cursor, sql.SQL("copy {} ({}) from stdin").format(stage, identifiers)) as copy:
            for row in frame[columns].itertuples(index=False, name=None):
                copy.write_row(tuple(None if pd.isna(value) else value for value in row))
        cursor.execute(
            sql.SQL(
                "insert into {} as t ({}) select {} from {} "
                "on conflict ({}) do update set {} "
                "where ({}) is distinct from ({})"
            ).format(
                target,
                identifiers,
                identifiers,
                stage,
                sql.Identifier(identity),
                assignments,
                old,
                new,
            )
        )
        cursor.execute(
            sql.SQL(
                "delete from {} t where not exists (select 1 from {} s where s.{}=t.{})"
            ).format(target, stage, sql.Identifier(identity), sql.Identifier(identity))
        )
        cursor.execute(
            "insert into ingest_private.place_snapshots(target_table,source,source_version,"
            "raw_key,row_count,located_count,report) values (%s,%s,%s,%s,%s,%s,%s) "
            "on conflict(target_table) do update set source=excluded.source,"
            "source_version=excluded.source_version,raw_key=excluded.raw_key,"
            "row_count=excluded.row_count,located_count=excluded.located_count,"
            "report=excluded.report,ingested_at=now()",
            (
                table,
                source,
                version,
                raw_key,
                len(frame),
                int(frame.geom.notna().sum()),
                Jsonb(report),
            ),
        )
        cursor.execute(
            "insert into ingest_private.ingest_runs "
            "(source,source_version,target_table,row_count) values (%s,%s,%s,%s)",
            (source, version, table, len(frame)),
        )
        cursor.execute(sql.SQL("drop table {}").format(stage))
    return len(frame)
