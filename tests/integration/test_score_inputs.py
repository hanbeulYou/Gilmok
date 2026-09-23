"""Independent, rollback-only data proves the S2 input contract, not live statistics."""

import copy

import psycopg
import pytest

POINT = "extensions.st_setsrid(extensions.st_makepoint(127.4,37.7),4326)"
AREA = (
    f"extensions.st_multi(extensions.st_buffer({POINT}::extensions.geography,2000)"
    "::extensions.geometry)"
)
PK = "9999999999999999999901"
PNU = "1168010100100010000"
BUNDLES = {"demand", "flow", "transit", "market", "compete", "building", "rent"}


def query(db, **changes):
    args = dict(lat=37.7, lng=127.4, radius_m=500, floor=2, address=None)
    args.update(changes)
    return db.execute(
        "select public.score_inputs(%(lat)s,%(lng)s,%(radius_m)s,%(floor)s,%(address)s)", args
    ).fetchone()[0]


def stable_result(result):
    result = copy.deepcopy(result)
    for name in ["computed_at", "bundle_ms", "sources_ms", "total_ms"]:
        result["meta"].pop(name)
    return result


@pytest.fixture
def data(db):
    # A synthetic location outside the live Seoul data: no production rows are replaced.
    db.execute(f"""insert into public.admin_dongs(adm_cd,name,geom,source,source_version)
        values('pr7','fixture',{AREA},'pr7','2026-08-01')""")
    db.execute("""insert into public.population_age
        (adm_cd,age_band,population,ref_month,source,source_version)
        values ('pr7','5_9',100,'2026-08-01','pr7','2026-08'),
        ('pr7','10_14',200,'2026-08-01','pr7','2026-08'),
        ('pr7','15_18',300,'2026-08-01','pr7','2026-08')""")
    db.execute(f"""insert into public.population_cells
        (resolution_m,cell_id,geom,boundary_generated,source,source_version)
        select 250,'pr7',extensions.st_transform(
          extensions.st_makeenvelope(extensions.st_x(p)-125,extensions.st_y(p)-125,
           extensions.st_x(p)+125,extensions.st_y(p)+125,5186),4326),false,'pr7','fixture'
        from (select extensions.st_transform({POINT},5186) p) q""")
    db.execute("""insert into public.living_pop
        (resolution_m,cell_id,dow_type,hour,total,sample_days,period_start,period_end,
         source,source_version)
        select 250,'pr7',d,h,10+h+case d when 'weekday' then 0 else 100 end,10,
        '2026-06-01'::date,'2026-08-31'::date,'pr7','fixture'
        from (values('weekday'),('weekend')) days(d),generate_series(0,23) hours(h)""")
    for table in ["stores", "academies", "schools"]:
        db.execute(
            """insert into ingest_private.place_snapshots
            (target_table,source,source_version,raw_key,row_count,located_count,report)
            values(%s,'pr7','2026-08','fixture',3,3,'{}')
            on conflict(target_table) do update set row_count=3,located_count=3""",
            (table,),
        )
    db.execute(f"""insert into public.stores
        select 'pr7-'||n,'P1','P105','P10501',null,{POINT} from generate_series(1,2) n""")
    db.execute(f"""insert into public.academies
        (id,name,institution_type,registration_status,field,affiliation,course_list,course,
        address,geom,geocode_failed,source,source_version)
        select 'pr7-'||n,'fixture','교습소','개원','보습','보통교과','원문','원문','fixture',
        {POINT},false,'pr7','fixture' from generate_series(1,2) n""")
    db.execute(f"""insert into public.schools
        (id,name,level,school_type,address,geom,geocode_failed,source,source_version)
        select 'pr7-'||n,'fixture','elem','초등학교','fixture',{POINT},false,'pr7','fixture'
        from generate_series(1,3) n""")
    db.execute("""insert into ingest_private.transit_coverage(type,report) values
        ('subway','{"coordinates":{"retrieved_on":"2026-09-19"}}'),
        ('bus','{"coordinates":{"retrieved_on":"2026-09-19"}}') on conflict do nothing""")
    db.execute(f"""insert into public.transit_stops(id,type,name,line,geom,source,source_version)
        values('pr7-subway','subway','fixture','fixture',{POINT},'pr7','fixture'),
        ('pr7-bus','bus','fixture','fixture',{POINT},'pr7','fixture')""")
    db.execute("""insert into public.transit_boardings
        (stop_id,hour,boarding,alighting,sample_months,period_start,period_end,source,source_version)
        select 'pr7-subway',h,10,20,3,'2026-06-01'::date,'2026-08-31'::date,'pr7','fixture'
        from generate_series(15,21) h""")
    db.execute(
        """insert into public.building_registers
        (register_pk,pnu,passenger_elevators,emergency_elevators,source_version)
        values(%s,%s,1,0,'fixture')""",
        (PK, PNU),
    )
    db.execute(
        f"""insert into public.buildings
        (id,source_id,pnu,source,source_version,register_pk,register_link_status,geom,
         geometry_repaired,source_height_m,floors_above,height_m,height_source,
         height_estimated)
        values('pr7','pr7',%s,'gis_buildings_shp','fixture',%s,'matched',
         extensions.st_multi(extensions.st_buffer({POINT}::extensions.geography,10)
          ::extensions.geometry),false,12.5,4,12.5,'source',false)""",
        (PNU, PK),
    )
    db.execute(
        """insert into public.building_floors
        (id,source_register_pk,register_pk,register_link_status,pnu,floor_kind,floor_no,
         use_code,use_name,area,main_attached_code,source_version)
        select 'pr7-'||n,%s,%s,'matched',%s,'20',2,'03','근린생활시설',50,'0','fixture'
        from generate_series(1,2) n""",
        (PK, PK, PNU),
    )
    db.execute(f"""insert into public.legal_dongs(code8,name,geom,source,source_version)
        values('11680999','fixture',{AREA},'pr7','fixture')""")
    db.execute("""insert into public.commercial_trade_stats
        (legal_dong_code,trade_kind,aggregation_level,floor,period_start,period_end,
         median_price_per_m2,sample_count,unknown_floor_count,area_basis,source,source_version)
        values('11680999','general','floor',2,'2024-09-01','2026-08-31',1000,5,0,
         'building_area','pr7','fixture'),
        ('11680999','collective','floor',2,'2024-09-01','2026-08-31',2000,10,0,
         'building_area','pr7','fixture')""")
    return db


