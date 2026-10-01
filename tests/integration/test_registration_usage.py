import json
from uuid import uuid4

import pytest
from psycopg.errors import InsufficientPrivilege, InvalidParameterValue


def create_user(db):
    uid = uuid4()
    db.execute("insert into auth.users(id,is_anonymous) values(%s,true)", (uid,))
    return uid


def as_user(db, uid):
    db.execute("set local role authenticated")
    db.execute("select set_config('request.jwt.claims',%s,true)",
               (json.dumps({'sub': str(uid), 'role': 'authenticated'}),))


def test_daily_limit_provider_counts_and_private_activity(db):
    owner, other = create_user(db), create_user(db)
    as_user(db, owner)
    for index in range(100):
        provider = 'juso_search' if index < 70 else 'vworld_coordinate'
        assert db.execute('select claim_address_call(%s)', (provider,)).fetchone()[0]
    assert not db.execute("select claim_address_call('juso_search')").fetchone()[0]
    with pytest.raises(InsufficientPrivilege), db.transaction():
        db.execute('select * from app_private.address_daily_usage')
    as_user(db, other)
    assert db.execute("select claim_address_call('juso_search')").fetchone()[0]
    db.execute('reset role')
    assert db.execute('select total,juso_search,vworld_coordinate '
                      'from app_private.address_daily_usage where user_id=%s',
                      (owner,)).fetchone() == (100, 70, 30)
    assert db.execute('select last_active_at <= now() '
                      'from app_private.user_activity where user_id=%s', (owner,)).fetchone()[0]


def test_requires_authenticated_identity_and_valid_provider(db):
    uid = create_user(db)
    db.execute('set local role anon')
    with pytest.raises(InsufficientPrivilege), db.transaction():
        db.execute("select claim_address_call('juso_search')")
    as_user(db, uid)
    with pytest.raises(InvalidParameterValue), db.transaction():
        db.execute("select claim_address_call('kakao')")
    with pytest.raises(InsufficientPrivilege), db.transaction():
        db.execute('select * from public.geocode_cache')
