import copy
import json

import pytest

from ingest.legal_boundaries import (
    GANGNAM_DONGS,
    fetch_legal_boundaries,
    prepare_legal_boundaries,
    raw_legal_boundaries,
)


def collection():
    features = []
    for index, (code, name) in enumerate(GANGNAM_DONGS.items()):
        x = 127 + index * .001
        features.append({"type": "Feature", "id": f"dong.{code}",
                         "properties": {"emd_cd": code, "emd_kor_nm": name,
                                        "unmodeled_attribute": "keep me"},
                         "geometry": {"type": "Polygon", "coordinates": [[
                             [x, 37.5], [x + .0005, 37.5], [x + .0005, 37.501],
                             [x, 37.501], [x, 37.5],
                         ]]}})
    return {"type": "FeatureCollection", "features": features, "totalFeatures": 14,
            "numberMatched": 14, "numberReturned": 14, "timeStamp": "2026-09-20",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::4326"}}}


def write(tmp_path, data):
    path = tmp_path / "dongs.geojson"
    path.write_text(json.dumps(data))
    return path


def test_exact_legal_codes_and_raw_attributes_are_preserved(tmp_path):
    data = collection()
    other = copy.deepcopy(data["features"][0])
    other["properties"]["emd_cd"] = "41290105"
    other["properties"]["emd_kor_nm"] = "과천동"
    data["features"].append(other)
    for key in ("totalFeatures", "numberMatched", "numberReturned"):
        data[key] = 15
    path = write(tmp_path, data)
    frame = prepare_legal_boundaries(path)
    assert dict(zip(frame.code8, frame.name, strict=True)) == GANGNAM_DONGS
    assert frame.wkt.str.startswith("POLYGON").all()
    raw = raw_legal_boundaries(path)
    assert len(raw) == 15
    assert json.loads(raw.iloc[0].feature_json) == data["features"][0]
    assert json.loads(raw.iloc[0].properties_json)["unmodeled_attribute"] == "keep me"
    assert "features" not in json.loads(raw.iloc[0].collection_metadata_json)
    assert fetch_legal_boundaries(path, environ={}) == path  # No key or network needed.


@pytest.mark.parametrize("mutation", ["crs", "missing_name", "duplicate_code", "missing_dong",
                                       "truncated", "missing_count", "duplicate_geom", "swap_xy",
                                       "empty", "self_intersection"])
def test_bad_boundaries_fail_closed(tmp_path, mutation):
    data = collection()
    if mutation == "crs":
        data["crs"]["properties"]["name"] = "EPSG:5186"
    elif mutation == "missing_name":
        del data["features"][0]["properties"]["emd_kor_nm"]
    elif mutation == "duplicate_code":
        data["features"][1] = copy.deepcopy(data["features"][0])
    elif mutation == "missing_dong":
        data["features"].pop()
        for key in ("totalFeatures", "numberMatched", "numberReturned"):
            data[key] = 13
    elif mutation == "truncated":
        data["numberMatched"] = 15
    elif mutation == "missing_count":
        del data["numberMatched"]
    elif mutation == "duplicate_geom":
        data["features"][1]["geometry"] = copy.deepcopy(data["features"][0]["geometry"])
    elif mutation == "swap_xy":
        coords = data["features"][0]["geometry"]["coordinates"][0]
        data["features"][0]["geometry"]["coordinates"] = [[[y, x] for x, y in coords]]
    elif mutation == "empty":
        data["features"][0]["geometry"]["coordinates"] = []
    elif mutation == "self_intersection":
        data["features"][0]["geometry"]["coordinates"] = [[
            [127, 37.5], [127.1, 37.6], [127.1, 37.5], [127, 37.6], [127, 37.5],
        ]]
    with pytest.raises(ValueError):
        prepare_legal_boundaries(write(tmp_path, data))


def test_archive_failure_does_not_publish(tmp_path, monkeypatch):
    def fail(*_, **__):
        raise ValueError("Archived WFS checksum mismatch")
    monkeypatch.setattr("ingest.archived_wfs.archived_legal_collection", fail)
    with pytest.raises(ValueError, match="checksum"):
        fetch_legal_boundaries(tmp_path / "missing.geojson", environ={})
    assert not (tmp_path / "missing.geojson").exists()


@pytest.mark.parametrize("truncated", [False, True])
def test_replay_publishes_only_complete_validated_original(tmp_path, monkeypatch, truncated):
    data = collection()
    if truncated:
        data["numberMatched"] = 99
    calls = []
    def replay(*_, **__):
        calls.append(1)
        return data
    monkeypatch.setattr("ingest.archived_wfs.archived_legal_collection", replay)
    path = tmp_path / "legal.geojson"
    if truncated:
        with pytest.raises(ValueError, match="truncated"):
            fetch_legal_boundaries(path, environ={})
        assert not path.exists()
    else:
        assert fetch_legal_boundaries(path, environ={}) == path
        assert json.loads(path.read_text()) == data
        assert fetch_legal_boundaries(path, environ={}) == path
    assert calls == [1]
