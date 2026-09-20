import pandas as pd
import psycopg
import pytest

from ingest.building_footprints import SHP_SOURCE, WFS_SOURCE
from ingest.buildings_database import (
    FLOOR_COLUMNS,
    FOOTPRINT_COLUMNS,
    TITLE_COLUMNS,
    load_snapshot,
)

PK = "1168020200000000000001"
PNU = "1168010100100010000"


def frames(db):
    x, y = db.execute("""
      select extensions.st_x(p),extensions.st_y(p) from
        (select extensions.st_transform(extensions.st_setsrid(
          extensions.st_makepoint(127.062,37.496),4326),5186) p) q
    """).fetchone()
    buildings = []
    for i in range(4):
        row = dict.fromkeys(FOOTPRINT_COLUMNS)
        row.update(
            id=f"fixture:{i}",
            source_id=str(i),
            gis_id=str(i),
            pnu=PNU,
            source=WFS_SOURCE if i == 3 else SHP_SOURCE,
            source_version="fixture",
            source_register_pk=PK if i < 2 else None,
            candidate_register_pk=PK if i < 2 else None,
            source_height_m=12.5 if i < 2 else None,
            height_m=12.5 if i < 2 else None,
            height_source="source" if i < 2 else "unknown",
            height_estimated=False,
            source_srid=5186,
            source_geometry_wkb=bytes(
                db.execute(
                    "select extensions.st_asbinary(extensions.st_makeenvelope(%s,%s,%s,%s,5186))",
                    (x + i * 20, y, x + i * 20 + 10, y + 10),
                ).fetchone()[0]
            ),
        )
        buildings.append(row)
    title = dict.fromkeys(TITLE_COLUMNS)
    title.update(
        register_pk=PK,
        pnu=PNU,
        main_use_code="04000",
        main_use_name="제2종근린생활시설",
        passenger_elevators=2,
        emergency_elevators=1,
    )
    floors = []
    for i, use in enumerate(("04000", "03000")):
        row = dict.fromkeys(FLOOR_COLUMNS)
        row.update(
            id=f"floor:{i}",
            register_pk=PK,
            pnu=PNU,
            floor_kind="20",
            floor_no=1,
            floor_name="1층",
            use_code=use,
            area=30.0,
        )
        floors.append(row)
    return pd.DataFrame(buildings), pd.DataFrame([title]), pd.DataFrame(floors)


def load(db, data):
    return load_snapshot(db, *data, snapshot="fixture", raw_objects={"fixture": True})


def rpc(db, lng=127.062, lat=37.496, radius=500):
    return db.execute("select public.buildings_in_radius(%s,%s,%s)", (lng, lat, radius)).fetchone()[
        0
    ]


def test_both_sources_occlude_but_registers_are_distinct_primary_only(db):
    data = frames(db)
    for _ in range(2):
        report = load(db, data)
        assert report["row_counts"] == {
            "buildings": 4,
            "building_registers": 1,
            "building_floors": 2,
        }
    payload = rpc(db)
    assert payload["meta"]["unknown_ratio"] == 0.5
    assert payload["meta"]["confidence"] == {
        "unknown_ratio": 0.5,
        "unknown_count": 2,
        "occluder_count": 4,
    }
    assert payload["registry"] == {
        "scope": "matched_primary_registers_only",
        "register_count": 1,
        "main_use_counts": {"04000": 1},
        "passenger_elevators": 2,
        "emergency_elevators": 1,
        "elevator_known_registers": 1,
        "floor_rows": 2,
    }
    for feature in payload["features"]:
        props = feature["properties"]
        assert props["occlusion_included"] is True
        if props["height_source"] == "unknown":
            assert props["height_m"] is None
            assert props["render_height_m"] == props["occlusion_height_m"] == 4
            assert props["estimated"] is True
        if props["source"] == WFS_SOURCE:
            assert props["register_pk"] is None
            assert props["register_link_status"] == "supplemental_unlinked"
    assert rpc(db, 126.9, 37.6)["meta"]["unknown_ratio"] is None


