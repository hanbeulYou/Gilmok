from decimal import Decimal
from xml.etree.ElementTree import Element, SubElement, tostring

import pandas as pd
import pytest

from ingest.commercial_trades import TradeClient, collect_months, normalize_trades, parse_page


def row(**changes):
    return (
        dict(
            sggCd="11680",
            dealYear="2024",
            dealMonth="9",
            dealDay="24",
            buildingType="일반",
            buildingAr="25",
            dealAmount="1,000",
            floor=" ",
            cdealType=" ",
            cdealDay=" ",
            shareDealingType=" ",
            umdNm="대치동",
            jibun="5**",
        )
        | changes
    )


def xml(rows, total=None, page=1, size=2, code="000"):
    root = Element("response")
    SubElement(SubElement(root, "header"), "resultCode").text = code
    body = SubElement(root, "body")
    for k, v in {
        "totalCount": len(rows) if total is None else total,
        "pageNo": page,
        "numOfRows": size,
    }.items():
        SubElement(body, k).text = str(v)
    items = SubElement(body, "items")
    for record in rows:
        item = SubElement(items, "item")
        for k, v in record.items():
            SubElement(item, k).text = v
    return tostring(root)


def test_units_missing_floor_and_area_basis():
    actual = normalize_trades(
        pd.DataFrame([row(), row(buildingType="집합", floor="-1")]), {"대치동": "11680106"}
    )
    assert actual.iloc[0].deal_amount_won == Decimal("10000000")
    assert actual.iloc[0].price_per_m2_won == Decimal("400000")
    assert pd.isna(actual.iloc[0].floor_number)
    assert actual.iloc[1].floor_number == -1
    assert actual.trade_kind.tolist() == ["general", "collective"]
    assert actual.area_basis.tolist() == ["building_area", "building_area"]
    assert actual.iloc[0].jibun == "5**"
    assert actual.iloc[0].floor == " "


def test_cancel_share_and_invalid_numeric_exclusions():
    actual = normalize_trades(
        pd.DataFrame(
            [
                row(cdealType="O", cdealDay="25.02.28"),
                row(shareDealingType="지분"),
                row(dealAmount="0"),
                row(buildingAr="NaN"),
                row(buildingAr="-4"),
                row(dealAmount="garbage"),
                row(buildingAr="Infinity"),
            ]
        )
    )
    assert actual.eligible.tolist() == [False] * 7
    assert actual.exclusion_reason.tolist() == [
        "cancelled",
        "share",
        "invalid_amount",
        "invalid_area",
        "invalid_area",
        "invalid_amount",
        "invalid_area",
    ]
    assert str(actual.iloc[0].cancel_date) == "2025-02-28"


def test_two_page_resume_preserves_identical_rows(tmp_path):
    calls = []

    def fetch(params):
        calls.append(params["pageNo"])
        return xml([row()] * (2 if params["pageNo"] == 1 else 1), total=3, page=params["pageNo"])

    client = TradeClient(tmp_path, page_size=2, fetch=fetch)
    actual = collect_months("202409", "202409", tmp_path, client=client)
    assert len(actual) == 3
    assert calls == [1, 2]
    assert actual.request_page.tolist() == [1, 1, 2]
    assert actual.request_row.tolist() == [1, 2, 1]
    again = TradeClient(tmp_path, page_size=2, request_limit=0)
    assert len(again.month("202409")) == 3
    assert again.request_count == 0


def test_cached_first_page_resumes_missing_second_page(tmp_path):
    (tmp_path / "trades-202409-p1.xml").write_bytes(xml([row(), row()], total=3))
    calls = []

    def fetch(params):
        calls.append(params["pageNo"])
        return xml([row()], total=3, page=2)

    assert len(TradeClient(tmp_path, page_size=2, fetch=fetch).month("202409")) == 3
    assert calls == [2]


@pytest.mark.parametrize("payload", [xml([], code="99"), b"<broken", xml([], total=-1)])
def test_reject_provider_errors(payload):
    with pytest.raises(ValueError):
        parse_page(payload)


@pytest.mark.parametrize(
    "payload",
    [
        xml([row()], total=2),
        xml([row()], page=2),
        xml([row(sggCd="11110")]),
        xml([row(dealMonth="10")]),
    ],
)
def test_reject_incomplete_or_misdirected_pages(tmp_path, payload):
    client = TradeClient(tmp_path, page_size=2, fetch=lambda _: payload)
    with pytest.raises(ValueError):
        client.month("202409")
    assert not list(tmp_path.glob("*.xml"))


def test_changed_total_rejected(tmp_path):
    def fetch(params):
        return xml([row(), row()], total=3 if params["pageNo"] == 1 else 4, page=params["pageNo"])

    with pytest.raises(ValueError, match="changed"):
        TradeClient(tmp_path, page_size=2, fetch=fetch).month("202409")


def test_unmatched_legal_dong_is_not_administrative_fallback():
    with pytest.raises(ValueError, match="legal dong"):
        normalize_trades(pd.DataFrame([row()]), {"대치1동": "11680600"})


@pytest.mark.parametrize(
    "changes",
    [
        dict(cdealType="X"),
        dict(cdealType="O"),
        dict(cdealDay="25.02.28"),
        dict(buildingType="unknown"),
    ],
)
def test_unknown_semantics_fail_closed(changes):
    with pytest.raises(ValueError):
        normalize_trades(pd.DataFrame([row(**changes)]))
