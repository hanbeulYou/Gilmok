import copy

import pytest

from ingest.building_on_demand import address_parcel, integer, normalize_register, number

ADDRESS = "서울특별시 강남구 역삼로 460"
PNU = "1168010600109120013"


def response():
    return dict(
        meta=dict(total_count=1),
        documents=[
            dict(
                x="127.057585738094",
                y="37.5025724504279",
                address_type="ROAD_ADDR",
                road_address=dict(
                    road_name="역삼로",
                    main_building_no="460",
                    sub_building_no="",
                    region_2depth_name="강남구",
                ),
                address=dict(
                    b_code="1168010600", main_address_no="912", sub_address_no="13", mountain_yn="N"
                ),
            )
        ],
    )


def title():
    return dict(
        sigunguCd="11680",
        bjdongCd="10600",
        platGbCd="0",
        bun="0912",
        ji="0013",
        mainAtchGbCd="0",
        newPlatPlc=ADDRESS,
        mgmBldrgstPk="1024123872",
        mainPurpsCd="04",
        mainPurpsCdNm="제2종근린생활시설",
        etcPurps="근린생활시설",
        grndFlrCnt=4,
        ugrndFlrCnt=1,
        heit=0,
        rideUseElvtCnt=0,
        emgenUseElvtCnt=0,
    )


def test_exact_road_to_parcel_and_register_preserves_observed_zeros():
    parcel = address_parcel(response(), ADDRESS)
    assert parcel["pnu"] == PNU
    floor = dict(
        title(), flrGbCd="20", flrNo=2, mainPurpsCd="04010", mainPurpsCdNm="학원", area=173.68
    )
    result = normalize_register(parcel, [title()], [floor])
    assert result["status"] == "ready"
    b = result["payload"]["building"]
    assert b["floors_above"] == 4 and b["floors_below"] == 1
    assert b["height_m"] is None and b["height_source"] == "unknown"
    assert b["elevators"] == dict(passenger=0, emergency=0)
    assert result["payload"]["floors"][0]["area_m2"] == 173.68


def test_geocoder_correction_and_invalid_parcel_are_rejected():
    r = response()
    r["documents"][0]["road_address"]["main_building_no"] = "462"
    with pytest.raises(ValueError):
        address_parcel(r, ADDRESS)
    r = response()
    r["documents"][0]["address"]["b_code"] = "1111010600"
    with pytest.raises(ValueError):
        address_parcel(r, ADDRESS)


def test_register_requires_unique_main_building_and_matching_parcel():
    parcel = address_parcel(response(), ADDRESS)
    assert normalize_register(parcel, [], [])["status"] == "not_found"
    second = dict(title(), mgmBldrgstPk="1024123873")
    assert normalize_register(parcel, [title(), second], [])["status"] == "ambiguous"
    auxiliary = dict(second, mainAtchGbCd="1")
    assert normalize_register(parcel, [title(), auxiliary], [])["status"] == "ready"
    mismatch = dict(title(), ji="0014")
    with pytest.raises(ValueError):
        normalize_register(parcel, [mismatch], [])
    moved = dict(title(), newPlatPlc="서울특별시 강남구 역삼로 462")
    assert normalize_register(parcel, [moved], [])["status"] == "ambiguous"


@pytest.mark.parametrize("value", [-1, "NaN", "Infinity"])
def test_invalid_numeric_facts_rejected(value):
    with pytest.raises(ValueError):
        number(value)


def test_counts_cannot_be_fractional_and_missing_is_not_zero():
    with pytest.raises(ValueError):
        integer(1.5)
    assert integer("") is None
    assert integer(0) == 0
    assert number(0, positive=True) is None


def test_geocoder_ambiguity_never_chooses_first_document():
    r = response()
    r["meta"]["total_count"] = 2
    r["documents"].append(copy.deepcopy(r["documents"][0]))
    assert address_parcel(r, ADDRESS)["status"] == "ambiguous"


def test_negative_geocoder_response_is_also_published_and_re_read(tmp_path):
    from ingest.building_on_demand import publish_raw
    from ingest.common import RawStore, Settings

    store = RawStore(Settings.from_env({"INGEST_LOCAL_ROOT": str(tmp_path / "raw")}))
    empty = dict(meta=dict(total_count=0), documents=[])
    key = publish_raw(store, tmp_path, ADDRESS, empty, [], [], "20260921T000000Z", None)
    assert (tmp_path / "raw" / key).exists()
    with store.connection() as db:
        rows = db.read_parquet(str(tmp_path / "raw" / key)).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "geocode"
