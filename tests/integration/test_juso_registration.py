"""New coordinate projection and quota; existing provider counters remain usable."""

import pytest
from psycopg.errors import InsufficientPrivilege, InvalidParameterValue

from tests.integration.test_registration_usage import as_user, create_user


def test_juso_coordinate_quota_is_separate_and_shared_limit_is_atomic(db):
    owner, other = create_user(db), create_user(db)
    as_user(db, owner)
    for index in range(100):
        provider = 'juso_search' if index < 60 else 'juso_coordinate'
        assert db.execute('select claim_address_call(%s)', (provider,)).fetchone()[0]
    assert not db.execute("select claim_address_call('juso_coordinate')").fetchone()[0]
    as_user(db, other)
    assert db.execute("select claim_address_call('juso_coordinate')").fetchone()[0]
    db.execute('reset role')
    assert db.execute('''select total,juso_search,juso_coordinate,vworld_coordinate
        from app_private.address_daily_usage where user_id=%s''',
        (owner,)).fetchone() == (100, 60, 40, 0)


def test_projection_authenticated_only_and_epsg_origin(db):
    uid = create_user(db)
    db.execute('set local role anon')
    with pytest.raises(InsufficientPrivilege), db.transaction():
        db.execute('select project_juso_coordinate(1000000,2000000)')
    as_user(db, uid)
    point = db.execute('select project_juso_coordinate(1000000,2000000)').fetchone()[0]
    assert point['lng'] == pytest.approx(127.5, abs=1e-9)
    assert point['lat'] == pytest.approx(38, abs=1e-9)
    for x, y in [(None, 2000000), (float('nan'), 2000000), (0, 0), (float('inf'), 2000000)]:
        with pytest.raises(InvalidParameterValue), db.transaction():
            db.execute('select project_juso_coordinate(%s,%s)', (x, y))
