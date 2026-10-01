import math

import pytest
from psycopg.errors import InsufficientPrivilege, InvalidParameterValue
from psycopg.types.json import Jsonb

PRESET = "s3_registration_fixture"


@pytest.fixture
def populated_reference(db):
    db.execute(
        """insert into public.score_reference_sets
        (preset_id,preset_version,snapshot,computed_at,inputs_schema_version,
         cell_count,source_fingerprint,source_versions,statistics)
        values (%s,'0.1.2','20260930T000000Z',now(),'1.3',5,'fixture',
          '{"sources":{}}','{}')""",
        (PRESET,),
    )
    for key in ["demand", "flow", "transit.nearest_subway_m"]:
        for i, value in enumerate([10.0, 20.0, 20.0, 30.0, None]):
            db.execute(
                """insert into public.score_reference values
                (%s,'0.1.2','20260930T000000Z',800,%s,%s,%s,now(),'1.3')""",
                (PRESET, str(i), key, value),
            )
    db.execute("set local role authenticated")
    return db


def compact(db, raw, radius=800, preset=PRESET):
    return db.execute(
        "select public.score_reference_percentiles(%s,%s,%s)",
        (preset, radius, Jsonb(raw)),
    ).fetchone()[0]


@pytest.mark.parametrize(
    "value,expected", [(0, 0), (10, 25), (20, 62.5), (25, 75), (30, 100), (40, 100), (None, None)]
)
def test_compact_exact_rank_histogram_and_legacy_preservation(populated_reference, value, expected):
    db = populated_reference
    before = db.execute("select public.score_reference_distribution(%s,800)", (PRESET,)).fetchone()[
        0
    ]
    result = compact(db, {"demand": value, "flow": value})
    assert result["kind"] == "percentiles"
    assert "distributions" not in result
    for key in ["preset", "sources", "snapshot", "inputs_schema_version", "source_fingerprint"]:
        assert result[key] == before[key]
    for row in result["percentiles"]:
        assert row["raw"] == value
        assert row["percentile"] == expected
        assert (row["cell_count"], row["population_size"]) == (5, 4)
        assert row["histogram"]["min"] == 10
        assert row["histogram"]["max"] == 30
        assert len(row["histogram"]["bins"]) == 20
        assert sum(row["histogram"]["bins"]) == 4
    assert (
        db.execute("select public.score_reference_distribution(%s,800)", (PRESET,)).fetchone()[0]
        == before
    )


def test_empty_null_missing_snapshot_and_wrong_radius(populated_reference):
    db = populated_reference
    assert compact(db, {"demand": 5}, 1000)["percentiles"] == []
    assert compact(db, {"demand": 5}, preset="missing-s3-reference") is None


@pytest.mark.parametrize(
    "raw,radius",
    [
        ({}, 800),
        ({"unknown": 1}, 800),
        ({"demand": -1}, 800),
        ({"demand": "2"}, 800),
        ({"demand": True}, 800),
        ([1], 800),
        ({"demand": 1}, 500),
        ({"demand": 1}, None),
    ],
)
def test_reject_invalid_requests(populated_reference, raw, radius):
    with pytest.raises(InvalidParameterValue), populated_reference.transaction():
        compact(populated_reference, raw, radius)


def test_authenticated_only(db):
    db.execute("set local role anon")
    with pytest.raises(InsufficientPrivilege), db.transaction():
        compact(db, {"demand": 1})


def test_float8_ties_not_json_decimal_rounding(db):
    # Reuse an isolated test set and insert a value differing at the last float8 digits.
    value = math.log1p(2)
    db.execute(
        """insert into public.score_reference_sets values
        (%s,'0.1.2','20260930T000000Z',now(),'1.3',3,'fixture','{"sources":{}}','{}')""",
        (PRESET,),
    )
    db.execute(
        """insert into public.score_reference
        select %s,'0.1.2','20260930T000000Z',800,i::text,'demand',%s,now(),'1.3'
        from generate_series(1,3) i""",
        (PRESET, value),
    )
    exact = compact(db, {"demand": value})["percentiles"][0]
    rounded = compact(db, {"demand": float(format(value, ".15g"))})["percentiles"][0]
    assert exact["raw"] == value
    assert exact["percentile"] == 100 * 2 / 3
    assert exact["percentile"] != rounded["percentile"]
    assert exact["histogram"]["bins"] == [3] + [0] * 19


def test_all_null_population_is_distinct_from_absent_key(populated_reference):
    db = populated_reference
    db.execute("reset role")
    db.execute("update public.score_reference set raw_value=null where preset_id=%s", (PRESET,))
    db.execute("set local role authenticated")
    row = compact(db, {"demand": 5})["percentiles"][0]
    assert row["percentile"] is None and row["population_size"] == 0
    assert row["histogram"] == {"min": None, "max": None, "bins": []}
