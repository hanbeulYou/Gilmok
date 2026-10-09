import json

import psycopg
import pytest
from psycopg.types.json import Jsonb

from tests.integration.test_s3_auth import as_user, user


def item(kind, coordinates, key="geometry"):
    return {"id": key, "geometry": {"type": kind, "coordinates": coordinates}}


def project(db, items):
    return db.execute("select public.project_exposure_geometry(%s)", (Jsonb(items),)).fetchone()[0]


def test_projection_holes_multi_points_lines_order_and_precision(db):
    ring = [[200000, 500000], [200030, 500000], [200030, 500030], [200000, 500000]]
    hole = [[200015, 500005], [200025, 500005], [200025, 500010], [200015, 500005]]
    items = [item("Point", [200000, 500000], "origin")]
    for name, dx, dy in [("N", 0, 60), ("E", 60, 0), ("S", 0, -60), ("W", -60, 0)]:
        items.append(item("Point", [200000 + dx, 500000 + dy], name))
    items += [
        item("Polygon", [ring, hole], "hole"),
        item("MultiPolygon", [[ring]], "multi"),
        item("LineString", [[200000, 500000], [200060, 500000]], "line"),
    ]
    as_user(db, user(db))
    db.execute("set local extra_float_digits='-1'")
    result = project(db, items)
    assert [x["id"] for x in result] == [x["id"] for x in items]
    for before, after in zip(items, result, strict=True):
        error = db.execute(
            """select extensions.st_hausdorffdistance(
          extensions.st_setsrid(extensions.st_geomfromgeojson(%s),5186),
          extensions.st_transform(extensions.st_setsrid(extensions.st_geomfromgeojson(%s),4326),5186))""",
            (json.dumps(before["geometry"]), json.dumps(after["geometry"])),
        ).fetchone()[0]
        assert error < 0.01
    assert len(result[-3]["geometry"]["coordinates"]) == 2
    assert project(db, []) == []


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        [item("Point", [0, 0])],
        [item("Point", [200000, 500000, 3])],
        [item("Point", ["NaN", 500000])],
        [item("LineString", [[200000, 500000]])],
        [item("GeometryCollection", [])],
        [item("Polygon", [[[200000, 500000], [200001, 500000], [200000, 500001]]])],
        [item("Point", [200000, 500000]), item("Point", [200000, 500000])],
        [item("MultiPolygon", [])],
        [item("Point", [200000, 500000], "x" * 201)],
    ],
)
def test_bad_geometry_rejected(db, value):
    with pytest.raises(psycopg.errors.InvalidParameterValue), db.transaction():
        project(db, value)


def test_size_limits_no_partial_response(db):
    for values in [
        [item("Point", [200000, 500000], str(i)) for i in range(10001)],
        [item("LineString", [[200000 + i % 2, 500000] for i in range(200001)])],
        [{**item("Point", [200000, 500000]), "extra": "x" * 8388608}],
    ]:
        with pytest.raises(psycopg.errors.InvalidParameterValue), db.transaction():
            project(db, values)


def test_readonly_invoker_and_privileges(db):
    contract = db.execute("""select p.prosecdef,p.provolatile,p.proconfig,
      has_function_privilege('anon',p.oid,'execute'),has_function_privilege('authenticated',p.oid,'execute')
      from pg_proc p where
      p.oid='public.project_exposure_geometry(jsonb)'::regprocedure""").fetchone()
    assert contract == (False, "i", ['search_path=""', "extra_float_digits=3"], False, True)
    db.execute("set local role anon")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        project(db, [])
    db.execute("reset role")
    as_user(db, user(db))
    before = db.execute("select count(*) from public.candidates").fetchone()[0]
    project(db, [item("Point", [200000, 500000])])
    assert db.execute("select count(*) from public.candidates").fetchone()[0] == before
