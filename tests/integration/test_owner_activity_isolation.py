from uuid import UUID

import psycopg
import pytest

from ingest.cleanup_anonymous import classify
from tests.integration.test_comparison_save import row, save
from tests.integration.test_s3_auth import as_user, user


def inject(db, table, events="insert or update"):
    db.execute("""create or replace function pg_temp.fail_activity() returns trigger
      language plpgsql as $$begin raise exception 'synthetic failure'
      using errcode='P0001'; end$$""")
    db.execute(
        f"create trigger synthetic_failure before {events} on {table} "
        "for each row execute function pg_temp.fail_activity()"
    )


@pytest.mark.parametrize("table", ["candidates", "comparisons", "user_weight_presets"])
def test_activity_failure_passes_source_write_and_logs_once(db, table):
    owner = user(db)
    as_user(db, owner)
    item = row()
    comparison = save(db, [item])
    db.execute("reset role")
    inject(db, "app_private.user_activity")
    as_user(db, owner)
    if table == "candidates":
        db.execute("update public.candidates set alias='유지' where id=%s", (item["id"],))
        assert (
            db.execute("select alias from public.candidates where id=%s", (item["id"],)).fetchone()[
                0
            ]
            == "유지"
        )
    elif table == "comparisons":
        db.execute("update public.comparisons set manual_order=false where id=%s", (comparison,))
        assert (
            db.execute(
                "select manual_order from public.comparisons where id=%s", (comparison,)
            ).fetchone()[0]
            is False
        )
    else:
        db.execute(
            "insert into public.user_weight_presets(name,weights) select '유지',weights "
            "from public.comparisons where id=%s",
            (comparison,),
        )
        assert (
            db.execute(
                "select count(*) from public.user_weight_presets where name='유지'"
            ).fetchone()[0]
            == 1
        )
    db.execute("reset role")
    errors = db.execute(
        "select sqlstate from app_private.projection_errors "
        "where source_table='app_private.user_activity' "
        "and row_id=%s and resolved_at is null",
        (str(owner),),
    ).fetchall()
    assert errors == [("P0001",)]
    now = db.execute("select now()").fetchone()[0]
    assert (
        next(r for r in classify(db, now) if r["id"] == owner)["reason"] == "activity_record_failed"
    )
    db.execute("drop trigger synthetic_failure on app_private.user_activity")
    as_user(db, owner)
    db.execute("select public.touch_user_activity()")
    db.execute("reset role")
    assert (
        db.execute(
            "select count(*) from app_private.projection_errors "
            "where row_id=%s and resolved_at is null",
            (str(owner),),
        ).fetchone()[0]
        == 0
    )


def test_save_rpc_activity_failure_does_not_abort_transaction(db):
    owner = user(db)
    inject(db, "app_private.user_activity")
    as_user(db, owner)
    item = row()
    comparison = save(db, [item])
    assert db.execute(
        "select candidate_ids from public.comparisons where id=%s", (comparison,)
    ).fetchone()[0] == [UUID(item["id"])]


def test_error_journal_failure_is_also_nonblocking(db):
    owner = user(db)
    inject(db, "app_private.user_activity")
    inject(db, "app_private.projection_errors")
    as_user(db, owner)
    save(db, [row()])


def test_candidate_delete_integrity_failure_rolls_back_source_delete(db):
    owner = user(db)
    as_user(db, owner)
    item = row()
    comparison = save(db, [item])
    db.execute("reset role")
    inject(db, "public.comparisons", "update or delete")
    as_user(db, owner)
    with pytest.raises(psycopg.errors.RaiseException), db.transaction():
        db.execute("delete from public.candidates where id=%s", (item["id"],))
    assert (
        db.execute("select count(*) from public.candidates where id=%s", (item["id"],)).fetchone()[
            0
        ]
        == 1
    )
    assert (
        len(
            db.execute(
                "select candidate_ids from public.comparisons where id=%s", (comparison,)
            ).fetchone()[0]
        )
        == 1
    )
