import pandas as pd
import pytest

from ingest import bus, subway
from ingest import seoul_transit as api
from ingest.seoul_transit import check_stops, hourly_values
from ingest.verify_transit import CoverageAlert, aggregate_months, coverage, require_coverage


def hourly(value=1):
    return {f"HR_{hour}_GET_{direction}_NOPE": value
            for hour in range(24) for direction in ("ON", "OFF")}


def subway_master():
    return subway.stops(pd.DataFrame([
        {"BLDN_ID": "0001", "BLDN_NM": "환승역(부기)", "ROUTE": "2호선",
         "LAT": "37.5", "LOT": "127"},
        {"BLDN_ID": "0002", "BLDN_NM": "환승역", "ROUTE": "3호선",
         "LAT": "37.5001", "LOT": "127"},
    ]))


def bus_master():
    return bus.stops(pd.DataFrame([
        {"STOPS_NO": "100000001", "STOPS_NM": "동명정류장", "XCRD": "127",
         "YCRD": "37.5", "NODE_ID": "01001", "STOPS_TYPE": "일반"},
        {"STOPS_NO": "100000002", "STOPS_NM": "동명정류장", "XCRD": "127.001",
         "YCRD": "37.5", "NODE_ID": "01002", "STOPS_TYPE": "일반"},
    ]))


def bus_row(**overrides):
    return {"USE_YM": "202606", "TRFC_MNS_TYPE_CD": "010", "RTE_NO": "100",
            "RTE_NM": "100번", "STOPS_ID": "100000001", "STOPS_ARS_NO": "01001",
            "SBWY_STNS_NM": "구이름(00001)", **hourly(), **overrides}


def test_subway_transfer_lines_remain_distinct_exact_copies_removed():
    first = {"USE_MM": "202606", "SBWY_ROUT_LN_NM": "2호선", "STTN": "환승역",
             **hourly(30)}
    second = {**first, "SBWY_ROUT_LN_NM": "3호선"}
    result = subway.normalize(pd.DataFrame([first, first, second]), subway_master(), "2026-06")
    assert result.stop_id.tolist() == ["subway:0001", "subway:0002"]
    assert result.boarding_15.sum() == 60
    with pytest.raises(ValueError, match="Duplicate subway"):
        subway.normalize(pd.DataFrame([first, {**first, "HR_15_GET_ON_NOPE": 99}]),
                         subway_master(), "2026-06")


def test_ambiguous_normalized_station_names_fail():
    raw = pd.DataFrame([{"BLDN_ID": str(i), "BLDN_NM": name, "ROUTE": "2호선",
                         "LAT": "37.5", "LOT": "127"}
                        for i, name in enumerate(["역(가)", "역(나)"])])
    with pytest.raises(ValueError, match="Ambiguous"):
        subway.stops(raw)


def test_bus_renames_routes_and_repeated_visits_are_additive_opposite_stop_distinct():
    raw = pd.DataFrame([
        bus_row(), bus_row(SBWY_STNS_NM="새이름(00001)"),
        bus_row(SBWY_STNS_NM="새이름(00060)"), bus_row(RTE_NO="200"),
        bus_row(STOPS_ID="100000002", STOPS_ARS_NO="01002"),
    ])
    result = bus.normalize(raw, bus_master(), "2026-06")
    assert result.groupby("stop_id").boarding_15.sum().to_dict() == {
        "bus:100000001": 4, "bus:100000002": 1}
    # Opposite stop is not merged by name, and neither ID is coerced to an integer.
    assert bus_master().NODE_ID.tolist() == ["01001", "01002"]


def test_bus_conflicting_duplicate_fails_and_unlocated_is_not_fuzzy_matched():
    with pytest.raises(ValueError, match="Duplicate bus"):
        bus.normalize(pd.DataFrame([bus_row(), bus_row(HR_15_GET_ON_NOPE=2)]),
                      bus_master(), "2026-06")
    result = bus.normalize(pd.DataFrame([bus_row(STOPS_ID="999999999")]),
                           bus_master(), "2026-06")
    assert result.stop_id.isna().all()


