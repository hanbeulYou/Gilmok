"""Gangnam legal-dong polygons; these codes must not join administrative dongs."""

import json
import math
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import duckdb
import pandas as pd
from dotenv import dotenv_values

from ingest.common import ROOT

SOURCE = "vworld_lt_c_ademd_info"
GANGNAM_DONGS = {
    "11680101": "역삼동", "11680103": "개포동", "11680104": "청담동",
    "11680105": "삼성동", "11680106": "대치동", "11680107": "신사동",
    "11680108": "논현동", "11680110": "압구정동", "11680111": "세곡동",
    "11680112": "자곡동", "11680113": "율현동", "11680114": "일원동",
    "11680115": "수서동", "11680118": "도곡동",
}


def _collection(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("type") != "FeatureCollection":
        raise ValueError("Expected legal-dong FeatureCollection")
    crs = data.get("crs", {}).get("properties", {}).get("name")
    if crs != "urn:ogc:def:crs:EPSG::4326":
        raise ValueError("Expected verified EPSG:4326 longitude/latitude coordinates")
    features = data.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("Empty legal-dong response")
    # A WFS response truncated by maxFeatures must never become a snapshot.
    for key in ("totalFeatures", "numberMatched", "numberReturned"):
        value = data.get(key)
        if type(value) is not int or value != len(features):
            raise ValueError(f"Missing or truncated WFS count: {key}")
    return data


def raw_legal_boundaries(path: Path) -> pd.DataFrame:
    """Keep every received feature and collection metadata in raw Parquet columns."""
    data = _collection(path)
    metadata = json.dumps({k: v for k, v in data.items() if k != "features"},
                          ensure_ascii=False)
    return pd.DataFrame([
        {"feature_json": json.dumps(feature, ensure_ascii=False),
         "properties_json": json.dumps(feature.get("properties"), ensure_ascii=False),
         "geometry_json": json.dumps(feature.get("geometry")),
         "collection_metadata_json": metadata}
        for feature in data["features"]
    ])


def prepare_legal_boundaries(path: Path, *, source_version: str | None = None) -> pd.DataFrame:
    """Validate the complete 14-dong set; preserve original attributes, never repair."""
    data = _collection(path)
    version = source_version or data.get("timeStamp")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("Boundary source_version is required")
    rows = []
    for feature in data["features"]:
        if feature.get("type") != "Feature" or not isinstance(feature.get("properties"), dict):
            raise ValueError("Invalid legal-dong feature")
        properties = feature["properties"]
        code = properties.get("emd_cd")
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{8}", code):
            raise ValueError("Expected eight-digit legal-dong emd_cd")
        if not code.startswith("11680"):
            continue
        name = properties.get("emd_kor_nm")
        if code not in GANGNAM_DONGS or name != GANGNAM_DONGS[code]:
            raise ValueError("Unexpected Gangnam legal-dong code/name")
        geometry = feature.get("geometry")
        if (not isinstance(geometry, dict)
                or geometry.get("type") not in {"Polygon", "MultiPolygon"}):
            raise ValueError("Expected legal-dong polygon geometry")
        polygons = geometry.get("coordinates")
        if geometry["type"] == "Polygon":
            polygons = [polygons]
        if not isinstance(polygons, list) or not polygons:
            raise ValueError("Empty legal-dong polygon")
        for polygon in polygons:
            if not isinstance(polygon, list) or not polygon:
                raise ValueError("Empty legal-dong polygon")
            for ring in polygon:
                if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                    raise ValueError("Expected closed legal-dong ring")
                for point in ring:
                    if (not isinstance(point, list) or len(point) != 2
                            or any(type(v) not in (int, float) or not math.isfinite(v)
                                   for v in point)):
                        raise ValueError("Expected finite 2D legal-dong coordinates")
        rows.append({"code8": code, "name": name, "source": SOURCE,
                     "source_version": version,
                     "properties_json": json.dumps(properties, ensure_ascii=False),
                     "geometry_json": json.dumps(geometry),
                     "feature_json": json.dumps(feature, ensure_ascii=False)})
    if len(rows) != 14 or {row["code8"] for row in rows} != set(GANGNAM_DONGS):
        raise ValueError("Expected exactly 14 unique Gangnam legal-dong codes")
    with duckdb.connect() as connection:
        connection.execute("LOAD spatial")
        connection.register("incoming", pd.DataFrame(rows))
        try:
            connection.execute("CREATE TABLE polygons AS SELECT *, "
                               "ST_GeomFromGeoJSON(geometry_json) AS geom FROM incoming")
            invalid = connection.execute("""
                SELECT count(*) FROM polygons WHERE NOT ST_IsValid(geom) OR ST_IsEmpty(geom)
                OR ST_XMin(geom) < 126 OR ST_XMax(geom) > 128
                OR ST_YMin(geom) < 37 OR ST_YMax(geom) > 38
            """).fetchone()[0]
            duplicates = connection.execute("""
                SELECT count(*) FROM polygons a JOIN polygons b ON a.code8 < b.code8
                AND ST_Equals(a.geom, b.geom)
            """).fetchone()[0]
            if invalid or duplicates:
                raise ValueError("Invalid, out-of-range or duplicate legal-dong geometry")
            return connection.execute("""
                SELECT * EXCLUDE (geom), ST_AsText(geom) AS wkt FROM polygons ORDER BY code8
            """).df()
        except duckdb.Error:
            raise ValueError("Invalid legal-dong geometry") from None


def fetch_legal_boundaries(cache_path: Path, *, environ=None) -> Path:
    """Reuse a validated supplied file, or atomically cache one complete WFS response."""
    if cache_path.exists():
        prepare_legal_boundaries(cache_path)
        return cache_path
    env = {**dotenv_values(ROOT / ".env"), **os.environ} if environ is None else environ
    key = env.get("VWORLD_API_KEY")
    if not key:
        raise ValueError("VWORLD_API_KEY is required for legal-dong WFS")
    endpoint = env.get("VWORLD_WFS_URL") or "https://api.vworld.kr/req/wfs"
    if not endpoint.startswith("https://") or "?" in endpoint or "#" in endpoint:
        raise ValueError("VWORLD_WFS_URL must be an HTTPS endpoint without query parameters")
    params = {"service": "WFS", "request": "GetFeature", "version": "1.1.0",
              "typename": "lt_c_ademd_info", "srsname": "EPSG:4326",
              "output": "application/json", "maxFeatures": 1000,
              "bbox": "127.0,37.43,127.2,37.55", "key": key,
              "domain": env.get("VWORLD_SERVICE_URL") or "http://localhost"}
    try:
        request = Request(endpoint + "?" + urlencode(params),
                          headers={"User-Agent": "Gilmok-ingest/1.0"})
        with urlopen(request, timeout=60) as response:
            payload = response.read()
    except Exception:
        raise RuntimeError("Legal-dong WFS request failed (credentials omitted)") from None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=cache_path.parent, suffix=".geojson", delete=False
        ) as f:
            temporary = Path(f.name)
            f.write(payload)
        prepare_legal_boundaries(temporary)
        temporary.replace(cache_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return cache_path
