import json

import psycopg
import pytest

from tests.integration.test_s3_auth import as_user, user

LAT, LNG = 37.5025724504279, 127.057585738094


@pytest.fixture(autouse=True)
def seoul_boundary(db):
    # CI starts with an empty database; no reliance on the developer's live data.
    db.execute("""insert into public.admin_dongs(adm_cd,name,geom,source,source_version)
        values('11-map-fixture','map fixture',extensions.st_multi(
          extensions.st_makeenvelope(126.9,37.4,127.2,37.7,4326)),
          'map-fixture','20261007')""")


def fetch(db, lat=LAT, lng=LNG):
    return db.execute("select public.compare_map_context(%s,%s)", (lat, lng)).fetchone()[0]


def test_map_center_rings_and_exact_distance(db):
    db.execute("set local extra_float_digits='-1'")
    as_user(db, user(db))
    value = fetch(db)
    assert value["center"] == [LNG, LAT]
    assert value["meta"]["crs"] == "EPSG:4326"
    assert value["meta"]["covered"] is True
    rings = [f for f in value["collection"]["features"] if f["properties"]["kind"] == "radius"]
    assert len(rings) == 2
    for ring in rings:
        radius = ring["properties"]["radius_m"]
        points = ring["geometry"]["coordinates"][0]
        assert len(points) == 129 and points[0] == points[-1]
        distance = db.execute(
            """select max(abs(extensions.st_distance(
            p.geom::extensions.geography,extensions.st_setsrid(
            extensions.st_makepoint(%s,%s),4326)::extensions.geography)-%s))
            from extensions.st_dumppoints(extensions.st_geomfromgeojson(%s)) p""",
            (LNG, LAT, radius, json.dumps(ring["geometry"])),
        ).fetchone()[0]
        assert distance < 0.001


def test_station_boundaries_preserve_interchange_ids_and_school_missing(db):
    db.execute("delete from public.transit_boardings")
    db.execute("delete from public.transit_stops")
    db.execute("delete from public.schools")
    for stop, distance, kind in [
        ("A", 500, "subway"),
        ("B", 500, "subway"),
        ("edge", 1199.99, "subway"),
        ("out", 1200.01, "subway"),
        ("bus", 100, "bus"),
    ]:
        db.execute(
            """insert into public.transit_stops(id,type,name,line,geom,source,source_version)
            values(%s,%s,'환승역',%s,extensions.st_project(extensions.st_setsrid(
            extensions.st_makepoint(%s,%s),4326)::extensions.geography,%s,0)
            ::extensions.geometry,'fixture','20261007')""",
            (stop, kind, stop, LNG, LAT, distance),
        )
    for school, distance in [("in", 999.99), ("out", 1000.01), ("unlocated", None)]:
        db.execute(
            """insert into public.schools(id,name,level,school_type,address,geom,
            geocode_failed,source,source_version) values(%s,'학교','elem','초등학교','공개 주소',
            extensions.st_project(extensions.st_setsrid(extensions.st_makepoint(%s,%s),4326)
            ::extensions.geography,%s,0)::extensions.geometry,%s,'fixture','20261007')""",
            (school, LNG, LAT, distance, distance is None),
        )
    as_user(db, user(db))
    value = fetch(db)
    stations = [f for f in value["collection"]["features"] if f["properties"]["kind"] == "station"]
    assert {f["properties"]["source_id"] for f in stations} == {"A", "B", "edge"}
    assert stations[0]["geometry"] == stations[1]["geometry"]
    schools = [f for f in value["collection"]["features"] if f["properties"]["kind"] == "school"]
    assert [f["properties"]["source_id"] for f in schools] == ["in"]
    assert value["meta"]["sources"]["schools"]["unlocated_count"] == 1
    assert value["meta"]["unlocated_scope"] == "whole_source_not_radius"
    assert all(f["properties"]["estimated"] is False for f in stations + schools)


def test_empty_available_differs_from_unavailable_and_outside(db):
    # Source exists, but no feature within this Seoul corner: still an available source.
    as_user(db, user(db))
    outside = fetch(db, 35.2, 129.1)
    assert outside["meta"]["covered"] is False
    assert all(f["properties"]["kind"] == "radius" for f in outside["collection"]["features"])
    db.execute("reset role")
    db.execute("delete from public.transit_boardings")
    db.execute("delete from public.transit_stops")
    db.execute("delete from public.schools")
    as_user(db, user(db))
    empty = fetch(db)
    assert empty["meta"]["covered"] is True
    assert all(not source["available"] for source in empty["meta"]["sources"].values())


@pytest.mark.parametrize("point", [(None, LNG), (LAT, None), (0, LNG), (LAT, float("nan"))])
def test_invalid_coordinates(db, point):
    with pytest.raises(psycopg.errors.InvalidParameterValue), db.transaction():
        fetch(db, *point)


def test_map_invoker_permissions_and_read_only(db):
    contract = db.execute("""select p.prosecdef,p.proconfig,
        has_function_privilege('anon',p.oid,'execute'),
        has_function_privilege('authenticated',p.oid,'execute')
        from pg_proc p where
        oid='public.compare_map_context(double precision,double precision)'::regprocedure
        """).fetchone()
    assert contract == (False, ['search_path=""', "extra_float_digits=3"], False, True)
    db.execute("set local role anon")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        fetch(db)
    db.execute("reset role")
    as_user(db, user(db))
    before = db.execute("select count(*) from public.candidates").fetchone()[0]
    fetch(db)
    assert db.execute("select count(*) from public.candidates").fetchone()[0] == before
