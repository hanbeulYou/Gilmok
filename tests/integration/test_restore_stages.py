from contextlib import contextmanager

import psycopg
import pytest

from ingest.copy_batches import chunked_copy
from ingest.restore_provenance import table_signature
from ingest.restore_stages import execute_stage


def test_copy_failure_rolls_back_prior_completed_copy_batch(db):
    db.execute("create temporary table copy_proof(value integer) on commit drop")
    with pytest.raises(psycopg.errors.InvalidTextRepresentation), db.transaction():
        with db.cursor() as cursor, chunked_copy(cursor, "copy copy_proof from stdin") as copy:
            for n in range(50_001):
                copy.write_row((n,))
            copy.write_row(("invalid integer",))
    assert db.execute("select count(*) from copy_proof").fetchone()[0] == 0


def test_stage_checkpoint_is_atomic_and_refuses_changed_manifest_or_data(db):
    db.execute("truncate ingest_private.restore_stages,public.admin_dongs,"
               "public.legal_dongs cascade")
    tables = ("admin_dongs", "legal_dongs")
    expected = {t: table_signature(db, t) for t in tables}

    @contextmanager
    def factory():
        with db.transaction():
            yield db

    def fail(connection):
        connection.execute("create temporary table rolled_back_stage(id integer)")
        raise RuntimeError("injected failure")

    with pytest.raises(RuntimeError, match="injected"):
        execute_stage(factory, 1, "a" * 64, expected, fail)
    assert db.execute("select count(*) from ingest_private.restore_stages").fetchone()[0] == 0
    assert db.execute("select to_regclass('pg_temp.rolled_back_stage')").fetchone()[0] is None
    result = execute_stage(factory, 1, "a" * 64, expected, lambda _: None)
    assert result["status"] == "committed"
    result = execute_stage(factory, 1, "a" * 64, expected, fail)
    assert result["status"] == "skipped"
    with pytest.raises(ValueError, match="manifest differs"):
        execute_stage(factory, 1, "b" * 64, expected, fail)
    db.execute("update ingest_private.restore_stages set row_counts='{}'")
    with pytest.raises(ValueError, match="checkpoint differs"):
        execute_stage(factory, 1, "a" * 64, expected, fail)
