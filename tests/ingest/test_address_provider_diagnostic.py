import json
from urllib.error import HTTPError

from ingest.address_provider_diagnostic import ADDRESS, diagnose
from tests.ingest.test_juso import item, search_response, vworld_response

ENV = {"JUSO_API_KEY": "secret-search", "VWORLD_API_KEY": "secret-coordinate"}


def search(*_):
    return search_response([item(roadAddrPart1=ADDRESS, rn="강남대로92길", buldMnnm="33")])


def test_search_business_failure_stops_before_coordinate_and_redacts_keys():
    def forbidden(*_):
        raise AssertionError("coordinate must not run")

    result = diagnose(
        ENV, search=lambda *_: search_response(code=ENV["JUSO_API_KEY"]), coordinate=forbidden
    )
    assert result["steps"] == [
        {"stage": "juso_search", "status": "business_error", "code": "redacted"}
    ]
    assert ENV["JUSO_API_KEY"] not in json.dumps(result)


def test_coordinate_http_error_never_prints_keyed_url_or_response():
    def failed(*_):
        raise HTTPError(
            "https://api.vworld.kr/?key=secret-coordinate", 403, "secret-coordinate", {}, None
        )

    result = diagnose(ENV, search=search, coordinate=failed)
    assert result["steps"][-1] == {
        "stage": "vworld_coordinate",
        "status": "http_error",
        "http_status": 403,
    }
    assert "secret-" not in json.dumps(result)


def test_vworld_business_error_reports_code_without_fallback_retry():
    calls = []

    def failed(*_):
        calls.append(1)
        return {
            "response": {
                "status": "ERROR",
                "error": {"code": "INCORRECT_KEY", "text": "secret-coordinate"},
            }
        }

    result = diagnose(ENV, search=search, coordinate=failed)
    assert calls == [1]
    assert result["steps"][-1]["code"] == "INCORRECT_KEY"
    assert "secret-" not in json.dumps(result)


def test_approved_vworld_coordinate_path_needs_no_juso_coordinate_key():
    response = vworld_response()
    response["response"]["refined"]["structure"].update(level4L="강남대로92길", level5="33")
    result = diagnose(ENV, search=search, coordinate=lambda *_: response)
    assert result["steps"] == [
        {"stage": "juso_search", "status": "ok"},
        {"stage": "vworld_coordinate", "status": "success"},
    ]
