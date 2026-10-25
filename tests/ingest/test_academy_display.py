import pytest

from ingest.academy_display import explicit_floor


@pytest.mark.parametrize(
    "text,expected",
    [
        ("3층 301호", "3층"),
        ("지하1층", "지하 1층"),
        ("B1층 101호", "지하 1층"),
        ("2~3층", "2~3층"),
        ("2층, 3층", "2층 · 3층"),
        ("지하1~2층", "지하 1~2층"),
        ("3층(3층)", "3층"),
    ],
)
def test_explicit_only(text, expected):
    assert explicit_floor(text) == (expected, "explicit")


def test_road_number_and_detail_floor_are_separate_fields():
    assert explicit_floor("서울특별시 강남구 역삼로 460", ", 3층") == ("3층", "explicit")


@pytest.mark.parametrize("text", ["301호", "B101호", "서울특별시 강남구 역삼로 460", "지하층", ""])
def test_missing_floor_is_not_inferred(text):
    assert explicit_floor(text) == (None, "missing")


@pytest.mark.parametrize("text", ["3~2층", "지하1층~지상3층", "2층-3층", "2,3층"])
def test_ambiguous_floor_is_not_partially_shown(text):
    assert explicit_floor(text) == (None, "ambiguous")
