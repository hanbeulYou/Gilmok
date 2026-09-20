"""Atomic Gangnam snapshots with explicit footprint quality and register joins."""

import pandas as pd
from psycopg import sql
from psycopg.types.json import Jsonb

from ingest.building_footprints import SHP_SOURCE, WFS_SOURCE

FOOTPRINT_COLUMNS = [
    "id",
    "source_id",
    "gis_id",
    "pnu",
    "source",
    "source_version",
    "source_register_pk",
    "candidate_register_pk",
    "source_height_m",
    "floors_above",
    "floors_below",
    "main_use_code",
    "main_use_name",
    "height_m",
    "height_source",
    "height_estimated",
    "source_geometry_wkb",
    "source_srid",
]
TITLE_COLUMNS = [
    "register_pk",
    "pnu",
    "name",
    "dong_name",
    "floors_above",
    "floors_below",
    "height_m",
    "main_use_code",
    "main_use_name",
    "other_use",
    "gross_area",
    "passenger_elevators",
    "emergency_elevators",
    "use_approval_date",
]
FLOOR_COLUMNS = [
    "id",
    "register_pk",
    "pnu",
    "floor_kind",
    "floor_kind_name",
    "floor_no",
    "floor_name",
    "use_code",
    "use_name",
    "other_use",
    "area",
    "main_attached_code",
]


def copy_frame(cursor, table, columns, frame):
    identifiers = sql.SQL(",").join(map(sql.Identifier, columns))
    with cursor.copy(
        sql.SQL("copy {} ({}) from stdin").format(sql.Identifier(table), identifiers)
    ) as copy:
        integral = {
            "floors_above",
            "floors_below",
            "source_srid",
            "passenger_elevators",
            "emergency_elevators",
            "floor_no",
        }
        for row in frame[columns].itertuples(index=False, name=None):
            values = []
            for column, value in zip(columns, row, strict=True):
                if pd.isna(value):
                    value = None
                elif column in integral:
                    if float(value) != int(value):
                        raise ValueError("Non-integral floor/elevator count")
                    value = int(value)
                values.append(value)
            copy.write_row(tuple(values))


