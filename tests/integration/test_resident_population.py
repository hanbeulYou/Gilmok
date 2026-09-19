from uuid import uuid4

import psycopg
import pytest

from ingest.population_database import load_resident_snapshot

POLYGON = "POLYGON((127.05 37.49,127.06 37.49,127.06 37.50,127.05 37.50,127.05 37.49))"
SOURCE = "resident_snapshot_test"


def rows():
    code = str(uuid4())
    return ([{"code": code, "name": "fixture", "wkt": POLYGON}],
            [{"adm_cd": code, "age_band": band, "population": value, "ref_month": "2026-08-01"}
             for band, value in [("5_9", 0), ("10_14", None), ("15_18", 50)]])


def load(db, boundaries, residents):
    return load_resident_snapshot(db, boundaries, residents, boundary_source=SOURCE,
                                  boundary_version="fixture", source=SOURCE,
                                  source_version="2026-08")


def test_atomic_snapshot_is_idempotent_and_preserves_null_and_zero(db):
    boundaries, residents = rows()
    assert load(db, boundaries, residents) == load(db, boundaries, residents)
    assert db.execute(
        "select age_band,population,estimated from public.population_age "
        "where source=%s order by age_band", (SOURCE,)
    ).fetchall() == [("10_14", None, False), ("15_18", 50, False), ("5_9", 0, False)]
    assert db.execute("select count(*) from ingest_private.ingest_runs where source=%s",
                      (SOURCE,)).fetchone() == (4,)


@pytest.mark.parametrize("failure", ["missing", "duplicate", "negative", "month", "geometry"])
def test_failed_resident_load_rolls_back_boundaries_population_and_audit(db, failure):
    boundaries, residents = rows()
    load(db, boundaries, residents)
    replacement, changed = rows()
    if failure == "missing":
        changed.pop()
    elif failure == "duplicate":
        changed.append(changed[0])
    elif failure == "negative":
        changed[0]["population"] = -1
    elif failure == "month":
        changed[0]["ref_month"] = "2026-07-01"
    else:
        replacement[0]["wkt"] = "POINT(127 37.5)"
    with pytest.raises((ValueError, psycopg.Error)):
        load(db, replacement, changed)
    assert db.execute("select adm_cd from public.admin_dongs where source=%s", (SOURCE,)
                      ).fetchall() == [(boundaries[0]["code"],)]
    assert db.execute("select count(*) from public.population_age where source=%s", (SOURCE,)
                      ).fetchone() == (3,)
    assert db.execute("select count(*) from ingest_private.ingest_runs where source=%s", (SOURCE,)
                      ).fetchone() == (2,)


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_resident_api_access_is_read_only(db, role):
    load(db, *rows())
    db.execute(f"set local role {role}")
    assert db.execute("select count(*) from public.population_age where source=%s", (SOURCE,)
                      ).fetchone() == (3,)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("delete from public.population_age where source=%s", (SOURCE,))