def test_complete_contract_single_row_and_independent_counts(data):
    r = query(data)
    assert set(r) == BUNDLES | {"meta"}
    assert r["market"]["stores_total"] == r["compete"]["academies_total"] == 2
    assert r["demand"]["schools"] == dict(elem=3, mid=0, high=0)
    assert r["demand"]["pop_10_14"] == pytest.approx(r["demand"]["pop_5_9"] * 2)
    assert r["flow"]["weekday"]["hourly"] == pytest.approx(list(range(10, 34)))
    assert r["flow"]["weekend"]["golden_avg_pop"] == pytest.approx(128)
    assert r["transit"]["subway_boardings_golden"] == 210
    assert r["building"]["elevators"] == dict(passenger=1, emergency=0)
    assert len(r["building"]["floor_use"]) == 2
    assert r["rent"]["trade_sample_count"] == 10
    assert r["rent"]["trade_median_per_m2"] == 2000
    assert r["meta"]["flow_coverage"]["weekday"]["valid_cells"] == [1] * 24
    assert set(r["meta"]["bundle_ms"]) == BUNDLES
    assert all(ms >= 0 for ms in r["meta"]["bundle_ms"].values())
    assert r["meta"]["total_ms"] >= sum(r["meta"]["bundle_ms"].values())
    expected_nulls = data.execute(
        "select path from score_internal.null_paths(%s::jsonb)",
        (psycopg.types.json.Jsonb({k: v for k, v in r.items() if k != "meta"}),),
    ).fetchall()
    assert {x["path"] for x in r["meta"]["missing_fields"]} == {x[0] for x in expected_nulls}


@pytest.mark.parametrize("missing", sorted(BUNDLES))
def test_one_missing_bundle_does_not_remove_or_change_other_bundles(data, missing):
    before = query(data)
    statements = {
        "demand": [
            "update public.population_age set population=null where adm_cd='pr7'",
            "delete from ingest_private.place_snapshots where target_table='schools'",
        ],
        "flow": ["update public.living_pop set total=null where cell_id='pr7'"],
        "transit": ["delete from ingest_private.transit_coverage"],
        "market": ["delete from ingest_private.place_snapshots where target_table='stores'"],
        "compete": ["delete from ingest_private.place_snapshots where target_table='academies'"],
        "building": ["delete from public.buildings where id='pr7'"],
        "rent": ["delete from public.commercial_trade_stats where legal_dong_code='11680999'"],
    }
    for statement in statements[missing]:
        data.execute(statement)
    after = query(data)
    assert after[missing] != before[missing]
    for bundle in BUNDLES - {missing}:
        assert after[bundle] == before[bundle]
    assert any(x["path"].startswith(missing + ".") for x in after["meta"]["missing_fields"])


