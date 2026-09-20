from pathlib import Path
from urllib.error import HTTPError
from uuid import uuid4

import pytest

from ingest.database import connect_database
from ingest.geocode import GeocodeStopped, cached, resolve_one


@pytest.fixture
def durable_cache():
    address = "서울특별시 강남구 테스트로 123 (pytest-" + uuid4().hex + ")"
    with connect_database(local_only=True) as connection:
        connection.autocommit = True
        try:
            yield connection, address
        finally:
            connection.execute("delete from public.geocode_cache where address=%s", (address,))
            connection.execute(
                "delete from ingest_private.geocode_requests where address=%s", (address,)
            )


@pytest.mark.parametrize("found", [True, False])
def test_success_and_negative_results_survive_rerun(durable_cache, tmp_path, found):
    connection, address = durable_cache
    calls = []

    def request(*_):
        calls.append(1)
        return {
            "meta": {"total_count": int(found)},
            "documents": [
                {
                    "address_type": "ROAD_ADDR",
                    "x": "127.05",
                    "y": "37.5",
                    "road_address": {
                        "road_name": "테스트로",
                        "main_building_no": "123",
                        "region_2depth_name": "강남구",
                    },
                }
            ]
            if found
            else [],
        }

    kwargs = dict(key="test", budget=100000, journal=tmp_path, requester=request)
    resolve_one(connection, address, **kwargs)
    assert resolve_one(connection, "  " + address + " ", **kwargs) == "cached"
    assert len(calls) == 1
    assert cached(connection, address)[0] is not found


@pytest.mark.parametrize(
    "error,status",
    [
        (TimeoutError(), "unknown"),
        (HTTPError("redacted", 403, "Forbidden", {}, None), "blocked"),
        (HTTPError("redacted", 429, "Quota", {}, None), "blocked"),
    ],
)
def test_operational_failure_stops_without_negative_cache(durable_cache, tmp_path, error, status):
    connection, address = durable_cache
    calls = []

    def request(*_):
        calls.append(1)
        raise error

    for _ in range(2):
        with pytest.raises(GeocodeStopped):
            resolve_one(
                connection, address, key="test", budget=100000, journal=tmp_path, requester=request
            )
    assert len(calls) == 1
    assert cached(connection, address) is None
    assert (
        connection.execute(
            "select status from ingest_private.geocode_requests where address=%s", (address,)
        ).fetchone()[0]
        == status
    )


def test_budget_stops_before_request(durable_cache):
    connection, address = durable_cache
    with pytest.raises(GeocodeStopped, match="budget"):
        resolve_one(
            connection,
            address,
            key="test",
            budget=0,
            journal=Path("unused"),
            requester=lambda *_: pytest.fail("Must not call provider"),
        )
    assert cached(connection, address) is None
