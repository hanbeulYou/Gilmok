from datetime import date
from uuid import uuid4

import psycopg
import pytest

from ingest.living_population import POPULATION_COLUMNS
from ingest.population_database import load_living_population, load_population_cells

SOURCE = "fixed_living_test"
POLYGON = "POLYGON((127.05 37.49,127.06 37.49,127.06 37.50,127.05 37.50,127.05 37.49))"


@pytest.fixture
def profile(db):
    cell = str(uuid4())
    load_population_cells(db, [{"cell_id": cell, "wkt": POLYGON, "boundary_generated": False}],
                          source=SOURCE, source_version="fixture")
    return {"cell_id": cell, "dow_type": "weekday", "hour": 15,
            **dict.fromkeys(POPULATION_COLUMNS, 123.45), "age_0_4": None, "age_5_9": None,
            "sample_days": 2, "period_start": date(2026, 8, 3), "period_end": date(2026, 8, 4)}


def load(db, rows):
    return load_living_population(db, rows, source=SOURCE, source_version="fixture")


def test_fixed_profile_roundtrip_idempotence_and_geometry_reload(db, profile):
    assert load(db, [profile]) == load(db, [profile]) == 1
    assert db.execute(
        "select total,age_0_4,age_5_9,age_15_19,sample_days,estimated "
        "from public.living_pop where source=%s", (SOURCE,)
    ).fetchone() == (123.45, None, None, 123.45, 2, False)
    # Existing boundary writer can replace the same cells despite the new FK.
    load_population_cells(
        db, [{"cell_id": profile["cell_id"], "wkt": POLYGON, "boundary_generated": False}],
        source=SOURCE, source_version="new",
    )
    db.execute("set constraints public.living_pop_cell_fkey immediate")
    assert db.execute("select count(*) from public.living_pop where source=%s",
                      (SOURCE,)).fetchone() == (1,)


@pytest.mark.parametrize("failure", ["empty", "duplicate", "unknown_cell", "negative", "nan",
                                     "infinite", "bad_hour", "bad_day_type", "sample_days",
                                     "mixed_period"])
def test_invalid_snapshot_preserves_previous_data_and_audit(db, profile, failure):
    load(db, [profile])
    alternatives = {
        "empty": [], "duplicate": [profile, profile],
        "unknown_cell": [{**profile, "cell_id": str(uuid4())}],
        "negative": [{**profile, "age_15_19": -1}],
        "nan": [{**profile, "total": float("nan")}],
        "infinite": [{**profile, "total": float("inf")}],
        "bad_hour": [{**profile, "hour": 24}],
        "bad_day_type": [{**profile, "dow_type": "all"}],
        "sample_days": [{**profile, "dow_type": "weekend", "sample_days": 1}],
        "mixed_period": [profile, {**profile, "hour": 16, "period_end": date(2026, 8, 5)}],
    }
    with pytest.raises((ValueError, psycopg.Error)):
        load(db, alternatives[failure])
    assert db.execute("select total from public.living_pop where source=%s",
                      (SOURCE,)).fetchall() == [(123.45,)]
    assert db.execute("select count(*) from ingest_private.ingest_runs "
                      "where source=%s and target_table='living_pop'", (SOURCE,)).fetchone() == (1,)


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_fixed_profile_is_publicly_readable_but_not_writable(db, profile, role):
    load(db, [profile])
    db.execute(f"set local role {role}")
    assert db.execute("select total from public.living_pop where source=%s",
                      (SOURCE,)).fetchone() == (123.45,)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("update public.living_pop set total=0 where source=%s", (SOURCE,))
