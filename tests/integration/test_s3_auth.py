import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest

from ingest.database import connect_database


def user(db):
    uid = uuid4()
    db.execute("insert into auth.users(id,is_anonymous) values(%s,true)", (uid,))
    return uid


def as_user(db, uid, *, anonymous=True):
    db.execute("set local role authenticated")
    claims = json.dumps(dict(sub=str(uid), role="authenticated", is_anonymous=anonymous))
    db.execute("select set_config('request.jwt.claims',%s,true)", (claims,))


def candidate(db, uid):
    return db.execute("""insert into public.candidates(user_id,geom,floor) values
        (%s,extensions.st_geomfromtext('POINT(127.05 37.5)',4326),3) returning id""",
        (uid,)).fetchone()[0]


def request(db, address):
    return db.execute("""select score_internal.address_building(%s,3,
        extensions.st_geomfromtext('POINT(127.05 37.5)',4326))""", (address,)).fetchone()[0]


def test_comparisons_uid_rls_and_email_upgrade(db):
    owner, other = user(db), user(db)
    owned, foreign = candidate(db, owner), candidate(db, other)
    as_user(db, owner)
    query = """insert into public.comparisons(candidate_ids,weights,preset_id)
        values(%s,'{}','academy_v0') returning id"""
    comparison = db.execute(query, ([owned],)).fetchone()[0]
    for ids in ([foreign], [owned, foreign], [owned, owned], [uuid4()]):
        with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
            db.execute(query, (ids,))
    as_user(db, other)
    assert db.execute("select id from public.comparisons where id=%s",
                      (comparison,)).fetchall() == []
    assert db.execute("delete from public.comparisons where id=%s",
                      (comparison,)).rowcount == 0
    db.execute("reset role")
    db.execute("update auth.users set is_anonymous=false,email=%s where id=%s",
               (f"{owner}@example.invalid", owner))
    as_user(db, owner, anonymous=False)
    assert db.execute("select user_id from public.comparisons where id=%s",
                      (comparison,)).fetchone()[0] == owner
    assert db.execute("select id from public.candidates where id=%s", (owned,)).fetchone()
    with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.CheckViolation)), \
            db.transaction():
        db.execute("update public.comparisons set user_id=%s,candidate_ids=%s where id=%s",
                   (other, [foreign], comparison))


def test_queue_limit_counts_jobs_not_duplicate_upserts(db):
    uid = user(db)
    base = int(uid.hex[:8], 16)
    as_user(db, uid)
    for index in range(10):
        address = f"테스트로 {base + index}"
        assert request(db, address)["status"] == "pending"
        assert request(db, address)["status"] == "pending"
    with pytest.raises(psycopg.errors.RaiseException, match="address_request_daily_limit"), \
            db.transaction():
        request(db, f"테스트로 {base + 10}")
    db.execute("reset role")
    assert db.execute("select request_count from ingest_private.address_daily_usage "
                      "where user_id=%s", (uid,)).fetchone()[0] == 10
    assert db.execute("select count(*) from ingest_private.building_address_requests "
                      "where requester_uid=%s", (uid,)).fetchone()[0] == 10


def test_queue_requeue_and_korean_day_boundary(db):
    uid = user(db)
    address = f"테스트로 {int(uid.hex[:8], 16)}"
    db.execute("""insert into ingest_private.address_daily_usage values
        (%s,(statement_timestamp() at time zone 'Asia/Seoul')::date - 1,10)""", (uid,))
    as_user(db, uid)
    request(db, address)
    db.execute("reset role")
    db.execute("update ingest_private.building_address_requests set status='done' "
               "where requester_uid=%s", (uid,))
    as_user(db, uid)
    request(db, address)
    db.execute("reset role")
    assert db.execute("select request_count from ingest_private.address_daily_usage "
                      "where user_id=%s order by day_kst", (uid,)).fetchall() == [(10,), (2,)]


def test_unauthenticated_queue_creation_and_private_counters_are_denied(db):
    db.execute("set local role anon")
    with pytest.raises(psycopg.errors.InsufficientPrivilege,
                       match="address_request_requires_sign_in"), db.transaction():
        request(db, f"테스트로 {int(uuid4().hex[:8], 16)}")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("select * from ingest_private.address_daily_usage")


def test_cache_hit_and_worker_status_changes_do_not_consume_quota(db):
    uid = user(db)
    address = f"서울특별시 강남구 테스트로 {int(uid.hex[:8], 16)}"
    db.execute("""insert into ingest_private.building_address_cache
        (address,status,payload,fetched_at,expires_at)
        values(%s,'not_found','{}',now(),now()+interval '30 days')""", (address,))
    as_user(db, uid)
    assert request(db, address)["status"] == "not_found"
    db.execute("reset role")
    assert db.execute("select count(*) from ingest_private.address_daily_usage where user_id=%s",
                      (uid,)).fetchone()[0] == 0
    db.execute("delete from ingest_private.building_address_cache where address=%s", (address,))
    as_user(db, uid)
    assert request(db, address)["status"] == "pending"
    db.execute("reset role")
    for status in ("processing", "done"):
        db.execute("update ingest_private.building_address_requests set status=%s where address=%s",
                   (status, address))
    assert db.execute("select request_count from ingest_private.address_daily_usage "
                      "where user_id=%s",
                      (uid,)).fetchone()[0] == 1


def test_concurrent_eleventh_request_is_rolled_back():
    # Separate committed connections are needed to exercise the counter row lock.
    uid = uuid4()
    base = int(uid.hex[:8], 16)
    with connect_database(local_only=True) as db:
        db.execute("insert into auth.users(id,is_anonymous) values(%s,true)", (uid,))
        db.execute("""insert into ingest_private.address_daily_usage values
            (%s,(statement_timestamp() at time zone 'Asia/Seoul')::date,9)""", (uid,))
    barrier = Barrier(2)

    def submit(offset):
        try:
            with connect_database(local_only=True) as db:
                as_user(db, uid)
                barrier.wait(timeout=10)
                assert request(db, f"테스트로 {base + offset}")["status"] == "pending"
            return "accepted"
        except psycopg.errors.RaiseException as error:
            assert "address_request_daily_limit" in str(error)
            return "limited"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(submit, [0, 1])) == ["accepted", "limited"]
        with connect_database(local_only=True) as db:
            assert db.execute("select count(*) from ingest_private.building_address_requests "
                              "where requester_uid=%s", (uid,)).fetchone()[0] == 1
    finally:
        with connect_database(local_only=True) as db:
            db.execute("delete from ingest_private.building_address_requests "
                       "where requester_uid=%s", (uid,))
            db.execute("delete from auth.users where id=%s", (uid,))
