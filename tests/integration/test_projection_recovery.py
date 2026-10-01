import pytest
from psycopg.errors import InsufficientPrivilege

from tests.integration.test_registration_usage import as_user, create_user


@pytest.fixture
def watched(db):
    uid = create_user(db)
    address = '서울특별시 강남구 역삼로 99999-6101'
    db.execute('insert into ingest_private.building_address_requests(address) values(%s)',
               (address,))
    as_user(db, uid)
    request_id = db.execute('select watch_candidate_lookup(%s)', (address,)).fetchone()[0]
    db.execute('reset role')
    return db, uid, address, request_id


def fail_projection(db):
    db.execute("""create function pg_temp.fail_projection() returns trigger language plpgsql as $$
        begin raise exception 'forced_projection_failure' using errcode='P0001'; end; $$""")
    db.execute('''create trigger forced_projection_failure before update on candidate_lookup_status
        for each row execute function pg_temp.fail_projection()''')


def status(db, request_id):
    return db.execute('select status from candidate_lookup_status where request_id=%s',
                      (request_id,)).fetchone()[0]


@pytest.mark.parametrize('source', ['queue', 'cache'])
def test_source_write_survives_and_sweep_recovers(watched, source):
    db, uid, address, request_id = watched
    fail_projection(db)
    if source == 'queue':
        db.execute("update ingest_private.building_address_requests set status='processing' "
                   'where address=%s', (address,))
        assert db.execute('select status from ingest_private.building_address_requests '
                          'where address=%s', (address,)).fetchone()[0] == 'processing'
        expected, table = 'processing', 'ingest_private.building_address_requests'
    else:
        db.execute("""insert into ingest_private.building_address_cache
            (address,status,payload,fetched_at,expires_at) values(%s,'not_found','{}',
            now(),now()+interval '30 days')""", (address,))
        assert db.execute('select status from ingest_private.building_address_cache '
                          'where address=%s', (address,)).fetchone()[0] == 'not_found'
        expected, table = 'not_found', 'ingest_private.building_address_cache'
    assert status(db, request_id) == 'pending'
    assert db.execute('select source_table,row_id,sqlstate,message '
                      'from app_private.projection_errors').fetchall() == [
        (table, address, 'P0001', 'forced_projection_failure')]
    dry = db.execute('select app_private.reconcile_candidate_lookup(false)').fetchone()[0]
    assert dry['dry_run'] and dry['mismatched'] == 1 and dry['repaired'] == 0
    assert dry['unresolved_errors'] == 1
    assert status(db, request_id) == 'pending'
    db.execute('drop trigger forced_projection_failure on candidate_lookup_status')
    result = db.execute('select app_private.reconcile_candidate_lookup(true)').fetchone()[0]
    assert result['repaired'] == result['errors_resolved'] == 1
    assert result['unresolved_errors'] == result['failed_addresses'] == 0
    assert status(db, request_id) == expected
    again = db.execute('select app_private.reconcile_candidate_lookup(true)').fetchone()[0]
    assert again['repaired'] == again['errors_resolved'] == 0
    as_user(db, uid)
    with pytest.raises(InsufficientPrivilege), db.transaction():
        db.execute('select * from app_private.projection_errors')
    with pytest.raises(InsufficientPrivilege), db.transaction():
        db.execute('select app_private.reconcile_candidate_lookup(true)')


def test_journal_failure_also_preserves_queue_and_sweep_finds_drift(watched):
    db, _, address, request_id = watched
    fail_projection(db)
    db.execute('''create trigger forced_journal_failure
        before insert on app_private.projection_errors
        for each row execute function pg_temp.fail_projection()''')
    db.execute("update ingest_private.building_address_requests set status='processing' "
               'where address=%s', (address,))
    assert db.execute('select count(*) from app_private.projection_errors').fetchone()[0] == 0
    assert status(db, request_id) == 'pending'
    db.execute('drop trigger forced_projection_failure on candidate_lookup_status')
    repaired = db.execute('select app_private.reconcile_candidate_lookup(true)').fetchone()[0]
    assert repaired['repaired'] == 1
    assert status(db, request_id) == 'processing'


def test_failed_reconcile_keeps_errors_unresolved(watched):
    db, _, address, _ = watched
    fail_projection(db)
    db.execute("update ingest_private.building_address_requests set status='processing' "
               'where address=%s', (address,))
    result = db.execute('select app_private.reconcile_candidate_lookup(true)').fetchone()[0]
    assert result['repaired'] == result['errors_resolved'] == 0
    assert result['failed_addresses'] == 1 and result['unresolved_errors'] == 2
