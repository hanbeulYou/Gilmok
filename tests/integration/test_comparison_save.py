from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from tests.integration.test_s3_auth import as_user, user

WEIGHTS = dict(
    demand=30,
    flow=15,
    transit=15,
    cluster=15,
    exposure=5,
    building=10,
    environment=5,
    rent_efficiency=5,
)


def row(**changes):
    return dict(
        id=str(uuid4()),
        alias="검증",
        lat=37.5,
        lng=127.05,
        floor=3,
        address="서울특별시 강남구 역삼로 460",
        pnu="1168010600109120013",
        deposit=0,
        user_rent=None,
        management_fee=None,
        area_m2=42,
        address_provenance={},
        registration_context={},
        **changes,
    )


def save(db, rows, *, weights=None, comparison=None, order=None):
    return db.execute(
        "select public.save_comparison(%s,%s,%s,%s,true,%s)",
        (
            comparison or uuid4(),
            Jsonb(rows),
            Jsonb(weights or WEIGHTS),
            order or [r["id"] for r in rows],
            "20260923T111436Z",
        ),
    ).fetchone()[0]


def test_atomic_owner_save_reopen_retry_and_upgrade(db):
    owner, other = user(db), user(db)
    as_user(db, owner)
    rows = [row(), row()]
    comparison = save(db, rows, order=[rows[1]["id"], rows[0]["id"]])
    assert save(db, rows, comparison=comparison, order=[rows[1]["id"], rows[0]["id"]]) == comparison
    loaded = db.execute("select public.load_comparison(%s)", (comparison,)).fetchone()[0]
    assert loaded["comparison"]["candidate_ids"] == [rows[1]["id"], rows[0]["id"]]
    assert loaded["comparison"]["weights"] == WEIGHTS
    assert loaded["comparison"]["manual_order"] is True
    assert loaded["candidates"][0]["deposit"] == 0
    assert loaded["candidates"][0]["user_rent"] is None
    as_user(db, other)
    assert db.execute("select public.load_comparison(%s)", (comparison,)).fetchone()[0] is None
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        save(db, rows, comparison=comparison)
    db.execute("reset role")
    db.execute(
        "update auth.users set is_anonymous=false,email=%s where id=%s",
        (f"{owner}@example.invalid", owner),
    )
    as_user(db, owner, anonymous=False)
    assert db.execute("select public.load_comparison(%s)", (comparison,)).fetchone()[0] == loaded


def test_partial_candidate_write_rolls_back_on_foreign_id(db):
    owner, other = user(db), user(db)
    foreign = row()
    as_user(db, other)
    save(db, [foreign])
    as_user(db, owner)
    first = row()
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        save(db, [first, foreign])
    assert (
        db.execute("select count(*) from public.candidates where id=%s", (first["id"],)).fetchone()[
            0
        ]
        == 0
    )


@pytest.mark.parametrize(
    "case", ["duplicate", "six", "foreign_order", "zero_floor", "weight_41", "unknown_lookup"]
)
def test_save_rejects_invalid_transaction(db, case):
    as_user(db, user(db))
    rows, weights, order = [row()], WEIGHTS, None
    if case == "duplicate":
        rows *= 2
    elif case == "six":
        rows = [row() for _ in range(6)]
    elif case == "foreign_order":
        order = [str(uuid4())]
    elif case == "zero_floor":
        rows[0]["floor"] = 0
    elif case == "weight_41":
        weights = {**WEIGHTS, "demand": 41}
    else:
        rows[0]["lookup_request_id"] = str(uuid4())
    with (
        pytest.raises((psycopg.errors.InvalidParameterValue, psycopg.errors.InsufficientPrivilege)),
        db.transaction(),
    ):
        save(db, rows, weights=weights, order=order)
    assert db.execute("select count(*) from public.candidates").fetchone()[0] == 0


def test_delete_candidate_repairs_all_comparisons_and_empty_set(db):
    as_user(db, user(db))
    a, b = row(), row()
    first, second = save(db, [a, b]), save(db, [a])
    db.execute("delete from public.candidates where id=%s", (a["id"],))
    assert db.execute(
        "select candidate_ids from public.comparisons where id=%s", (first,)
    ).fetchone()[0] == [uuid4_from(b["id"])]
    assert db.execute("select id from public.comparisons where id=%s", (second,)).fetchone() is None


def uuid4_from(value):
    from uuid import UUID

    return UUID(value)


def test_presets_raw_ratio_rls_and_all_zero(db):
    owner, other = user(db), user(db)
    as_user(db, owner)
    weights = {**WEIGHTS, "demand": 17}
    preset = db.execute(
        (
            "insert into public.user_weight_presets(name,weights) values('나의 "
            "학원',%s) returning id,weights,normalized_weights"
        ),
        (Jsonb(weights),),
    ).fetchone()
    assert preset[1]["demand"] == 17
    assert preset[2]["demand"] == pytest.approx(17 / 87)
    zero = {k: 0 for k in WEIGHTS}
    assert save(db, [row()], weights=zero)
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(
            "insert into public.user_weight_presets(name,weights) values('영',%s)", (Jsonb(zero),)
        )
    as_user(db, other)
    assert (
        db.execute("select * from public.user_weight_presets where id=%s", (preset[0],)).fetchall()
        == []
    )
    assert (
        db.execute("delete from public.user_weight_presets where id=%s", (preset[0],)).rowcount == 0
    )
