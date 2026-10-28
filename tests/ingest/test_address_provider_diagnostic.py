import json
from urllib.error import HTTPError

import pytest

from ingest.address_provider_diagnostic import ADDRESS, diagnose
from tests.ingest.test_juso import item, search_response

ENV = {"JUSO_API_KEY": "secret-search", "JUSO_COORD_API_KEY": "secret-coordinate"}


def search(*_):
    return search_response([item(roadAddrPart1=ADDRESS, rn="강남대로92길", buldMnnm="33")])


def coordinate(*_):
    return {
        "results": {
            "common": {"errorCode": "0", "totalCount": "1"},
            "juso": [{"bdMgtSn": item()["bdMgtSn"], "entX": "960000", "entY": "1940000"}],
        }
    }


def test_juso_success_no_coordinate_or_secret_logging():
    result = diagnose(ENV, search=search, coordinate=coordinate)
    assert result["steps"][-1] == dict(
        stage="juso_coordinate",
        status="ready",
        building_identifier_match=True,
        source_crs="EPSG:5179",
    )
    assert "960000" not in json.dumps(result)
    assert all(secret not in json.dumps(result) for secret in ENV.values())


@pytest.mark.parametrize(
    "change,expected",
    [
        ("missing", "missing"),
        ("mismatch", "transport_or_schema_error"),
        ("business", "business_error"),
        ("http", "http_error"),
    ],
)
def test_juso_failure_stages_are_bounded(change, expected):
    def response(*_):
        if change == "http":
            raise HTTPError(
                "https://example.invalid/?key=secret-coordinate", 403, "secret-coordinate", {}, None
            )
        data = coordinate()
        r = data["results"]
        if change == "missing":
            r["common"]["totalCount"] = "0"
            r["juso"] = []
        elif change == "mismatch":
            r["juso"][0]["bdMgtSn"] = "other"
        else:
            r["common"]["errorCode"] = "secret-coordinate"
        return data

    result = diagnose(ENV, search=search, coordinate=response)
    assert result["steps"][-1]["status"] == expected
    assert all(secret not in json.dumps(result) for secret in ENV.values())


def test_missing_key_and_search_failure_never_call_coordinates():
    def forbidden(*_):
        raise AssertionError("must not call coordinate")

    assert diagnose({}, coordinate=forbidden)["steps"][0]["status"] == "missing_key"
    result = diagnose(
        ENV, search=lambda *_: search_response(code=ENV["JUSO_API_KEY"]), coordinate=forbidden
    )
    assert result["steps"][-1]["code"] == "redacted"
