"""Aggregation contracts use deliberately synthetic normalized transactions."""

import pandas as pd

from ingest.rent_database import aggregate_trades


def row(price, *, kind="general", floor=1, eligible=True, month="202601"):
    return {"legal_dong_code": "11680106", "trade_kind": kind, "floor_number": floor,
            "price_per_m2_won": price, "eligible": eligible, "deal_month": month}


def test_whole_window_median_keeps_identical_transactions_and_excludes_ineligible():
    # Monthly medians 1 and 100 would incorrectly produce 50.5.
    frame = pd.DataFrame([row(1)] * 9 + [row(100, month="202602"),
                                       row(999999, eligible=False)])
    result = aggregate_trades(frame)
    overall = result[result.aggregation_level == "all_floors"].iloc[0]
    assert overall.sample_count == 10
    assert overall.median_price_per_m2 == 1
    assert overall.unknown_floor_count == 0
    assert overall.area_basis == "building_area"


def test_types_and_exact_floors_stay_separate_unknown_only_in_overall():
    result = aggregate_trades(pd.DataFrame([
        row(10, floor=-1), row(30, floor=None), row(200, kind="collective", floor=2),
        row(300, kind="collective", floor=2),
    ]))
    general = result[(result.trade_kind == "general") &
                     (result.aggregation_level == "all_floors")].iloc[0]
    assert general.sample_count == 2
    assert general.unknown_floor_count == 1
    assert general.median_price_per_m2 == 20
    floors = result[result.aggregation_level == "floor"]
    assert set(zip(floors.trade_kind, floors.floor, strict=True)) == {
        ("general", -1), ("collective", 2),
    }
    assert (floors.unknown_floor_count == 0).all()
    collective = floors[floors.trade_kind == "collective"].iloc[0]
    assert collective.median_price_per_m2 == 250
    assert collective.sample_count == 2


def test_no_eligible_transactions_produces_no_aggregates():
    result = aggregate_trades(pd.DataFrame([row(20, eligible=False)]))
    assert result.empty
