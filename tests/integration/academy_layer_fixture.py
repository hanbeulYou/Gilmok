"""Synthetic-only academy data shared by RPC tests and local performance measurement."""

import json
from pathlib import Path

from psycopg.types.json import Jsonb

LAT, LNG = 37.5, 127.0
FIELD = "입시.검정 및 보습"
REVISION, REVIEW, SHA = "synthetic-v1", "synthetic-review-101", "a" * 64


def seed(db, count=300):
    if db.execute(
        "select exists(select 1 from public.academies where source<>'academy-layer-fixture')"
    ).fetchone()[0]:
        raise ValueError(
            "Use an empty synthetic-only local database; never replace real source data"
        )
    db.execute((Path(__file__).parents[1] / "fixtures/academy-display-schema.sql").read_text())
    for table in [
        "app_private.academy_layer_release",
        "app_private.academy_coordinate_reviews",
        "app_private.academy_display",
        "app_private.academy_display_release",
        "public.academies",
    ]:
        db.execute("delete from " + table)
    db.execute("delete from ingest_private.place_snapshots where target_table='academies'")
    db.execute("""insert into public.admin_dongs(adm_cd,name,geom,source,source_version)
        values('11-academy-fixture','합성 경계',extensions.st_multi(
        extensions.st_makeenvelope(126.8,37.3,127.2,37.7,4326)),'academy-layer-fixture','synthetic')
        on conflict(adm_cd) do nothing""")
    db.execute(
        """insert into public.academies(id,name,institution_type,registration_status,
        field,affiliation,course_list,course,address,geom,geocode_failed,geocode_provider,
        source,source_version)
        select 'synthetic-'||lpad(i::text,6,'0'),'합성 공개 기관 '||i,
          case when i%%2=0 then '학원' else '교습소' end,'개원',
          case when i%%3=0 then %s when i%%3=1 then '예능(대)' else '' end,
          'fixture','fixture','fixture','비공개 합성 상세주소',
          extensions.st_project(extensions.st_setsrid(extensions.st_makepoint(%s,%s),4326)
            ::extensions.geography,case when i<=10 then 10 else 20+(i%%750) end,
            case when i<=10 then 0 else i*0.61803398875 end)::extensions.geometry,
          false,'juso','academy-layer-fixture','synthetic'
        from generate_series(1,%s) i""",
        (FIELD, LNG, LAT, count),
    )
    db.execute(
        """insert into app_private.academy_display
        select id,case when right(id,1) in ('0','1') then '지하 1층'
          when right(id,1)='2' then '2~3층' end,
          case when right(id,1) in ('0','1','2') then 'explicit'
          when right(id,1)='3' then 'ambiguous' else 'missing' end,
          %s,%s from public.academies""",
        (REVISION, SHA),
    )
    db.execute(
        """insert into app_private.academy_display_release
        (singleton,source_revision,source_version,raw_sha256,row_count,coordinate_provider)
        values(true,%s,'synthetic',%s,%s,'juso')""",
        (REVISION, SHA, count),
    )
    db.execute(
        """insert into ingest_private.place_snapshots
        (target_table,source,source_version,raw_key,row_count,located_count,report)
        values('academies','academy-layer-fixture','synthetic','synthetic-only',%s,%s,'{}')""",
        (count, count),
    )
    db.execute(
        """insert into app_private.academy_coordinate_reviews
        select 'academy','synthetic-'||lpad(i::text,6,'0'),%s,%s,%s,'movement_gt_500m'
        from generate_series(1,99) i""",
        (REVISION, SHA, REVIEW),
    )
    db.execute(
        """insert into app_private.academy_coordinate_reviews
        select 'school','synthetic-school-'||i,'school-synthetic',%s,%s,'movement_gt_500m'
        from generate_series(1,2) i""",
        (SHA, REVIEW),
    )
    source = db.execute("select score_internal.sources()->'academies'").fetchone()[0]
    db.execute(
        """insert into app_private.academy_layer_release values(true,%s,%s,%s,%s,99,2)""",
        (REVISION, SHA, Jsonb(source), REVIEW),
    )
    return source


def fetch(db, source, *, lat=LAT, lng=LNG, radius=800, field=FIELD):
    return db.execute(
        "select public.academy_layer(%s,%s,%s,%s,%s)", (lat, lng, radius, field, Jsonb(source))
    ).fetchone()[0]


def serialized(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