def stage_footprints(connection, frame):
    if frame.empty or frame.id.duplicated().any() or SHP_SOURCE not in set(frame.source):
        raise ValueError("A footprint snapshot needs distinct IDs and a primary SHP source")
    with connection.cursor() as cursor:
        cursor.execute("""
          create temporary table gilmok_building_stage (
            id text primary key,source_id text,gis_id text,pnu text,source text,source_version text,
            source_register_pk text,candidate_register_pk text,source_height_m float8,
            floors_above integer,floors_below integer,main_use_code text,main_use_name text,
            height_m float8,height_source text,height_estimated boolean,
            source_geometry_wkb bytea,source_srid integer,
            original_geom extensions.geometry,clean_geom extensions.geometry,
            geom5186 extensions.geometry,geometry_repaired boolean,exclusion_reason text
          ) on commit drop
        """)
        copy_frame(cursor, "gilmok_building_stage", FOOTPRINT_COLUMNS, frame)
        cursor.execute("""
          update gilmok_building_stage set original_geom=extensions.st_setsrid(
            extensions.st_geomfromwkb(source_geometry_wkb),source_srid)
        """)
        cursor.execute("""
          update gilmok_building_stage set
            geometry_repaired=not extensions.st_isvalid(original_geom),
            clean_geom=case when extensions.st_isvalid(original_geom) then original_geom
                           else extensions.st_makevalid(original_geom) end
        """)
        cursor.execute("""
          update gilmok_building_stage set exclusion_reason='non_polygon_supplement'
          where source='vworld_wfs_supplement' and (
            not extensions.st_isvalid(clean_geom) or extensions.st_isempty(clean_geom)
            or extensions.st_geometrytype(clean_geom) not in ('ST_Polygon','ST_MultiPolygon'))
        """)
        bad = cursor.execute("""
          select count(*) from gilmok_building_stage where exclusion_reason is null and (
            not extensions.st_isvalid(clean_geom) or extensions.st_isempty(clean_geom)
            or extensions.st_geometrytype(clean_geom) not in ('ST_Polygon','ST_MultiPolygon')
            or (geometry_repaired and (
              not extensions.st_equals(extensions.st_envelope(original_geom),
                                       extensions.st_envelope(clean_geom))
              or abs(extensions.st_area(original_geom)-extensions.st_area(clean_geom))
                 > greatest(1e-10,abs(extensions.st_area(original_geom))*1e-6))))
        """).fetchone()[0]
        if bad:
            raise ValueError("Geometry repair changed area/bounds/type; inspect before loading")
        cursor.execute("""
          update gilmok_building_stage set geom5186=extensions.st_transform(clean_geom,5186)
        """)
        cursor.execute("""
          create index on gilmok_building_stage using gist(geom5186)
            where source='gis_buildings_shp'
        """)
        cursor.execute("analyze gilmok_building_stage")
        # A supplement must be missing spatially too, not merely lack the SHP GIS ID.
        # Ignore projected overlap at or below 0.01 square metres as coordinate noise.
        cursor.execute("""
          update gilmok_building_stage w set exclusion_reason='overlaps_primary'
          where w.source='vworld_wfs_supplement' and w.exclusion_reason is null and exists (
            select 1 from gilmok_building_stage p where p.source='gis_buildings_shp'
              and p.geom5186 && w.geom5186
              and extensions.st_intersects(p.geom5186,w.geom5186)
              and extensions.st_area(extensions.st_intersection(p.geom5186,w.geom5186))>0.01)
        """)
        duplicates = cursor.execute("""
          select count(*)-count(distinct extensions.st_asbinary(geom5186))
          from gilmok_building_stage where exclusion_reason is null
        """).fetchone()[0]
        if duplicates:
            raise ValueError("Duplicate normalized geometry remains; inspect source attributes")
        counts = cursor.execute("""
          select source,count(*),count(*) filter(where geometry_repaired),
            count(*) filter(where exclusion_reason is not null),
            count(*) filter(where exclusion_reason is null)
          from gilmok_building_stage group by source order by source
        """).fetchall()
        exclusions = cursor.execute("""
          select id,exclusion_reason from gilmok_building_stage
          where exclusion_reason is not null order by id
        """).fetchall()
    return {
        "sources": {
            source: {
                "candidates": n,
                "repaired": fixed,
                "excluded_count": excluded,
                "retained": retained,
            }
            for source, n, fixed, excluded, retained in counts
        },
        "excluded_supplements": [
            {"id": identity, "reason": reason} for identity, reason in exclusions
        ],
    }


