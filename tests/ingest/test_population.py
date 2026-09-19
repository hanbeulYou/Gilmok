import csv
import io
from datetime import date
from zipfile import ZipFile

import duckdb
import pandas as pd
import pytest

from ingest.living_population import COLUMNS, aggregate_window, prepare_month, validate_rows
from ingest.population import normalize_residents


def raw_row(day="20260201", hour="15", cell="다사52255350", dong="11110515", **values):
    return {**dict.fromkeys(COLUMNS, "10."), "일자": day, "시간": hour,
            "250M격자": cell, "행정동코드": dong, **values}


def raw_parquet(path, rows):
    with duckdb.connect() as connection:
        connection.register("rows", pd.DataFrame(rows))
        connection.table("rows").write_parquet(str(path))
    return path


def test_monthly_archive_accepts_verified_folder_and_trailing_decimal(tmp_path):
    archive, output = tmp_path / "source.zip", tmp_path / "raw.parquet"
    with ZipFile(archive, "w") as bundle:
        for day in range(1, 29):
            text = io.StringIO()
            writer = csv.DictWriter(text, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(raw_row(day=f"202602{day:02}", hour=f"{h:02}") for h in range(24))
            bundle.writestr(f"250_LOCAL_RESD_202602/250_LOCAL_RESD_202602{day:02}.csv",
                            text.getvalue().encode("cp949"))
    report = prepare_month(archive, "2026-02", output)
    assert report["rows"] == 28 * 24
    assert report["cells"] == 1
    with duckdb.connect() as connection:
        assert connection.read_parquet(str(output)).fetchone()[4] == "10."


def test_bad_archive_preserves_previous_snapshot(tmp_path):
    archive, output = tmp_path / "bad.zip", tmp_path / "raw.parquet"
    output.write_bytes(b"previous snapshot")
    with ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.csv", "invalid")
    with pytest.raises(ValueError, match="exactly one CSV"):
        prepare_month(archive, "2026-02", output)
    assert output.read_bytes() == b"previous snapshot"
    assert not (tmp_path.parent / "outside.csv").exists()


@pytest.mark.parametrize("change", [{"시간": "24"}, {"일자": "20260301"},
                                   {"생활인구합계": "-1"}, {"행정동코드": "26110515"}])
def test_reject_invalid_source_values(change):
    with duckdb.connect() as connection:
        connection.register("raw", pd.DataFrame([raw_row(**change)]))
        with pytest.raises(ValueError, match="Invalid source rows"):
            validate_rows(connection, "2026-02")


def test_reject_true_duplicates_instead_of_dropping_dong_fragments():
    row = raw_row()
    with duckdb.connect() as connection:
        connection.register("raw", pd.DataFrame([row, row]))
        with pytest.raises(ValueError, match="Duplicate date/hour/dong/cell"):
            validate_rows(connection, "2026-02")


def test_daily_weighting_weekends_fragments_and_suppression(tmp_path):
    # Friday, Saturday, Sunday, Monday: weekend must not be mixed with weekdays.
    rows = [raw_row(day=day, **{"생활인구합계": value}) for day, value in
            [("20260731", "10"), ("20260801", "100"), ("20260802", "200"), ("20260803", "30")]]
    rows.append(raw_row(day="20260803", dong="11110530", **{"생활인구합계": "20"}))
    rows[0]["남자 10~14세"] = "*"
    first = raw_parquet(tmp_path / "july.parquet", rows[:1])
    second = raw_parquet(tmp_path / "august.parquet", rows[1:])
    destination = tmp_path / "profile.parquet"
    aggregate_window([first, second], date(2026, 7, 31), date(2026, 8, 3), destination)
    with duckdb.connect() as connection:
        connection.read_parquet(str(destination)).create_view("profile")
        assert connection.execute(
            "select dow_type,avg_pop from profile where age_band='total' order by dow_type"
        ).fetchall() == [("weekday", 30), ("weekend", 150)]
        assert connection.execute(
            "select avg_pop,suppressed_parts from profile "
            "where age_band='10_14' and dow_type='weekday'"
        ).fetchone() == (None, 1)


def test_missing_cell_day_is_null_and_incomplete_window_fails(tmp_path):
    rows = [raw_row(day="20260803"), raw_row(day="20260804", cell="다사52505325")]
    path = raw_parquet(tmp_path / "raw.parquet", rows)
    destination = tmp_path / "profile.parquet"
    aggregate_window([path], date(2026, 8, 3), date(2026, 8, 4), destination)
    with duckdb.connect() as connection:
        values = connection.read_parquet(str(destination)).df()
        assert values.avg_pop.isna().all()
        assert values.observed_days.eq(1).all()
        assert values.expected_days.eq(2).all()
    with pytest.raises(ValueError, match="complete period"):
        aggregate_window([path], date(2026, 8, 3), date(2026, 8, 5), destination)


def test_resident_age_bands_and_seoul_dong_filter(tmp_path):
    values = {f"2026년08월_계_{age}세": "1,000" for age in range(5, 20)}
    rows = [{"행정구역": name, **values} for name in [
        "서울특별시(1100000000)", "서울특별시 강남구(1168000000)",
        "서울특별시 강남구 대치1동(1168060000)", "부산광역시 중구 중앙동(2611051000)"]]
    path = tmp_path / "population.csv"
    pd.DataFrame(rows).to_csv(path, encoding="cp949", index=False)
    output = normalize_residents(path, "2026-08")
    assert output.adm_cd.unique().tolist() == ["11680600"]
    assert output.set_index("age_band").population.to_dict() == {
        "5_9": 5000, "10_14": 5000, "15_18": 4000}
    with pytest.raises(ValueError, match="requested month"):
        normalize_residents(path, "2026-07")


def test_repeated_or_overlapping_inputs_do_not_double_population(tmp_path):
    first = raw_parquet(tmp_path / "a.parquet", [raw_row()])
    second = raw_parquet(tmp_path / "b.parquet", [raw_row()])
    output = tmp_path / "out.parquet"
    output.write_bytes(b"previous")
    for inputs, destination, message in [
        ([first, first], output, "distinct"),
        ([first, second], output, "overlapping"),
        ([first], first, "separate"),
    ]:
        with pytest.raises(ValueError, match=message):
            aggregate_window(inputs, date(2026, 2, 1), date(2026, 2, 1), destination)
    assert output.read_bytes() == b"previous"
    with duckdb.connect() as connection:
        assert connection.read_parquet(str(first)).count("*").fetchone() == (1,)
