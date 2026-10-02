from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from ingest.cleanup_anonymous import apply_manifest, classify, manifest_hash, report
from tests.integration.test_comparison_save import WEIGHTS


def seed(db, now, days, *, saved=False, **changes):
    uid = uuid4()
    old = now - timedelta(days=days)
    db.execute(
        (
            "insert into "
            "auth.users(id,is_anonymous,created_at,last_sign_in_at,raw_user_meta_data) "
            "values(%s,true,%s,%s,%s)"
        ),
        (uid, old, old, Jsonb({"retention_test": True})),
    )
    db.execute(
        "insert into app_private.user_activity(user_id,last_active_at) values(%s,%s)", (uid, old)
    )
    if saved:
        candidate = db.execute(
            (
                "insert into "
                "public.candidates(user_id,geom,floor,created_at,updated_at) "
                "values(%s,extensions.st_geomfromtext('POINT(127.05 "
                "37.5)',4326),3,%s,%s) returning id"
            ),
            (uid, old, old),
        ).fetchone()[0]
        db.execute(
            (
                "insert into "
                "public.comparisons(user_id,candidate_ids,weights,preset_id,created_at,updated_at) "
                "values(%s,%s,%s,'academy_v0',%s,%s)"
            ),
            (uid, [candidate], Jsonb(WEIGHTS), old, old),
        )
    for column, value in changes.items():
        from psycopg import sql

        db.execute(
            sql.SQL("update auth.users set {}=%s where id=%s").format(sql.Identifier(column)),
            (value, uid),
        )
    return uid


def test_retention_boundaries_exclusions_and_no_dry_run_mutation(db):
    now = datetime.now(timezone.utc)
    cases = {
        seed(db, now, 30): "recent",
        seed(db, now, 31): "eligible",
        seed(db, now, 90, saved=True): "recent",
        seed(db, now, 91, saved=True): "eligible",
        seed(db, now, 99, is_anonymous=False): "permanent",
        seed(db, now, 99, email_change="pending@example.invalid"): "linked_or_linking",
        seed(db, now, 99, email="linked@example.invalid"): "linked_or_linking",
    }
    recent = seed(db, now, 99)
    db.execute(
        "update app_private.user_activity set last_active_at=%s where user_id=%s", (now, recent)
    )
    cases[recent] = "recent"
    before = db.execute("select count(*) from auth.users").fetchone()[0]
    actual = {r["id"]: r["reason"] for r in classify(db, now.isoformat())}
    assert {uid: actual[uid] for uid in cases} == cases
    result, manifest = report(db, now.isoformat())
    assert db.execute("select count(*) from auth.users").fetchone()[0] == before
    assert result["shared_cache_rows_to_delete"] == 0
    assert result["selection_sha256"] == manifest_hash(manifest["as_of"], manifest["ids"])
    assert "ids" not in result


def test_apply_requires_separate_gate_and_approved_hash(db):
    manifest = {"as_of": datetime.now(timezone.utc).isoformat(), "ids": []}
    with pytest.raises(ValueError, match="AUTH_CLEANUP_ENABLED"):
        apply_manifest(db, manifest, manifest_hash(manifest["as_of"], []))
    with pytest.raises(ValueError, match="mismatch"):
        apply_manifest(db, manifest, "not-approved", enabled=True)


def test_actual_local_delete_rechecks_activity_and_upgrade_and_is_repeatable(db):
    now = datetime.now(timezone.utc)
    doomed = seed(db, now, 91, saved=True)
    upgraded = seed(db, now, 91, saved=True)
    active = seed(db, now, 31)
    ids = [str(u) for u in (doomed, upgraded, active)]
    manifest = {"as_of": now.isoformat(), "ids": ids}
    digest = manifest_hash(manifest["as_of"], ids)
    db.execute(
        "update auth.users set is_anonymous=false,email=%s where id=%s",
        (f"{upgraded}@example.invalid", upgraded),
    )
    db.execute(
        "update app_private.user_activity set last_active_at=%s where user_id=%s", (now, active)
    )
    try:
        result = apply_manifest(db, manifest, digest, enabled=True)
        assert result["deleted_users"] == 1
        assert result["skipped_after_recheck"] == 2
        assert (
            db.execute(
                "select count(*) from public.candidates where user_id=%s", (doomed,)
            ).fetchone()[0]
            == 0
        )
        assert (
            db.execute(
                "select count(*) from public.comparisons where user_id=%s", (doomed,)
            ).fetchone()[0]
            == 0
        )
        assert (
            db.execute(
                "select count(*) from public.candidates where user_id=%s", (upgraded,)
            ).fetchone()[0]
            == 1
        )
        assert apply_manifest(db, manifest, digest, enabled=True)["deleted_users"] == 0
    finally:
        db.execute("delete from auth.users where id=any(%s::uuid[])", (ids,))
        db.commit()