def test_three_month_mean_weights_calendar_days_and_propagates_missing():
    rows = []
    for month, days, daily in [("2026-06", 30, 1), ("2026-07", 31, 2), ("2026-08", 31, 3)]:
        row = {"stop_id": "bus:1", "month": month,
               **{f"{direction}_{hour}": days * daily for direction in ("boarding", "alighting")
                  for hour in range(24)}}
        row["boarding_0"] = 0
        if month == "2026-07":
            row["boarding_1"] = None
        rows.append(pd.DataFrame([row]))
    result = aggregate_months(rows)
    assert result.loc[result.hour == 15, "boarding"].item() == pytest.approx(185 / 92)
    assert result.loc[result.hour == 0, "boarding"].item() == 0
    assert pd.isna(result.loc[result.hour == 1, "boarding"].item())
    assert result.loc[result.hour == 1, "alighting"].item() == pytest.approx(185 / 92)
    # Missing one constituent route/hour must not produce a partial stop sum.
    extra = rows[1].copy()
    extra["boarding_2"] = None
    result = aggregate_months([rows[0], pd.concat([rows[1], extra]), rows[2]])
    assert pd.isna(result.loc[result.hour == 2, "boarding"].item())
    rows[2]["stop_id"] = "bus:2"
    result = aggregate_months(rows)
    assert result.boarding.isna().all()


def test_coverage_uses_passengers_not_rows_and_stops_before_below_90():
    raw = pd.DataFrame([bus_row(), bus_row(STOPS_ID="missing", **hourly(100))])
    normalized = bus.normalize(raw, bus_master(), "2026-06")
    report = coverage(raw, normalized, set(bus_master().stop_id))
    assert report["row_join_rate"] == .5
    assert report["passenger_join_rate"] == pytest.approx(1 / 101)
    assert report["unmatched"][0]["source_id"] == "missing"
    with pytest.raises(CoverageAlert):
        require_coverage(report)
    require_coverage({"passenger_join_rate": .9})
    with pytest.raises(CoverageAlert):
        require_coverage({"passenger_join_rate": None})


@pytest.mark.parametrize("value", [-1, float("inf"), 1.5])
def test_invalid_counts_rejected(value):
    with pytest.raises(ValueError, match="Invalid passenger"):
        hourly_values(pd.DataFrame([hourly(value)]))


def test_wrong_month_missing_hours_and_projected_coordinates_rejected():
    with pytest.raises(ValueError, match="wrong-month"):
        bus.normalize(pd.DataFrame([bus_row()]), bus_master(), "2026-07")
    raw = pd.DataFrame([hourly()]).drop(columns="HR_23_GET_ON_NOPE")
    with pytest.raises(ValueError, match="24"):
        hourly_values(raw)
    master = bus_master()
    master["lng"] = 950000
    with pytest.raises(ValueError, match="4326"):
        check_stops(master)


def test_download_rejects_changing_page_totals_without_publishing_cache(monkeypatch, tmp_path):
    def response(service, start, end, argument):
        return {service: {"RESULT": {"CODE": "INFO-000"},
                          "list_total_count": 1001 if start == 1 else 1002,
                          "row": [{"id": n} for n in range(start, min(end, 1001) + 1)]}}
    monkeypatch.setattr(api, "fetch_json", response)
    with pytest.raises(ValueError, match="changed"):
        api.download("fixture", "202606", tmp_path)
    assert not list(tmp_path.iterdir())


def test_failed_http_request_does_not_expose_key_or_url(monkeypatch):
    monkeypatch.setattr(api, "dotenv_values", lambda _: {})
    monkeypatch.setenv("SEOUL_OPEN_DATA_API_KEY", "fixture-secret")
    monkeypatch.setattr(api.time, "sleep", lambda _: None)

    def fail(url, **kwargs):
        raise RuntimeError(url)

    monkeypatch.setattr(api, "urlopen", fail)
    with pytest.raises(RuntimeError) as error:
        api.fetch_json("fixture", 1, 1, "202606")
    assert "fixture-secret" not in str(error.value)
    assert error.value.__suppress_context__
