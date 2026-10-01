import pytest
from psycopg.errors import InsufficientPrivilege, InvalidParameterValue

PNU = "1168010600100000999"


def resolve(db, pnu=PNU, lat=35.5, lng=127.0):
    return db.execute(
        "select public.resolve_candidate_location(%s,%s,%s)", (lat, lng, pnu)
    ).fetchone()[0]


@pytest.fixture
def spatial_fixture(db):
    db.execute("""insert into public.admin_dongs(adm_cd,name,geom,source,source_version)
        values('s3-context','fixture',extensions.st_multi(
          extensions.st_makeenvelope(126.9,35.4,127.1,35.6,4326)),'fixture','fixture')""")
    db.execute(
        """insert into public.buildings
        (id,source_id,pnu,source,source_version,register_link_status,geom,
         geometry_repaired,height_source,height_estimated)
        values('s3-context-building','fixture',%s,'gis_buildings_shp','fixture',
          'missing_source_pk',extensions.st_multi(
            extensions.st_makeenvelope(126.999,35.499,127.001,35.501,4326)),
          false,'unknown',false)""",
        (PNU,),
    )
    return db


def test_exact_input_preserved_and_matching_context(spatial_fixture):
    db = spatial_fixture
    db.execute("set local role authenticated")
    r = resolve(db)
    assert r["status"] == "matched"
    assert (r["lat"], r["lng"]) == (35.5, 127)
    assert r["building"]["id"] == "s3-context-building"
    assert r["context"]["inside_seoul"] is True
    assert r["context"]["seoul_boundary_distance_m"] > 8000
    assert resolve(db, pnu=None)["status"] == "matched"
    assert resolve(db, pnu="1168010600100000998")["status"] == "pnu_mismatch"
    assert resolve(db, lng=127.05)["status"] == "footprint_missing"
    assert resolve(db, lat=0, lng=0)["status"] == "outside_seoul"


def test_overlapping_footprints_never_choose_one(spatial_fixture):
    db = spatial_fixture
    db.execute("""insert into public.buildings
        (id,source_id,pnu,source,source_version,register_link_status,geom,
         geometry_repaired,height_source,height_estimated)
        select 's3-context-second',source_id,pnu,source,source_version,
         register_link_status,geom,geometry_repaired,height_source,height_estimated
        from public.buildings where id='s3-context-building'""")
    r = resolve(db)
    assert r["status"] == "ambiguous_footprint"
    assert r["building"] is None and r["covering_building_count"] == 2


@pytest.mark.parametrize(
    "lat,lng,pnu",
    [
        (None, 127, None),
        (float("nan"), 127, None),
        (35, float("inf"), None),
        (91, 127, None),
        (35, 181, None),
        (35, 127, "bad"),
    ],
)
def test_invalid_context_arguments(db, lat, lng, pnu):
    with pytest.raises(InvalidParameterValue), db.transaction():
        resolve(db, pnu, lat, lng)


def test_context_requires_session(db):
    db.execute("set local role anon")
    with pytest.raises(InsufficientPrivilege), db.transaction():
        resolve(db)