def test_supplement_overlap_and_collapsed_shape_are_audited(db):
    data = frames(db)
    overlap = data[0].iloc[3].to_dict() | {
        "id": "overlap",
        "source_geometry_wkb": data[0].iloc[0].source_geometry_wkb,
    }
    collapsed = overlap | {
        "id": "collapsed",
        "source_geometry_wkb": bytes(
            db.execute(
                "select extensions.st_asbinary(extensions.st_geomfromtext(%s))",
                ("POLYGON((0 0,1 1,0 0,0 0))",),
            ).fetchone()[0]
        ),
    }
    data = (pd.concat([data[0], pd.DataFrame([overlap, collapsed])], ignore_index=True), *data[1:])
    report = load(db, data)
    assert report["row_counts"]["buildings"] == 4
    assert {v["id"]: v["reason"] for v in report["excluded_supplements"]} == {
        "overlap": "overlaps_primary",
        "collapsed": "non_polygon_supplement",
    }


def test_geometry_repair_preserves_bounds_area_and_bad_reload_rolls_back(db):
    data = frames(db)
    original = "POLYGON((0 0,10 0,10 10,20 10,20 20,10 20,10 10,0 10,0 0))"
    data[0].loc[0, "source_geometry_wkb"] = bytes(
        db.execute(
            "select extensions.st_asbinary(extensions.st_geomfromtext(%s))", (original,)
        ).fetchone()[0]
    )
    load(db, data)
    assert db.execute(
        "select geometry_repaired from public.buildings where id='fixture:0'"
    ).fetchone()[0]
    before = db.execute(
        "select id,extensions.st_asbinary(geom) from public.buildings order by id"
    ).fetchall()
    data[0].loc[0, "source_geometry_wkb"] = bytes(
        db.execute(
            "select extensions.st_asbinary(extensions.st_geomfromtext(%s))",
            ("POLYGON((0 0,10 10,0 10,10 0,0 0))",),
        ).fetchone()[0]
    )
    with pytest.raises(ValueError, match="repair changed"):
        load(db, data)
    assert (
        db.execute(
            "select id,extensions.st_asbinary(geom) from public.buildings order by id"
        ).fetchall()
        == before
    )


def test_register_pnu_mismatch_and_missing_floor_parent_are_preserved(db):
    data = frames(db)
    data[0].loc[0, "pnu"] = "1168010100100020000"
    data[2].loc[0, "register_pk"] = "99999"
    report = load(db, data)
    assert report["register_links"]["pnu_mismatch"] == 1
    assert report["floor_links"] == {"title_missing": 1, "matched": 1}
    assert db.execute(
        "select source_register_pk,register_pk from public.building_floors where id='floor:0'"
    ).fetchone() == ("99999", None)
    assert rpc(db)["registry"]["floor_rows"] == 1


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_public_reads_and_rpc_but_no_mutation_or_private_audit(db, role):
    load(db, frames(db))
    with db.transaction():
        db.execute(f"set local role {role}")
        assert len(rpc(db)["features"]) == 4
        assert db.execute("select count(*) from public.building_floors").fetchone()[0] == 2
        with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
            db.execute("delete from public.buildings")
        with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
            db.execute("select * from ingest_private.building_snapshots")


def test_failed_constraint_load_keeps_previous_snapshot(db):
    data = frames(db)
    load(db, data)
    data[1].loc[0, "passenger_elevators"] = -1
    with pytest.raises(psycopg.errors.CheckViolation):
        load(db, data)
    assert rpc(db)["registry"]["passenger_elevators"] == 2


@pytest.mark.parametrize("args", [(127, 37, 0), (127, 37, 5001), (0, 0, 500)])
def test_invalid_radius_or_coordinates(db, args):
    with pytest.raises(psycopg.errors.RaiseException, match="Invalid building query"):
        rpc(db, *args)