def test_no_cross_source_multiplication(data):
    before = query(data)
    data.execute(f"""insert into public.stores
      select 'pr7-extra-'||n,'P1','P105','P10501',null,{POINT} from generate_series(1,5) n""")
    after = query(data)
    assert after["market"]["stores_total"] == 7
    for name in BUNDLES - {"market"}:
        assert before[name] == after[name]


def test_partial_hour_is_null_not_shorter_golden_average(data):
    data.execute("update public.living_pop set total=null where cell_id='pr7' and hour=17")
    r = query(data)
    assert r["flow"]["weekday"]["golden_avg_pop"] is None
    assert r["flow"]["weekday"]["hourly"][16] == pytest.approx(26)
    assert r["flow"]["weekday"]["hourly"][17] is None
    assert r["meta"]["flow_coverage"]["weekday"]["valid_cells"][17] == 0


def test_floor_exact_match_unknown_ratio_and_ambiguous_building(data):
    assert query(data, floor=-2)["building"]["floor_use"] is None
    data.execute("""update public.buildings set source_height_m=null,height_m=null,
        floors_above=null,height_source='unknown' where id='pr7'""")
    r = query(data)
    assert r["building"]["height_m"] is None  # no display-only 4m substitution
    assert r["meta"]["height_quality"]["unknown_ratio"] == 1
    data.execute("""insert into public.buildings
      (id,source_id,pnu,source,source_version,register_link_status,geom,geometry_repaired,
       height_source,height_estimated)
      select 'pr7-overlap','pr7-overlap',pnu,'vworld_wfs_supplement','fixture',
       'supplemental_unlinked',geom,false,'unknown',false
      from public.buildings where id='pr7'""")
    r = query(data)
    assert r["building"]["id"] is None
    assert any(x["reason"] == "ambiguous_containing_building" for x in r["meta"]["missing_fields"])


def test_zero_is_different_from_unloaded(data):
    data.execute("delete from public.stores where store_id like 'pr7-%'")
    assert query(data)["market"]["stores_total"] == 0
    data.execute("delete from ingest_private.place_snapshots where target_table='stores'")
    assert query(data)["market"]["stores_total"] is None


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_public_read_preserves_rls_and_hides_private_metadata(data, role):
    before = stable_result(query(data))
    data.execute(f"set local role {role}")
    assert stable_result(query(data)) == before
    for sql in [
        "select * from ingest_private.place_snapshots",
        "select * from ingest_private.rent_snapshots",
        "update public.stores set floor='2'",
        "delete from public.population_age",
    ]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), data.transaction():
            data.execute(sql)
    sources = query(data)["meta"]["sources"]
    assert all(not ({"report", "raw_key", "raw_objects"} & set(v)) for v in sources.values())


@pytest.mark.parametrize(
    "changes",
    [
        dict(lat=None),
        dict(lng=37.7),
        dict(radius_m=0),
        dict(floor=None),
        dict(floor=0),
        dict(lat=float("nan")),
    ],
)
def test_invalid_inputs_rejected(db, changes):
    with pytest.raises(psycopg.errors.InvalidParameterValue), db.transaction():
        query(db, **changes)


def test_legacy_rent_rpc_result_preserved(data):
    args = (127.4, 37.7, 500, 2, None)
    old = data.execute("select public.rent_inputs(%s,%s,%s,%s,%s)", args).fetchone()[0]
    internal = data.execute("select score_internal.rent_inputs(%s,%s,%s,%s,%s)", args).fetchone()[0]
    assert old == internal
    assert old["trade_median_per_m2"] == query(data)["rent"]["trade_median_per_m2"]


