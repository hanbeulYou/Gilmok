from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from tests.integration.test_comparison_save import WEIGHTS, row, save
from tests.integration.test_s3_auth import as_user, user


def save_v2(db, rows, *, version="0.4.0", comparison=None, weights=None):
    return db.execute(
        "select public.save_comparison_v2(%s,%s,%s,%s,%s,true,%s)",
        (
            comparison or uuid4(),
            Jsonb(rows),
            Jsonb(weights or WEIGHTS),
            [r["id"] for r in rows],
            version,
            "20260923T111436Z",
        ),
    ).fetchone()[0]


def loaded(db, comparison):
    return db.execute("select public.load_comparison(%s)", (comparison,)).fetchone()[0]


def test_mixed_client_versions_and_retry_preserve_inputs(db):
    as_user(db, user(db))
    rows = [row(), row()]
    comparison = save(db, rows)
    assert loaded(db, comparison)["comparison"]["scoring_model_version"] is None
    save_v2(db, rows, comparison=comparison)
    assert save_v2(db, rows, comparison=comparison) == comparison
    value = loaded(db, comparison)
    assert value["comparison"]["scoring_model_version"] == "0.4.0"
    assert value["comparison"]["preset_version"] == "0.3"
    assert value["comparison"]["weights"] == WEIGHTS
    assert value["comparison"]["candidate_ids"] == [r["id"] for r in rows]
    assert [r["id"] for r in value["candidates"]] == [r["id"] for r in rows]
    save(db, rows, comparison=comparison)
    assert loaded(db, comparison)["comparison"]["scoring_model_version"] is None
    save_v2(db, rows, comparison=comparison, version=None)
    assert loaded(db, comparison)["comparison"]["scoring_model_version"] is None


def test_versioned_save_uid_isolation(db):
    owner, other = user(db), user(db)
    as_user(db, owner)
    rows = [row()]
    comparison = save_v2(db, rows)
    as_user(db, other)
    assert loaded(db, comparison) is None
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        save_v2(db, rows, comparison=comparison)
    assert db.execute("select count(*) from public.candidates").fetchone()[0] == 0
    as_user(db, owner)
    assert loaded(db, comparison)["comparison"]["scoring_model_version"] == "0.4.0"


@pytest.mark.parametrize("version", ["", "latest", "0.4.x", "0.4.0 ", "1" * 33 + ".0"])
def test_invalid_version_saves_nothing(db, version):
    as_user(db, user(db))
    with pytest.raises(psycopg.errors.InvalidParameterValue), db.transaction():
        save_v2(db, [row()], version=version)
    assert db.execute("select count(*) from public.candidates").fetchone()[0] == 0
    assert db.execute("select count(*) from public.comparisons").fetchone()[0] == 0


def test_model_tag_failure_rolls_back_all_writes(db):
    owner = user(db)
    as_user(db, owner)
    rows = [row()]
    comparison = save_v2(db, rows)
    before = loaded(db, comparison)
    db.execute("reset role")
    db.execute("""create function pg_temp.reject_model_tag() returns trigger
        language plpgsql as $$ begin raise exception 'forced_model_tag_failure'
        using errcode='P0001'; end; $$""")
    db.execute("""create trigger reject_model_tag before update of scoring_model_version
        on public.comparisons for each row when (new.scoring_model_version is not null)
        execute function pg_temp.reject_model_tag()""")
    as_user(db, owner)
    changed = [{**rows[0], "alias": "롤백 대상"}, row()]
    with (
        pytest.raises(psycopg.errors.RaiseException, match="forced_model_tag_failure"),
        db.transaction(),
    ):
        save_v2(db, changed, comparison=comparison, weights={**WEIGHTS, "demand": 17})
    assert loaded(db, comparison) == before
    assert db.execute("select count(*) from public.candidates").fetchone()[0] == 1


def test_rpc_security_contract(db):
    for name, arguments in [
        ("save_comparison", "uuid,jsonb,jsonb,uuid[],boolean,text"),
        ("save_comparison_v2", "uuid,jsonb,jsonb,uuid[],text,boolean,text"),
    ]:
        value = db.execute(
            """select p.prosecdef, p.proconfig,
            has_function_privilege('authenticated',p.oid,'execute'),
            has_function_privilege('anon',p.oid,'execute')
            from pg_proc p where p.oid=%s::regprocedure""",
            (f"public.{name}({arguments})",),
        ).fetchone()
        assert value == (True, ['search_path=""'], True, False)
    db.execute("set local role anon")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        save_v2(db, [row()])
