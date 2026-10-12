"""Real PostgreSQL commit visibility, source failure and reference failure proofs."""

import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from ingest.database import LOCAL_DB_URL
from ingest.refresh_monthly import execute_monthly
from ingest.score_reference import fingerprint


@pytest.mark.parametrize("failure", ["source", "display", "reference", None])
def test_academy_floor_source_reference_are_one_release(monthly_db, failure):
    from ingest.academy_display import load_display

    migration = Path("supabase/migrations/20261012150926_academy_display_provenance.sql")
    with monthly_db() as db:
        db.execute(migration.read_text())
        db.execute("create table public.academies(id text primary key,geocode_provider text)")
        db.execute("insert into public.academies values('1','juso')")
        load_display(
            db,
            [("1", "1층", "explicit", "old", "a" * 64)],
            revision="old",
            version="2026-09-19",
            raw_sha256="a" * 64,
        )
        if failure == "display":
            db.execute("""create function app_private.force_display_failure() returns trigger
                language plpgsql as $$begin raise exception 'forced display failure'
                using errcode='P0001'; end$$;
                create trigger display_fail before insert on app_private.academy_display
                for each row execute function app_private.force_display_failure()""")

    def observe():
        with monthly_db() as db:
            return db.execute("""select s.value,r.value,d.floor_label,m.source_revision
                from public.monthly_source s cross join public.score_reference r
                cross join app_private.academy_display d
                cross join app_private.academy_display_release m""").fetchone()

    old = observe()
    seen = []

    def prepare(_, db):
        def loader(db):
            db.execute("update public.monthly_source set value=2")
            seen.append(observe())
            if failure == "source":
                raise ValueError("forced source failure")
            load_display(
                db,
                [("1", "3층", "explicit", "new", "b" * 64)],
                revision="new",
                version="2026-10-10",
                raw_sha256="b" * 64,
            )
            seen.append(observe())

        return date(2026, 10, 10), {}, loader

    def reference(db):
        def loader(db):
            db.execute("update public.score_reference set value=2")
            seen.append(observe())
            if failure == "reference":
                raise ValueError("forced reference failure")

        return date(2026, 10, 13), {}, loader

    result = execute_monthly(
        ("monthly_test",),
        "20261013T000000Z",
        monthly_db,
        prepare,
        reference,
        maintenance=lambda *_: None,
    )
    assert result["committed"] == (failure is None)
    assert all(row == old for row in seen)
    assert observe() == ((2, 2, "3층", "new") if failure is None else old)


@pytest.fixture
def monthly_db(monkeypatch):
    # A disposable local database, never the user's source/candidate tables.
    assert conninfo_to_dict(LOCAL_DB_URL)["host"] == "127.0.0.1"
    name = "gilmok_monthly_test_" + uuid.uuid4().hex[:12]
    with psycopg.connect(LOCAL_DB_URL, autocommit=True) as admin:
        admin.execute(sql.SQL("create database {} template template0").format(sql.Identifier(name)))
    dsn = make_conninfo(LOCAL_DB_URL, dbname=name)
    try:
        with psycopg.connect(dsn, autocommit=True) as db:
            db.execute("create schema ingest_private")
            db.execute(
                "create table public.monthly_source (value int check(value>0)); "
                "insert into public.monthly_source values(1); "
                "create table public.score_reference (value int check(value>0)); "
                "insert into public.score_reference values(1)"
            )
            db.execute(
                "create table public.score_reference_sets (preset_id text,source_fingerprint text)"
            )
            db.execute(
                "create table ingest_private.refresh_snapshots "
                "(source text primary key,period_end date,snapshot text,manifest jsonb,"
                "committed_at timestamptz default now())"
            )
            for table in (
                "place_snapshots",
                "transit_coverage",
                "building_snapshots",
                "rent_snapshots",
            ):
                db.execute(
                    sql.SQL("create table ingest_private.{} (value int)").format(
                        sql.Identifier(table)
                    )
                )
        monkeypatch.setattr(
            "ingest.refresh_monthly.TABLES",
            {
                "monthly_test": ("monthly_source",),
                "score_reference": ("score_reference", "score_reference_sets"),
            },
        )
        monkeypatch.setattr(
            "ingest.refresh_monthly.source_state",
            lambda db: {
                "value": db.execute("select value from public.monthly_source").fetchone()[0]
            },
        )

        @contextmanager
        def factory():
            with psycopg.connect(dsn) as connection:
                yield connection

        yield factory
    finally:
        with psycopg.connect(LOCAL_DB_URL, autocommit=True) as admin:
            admin.execute(sql.SQL("drop database {} with(force)").format(sql.Identifier(name)))


