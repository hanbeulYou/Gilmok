import io
import json
from urllib.error import HTTPError

import pytest

from ingest import measure_product_rpc as measure


def fixture_payload():
    return {"demand": {"value": 12}, "meta": {
        "bundle_ms": {"demand": 1.0}, "total_ms": 1.2,
        "sources": {"transit_counts": {"source": "seoul_bus_boardings"}},
    }}


def test_http_uses_user_session_and_preserves_samples_on_failure(monkeypatch, tmp_path):
    case = {"name": "fixture", "lat": 37.5, "lng": 127, "radius_m": 500, "floor": 2}
    monkeypatch.setattr(measure, "cases", lambda: [case])
    calls = []

    def request(request, timeout):
        assert request.get_header("Authorization") == "Bearer session-jwt"
        assert request.get_header("Apikey") == "project-key"
        calls.append(request)
        if len(calls) == 3:
            raise HTTPError(request.full_url, 500, "timeout", {}, None)
        return io.BytesIO(json.dumps(fixture_payload()).encode())

    monkeypatch.setattr(measure, "urlopen", request)
    output = tmp_path / "report.json"
    with pytest.raises(HTTPError):
        measure.http_measure("http://localhost", "project-key", "session-jwt",
                             {"cases": [{"case": case, "result": fixture_payload()}]}, output)
    report = json.loads(output.read_text())
    assert report["status"] == "failed"
    assert report["http_status"] == 500
    assert report["cases"][0]["first"]["bundle_ms"] == {"demand": 1.0}
    assert len(report["cases"][0]["warm"]) == 1
    assert "session-jwt" not in output.read_text()
    assert "project-key" not in output.read_text()


def test_http_rejects_changed_rpc_value(monkeypatch, tmp_path):
    case = {"name": "fixture", "lat": 37.5, "lng": 127, "radius_m": 500, "floor": 2}
    monkeypatch.setattr(measure, "cases", lambda: [case])
    actual = fixture_payload()
    actual["demand"]["value"] = 13
    monkeypatch.setattr(measure, "urlopen", lambda *a, **k:
                        io.BytesIO(json.dumps(actual).encode()))
    with pytest.raises(ValueError, match="differs from frozen baseline"):
        measure.http_measure("http://localhost", "project-key", "session-jwt",
                             {"cases": [{"case": case, "result": fixture_payload()}]},
                             tmp_path / "report.json")
