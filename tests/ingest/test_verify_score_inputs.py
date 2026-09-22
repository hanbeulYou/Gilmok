import copy

import pytest

from ingest.verify_score_inputs import (
    bind_body,
    cases,
    check_measurements,
    equivalent,
    percentile,
    stable_payload,
)


def test_nearest_rank_uses_29th_sample_and_never_pools_cases():
    assert percentile(list(range(1, 31))) == 29
    rows = [{**case, "db_ms": [10] * 30} for case in cases()]
    check_measurements(rows)
    rows[-1]["db_ms"][-2:] = [1000, 1001]
    with pytest.raises(ValueError):
        check_measurements(rows)


@pytest.mark.parametrize("change", ["floor", "radius", "coordinate", "count", "duplicate"])
def test_acceptance_requires_exact_six_cases_and_thirty_samples(change):
    rows = [{**case, "db_ms": [10] * 30} for case in cases()]
    if change == "floor":
        rows[0]["floor"] = 3
    elif change == "radius":
        rows[0]["radius_m"] = 300
    elif change == "coordinate":
        rows[0]["lat"] += 0.001
    elif change == "count":
        rows[0]["db_ms"].pop()
    else:
        rows[-1] = copy.deepcopy(rows[0])
    with pytest.raises(ValueError):
        check_measurements(rows)


@pytest.mark.parametrize("values", [[], [float("nan")], [float("inf")], [-1]])
def test_invalid_measurements_cannot_pass(values):
    with pytest.raises(ValueError):
        percentile(values)


def test_body_binding_preserves_string_keys_and_qualified_column_names():
    text = "select jsonb_build_object('p', p, 'radius_m',radius_m), r.radius_m, 'it''s p'"
    result = bind_body(text, {"p": "POINT", "radius_m": "500"})
    assert result == "select jsonb_build_object('p', POINT, 'radius_m',500), r.radius_m, 'it''s p'"


def test_http_comparison_ignores_only_timestamps_and_timings():
    r = {
        "rent": {"rent_level": None},
        "meta": {
            "computed_at": "now",
            "bundle_ms": {"rent": 1},
            "sources_ms": 2,
            "total_ms": 4,
            "floor": 2,
        },
    }
    stable = stable_payload(r)
    assert stable["meta"] == {"floor": 2}
    assert r["meta"]["total_ms"] == 4
    assert not equivalent(stable, {"rent": {"rent_level": 0}, "meta": {"floor": 2}})
    assert not equivalent(True, 1)
    assert not equivalent(10_000_000_000, 10_000_000_001)
    assert equivalent({"value": 1.00000000001}, {"value": 1.0})
