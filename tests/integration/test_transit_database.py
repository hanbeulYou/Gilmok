import pandas as pd
import psycopg
import pytest

from ingest.common import ROOT
from ingest.transit_database import load_snapshot


def snapshot():
    stops = pd.DataFrame([
        {"stop_id": "subway:test", "type": "subway", "name": "fixture", "line": "test",
         "lng": 127.0, "lat": 37.5},
        {"stop_id": "bus:test", "type": "bus", "name": "fixture", "line": "",
         "lng": 127.0, "lat": 37.5},
    ])
    counts = pd.DataFrame([{"stop_id": "subway:test", "hour": hour,
                            "boarding": 2 if 15 <= hour < 22 else 100,
                            "alighting": 3 if 15 <= hour < 22 else 100, "sample_months": 3}
                           for hour in range(24)])
    return stops, counts


def load(db, stops, counts):
    return load_snapshot(db, stops, counts, {"subway": {}, "bus": {}},
                         start="2026-06-01", end="2026-08-31", coordinate_version="fixture")


def test_repeated_snapshot_and_golden_boundaries(db):
    stops, counts = snapshot()
    assert load(db, stops, counts) == load(db, stops, counts)
    query = (ROOT / "ingest/sql/transit_radius.sql").read_text()
    result = db.execute(query, (127., 37.5, 500)).fetchone()
    assert result == (0., 1, 35., 35., 0)
    counts.loc[counts.hour == 15, "boarding"] = None
    load(db, stops, counts)
    result = db.execute(query, (127., 37.5, 500)).fetchone()
    assert result[2] is None and result[4] == 1


def test_nearest_uses_2km_cap_independent_of_radius_and_bus_counts_physical_stops(db):
    stops, counts = snapshot()
    # Approximately 880m east: outside 500m, inside 1km and nearest-subway 2km.
    stops.loc[stops.type == "subway", "lng"] = 127.01
    load(db, stops, counts)
    query = (ROOT / "ingest/sql/transit_radius.sql").read_text()
    near = db.execute(query, (127., 37.5, 500)).fetchone()
    wider = db.execute(query, (127., 37.5, 1000)).fetchone()
    assert 500 < near[0] < 1000
    assert near[2] == 0 and wider[2] == 35
    assert near[1] == wider[1] == 1
    assert db.execute(query, (127.1, 37.5, 1000)).fetchone()[0] is None


@pytest.mark.parametrize("failure", ["negative", "geometry", "missing-hour", "orphan"])
def test_failure_preserves_previous_snapshot_and_audit(db, failure):
    stops, counts = snapshot()
    load(db, stops, counts)
    before = db.execute("select count(*) from ingest_private.ingest_runs").fetchone()
    if failure == "negative":
        counts.loc[0, "boarding"] = -1
    elif failure == "geometry":
        stops.loc[0, "lng"] = 1000000
    elif failure == "missing-hour":
        counts = counts.iloc[1:]
    else:
        counts.loc[0, "stop_id"] = "missing"
    with pytest.raises((ValueError, psycopg.Error)):
        load(db, stops, counts)
    assert db.execute("select count(*) from transit_boardings").fetchone() == (24,)
    assert db.execute("select boarding from transit_boardings where hour=0").fetchone() == (100.,)
    assert db.execute("select count(*) from ingest_private.ingest_runs").fetchone() == before


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_public_transit_read_only_private_coverage_not_exposed(db, role):
    load(db, *snapshot())
    db.execute(f"set local role {role}")
    assert db.execute("select count(*) from transit_stops").fetchone() == (2,)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("delete from transit_stops")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("select * from ingest_private.transit_coverage")
