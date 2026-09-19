"""Local atomic transit snapshots; geometry scope uses validated Seoul boundaries."""

import pandas as pd
from psycopg.types.json import Jsonb


def seoul_stops(connection, stops: pd.DataFrame) -> pd.DataFrame:
    with connection.transaction(), connection.cursor() as cursor:
        if cursor.execute("select count(*) from public.admin_dongs").fetchone()[0] != 427:
            raise ValueError("Expected the validated 427 Seoul administrative boundaries")
        cursor.execute("create temporary table transit_location_stage "
                       "(id text, lng float8, lat float8) on commit drop")
        with cursor.copy("copy transit_location_stage from stdin") as copy:
            for row in stops.itertuples():
                copy.write_row((row.stop_id, row.lng, row.lat))
        ids = {row[0] for row in cursor.execute(
            "select s.id from transit_location_stage s where exists "
            "(select 1 from public.admin_dongs a where extensions.st_covers(a.geom, "
            "extensions.st_setsrid(extensions.st_makepoint(s.lng,s.lat),4326)))"
        )}
        cursor.execute("drop table transit_location_stage")
    return stops[stops.stop_id.isin(ids)].copy()


def load_snapshot(connection, stops, boardings, reports, *, start, end, coordinate_version):
    if stops.empty or boardings.empty or set(reports) != {"subway", "bus"}:
        raise ValueError("Refusing an empty or incomplete transit snapshot")
    if stops.stop_id.duplicated().any() or boardings.duplicated(["stop_id", "hour"]).any():
        raise ValueError("Duplicate snapshot identities")
    if not set(boardings.stop_id).issubset(set(stops.stop_id)):
        raise ValueError("Boarding without a stop")
    expected = set(range(24))
    if any(set(group.hour) != expected for _, group in boardings.groupby("stop_id")):
        raise ValueError("Expected 24 hours for every observed stop")
    version = f"{start}/{end}"
    with connection.transaction(), connection.cursor() as cursor:
        # Serialize replacement so concurrent runs cannot mix coordinate/count snapshots.
        cursor.execute("select pg_advisory_xact_lock(7412303)")
        cursor.execute("delete from public.transit_boardings")
        cursor.execute("delete from public.transit_stops")
        with cursor.copy("copy public.transit_stops "
                         "(id,type,name,line,geom,source,source_version) from stdin") as copy:
            for row in stops.itertuples():
                copy.write_row((row.stop_id, row.type, row.name, row.line,
                                f"SRID=4326;POINT({row.lng} {row.lat})",
                                f"seoul_{row.type}_stops", coordinate_version))
        with cursor.copy("copy public.transit_boardings "
                         "(stop_id,hour,boarding,alighting,sample_months,period_start,period_end,"
                         "source,source_version) from stdin") as copy:
            for row in boardings.itertuples():
                copy.write_row((row.stop_id, row.hour,
                                None if pd.isna(row.boarding) else row.boarding,
                                None if pd.isna(row.alighting) else row.alighting,
                                row.sample_months, start, end,
                                f"seoul_{row.stop_id.split(':')[0]}_boardings", version))
        for kind, report in reports.items():
            cursor.execute(
                "insert into ingest_private.transit_coverage(type,report) values (%s,%s) "
                "on conflict(type) do update set report=excluded.report,ingested_at=now()",
                (kind, Jsonb(report)),
            )
        for table, count in (("transit_stops", len(stops)),
                             ("transit_boardings", len(boardings))):
            cursor.execute("insert into ingest_private.ingest_runs "
                           "(source,source_version,target_table,row_count) values (%s,%s,%s,%s)",
                           ("seoul_transit", version, table, count))
    return {"stops": len(stops), "boardings": len(boardings)}
