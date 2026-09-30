from copy import deepcopy

import pytest

from ingest.geocode import GeocodeStopped
from ingest.juso import (
    JusoCoordinates,
    VworldCoordinates,
    matches_address,
    parse_geocode,
    parse_search,
    resolve_address,
    selection,
)

ADDRESS = "서울특별시 강남구 테스트로 460"


def item(**changes):
    # Synthetic identifiers, not a recorded live API response.
    return dict(admCd="1168010600", rnMgtSn="116803122001", udrtYn="0", buldMnnm="460",
                buldSlno="0", mtYn="0", lnbrMnnm="912", lnbrSlno="13",
                bdMgtSn="1168010600109120013" + "000001", roadAddrPart1=ADDRESS,
                jibunAddr="서울특별시 강남구 대치동 912-13", bdNm="합성 fixture",
                rn="테스트로", sggNm="강남구", emdNm="대치동") | changes


def search_response(items=None, *, code="0", count=None):
    items = [item()] if items is None else items
    return dict(results=dict(common=dict(errorCode=code,
                                         totalCount=str(len(items) if count is None else count)),
                             juso=items))


def vworld_response(**changes):
    return {"response": {"status": "OK", "result": {"crs": "EPSG:4326",
                        "point": {"x": "127.05", "y": "37.5"}},
                        "refined": {"structure": {"level4L": "테스트로", "level5": "460",
                                                  "level2": "강남구"}}, **changes}}


def resolve(data=None):
    return resolve_address(ADDRESS, "fake", VworldCoordinates("fake", lambda *_: vworld_response()),
                           search=lambda *_: search_response() if data is None else data)


def test_pnu_land_not_road_number_and_mountain_zero_subnumber():
    assert selection(item())["pnu"] == "1168010600109120013"
    assert selection(item(mtYn="1", lnbrSlno="0", udrtYn="1"))["pnu"] == "1168010600209120000"
    assert not matches_address(selection(item(buldMnnm="462")), ADDRESS)


@pytest.mark.parametrize("change", [dict(admCd="11680"), dict(mtYn="2"), dict(lnbrMnnm="0"),
                                    dict(lnbrSlno="10000"), dict(bdMgtSn="short"),
                                    dict(rnMgtSn="x"), dict(buldMnnm="NaN")])
def test_invalid_identity_rejected(change):
    with pytest.raises(ValueError):
        selection(item(**change))


def test_search_errors_do_not_become_negative_cache():
    with pytest.raises(GeocodeStopped):
        parse_search(search_response(code="E0001"))
    assert resolve(search_response([]))["status"] == "not_found"
    assert resolve(search_response([item(), item()]))["status"] == "ambiguous"
    assert resolve(search_response(count=101))["status"] == "ambiguous"


def test_batch_never_chooses_unrelated_unique_address():
    assert resolve(search_response([item(rn="다른로")]))["status"] == "invalid"


def test_provider_provenance_and_worker_parcel():
    from ingest.building_on_demand import address_parcel

    result = resolve()
    assert parse_geocode(result, ADDRESS) == ("success", 127.05, 37.5)
    assert result["search_provider"] == "juso"
    assert result["location"]["coordinate_provider"] == "vworld"
    assert result["location"]["source_crs"] == "EPSG:4326"
    assert result["call_counts"] == {"juso_search": 1, "juso_coordinate": 0,
                                     "vworld_coordinate": 1}
    assert address_parcel(result, ADDRESS)["pnu"] == "1168010600109120013"
    altered = deepcopy(result)
    altered["selection"]["pnu"] = "1168010600100010000"
    assert parse_geocode(altered, ADDRESS) == ("invalid", None, None)


def test_vworld_wrong_road_and_failure_no_automatic_retry():
    provider = VworldCoordinates("fake", lambda *_: vworld_response(
        refined={"structure": {"level4L": "테스트로", "level5": "462", "level2": "강남구"}}))
    outcome, _ = provider.locate(selection(item()))
    assert outcome["status"] == "invalid"
    calls = []

    def fail(*_):
        calls.append(1)
        raise RuntimeError("secret-containing keyed URL")

    with pytest.raises(GeocodeStopped) as error:
        VworldCoordinates("fake", fail).locate(selection(item()))
    assert "secret-containing" not in str(error.value)
    assert len(calls) == 1


def test_juso_coordinate_swap_preserves_source_crs_and_checks_building():
    raw = search_response([dict(bdMgtSn=item()["bdMgtSn"], entX="958000", entY="1944000")])
    calls = []

    def project(x, y):
        calls.append((x, y))
        return 127.05, 37.5

    provider = JusoCoordinates("fake", project, lambda *_: raw)
    result, _ = provider.locate(selection(item()))
    assert calls == [(958000, 1944000)]
    assert result["source_crs"] == "EPSG:5179"
    assert result["coordinate_provider"] == "juso"
    raw["results"]["juso"][0]["bdMgtSn"] = "wrong"
    with pytest.raises(ValueError, match="building mismatch"):
        provider.locate(selection(item()))
