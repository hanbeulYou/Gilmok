import pandas as pd
import psycopg
import pytest

from ingest.commerce_education_database import load_snapshot
from ingest.verify_commerce_education import RADIUS_SQL, compare_database


def stores_frame():
    return pd.DataFrame(
        [
            dict(
                store_id="pr4-test",
                inds_lcls="P1",
                inds_mcls="P105",
                inds_scls="P10501",
                floor=None,
                lng=127.063642,
                lat=37.494612,
            )
        ]
    )


def load(db, table, frame, version="test-v1"):
    return load_snapshot(
        db,
        table,
        frame,
        source="test",
        version=version,
        raw_key=f"raw/{table}/2026-06.parquet",
        report={},
    )


def test_exact_six_store_columns_and_idempotent_snapshot(db):
    columns = db.execute(
        "select column_name from information_schema.columns "
        "where table_schema='public' and table_name='stores' "
        "order by ordinal_position"
    ).fetchall()
    assert [r[0] for r in columns] == [
        "store_id",
        "inds_lcls",
        "inds_mcls",
        "inds_scls",
        "floor",
        "geom",
    ]
    frame = stores_frame()
    load(db, "stores", frame)
    xmin = db.execute("select ctid::text from public.stores").fetchone()[0]
    load(db, "stores", frame)
    assert db.execute("select count(*),min(ctid::text) from public.stores").fetchone() == (1, xmin)
    assert compare_database(db, "stores", frame) == 0


def test_failed_replacement_preserves_previous_snapshot_and_metadata(db):
    frame = stores_frame()
    load(db, "stores", frame)
    invalid = frame.copy()
    invalid.loc[0, "inds_mcls"] = "I201"
    with pytest.raises(psycopg.errors.CheckViolation):
        load(db, "stores", invalid, version="bad")
    assert compare_database(db, "stores", frame) == 0
    assert (
        db.execute(
            "select source_version from ingest_private.place_snapshots where target_table='stores'"
        ).fetchone()[0]
        == "test-v1"
    )
    with pytest.raises(ValueError):
        load(db, "stores", frame.iloc[:0])


def test_raw_empty_field_and_unlocated_academies(db):
    frame = pd.DataFrame(
        [
            dict(
                id=str(i),
                name="학원",
                institution_type="교습소",
                registration_status="개원",
                field=field,
                affiliation="보통교과",
                course="보습·논술",
                course_list="국어",
                address="주소",
                lng=127.063642 if i < 2 else None,
                lat=37.494612 if i < 2 else None,
                geocode_failed=i == 2,
                geocode_provider="kakao",
                geocode_reason="not_found" if i == 2 else None,
            )
            for i, field in enumerate(["입시.검정 및 보습", "", "예능(대)"])
        ]
    )
    load(db, "academies", frame)
    row = db.execute(
        RADIUS_SQL.read_text(), dict(lng=127.063642, lat=37.494612, radius=500)
    ).fetchone()[0]
    assert row["compete"] == {
        "academies_total": 2,
        "academies_by_field": {"입시.검정 및 보습": 1, "": 1},
    }
    assert compare_database(db, "academies", frame) == 0
    assert row["meta"]["academies"]["row_count"] == 3
    assert row["meta"]["academies"]["located_count"] == 2
    assert row["meta"]["academies"]["unlocated_count"] == 1
    assert (
        db.execute("select count(*) from public.academies where geocode_failed").fetchone()[0] == 1
    )


def test_meter_radius_empty_vs_unloaded_and_read_only_rls(db):
    frame = stores_frame()
    load(db, "stores", frame)
    db.execute(
        "update public.stores set geom=extensions.st_project(geom::extensions.geography,"
        "500.1,0)::extensions.geometry"
    )

    def values(radius):
        return db.execute(
            RADIUS_SQL.read_text(), dict(lng=127.063642, lat=37.494612, radius=radius)
        ).fetchone()[0]

    assert values(500)["market"]["stores_total"] == 0
    assert values(1000)["market"]["stores_total"] == 1
    db.execute("delete from ingest_private.place_snapshots where target_table='stores'")
    assert values(500)["market"] is None
    with db.transaction():
        db.execute("set local role anon")
        assert db.execute("select count(*) from public.stores").fetchone()[0] == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
            db.execute("delete from public.stores")
        with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
            db.execute("select * from public.geocode_cache")