def test_partial_cells_sum_observed_values_and_coverage_threshold(data):
    data.execute("""insert into public.population_cells
        (resolution_m,cell_id,geom,boundary_generated,source,source_version)
        select 250,'pr7-extra-'||n,extensions.st_transform(
        extensions.st_translate(extensions.st_transform(geom,5186),x,y),4326),
        false,'pr7','fixture' from public.population_cells
        cross join (values(1,250,0),(2,-250,0),(3,0,250),(4,0,-250)) v(n,x,y)
        where cell_id='pr7'""")
    data.execute("""insert into public.living_pop
        (resolution_m,cell_id,dow_type,hour,total,sample_days,period_start,period_end,
        source,source_version)
        select 250,'pr7-extra-'||n,dow_type,hour,100,sample_days,period_start,period_end,
        source,source_version from public.living_pop cross join generate_series(1,4) n
        where cell_id='pr7'""")
    data.execute("""update public.living_pop set total=null
        where cell_id='pr7-extra-1' and dow_type='weekday' and hour=17""")
    r = query(data)
    c = r["meta"]["flow_coverage"]["weekday"]
    assert c["expected_cells"] == 5
    assert c["valid_cells"][17] == 4
    assert c["coverage_ratio"][17] == 0.8
    assert r["flow"]["weekday"]["hourly"][17] == pytest.approx(327)
    assert r["flow"]["low_coverage"] is False
    data.execute("""update public.living_pop set total=null
        where cell_id='pr7-extra-2' and dow_type='weekday' and hour=17""")
    r = query(data)
    assert r["meta"]["flow_coverage"]["weekday"]["coverage_ratio"][17] == 0.6
    assert r["flow"]["weekday"]["hourly"][17] == pytest.approx(227)
    assert r["flow"]["weekday"]["golden_avg_pop"] == pytest.approx((428 * 7 - 200) / 7)
    assert r["flow"]["weekend"]["hourly"][17] == pytest.approx(527)
    assert r["flow"]["low_coverage"] is True


def test_small_and_auxiliary_buildings_excluded_only_from_quality(data):
    data.execute(
        f"""insert into public.buildings
        (id,source_id,pnu,source,source_version,register_link_status,geom,
        geometry_repaired,height_source,height_estimated,height_m,source_height_m,main_use_name)
        select 'pr7-'||label,'pr7-'||label,%s,'vworld_wfs_supplement','fixture',
        'supplemental_unlinked',extensions.st_multi(extensions.st_transform(
        extensions.st_buffer(extensions.st_transform({POINT},5186),size),4326)),
        false,hs,false,h,h,use_name
        from (values('small',2,'unknown',null::numeric,null::text),
        ('small-known',2,'source',10,null),('warehouse',10,'unknown',null,'창고시설'))
        v(label,size,hs,h,use_name)""",
        (PNU,),
    )
    q = query(data)["meta"]["height_quality"]
    assert q == dict(
        radius_m=500,
        total_buildings=1,
        unknown_buildings=0,
        unknown_ratio=0,
        observed_buildings=4,
        observed_unknown_buildings=2,
        excluded_buildings=3,
        excluded_unknown_buildings=2,
        excluded_small_buildings=2,
        excluded_use_buildings=1,
    )
    visible = data.execute("select public.buildings_in_radius(127.4,37.7,500)").fetchone()[0]
    assert visible["meta"]["total_buildings"] == 4


ADDRESS = "서울특별시 강남구 역삼로 460"


def clear_address(data):
    for table in ("building_address_cache", "building_address_requests"):
        data.execute(f"delete from ingest_private.{table} where address=%s", (ADDRESS,))


def cached_address(data, status="ready"):
    from psycopg.types.json import Jsonb

    payload = dict(
        building=dict(
            id=None,
            pnu=PNU,
            source="building_hub_address",
            location_basis="address",
            register_pk=PK,
            main_use=dict(code="04", name="fixture", other_use=None),
            floors_above=4,
            floors_below=1,
            height_m=None,
            height_estimated=False,
            height_source="unknown",
            elevators=dict(passenger=0, emergency=0),
            estimated=False,
        ),
        floors=[
            dict(
                floor_kind="20",
                floor_no=2,
                use_code="04010",
                use_name="학원",
                other_use=None,
                area_m2=173.68,
                main_attached_code="0",
            )
        ],
    )
    data.execute(
        f"""insert into ingest_private.building_address_cache
        (address,pnu,geom,status,payload,fetched_at,expires_at)
        values(%s,%s,{POINT},%s,%s,now(),now()+interval '30 days')""",
        (ADDRESS, PNU, status, Jsonb(payload)),
    )


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_address_miss_enqueues_once_with_public_role(data, role):
    clear_address(data)
    data.execute("delete from public.buildings where id='pr7'")
    data.execute(f"set local role {role}")
    for address in ("역삼로460", ADDRESS, "서울 강남구 역삼로460"):
        r = query(data, address=address)
        assert r["meta"]["building_lookup"]["status"] == "pending"
        assert r["building"]["register_pk"] is None
        assert r["demand"]["estimated"] is True
    for table in ("building_address_cache", "building_address_requests"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege), data.transaction():
            data.execute(f"select * from ingest_private.{table}")
    data.execute("reset role")
    assert (
        data.execute(
            "select count(*) from ingest_private.building_address_requests where address=%s",
            (ADDRESS,),
        ).fetchone()[0]
        == 1
    )


