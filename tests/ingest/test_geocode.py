import pytest

from ingest.geocode import normalize_address, parse_kakao, same_road_address


def response(count=1, **changes):
    item = {"x": "127.05", "y": "37.5", "address_type": "ROAD_ADDR"}
    item.update(changes)
    return {"meta": {"total_count": count}, "documents": [item] if count else []}


def test_address_identity_preserves_building_numbers_and_parentheses():
    assert normalize_address("  서울  삼성로　２１２ (대치동) ") == "서울 삼성로 212 (대치동)"
    assert normalize_address("서울 삼성로 212-1") != normalize_address("서울 삼성로 212")


def test_exact_unique_building():
    assert parse_kakao(response()) == ("success", 127.05, 37.5)


@pytest.mark.parametrize(
    "data,status",
    [
        (response(0), "not_found"),
        (response(2), "ambiguous"),
        (response(address_type="REGION"), "invalid"),
        (response(x="NaN"), "invalid"),
        (response(x="37.5", y="127.05"), "invalid"),
    ],
)
def test_no_invented_coordinate(data, status):
    assert parse_kakao(data) == (status, None, None)


@pytest.mark.parametrize(
    "address,road,number,district,expected",
    [
        ("서울특별시 서초구 신반포로 50", "신반포로33길", "50", "서초구", False),
        ("서울특별시 마포구 월드컵로7길 27", "월드컵로7길", "27-10", "마포구", False),
        ("서울특별시 은평구 연서로 18길14(대조동)1층", "연서로", "18", "은평구", False),
        ("서울특별시 마포구 마포대로19길12", "마포대로12길", "19", "마포구", False),
        ("서울특별시 용산구 신흥로 14 1-3층", "신흥로", "14", "용산구", True),
        ("서울특별시 은평구 연서로 18길14(대조동)", "연서로18길", "14", "은평구", True),
    ],
)
def test_provider_address_corrections_are_not_accepted(address, road, number, district, expected):
    assert same_road_address(address, road, number, district) is expected


def test_literal_number_suffix_does_not_change_the_number():
    assert same_road_address("서울특별시 마포구 와우산로 145번지", "와우산로", "145", "마포구")
    assert not same_road_address(
        "서울특별시 마포구 와우산로 145번지", "와우산로", "145-1", "마포구"
    )


def test_exact_parcel_address_can_use_provider_coordinate_without_road_name_inference():
    data = response(
        address_type="REGION_ADDR",
        address={
            "region_2depth_name": "성동구",
            "region_3depth_name": "성수동1가",
            "main_address_no": "72",
            "sub_address_no": "64",
            "mountain_yn": "N",
        },
    )
    assert parse_kakao(data, "서울특별시 성동구 성수동1가 72-64,") == ("success", 127.05, 37.5)
    assert parse_kakao(data, "서울특별시 성동구 성수동1가 72-65,")[0] == "invalid"
