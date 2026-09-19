from uuid import uuid4

import pandas as pd
import psycopg
import pytest

from ingest.aggregate import aggregate
from ingest.common import RawStore, Settings
from ingest.database import load_boundaries

SOURCE = "pr1_test_fixture"
POLYGON = "POLYGON((127.05 37.49,127.06 37.49,127.06 37.50,127.05 37.50,127.05 37.49))"


def load(db, rows, table="admin_dongs"):
    return load_boundaries(db, table, rows, source=SOURCE, source_version="fixture", srid=4326)


def test_database_versions_and_spatial_indexes(db):
    assert int(db.execute("show server_version_num").fetchone()[0]) // 10000 == 17
    assert db.execute("select extensions.postgis_lib_version()").fetchone()[0] == "3.3.7"
    indexes = db.execute(
        "select indexdef from pg_indexes where schemaname='public' "
        "and tablename in ('admin_dongs', 'census_blocks')"
    ).fetchall()
    assert sum("USING gist (geom)" in row[0] for row in indexes) == 2


def test_parquet_duckdb_to_postgis_and_idempotent_load(db, tmp_path):
    code = str(uuid4())
    frame = pd.DataFrame([{"code": code, "name": "synthetic boundary", "wkt": POLYGON}])
    store = RawStore(Settings(tmp_path))
    store.write_parquet("boundaries", "2026-01", frame)
    query = tmp_path / "normalize.sql"
    query.write_text("select code, name, wkt from raw_data")
    rows = aggregate(store, "boundaries", "2026-01", query).to_dict("records")
    assert load(db, rows) == 1
    assert load(db, rows) == 1
    result = db.execute(
        "select name, source, source_version, estimated, extensions.st_srid(geom), "
        "extensions.st_covers(geom, extensions.st_setsrid("
        "extensions.st_makepoint(127.055,37.495),4326)) "
        "from public.admin_dongs where adm_cd=%s", (code,),
    ).fetchall()
    assert result == [("synthetic boundary", SOURCE, "fixture", False, 4326, True)]
    assert db.execute(
        "select row_count from ingest_private.ingest_runs where source=%s", (SOURCE,)
    ).fetchall() == [(1,), (1,)]


@pytest.mark.parametrize("failure", ["duplicate", "bad_geometry", "empty"])
def test_failed_snapshot_keeps_previous_rows_and_audit(db, failure):
    old = {"code": str(uuid4()), "name": "old", "wkt": POLYGON}
    load(db, [old])
    new = {"code": str(uuid4()), "name": "new", "wkt": POLYGON}
    rows = {
        "duplicate": [new, new],
        "bad_geometry": [{**new, "wkt": "POINT(127.05 37.49)"}],
        "empty": [],
    }[failure]
    with pytest.raises((psycopg.Error, ValueError)):
        load(db, rows)
    assert db.execute(
        "select adm_cd,name from public.admin_dongs where source=%s", (SOURCE,)
    ).fetchall() == [(old["code"], "old")]
    assert db.execute(
        "select count(*) from ingest_private.ingest_runs where source=%s", (SOURCE,)
    ).fetchone() == (1,)


def test_census_boundary_and_wrong_crs_rejection(db):
    row = {"code": str(uuid4()), "name": "block", "wkt": POLYGON}
    load(db, [row], "census_blocks")
    with pytest.raises(ValueError, match="EPSG:4326"):
        load_boundaries(db, "census_blocks", [row], source=SOURCE,
                        source_version="fixture", srid=5186)
    assert db.execute("select count(*) from public.census_blocks where source=%s",
                      (SOURCE,)).fetchone() == (1,)


def test_boundary_loader_cannot_target_personal_data(db):
    with pytest.raises(ValueError, match="boundary load targets"):
        load(db, [], "candidates")


def users_and_candidate(db):
    owner, other = uuid4(), uuid4()
    db.execute("insert into auth.users (id) values (%s),(%s)", (owner, other))
    candidate = db.execute(
        "insert into public.candidates (user_id,geom,floor,user_rent) "
        "values (%s,extensions.st_setsrid(extensions.st_makepoint(127.05,37.49),4326),2,100) "
        "returning id", (owner,),
    ).fetchone()[0]
    return owner, other, candidate


def act_as(db, user):
    db.execute("set local role authenticated")
    db.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(user),))


def test_rls_owner_can_read_and_update_only_own_candidate(db):
    owner, other, candidate = users_and_candidate(db)
    act_as(db, owner)
    assert db.execute("select user_rent from public.candidates where id=%s",
                      (candidate,)).fetchone() == (100,)
    assert db.execute("update public.candidates set user_rent=200 where id=%s",
                      (candidate,)).rowcount == 1
    act_as(db, other)
    assert db.execute("select * from public.candidates").fetchall() == []
    assert db.execute("update public.candidates set user_rent=0 where id=%s",
                      (candidate,)).rowcount == 0
    assert db.execute("delete from public.candidates where id=%s", (candidate,)).rowcount == 0


def test_rls_rejects_spoofed_ownership(db):
    owner, other, candidate = users_and_candidate(db)
    act_as(db, owner)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("update public.candidates set user_id=%s where id=%s", (other, candidate))
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute(
            "insert into public.candidates (user_id,geom,floor) "
            "values (%s,extensions.st_setsrid(extensions.st_makepoint(127.05,37.49),4326),2)",
            (other,),
        )


def test_anon_cannot_read_personal_data_or_write_public_boundaries(db):
    users_and_candidate(db)
    db.execute("set local role anon")
    db.execute("select * from public.admin_dongs")
    for query in ["select * from public.candidates", "select * from public.geocode_cache",
                  "delete from public.admin_dongs", "select * from ingest_private.ingest_runs"]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
            db.execute(query)


def test_successful_geocode_requires_a_coordinate(db):
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(
            "insert into public.geocode_cache (address,provider,source,source_version) "
            "values ('fixture','fixture',%s,'fixture')", (SOURCE,),
        )