def test_address_cache_ready_floor_matching_and_expiry(data):
    clear_address(data)
    data.execute(
        "update public.buildings set register_pk=null,register_link_status='title_not_found' "
        "where id='pr7'"
    )
    cached_address(data)
    r = query(data, address=ADDRESS)
    b = r["building"]
    assert b["location_basis"] == "address"
    assert b["floors_above"] == 4 and b["floors_below"] == 1
    assert b["elevators"] == dict(passenger=0, emergency=0)
    assert b["floor_use"][0]["area_m2"] == 173.68
    assert b["height_m"] is None
    assert r["meta"]["building_lookup"]["status"] == "ready"
    assert r["meta"]["sources"]["building_address"]["available"] is True
    assert query(data, address=ADDRESS, floor=-2)["building"]["floor_use"] is None
    assert (
        data.execute(
            "select count(*) from ingest_private.building_address_requests where address=%s",
            (ADDRESS,),
        ).fetchone()[0]
        == 0
    )
    data.execute(
        """update ingest_private.building_address_cache
        set fetched_at=now()-interval '31 days',expires_at=now()-interval '1 day'
        where address=%s""",
        (ADDRESS,),
    )
    r = query(data, address=ADDRESS)
    assert r["meta"]["building_lookup"]["status"] == "pending"
    assert r["building"]["register_pk"] is None
    assert r["building"]["location_basis"] == "footprint"


def test_address_absent_linked_invalid_and_ambiguous(data):
    clear_address(data)
    assert query(data)["meta"]["building_lookup"]["status"] == "not_requested"
    assert query(data, address=ADDRESS)["meta"]["building_lookup"]["status"] == "not_needed"
    data.execute("delete from public.buildings where id='pr7'")
    assert (
        query(data, address="서울특별시 종로구 역삼로460")["meta"]["building_lookup"]["status"]
        == "invalid_address"
    )
    cached_address(data, status="ambiguous")
    r = query(data, address=ADDRESS)
    assert r["meta"]["building_lookup"]["status"] == "ambiguous"
    assert r["building"]["register_pk"] is None
    assert r["building"]["floors_above"] is None
    assert (
        data.execute(
            "select count(*) from ingest_private.building_address_requests where address=%s",
            (ADDRESS,),
        ).fetchone()[0]
        == 0
    )


def test_all_floors_preserves_multi_use_basement_roof_and_requested_floor(data):
    data.execute(
        """insert into public.building_floors
        (id,register_pk,source_register_pk,register_link_status,pnu,floor_kind,floor_no,
         use_code,use_name,area,main_attached_code,source_version)
        select 'pr7-all-'||id,%s,%s,'matched',%s,kind,num,'04',name,area,'0','fixture'
        from (values('b1','10',1,'음식점',80),('3','20',3,'학원',130),
          ('4','20',4,'학원',140),('roof','30',1,'계단실',10)) f(id,kind,num,name,area)""",
        (PK, PK, PNU),
    )
    expected = [
        dict(floor_no=-1, floor_kind="10", use_name="음식점", area_m2=80),
        dict(floor_no=1, floor_kind="30", use_name="계단실", area_m2=10),
        dict(floor_no=2, floor_kind="20", use_name="근린생활시설", area_m2=50),
        dict(floor_no=2, floor_kind="20", use_name="근린생활시설", area_m2=50),
        dict(floor_no=3, floor_kind="20", use_name="학원", area_m2=130),
        dict(floor_no=4, floor_kind="20", use_name="학원", area_m2=140),
    ]
    for floor in (2, 3, 4, 9, -1):
        r = query(data, floor=floor)
        assert r["meta"]["schema_version"] == "1.3"
        assert r["building"]["all_floors"] == expected
        if floor == 9:
            assert r["building"]["floor_use"] is None
        else:
            areas = [u["area_m2"] for u in r["building"]["floor_use"]]
            assert areas == {2: [50, 50], 3: [130], 4: [140], -1: [80]}[floor]


