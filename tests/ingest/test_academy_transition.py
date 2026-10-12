import json

import pytest

from ingest.academy_transition import Journal, local_connection
from ingest.geocode import GeocodeStopped


def item():
    return dict(
        admCd="1168010600",
        rnMgtSn="116803122010",
        udrtYn="0",
        buldMnnm="460",
        buldSlno="0",
        mtYn="0",
        lnbrMnnm="912",
        lnbrSlno="13",
        bdMgtSn="1168010600109120013000000",
        rn="역삼로",
        emdNm="대치동",
        sggNm="강남구",
        roadAddrPart1="서울특별시 강남구 역삼로 460",
    )


def response(items):
    return dict(results=dict(common=dict(errorCode="0", totalCount=str(len(items))), juso=items))


def test_completed_requests_replay_and_same_building_reuses_coordinate(tmp_path):
    calls = []

    def request(url, params):
        calls.append(url)
        return (
            response([item()])
            if "keyword" in params
            else response([dict(bdMgtSn=item()["bdMgtSn"], entX="958000", entY="1944000")])
        )

    journal = Journal(tmp_path / "journal", request, interval=0)

    def project(x, y):
        return 127.05, 37.5

    a = "서울특별시 강남구 역삼로 460"
    b = "서울특별시 강남구 대치동 912-13"
    assert journal.resolve(a, "key", "coord", project)["status"] == "ready"
    assert journal.resolve(a, "key", "coord", project)["status"] == "ready"
    assert journal.resolve(b, "key", "coord", project)["status"] == "ready"
    assert len(calls) == 3  # two distinct searches, one coordinate lookup
    journal.db.close()
    reopened = Journal(tmp_path / "journal", lambda *_: pytest.fail("duplicate call"))
    assert reopened.resolve(a, "key", "coord", project)["status"] == "ready"


def test_error_claim_stops_retry_and_secret_not_logged(tmp_path):
    def failed(*_):
        raise RuntimeError("url?confmKey=SECRET")

    journal = Journal(tmp_path / "journal", failed)
    with pytest.raises(GeocodeStopped, match="inspect local journal") as error:
        journal.call("search", "public address", "url", {"confmKey": "SECRET"})
    assert "SECRET" not in str(error.value)
    with pytest.raises(GeocodeStopped, match="Unresolved journal claim"):
        journal.call("search", "public address", "url", {})
    assert journal.db.execute("select response,error_type from calls").fetchone() == (
        None,
        "RuntimeError",
    )


def test_no_result_is_explicit_and_skips_coordinates(tmp_path):
    journal = Journal(tmp_path / "journal", lambda *_: response([]))
    assert journal.resolve("없는 주소", "key", "coord", lambda *_: None)["status"] == "not_found"
    assert journal.summary()["calls"] == [dict(kind="search", status="complete", count=1)]


def test_unmatched_address_is_not_first_result(tmp_path):
    journal = Journal(tmp_path / "journal", lambda *_: response([item()]))
    assert (
        journal.resolve("서울특별시 강남구 역삼로 462", "key", "coord", None)["status"] == "invalid"
    )
    assert journal.db.execute("select count(*) from calls").fetchone()[0] == 1


def test_echoed_key_is_not_persisted(tmp_path):
    journal = Journal(tmp_path / "journal", lambda *_: {"echo": "SECRET"})
    with pytest.raises(GeocodeStopped):
        journal.call("search", "a", "url", {"confmKey": "SECRET"})
    assert "SECRET" not in json.dumps(journal.summary())
    assert journal.db.execute("select response from calls").fetchone()[0] is None


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:secret@remote.example/db",
        "host=127.0.0.1 hostaddr=10.0.0.1 dbname=test",
    ],
)
def test_remote_or_remote_hostaddr_rejected_before_connect(url):
    with pytest.raises(ValueError, match="explicit local"):
        local_connection(url)


def test_identical_parcel_and_entrance_are_not_ambiguous(tmp_path):
    calls = []

    def request(url, params):
        calls.append(url)
        return (
            response([item(), item()])
            if "currentPage" in params
            else response([dict(bdMgtSn=item()["bdMgtSn"], entX="1000000", entY="2000000")])
        )

    result = Journal(tmp_path / "journal", request, interval=0).resolve(
        "서울특별시 강남구 역삼로 460", "SEARCH", "COORD", lambda *_: (127.05, 37.5)
    )
    assert result["status"] == "ready"
    assert len(calls) == 2


@pytest.mark.parametrize("different_parcel", [False, True])
def test_all_search_pages_checked_before_selecting(tmp_path, different_parcel):
    pages = []
    coords = []

    def request(url, params):
        if "currentPage" not in params:
            coords.append(1)
            return response([dict(bdMgtSn=item()["bdMgtSn"], entX="1000000", entY="2000000")])
        page = params["currentPage"]
        pages.append(page)
        last = item() | (dict(lnbrSlno="14") if different_parcel else {})
        result = response([item()] * 100 if page == 1 else [last])
        result["results"]["common"]["totalCount"] = "101"
        return result

    journal = Journal(tmp_path / "journal", request, interval=0)
    args = ("서울특별시 강남구 역삼로 460", "SEARCH", "COORD", lambda *_: (127.05, 37.5))
    result = journal.resolve(*args)
    assert result["status"] == ("ambiguous" if different_parcel else "ready")
    assert pages == [1, 2]
    assert len(coords) == (0 if different_parcel else 1)
    assert journal.resolve(*args) == result
    assert pages == [1, 2]


def test_changing_pagination_stops_without_inventing_address_failure(tmp_path):
    def request(_, params):
        result = response([item()])
        result["results"]["common"]["totalCount"] = "2" if params["currentPage"] == 1 else "3"
        return result

    journal = Journal(tmp_path / "journal", request)
    with pytest.raises(GeocodeStopped, match="pagination changed"):
        journal.resolve(
            "서울특별시 강남구 역삼로 460", "SEARCH", "COORD", lambda *_: (127.05, 37.5)
        )
    assert journal.db.execute("select count(*) from outcomes").fetchone()[0] == 0


def test_same_coordinate_key_with_distinct_building_identity_stays_ambiguous(tmp_path):
    entries = [item(), item() | dict(bdMgtSn="1168010600109120013000001")]
    journal = Journal(tmp_path / "journal", lambda *_: response(entries))
    result = journal.resolve(
        "서울특별시 강남구 역삼로 460", "SEARCH", "COORD", lambda *_: (127.05, 37.5)
    )
    assert result["status"] == "ambiguous"
    assert (
        journal.db.execute("select count(*) from calls where kind='coordinate'").fetchone()[0] == 0
    )
