from uuid import uuid4

import pytest
from psycopg.errors import InsufficientPrivilege

from tests.integration.test_registration_usage import as_user, create_user


def test_shared_work_has_distinct_owner_ids_and_ready_projection(db):
    a, b = create_user(db), create_user(db)
    address = f'서울특별시 강남구 역삼로 {int(uuid4()) % 90000 + 10000}'
    db.execute('insert into ingest_private.building_address_requests(address) values(%s)',
               (address,))
    as_user(db, a)
    aid = db.execute('select watch_candidate_lookup(%s)', (address,)).fetchone()[0]
    assert db.execute('select watch_candidate_lookup(%s)', (address,)).fetchone()[0] == aid
    as_user(db, b)
    bid = db.execute('select watch_candidate_lookup(%s)', (address,)).fetchone()[0]
    assert aid != bid
    assert db.execute('select request_id,status from candidate_lookup_state').fetchall() == [
        (bid, 'pending')]
    assert not db.execute('select owns_candidate_lookup(%s)', (aid,)).fetchone()[0]
    with pytest.raises(InsufficientPrivilege), db.transaction():
        db.execute("update candidate_lookup_status set status='ready'")
    db.execute('reset role')
    db.execute("""insert into ingest_private.building_address_cache
        (address,pnu,geom,status,payload,fetched_at,expires_at)
        values(%s,'1168010600109120013',extensions.st_setsrid(
          extensions.st_makepoint(127.05,37.5),4326),'ready','{}',now(),now()+interval '30 days')""",
               (address,))
    as_user(db, a)
    assert db.execute('select request_id,status from candidate_lookup_status').fetchall() == [
        (aid, 'ready')]
    as_user(db, b)
    assert db.execute('select request_id,status from candidate_lookup_status').fetchall() == [
        (bid, 'ready')]
    db.execute('reset role')
    columns = db.execute("""select column_name from information_schema.columns
        where table_schema='public' and table_name='candidate_lookup_status'
        order by ordinal_position""").fetchall()
    assert columns == [('request_id',), ('status',), ('updated_at',)]


def test_score_inputs_supplies_pending_watch_id_and_reuses_across_radii(db):
    uid = create_user(db)
    address = f'서울특별시 강남구 역삼로 {int(uuid4()) % 90000 + 10000}'
    as_user(db, uid)
    ids = []
    for radius in (800, 1000):
        result = db.execute('select score_inputs(37.493,127.08,%s,3,%s)',
                            (radius, address)).fetchone()[0]
        lookup = result['meta']['building_lookup']
        assert lookup['status'] == 'pending'
        assert lookup['request_id']
        ids.append(lookup['request_id'])
    assert ids[0] == ids[1]
