from decimal import Decimal

import pandas as pd
import pytest

from ingest.rent_survey import TABLES, RoneClient, normalize_survey, parse_page

RENT = "T244363134858603"
VACANCY = "T249633134845544"


def row(table=RENT, **changes):
    return (
        dict(
            STATBL_ID=table,
            DTACYCLE_CD="QY",
            WRTTIME_IDTFR_ID="202602",
            CLS_ID=520025,
            ITM_ID=100001,
            DTA_VAL="52.4615798696052",
            UI_NM="천원/㎡" if table == RENT else "%",
            CLS_FULLNM="서울>강남>테헤란로",
        )
        | changes
    )


def page(rows, total=None, code="INFO-000"):
    return {
        "SttsApiTblData": [
            {
                "head": [
                    {"list_total_count": len(rows) if total is None else total},
                    {"RESULT": {"CODE": code}},
                ]
            },
            {"row": rows},
        ]
    }


def mapping(level="district"):
    scope = dict(
        area_code="61029510",
        area_name="테헤란로",
        level=level,
        building_class="medium_large",
        evidence="official verified classification",
    )
    return {(table, "520025"): scope for table in (RENT, VACANCY)}


def normalize(rows, scopes=None):
    return normalize_survey(
        pd.DataFrame(rows), mapping() if scopes is None else scopes, source_version="snapshot-test"
    )


def test_units_and_paired_metrics():
    actual = normalize([row(), row(VACANCY, DTA_VAL="9.04932599017198")]).iloc[0]
    assert actual.rent_per_m2 == Decimal("52461.5798696052000")
    assert actual.vacancy_rate == Decimal("9.04932599017198")
    assert actual.quarter == "2026-Q2"
    assert actual.rent_statbl_id == RENT
    assert actual.vacancy_statbl_id == VACANCY
    assert actual.level == "district"


@pytest.mark.parametrize("value", [None, "", "-", "…", "*", "***"])
def test_suppression_preserved_as_null(value):
    actual = normalize([row(DTA_VAL=value)]).iloc[0]
    assert actual.rent_per_m2 is None
    assert actual.vacancy_rate is None
    assert actual.rent_cls_id == "520025"


def test_zero_is_observation():
    assert normalize([row(DTA_VAL=0)]).iloc[0].rent_per_m2 == 0


def test_region_requires_explicit_evidenced_mapping():
    assert normalize([row()], {}).empty
    actual = normalize([row()], mapping("region"))
    assert actual.iloc[0].level == "region"
    scopes = mapping("region")
    scopes[(RENT, "520025")]["evidence"] = ""
    with pytest.raises(ValueError, match="scope"):
        normalize([row()], scopes)


def test_other_class_same_cls_does_not_inherit_scope():
    assert normalize([row(table="TT249843134237374")]).empty


@pytest.mark.parametrize(
    "changes",
    [
        dict(UI_NM="원/㎡"),
        dict(DTACYCLE_CD="YY"),
        dict(WRTTIME_IDTFR_ID="202605"),
        dict(ITM_ID=100002),
        dict(DTA_VAL="unknown"),
        dict(DTA_VAL=-1),
    ],
)
def test_unknown_semantics_fail(changes):
    with pytest.raises(ValueError):
        normalize([row(**changes)])


def test_duplicate_metric_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        normalize([row(), row()])


def test_full_pagination_resume(tmp_path):
    calls = []

    def fetch(parameters):
        calls.append(parameters)
        rows = [row(CLS_ID=1), row(CLS_ID=2)] if parameters["pIndex"] == 1 else [row(CLS_ID=3)]
        return page(rows, 3)

    client = RoneClient(tmp_path, page_size=2, fetch=fetch)
    raw = client.table(RENT, "2026-Q2")
    assert len(raw) == 3
    assert [r["request_page"] for r in raw] == [1, 1, 2]
    assert all("CLS_ID" not in p for p in calls)
    assert all(p["WRTTIME_IDTFR_ID"] == "202602" for p in calls)
    assert RoneClient(tmp_path, page_size=2, request_limit=0).table(RENT, "2026-Q2") == raw


@pytest.mark.parametrize(
    "rows,total", [([row()], 10), ([row(), row()], 2), ([row(WRTTIME_IDTFR_ID="202601")], 1)]
)
def test_sample_duplicates_wrong_quarter_fail(tmp_path, rows, total):
    with pytest.raises(ValueError):
        RoneClient(tmp_path, page_size=2, fetch=lambda _: page(rows, total)).table(RENT, "2026-Q2")
    assert not list(tmp_path.glob("*.json"))


def test_application_error_and_invalid_json():
    for payload in [page([], code="ERROR-300"), b"not json", {"RESULT": {"CODE": "INFO-200"}}]:
        with pytest.raises(ValueError):
            parse_page(payload)


def test_no_key_never_requests_network(tmp_path, monkeypatch):
    import ingest.rent_survey as module

    monkeypatch.setattr(module, "dotenv_values", lambda _: {})
    monkeypatch.delenv("RONE_API_KEY", raising=False)
    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: pytest.fail("network called"))
    with pytest.raises(ValueError, match="RONE_API_KEY"):
        RoneClient(tmp_path).table(RENT, "2026-Q2")


def test_all_four_building_classes_have_rent_and_vacancy():
    assert len(TABLES) == 8
    for building_class in ("office", "medium_large", "small", "collective"):
        assert {metric for kind, metric in TABLES.values() if kind == building_class} == {
            "rent",
            "vacancy",
        }
