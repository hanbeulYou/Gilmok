"""Validate the pinned admdongkor GeoJSON against current MOIS dong codes.

Underlying boundaries: Statistics Korea SGIS, KOGL Type 1.
Changes: vuski/admdongkor, CC BY 4.0. See docs/data-attribution.md.
"""

import json
import re
from pathlib import Path

import duckdb
import pandas as pd

BOUNDARY_VERSION = "2026-07-01"
BOUNDARY_COMMIT = "dd1881663fcabc69b81393604e91ebf3a4202e9a"
BOUNDARY_SOURCE = "sgis_admdongkor"
BOUNDARY_URL = (
    f"https://raw.githubusercontent.com/vuski/admdongkor/{BOUNDARY_COMMIT}/"
    "ver20260701/HangJeongDong_ver20260701.geojson"
)


def prepare_admin_boundaries(path: Path, resident_codes: set[str]) -> pd.DataFrame:
    """Return original Seoul properties and validated WGS84 WKT without repairs."""
    data = json.loads(path.read_text())
    if data.get("crs", {}).get("properties", {}).get("name") != "urn:ogc:def:crs:OGC:1.3:CRS84":
        raise ValueError("Expected verified CRS84 longitude/latitude coordinates")
    if data.get("type") != "FeatureCollection":
        raise ValueError("Expected GeoJSON FeatureCollection")
    rows = []
    for feature in data["features"]:
        properties = feature["properties"]
        if properties["sido"] != "11":
            continue
        # adm_cd is an SGIS statistical code, NOT a MOIS code.
        code = properties["adm_cd2"]
        if not re.fullmatch(r"11[0-9]{6}00", code):
            raise ValueError("Invalid MOIS dong code")
        if feature["geometry"]["type"] not in {"Polygon", "MultiPolygon"}:
            raise ValueError("Expected dong polygon")
        rows.append({**properties, "code": code[:8], "name": properties["adm_nm"],
                     "geometry_json": json.dumps(feature["geometry"]),
                     "source": BOUNDARY_SOURCE, "source_version": BOUNDARY_VERSION,
                     "source_commit": BOUNDARY_COMMIT,
                     "attribution": "Statistics Korea SGIS (KOGL-1); vuski/admdongkor (CC-BY-4.0)"})
    if not rows or len({row["code"] for row in rows}) != len(rows):
        raise ValueError("Empty or duplicate administrative boundaries")
    codes = {row["code"] for row in rows}
    if codes != resident_codes:
        raise ValueError(f"Boundary/resident codes differ: missing={sorted(resident_codes-codes)}, "
                         f"extra={sorted(codes-resident_codes)}")
    with duckdb.connect() as connection:
        connection.execute("LOAD spatial")
        connection.register("incoming", pd.DataFrame(rows))
        connection.execute(
            "create table validated as select *,ST_GeomFromGeoJSON(geometry_json) as geom "
            "from incoming"
        )
        invalid = connection.execute(
            "select count(*) from validated where not ST_IsValid(geom) or ST_IsEmpty(geom) "
            "or ST_XMin(geom)<126 or ST_XMax(geom)>128 "
            "or ST_YMin(geom)<37 or ST_YMax(geom)>38"
        ).fetchone()[0]
        if invalid:
            raise ValueError(f"Invalid Seoul boundary geometries: {invalid}; no repair applied")
        return connection.execute(
            "select * exclude(geom),ST_AsText(geom) as wkt from validated order by code"
        ).df()