def load_snapshot(connection, footprints, titles, floors, *, snapshot, raw_objects, load=True):
    if titles.empty or floors.empty or titles.register_pk.duplicated().any():
        raise ValueError("Refusing empty register data or duplicate title keys")
    if floors.id.duplicated().any():
        raise ValueError("Floor source row identities are not unique")
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("select pg_advisory_xact_lock(7412501)")
        report = stage_footprints(connection, footprints)
        if not load:
            cursor.execute("drop table gilmok_building_stage")
            return report
        for table in ("buildings", "building_registers", "building_floors"):
            foreign_scope = cursor.execute(
                sql.SQL(
                    "select count(*) from public.{} where pnu is not null and left(pnu,5)<>'11680'"
                ).format(sql.Identifier(table))
            ).fetchone()[0]
            if foreign_scope:
                raise ValueError("Gangnam loader refuses to replace another district")
        # Existing snapshot remains visible until every relation and audit commits together.
        cursor.execute("delete from public.buildings")
        cursor.execute("delete from public.building_floors")
        cursor.execute("delete from public.building_registers")
        cursor.execute("""
          create temporary table gilmok_title_stage
          (like public.building_registers including defaults) on commit drop
        """)
        cursor.execute("alter table gilmok_title_stage alter source_version drop not null")
        copy_frame(cursor, "gilmok_title_stage", TITLE_COLUMNS, titles)
        cols = sql.SQL(",").join(map(sql.Identifier, TITLE_COLUMNS))
        cursor.execute(
            sql.SQL(
                "insert into public.building_registers ({},source_version) "
                "select {},%s from gilmok_title_stage"
            ).format(cols, cols),
            (snapshot,),
        )
        cursor.execute("""
          create temporary table gilmok_floor_stage (
            id text primary key,register_pk text,pnu text,floor_kind text,floor_kind_name text,
            floor_no integer,floor_name text,use_code text,use_name text,other_use text,
            area float8,main_attached_code text
          ) on commit drop
        """)
        copy_frame(cursor, "gilmok_floor_stage", FLOOR_COLUMNS, floors)
        cursor.execute(
            """
          insert into public.building_floors (
            id,source_register_pk,register_pk,register_link_status,pnu,floor_kind,floor_kind_name,
            floor_no,floor_name,use_code,use_name,other_use,area,main_attached_code,source_version)
          select f.id,f.register_pk,case when f.pnu=r.pnu then r.register_pk end,
            case when f.pnu is null then 'unsupported_parcel'
                 when r.register_pk is null then 'title_missing'
                 when f.pnu<>r.pnu or r.pnu is null then 'pnu_mismatch' else 'matched' end,
            f.pnu,f.floor_kind,f.floor_kind_name,f.floor_no,f.floor_name,f.use_code,f.use_name,
            f.other_use,f.area,f.main_attached_code,%s
          from gilmok_floor_stage f left join public.building_registers r using(register_pk)
        """,
            (snapshot,),
        )
        cursor.execute("""
          insert into public.buildings (
            id,source_id,gis_id,pnu,source,source_version,source_register_pk,register_pk,
            register_link_status,geom,geometry_repaired,source_height_m,floors_above,floors_below,
            main_use_code,main_use_name,height_m,height_source,height_estimated)
          select b.id,b.source_id,b.gis_id,b.pnu,b.source,b.source_version,b.source_register_pk,
            case when b.source='gis_buildings_shp' and b.pnu=r.pnu then r.register_pk end,
            case when b.source='vworld_wfs_supplement' then 'supplemental_unlinked'
                 when b.candidate_register_pk is null then 'missing_source_pk'
                 when r.register_pk is null then 'title_not_found'
                 when b.pnu<>r.pnu or r.pnu is null then 'pnu_mismatch' else 'matched' end,
            extensions.st_multi(extensions.st_transform(b.clean_geom,4326)),
            b.geometry_repaired,b.source_height_m,b.floors_above,b.floors_below,
            b.main_use_code,b.main_use_name,b.height_m,b.height_source,b.height_estimated
          from gilmok_building_stage b left join public.building_registers r
            on b.source='gis_buildings_shp' and r.register_pk=b.candidate_register_pk
          where b.exclusion_reason is null
        """)
        report["row_counts"] = {}
        for table in ("buildings", "building_registers", "building_floors"):
            n = cursor.execute(
                sql.SQL("select count(*) from public.{}").format(sql.Identifier(table))
            ).fetchone()[0]
            report["row_counts"][table] = n
            cursor.execute(
                "insert into ingest_private.ingest_runs "
                "(source,source_version,target_table,row_count) values (%s,%s,%s,%s)",
                ("gangnam_buildings", snapshot, table, n),
            )
        report["register_links"] = dict(
            cursor.execute(
                "select register_link_status,count(*) from public.buildings group by 1"
            ).fetchall()
        )
        report["floor_links"] = dict(
            cursor.execute(
                "select register_link_status,count(*) from public.building_floors group by 1"
            ).fetchall()
        )
        report["height_sources"] = dict(
            cursor.execute(
                "select height_source,count(*) from public.buildings group by 1"
            ).fetchall()
        )
        if cursor.execute(
            "select count(*) from public.buildings where source=%s and register_pk is not null",
            (WFS_SOURCE,),
        ).fetchone()[0]:
            raise ValueError("Supplemental footprints must never join building registers")
        cursor.execute(
            """
          insert into ingest_private.building_snapshots(scope,snapshot_version,raw_objects,report)
          values ('11680',%s,%s,%s) on conflict(scope) do update set
            snapshot_version=excluded.snapshot_version,raw_objects=excluded.raw_objects,
            report=excluded.report,ingested_at=now()
        """,
            (snapshot, Jsonb(raw_objects), Jsonb(report)),
        )
        report["database_during_transaction_bytes"] = cursor.execute(
            "select pg_database_size(current_database())"
        ).fetchone()[0]
        cursor.execute("drop table gilmok_building_stage,gilmok_title_stage,gilmok_floor_stage")
    return report
