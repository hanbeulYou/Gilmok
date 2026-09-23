from datetime import date

import duckdb
import pytest
from psycopg.errors import CheckViolation, InsufficientPrivilege

from ingest.refresh import promote
from ingest.score_reference import fingerprint, load_snapshot, source_state


def fixture_file(tmp_path, value=1):
    path = tmp_path / (str(value) + ".parquet")
    with duckdb.connect() as c:
        c.sql(
            "select 'fixture' cell_id,800 radius_m,'demand' axis_key,?::double raw_value",
            params=[value],
        ).write_parquet(str(path))
    return path


def manifest(snapshot="20260923T000000Z"):
    return dict(
        snapshot=snapshot,
        computed_at="2026-09-23T00:00:00Z",
        preset=dict(id="pr_s2_fixture", version="0.1.2", schema_version="1.3"),
        cell_count=1,
        row_count=1,
        source_state={},
        source_fingerprint="fixture",
        statistics=[],
    )


def test_reference_failure_rolls_back_both_public_tables_and_private_manifest(db, tmp_path):
    old = manifest()

    def load_old(c):
        load_snapshot(c, fixture_file(tmp_path), old, verify_sources=False)

    promote(db, "score_reference_fixture", date(2026, 9, 23), old["snapshot"], old, load_old)
    before = db.execute(
        "select manifest from ingest_private.refresh_snapshots "
        "where source='score_reference_fixture'"
    ).fetchone()[0]
    new = manifest("20260923T010000Z")
    with pytest.raises(CheckViolation):
        promote(
            db,
            "score_reference_fixture",
            date(2026, 9, 23),
            new["snapshot"],
            new,
            lambda c: load_snapshot(c, fixture_file(tmp_path, -1), new, verify_sources=False),
        )
    assert (
        db.execute(
            "select raw_value from public.score_reference where preset_id='pr_s2_fixture'"
        ).fetchone()[0]
        == 1
    )
    assert (
        db.execute(
            "select snapshot from public.score_reference_sets where preset_id='pr_s2_fixture'"
        ).fetchone()[0]
        == old["snapshot"]
    )
    assert (
        db.execute(
            "select manifest from ingest_private.refresh_snapshots "
            "where source='score_reference_fixture'"
        ).fetchone()[0]
        == before
    )


def test_changed_sources_never_replace_reference(db, tmp_path):
    with pytest.raises(ValueError, match="Sources changed"):
        with db.transaction():
            load_snapshot(db, fixture_file(tmp_path), manifest())
    assert (
        db.execute(
            "select count(*) from public.score_reference where preset_id='pr_s2_fixture'"
        ).fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_reference_read_allowed_but_write_refused(db, role):
    from psycopg import sql

    with db.transaction():
        db.execute(sql.SQL("set local role {}").format(sql.Identifier(role)))
        db.execute("select * from public.score_reference limit 1")
        db.execute("select * from public.score_reference_sets limit 1")
        with pytest.raises(InsufficientPrivilege):
            with db.transaction():
                db.execute("delete from public.score_reference")


def test_source_fingerprint_changes_with_boundary_geometry(db):
    # Source tables may be empty in CI. A grid addition must still invalidate a captured run.
    before = fingerprint(source_state(db))
    db.execute("""insert into public.population_cells
        (resolution_m,cell_id,geom,source,source_version,
        boundary_generated,estimated) values(250,'pr_s2_fixture',
        extensions.st_geomfromtext(
          'POLYGON((127 37.5,127.001 37.5,127.001 37.501,127 37.501,127 37.5))',4326),
        'fixture','1',false,false)""")
    assert fingerprint(source_state(db)) != before


def test_copy_keeps_binary_float_precision_even_if_text_reads_are_rounded(db, tmp_path):
    value = 1.2345678901234567
    db.execute("set local extra_float_digits=0")
    load_snapshot(db, fixture_file(tmp_path, value), manifest(), verify_sources=False)
    exact = (
        db.cursor(binary=True)
        .execute("select raw_value from public.score_reference where preset_id='pr_s2_fixture'")
        .fetchone()[0]
    )
    assert exact == value


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_reference_rpc_preserves_float_precision_and_null_population(db, tmp_path, role):
    from psycopg import sql

    value = 1.2345678901234567
    load_snapshot(db, fixture_file(tmp_path, value), manifest(), verify_sources=False)
    db.execute("set local extra_float_digits=0")
    db.execute(sql.SQL("set local role {}").format(sql.Identifier(role)))
    result = db.execute(
        "select public.score_reference_distribution('pr_s2_fixture',800)"
    ).fetchone()[0]
    assert result["distributions"] == [
        dict(radius_m=800, key="demand", cell_count=1, values=[value])
    ]
    assert result["inputs_schema_version"] == "1.3"
    assert (
        db.execute("select public.score_reference_distribution('absent',800)").fetchone()[0] is None
    )


def test_reference_rpc_refuses_nearby_radius_substitution(db):
    from psycopg.errors import InvalidParameterValue

    with pytest.raises(InvalidParameterValue):
        with db.transaction():
            db.execute("select public.score_reference_distribution('academy_v0',500)")
