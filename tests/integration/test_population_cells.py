from uuid import uuid4

import psycopg
import pytest

from ingest.population_database import load_population_cells

POLYGON = "POLYGON((127.05 37.49,127.06 37.49,127.06 37.50,127.05 37.50,127.05 37.49))"
SOURCE = "population_cell_test"


def load(db, rows, **kwargs):
    return load_population_cells(
        db, rows, source=SOURCE, source_version="fixture", **kwargs
    )


def row():
    return {"cell_id": str(uuid4()), "wkt": POLYGON, "boundary_generated": True}


def test_cell_snapshot_is_idempotent_and_keeps_provenance(db):
    item = row()
    assert load(db, [item]) == load(db, [item]) == 1
    assert db.execute(
        "select resolution_m, boundary_generated, estimated, extensions.st_srid(geom), "
        "source_version from public.population_cells where cell_id=%s", (item["cell_id"],)
    ).fetchone() == (250, True, False, 4326, "fixture")
    assert db.execute(
        "select count(*) from ingest_private.ingest_runs where source=%s", (SOURCE,)
    ).fetchone() == (2,)
    assert db.execute(
        "select indexdef from pg_indexes where indexname='population_cells_geom_idx'"
    ).fetchone()[0].endswith("USING gist (geom)")


@pytest.mark.parametrize("failure", ["duplicate", "empty", "geometry", "generated"])
def test_failed_grid_load_preserves_snapshot_and_audit(db, failure):
    previous, new = row(), row()
    load(db, [previous])
    rows = {
        "duplicate": [new, new],
        "empty": [],
        "geometry": [{**new, "wkt": "POINT(127.05 37.49)"}],
        "generated": [{**new, "boundary_generated": "false"}],
    }[failure]
    with pytest.raises((psycopg.Error, ValueError)):
        load(db, rows)
    assert db.execute(
        "select cell_id from public.population_cells where source=%s", (SOURCE,)
    ).fetchall() == [(previous["cell_id"],)]
    assert db.execute(
        "select count(*) from ingest_private.ingest_runs where source=%s", (SOURCE,)
    ).fetchone() == (1,)


def test_new_resolution_can_coexist_but_unverified_loader_refuses_it(db):
    item = row()
    load(db, [item])
    db.execute(
        "insert into public.population_cells "
        "(resolution_m,cell_id,geom,source,source_version) "
        "select 500,cell_id,geom,source,source_version from public.population_cells "
        "where cell_id=%s", (item["cell_id"],)
    )
    load(db, [item])
    assert db.execute(
        "select count(*) from public.population_cells where cell_id=%s", (item["cell_id"],)
    ).fetchone() == (2,)
    with pytest.raises(ValueError, match="250m"):
        load(db, [item], resolution_m=500)


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_api_roles_can_read_but_not_write_cells(db, role):
    item = row()
    load(db, [item])
    # Role is a fixed test parameter, never supplied by application input.
    db.execute(f"set local role {role}")
    assert db.execute(
        "select cell_id from public.population_cells where cell_id=%s", (item["cell_id"],)
    ).fetchone() == (item["cell_id"],)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("delete from public.population_cells where cell_id=%s", (item["cell_id"],))


def test_conflicting_source_cannot_overwrite_cells(db):
    item = row()
    load(db, [item])
    with pytest.raises(psycopg.errors.UniqueViolation):
        load_population_cells(db, [item], source="another_source", source_version="fixture")
    assert db.execute(
        "select source from public.population_cells where cell_id=%s", (item["cell_id"],)
    ).fetchone() == (SOURCE,)