@pytest.mark.parametrize(
    "failure", ["collection", "source_copy", "reference", "reference_copy", None]
)
def test_old_pair_visible_until_both_commit(monthly_db, failure):
    seen = []

    def observe():
        with monthly_db() as observer:
            # Same SQL statement snapshot: never half a release.
            return observer.execute(
                "select s.value,r.value from public.monthly_source s "
                "cross join public.score_reference r"
            ).fetchone()

    def prepare(source, db):
        if failure == "collection":
            raise ConnectionError("Synthetic upstream failure")

        def loader(connection):
            connection.execute("update public.monthly_source set value=2")
            seen.append(observe())
            if failure == "source_copy":
                connection.execute("update public.monthly_source set value=0")

        return date(2026, 11, 30), {}, loader

    def reference(db):
        assert db.execute("select value from public.monthly_source").fetchone()[0] == 2
        seen.append(observe())
        if failure == "reference":
            raise ValueError("Synthetic bridge/publication failure")

        def loader(connection):
            connection.execute("update public.score_reference set value=2")
            seen.append(observe())
            if failure == "reference_copy":
                connection.execute("update public.score_reference set value=0")

        return date(2026, 12, 1), {}, loader

    report = execute_monthly(
        ("monthly_test",),
        "20261201T000000Z",
        monthly_db,
        prepare,
        reference,
        maintenance=lambda *_: None,
    )
    assert all(pair == (1, 1) for pair in seen)
    assert report["committed"] is (failure is None)
    assert observe() == ((2, 2) if failure is None else (1, 1))
    with monthly_db() as db:
        assert db.execute("select count(*) from ingest_private.refresh_snapshots").fetchone()[
            0
        ] == (2 if failure is None else 0)


def test_maintenance_failure_cannot_undo_valid_pair(monthly_db):
    def prepare(_, db):
        return (
            date(2026, 11, 30),
            {},
            lambda c: c.execute("update public.monthly_source set value=2"),
        )

    def reference(db):
        return (
            date(2026, 12, 1),
            {},
            lambda c: c.execute("update public.score_reference set value=2"),
        )

    def maintenance(*_):
        raise RuntimeError("Synthetic VACUUM failure")

    report = execute_monthly(
        ("monthly_test",),
        "20261201T000000Z",
        monthly_db,
        prepare,
        reference,
        maintenance=maintenance,
    )
    assert report["committed"] and report["status"] == "maintenance_failed"
    with monthly_db() as db:
        assert db.execute(
            "select s.value,r.value from public.monthly_source s cross join "
            "public.score_reference r"
        ).fetchone() == (2, 2)


def test_completed_snapshot_retry_skips_collection_and_rebuild(monthly_db):
    def prepare(_, db):
        return (
            date(2026, 11, 30),
            {},
            lambda c: c.execute("update public.monthly_source set value=2"),
        )

    def reference(db):
        def load(c):
            c.execute("update public.score_reference set value=2")
            c.execute(
                "insert into public.score_reference_sets values('academy_v0',%s)",
                (fingerprint({"value": 2}),),
            )

        return date(2026, 12, 1), {}, load

    first = execute_monthly(
        ("monthly_test",),
        "20261201T000000Z",
        monthly_db,
        prepare,
        reference,
        maintenance=lambda *_: None,
    )
    assert first["committed"]

    def forbidden(*_):
        raise AssertionError("Completed retry must not call upstream APIs or rebuild")

    again = execute_monthly(
        ("monthly_test",),
        "20261201T000000Z",
        monthly_db,
        forbidden,
        forbidden,
        maintenance=lambda *_: None,
    )
    assert again["status"] == "already_current" and again["committed"]


def test_concurrent_source_change_during_preparation_is_rejected(monthly_db):
    def prepare(_, db):
        # Represents a different source/manual publisher completing during API downloads.
        with monthly_db() as other:
            other.execute("update public.monthly_source set value=3")
            other.execute("update public.score_reference set value=3")
        return (
            date(2026, 11, 30),
            {},
            lambda c: c.execute("update public.monthly_source set value=2"),
        )

    def forbidden(*_):
        raise AssertionError("Stale preparation must not reach reference generation")

    result = execute_monthly(
        ("monthly_test",),
        "20261201T000000Z",
        monthly_db,
        prepare,
        forbidden,
        maintenance=lambda *_: None,
    )
    assert not result["committed"] and result["error_type"] == "ValueError"
    with monthly_db() as db:
        assert db.execute(
            "select s.value,r.value from public.monthly_source s cross join "
            "public.score_reference r"
        ).fetchone() == (3, 3)