def test_all_floors_is_always_an_array_when_no_floor_data(data):
    data.execute("delete from public.building_floors where register_pk=%s", (PK,))
    assert query(data)["building"]["all_floors"] == []
    data.execute(
        "update public.buildings set register_pk=null,"
        "register_link_status='title_not_found' where id='pr7'"
    )
    assert query(data)["building"]["all_floors"] == []
    data.execute("delete from public.buildings where id='pr7'")
    assert query(data)["building"]["all_floors"] == []
    clear_address(data)
    assert query(data, address=ADDRESS)["building"]["all_floors"] == []


def test_existing_address_cache_returns_all_floors_without_refetch(data):
    from psycopg.types.json import Jsonb

    clear_address(data)
    cached_address(data)
    data.execute("delete from public.buildings where id='pr7'")
    floors = [
        dict(floor_kind=k, floor_no=n, use_name=u, area_m2=a)
        for k, n, u, a in [
            ("20", 4, "학원", 140),
            ("10", 1, "음식점", 80),
            ("20", 3, "학원", 130),
            ("20", 3, "학원", 5),
            ("30", 1, "계단실", 10),
        ]
    ]
    data.execute(
        """update ingest_private.building_address_cache set payload=
        jsonb_set(payload,'{floors}',payload->'floors'||%s) where address=%s""",
        (Jsonb(floors), ADDRESS),
    )
    a = query(data, address=ADDRESS, floor=3)
    b = query(data, address=ADDRESS, floor=4)
    assert a["building"]["all_floors"] == b["building"]["all_floors"]
    assert [f["floor_no"] for f in a["building"]["all_floors"]] == [-1, 1, 2, 3, 3, 4]
    assert [f["area_m2"] for f in a["building"]["floor_use"]] == [130, 5]
    assert b["building"]["floor_use"][0]["area_m2"] == 140
    assert a["meta"]["building_lookup"]["status"] == "ready"
    assert (
        data.execute(
            "select count(*) from ingest_private.building_address_requests where address=%s",
            (ADDRESS,),
        ).fetchone()[0]
        == 0
    )


def test_v13_gross_area_comes_from_title_not_floor_or_footprint(data):
    data.execute(
        "update public.building_registers set gross_area=1649.99 where register_pk=%s", (PK,)
    )
    result = query(data)
    assert result["meta"]["schema_version"] == "1.3"
    assert result["building"]["gross_area"] == 1649.99
    assert all(f["area_m2"] == 50 for f in result["building"]["floor_use"])
    data.execute("update public.building_registers set gross_area=null where register_pk=%s", (PK,))
    result = query(data)
    assert result["building"]["gross_area"] is None
    assert any(f["path"] == "building.gross_area" for f in result["meta"]["missing_fields"])


def test_v13_address_legacy_cache_title_fallback_and_new_payload(data):
    clear_address(data)
    data.execute("delete from public.buildings where id='pr7'")
    cached_address(data)
    data.execute(
        "update public.building_registers set gross_area=849.97 where register_pk=%s", (PK,)
    )
    assert query(data, address=ADDRESS)["building"]["gross_area"] == 849.97
    # A new on-demand payload is authoritative even if no title row exists locally.
    data.execute(
        """update ingest_private.building_address_cache set payload=
      jsonb_set(jsonb_set(payload,'{building,register_pk}','"new_uncached_title"'),
      '{building,gross_area}','1650.5') where address=%s""",
        (ADDRESS,),
    )
    assert query(data, address=ADDRESS)["building"]["gross_area"] == 1650.5
    data.execute(
        """update ingest_private.building_address_cache set payload=
      jsonb_set(payload,'{building,gross_area}','null') where address=%s""",
        (ADDRESS,),
    )
    result = query(data, address=ADDRESS)
    assert result["building"]["gross_area"] is None
    assert (
        len([f for f in result["meta"]["missing_fields"] if f["path"] == "building.gross_area"])
        == 1
    )
