"""Manual SHP ZIP originals and cached WFS supplements; no archive extraction."""

import hashlib
import json
import os
import re
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import duckdb
import pandas as pd
from dotenv import dotenv_values

from ingest.building_register import atomic_json, current_pk
from ingest.common import ROOT

SHP_SOURCE = "gis_buildings_shp"
WFS_SOURCE = "vworld_wfs_supplement"
# Observed official main-use families: first/second neighborhood facility and retail.
COMMERCIAL_USE_PREFIXES = {"03", "04", "07"}


def positive_number(value):
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    number = float(value)
    if not 0 <= number < float("inf"):
        raise ValueError("Negative or non-finite building attribute")
    return number if number > 0 else None


def height_contract(height, floors, use_code):
    height = positive_number(height)
    floors = positive_number(floors)
    if floors is not None and floors != int(floors):
        raise ValueError("Above-ground floor count is not integral")
    if height is not None:
        return height, "source", False
    if floors is None:
        return None, "unknown", False
    commercial = str(use_code or "")[:2] in COMMERCIAL_USE_PREFIXES
    return (4.0 if floors == 1 and commercial else floors * 3.3), "floors_estimate", True


def read_shp_zip(archive: Path, directory: Path):
    """Preserve all Seoul source rows/fields and original WKB in Parquet; select Gangnam."""
    directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        members = zipped.namelist()
        shapes = [n for n in members if n.lower().endswith(".shp")]
        if len(shapes) != 1:
            raise ValueError("Expected exactly one shapefile in the source ZIP")
        stem = shapes[0][:-4]
        prj = zipped.read(stem + ".prj").decode("utf-8")
        if 'AUTHORITY["EPSG","5186"]' not in prj:
            raise ValueError("Unverified SHP CRS; expected EPSG:5186 in PRJ")
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest_path = directory / "shp-manifest.json"
    raw_path = directory / "shp-original.parquet"
    with duckdb.connect(config={"memory_limit": "2GB", "threads": 2}) as connection:
        connection.execute("INSTALL spatial")
        connection.execute("LOAD spatial")
        if raw_path.exists() and manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            if manifest["zip_sha256"] != digest:
                raise ValueError("Source ZIP differs; use a new snapshot directory")
        else:
            uri = f"/vsizip/{archive.resolve()}/{shapes[0]}"
            columns = connection.execute("describe select * from ST_Read(?)", [uri]).fetchall()
            fields = {r[0] for r in columns}
            if not {f"A{i}" for i in range(29)} <= fields:
                raise ValueError("SHP schema differs from the verified column definition")
            connection.create_function(
                "decode_cp949", lambda s: s.encode("latin1").decode("cp949"), return_type="VARCHAR"
            )
            expressions = []
            for name, datatype, *_ in columns:
                if name == "geom":
                    expressions.append('ST_AsWKB(geom) as "source_geometry_wkb"')
                elif datatype == "VARCHAR":
                    expressions.append(f'decode_cp949("{name}") as "{name}"')
                else:
                    expressions.append(f'"{name}"')
            temporary = raw_path.with_suffix(".tmp.parquet")
            connection.execute(
                "copy (select "
                + ",".join(expressions)
                + " from ST_Read($shp_uri,open_options=['ENCODING=ISO-8859-1'])) "
                "to $target (format parquet,compression zstd)",
                {"shp_uri": uri, "target": str(temporary)},
            )
            temporary.replace(raw_path)
            manifest = {
                "zip_name": archive.name,
                "zip_sha256": digest,
                "zip_bytes": archive.stat().st_size,
                "prj": prj,
                "encoding": "CP949 strict",
                "source_srid": 5186,
                "source_columns": [r[0] for r in columns if r[0] != "geom"],
                "original_rows": connection.execute(
                    "select count(*) from read_parquet(?)", [str(raw_path)]
                ).fetchone()[0],
            }
            atomic_json(manifest_path, manifest)
        result = connection.execute(
            "select * from read_parquet(?) where A23='11680'", [str(raw_path)]
        ).df()
    if result.empty:
        raise ValueError("The ZIP has no Gangnam buildings")
    result["source_geometry_wkb"] = result.source_geometry_wkb.map(bytes)
    if not result.A2.str.fullmatch(r"11680[0-9]{5}[12][0-9]{8}").all():
        raise ValueError("SHP contains an unverified Gangnam PNU")
    if not result.A3.str.startswith("11680").all():
        raise ValueError("SHP legal-dong jurisdiction differs")
    return result, raw_path, manifest


def normalize_shp(frame):
    original = len(frame)
    # A0 and OGC_FID are shape row identifiers, not building business attributes.
    business = [c for c in frame.columns if c not in {"A0", "OGC_FID"}]
    unique = frame.sort_values("A0").drop_duplicates(subset=business)
    if unique.A1.duplicated().any():
        raise ValueError("Same SHP GIS ID has conflicting attributes; do not merge")
    result = []
    for row in unique.to_dict("records"):
        height, kind, estimated = height_contract(row["A16"], row["A26"], row["A8"])
        result.append(
            {
                "id": "shp:" + str(row["A1"]),
                "source_id": str(row["A0"]),
                "gis_id": row["A1"],
                "pnu": row["A2"],
                "source": SHP_SOURCE,
                "source_version": str(row["A22"])[:10],
                "source_register_pk": row["A19"],
                "candidate_register_pk": current_pk(row["A19"]),
                "source_height_m": positive_number(row["A16"]),
                "floors_above": positive_number(row["A26"]),
                "floors_below": row["A27"],
                "main_use_code": row["A8"],
                "main_use_name": row["A9"],
                "height_m": height,
                "height_source": kind,
                "height_estimated": estimated,
                "source_geometry_wkb": row["source_geometry_wkb"],
                "source_srid": 5186,
            }
        )
    return pd.DataFrame(result), {
        "raw_rows": original,
        "normalized_rows": len(result),
        "complete_duplicates_removed": original - len(result),
    }


class WfsClient:
    def __init__(self, directory, snapshot, *, fetch=None):
        self.directory = Path(directory) / snapshot
        self.fetch = fetch or self._fetch
        self.requests = 0

    def _fetch(self, bbox):
        env = {**dotenv_values(ROOT / ".env"), **os.environ}
        key = env.get("VWORLD_API_KEY") or ""
        if not key:
            raise ValueError("VWORLD_API_KEY is required for missing-shape supplements")
        parameters = {
            "service": "WFS",
            "version": "1.1.0",
            "key": key,
            "domain": env.get("VWORLD_SERVICE_URL") or "http://localhost",
            "request": "GetFeature",
            "typename": "lt_c_bldginfo",
            "srsname": "EPSG:4326",
            "output": "application/json",
            "maxfeatures": 1000,
            "bbox": ",".join(map(str, bbox)),
        }
        try:
            with urlopen(
                Request(
                    "https://api.vworld.kr/req/wfs?" + urlencode(parameters),
                    headers={"User-Agent": "Gilmok-ingest/1.0"},
                ),
                timeout=60,
            ) as response:
                raw = response.read()
            if key.encode() in raw:
                raise ValueError("Provider response reflected credentials")
            return json.loads(raw)
        except HTTPError as error:
            raise ConnectionError(f"WFS HTTP {error.code}; resume saved tiles") from None
        except (URLError, TimeoutError, OSError, json.JSONDecodeError):
            raise ConnectionError("WFS request failed; resume saved tiles") from None

    def tile(self, bbox):
        key = hashlib.sha256(json.dumps(bbox).encode()).hexdigest()[:12]
        path = self.directory / f"{key}.json"
        if path.exists():
            cached = json.loads(path.read_text())
            if cached["bbox"] != list(bbox):
                raise ValueError("WFS cache bbox differs")
            response = cached["response"]
        else:
            self.requests += 1
            response = self.fetch(bbox)
            self.validate(response)
            atomic_json(path, {"bbox": list(bbox), "response": response})
        self.validate(response)
        return response

    @staticmethod
    def validate(response):
        if response.get("type") != "FeatureCollection":
            raise ValueError("WFS application error, not a successful feature response")
        if int(response["numberReturned"]) != len(response["features"]) or int(
            response["numberMatched"]
        ) < len(response["features"]):
            raise ValueError("WFS response count mismatch")

    def collect(self, bbox):
        features = {}
        tiles = []
        root = self.tile(bbox)

        def visit(bounds, response, depth=0):
            if int(response["numberMatched"]) > len(response["features"]):
                if depth >= 12:
                    raise ValueError("WFS response still truncated at maximum subdivision")
                x0, y0, x1, y1 = bounds
                xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
                for child in [
                    (x0, y0, xm, ym),
                    (xm, y0, x1, ym),
                    (x0, ym, xm, y1),
                    (xm, ym, x1, y1),
                ]:
                    visit(child, self.tile(child), depth + 1)
                return
            tiles.append(list(bounds))
            for feature in response["features"]:
                identity = feature["id"]
                if identity in features and features[identity] != feature:
                    raise ValueError("WFS feature changed between tiles")
                features[identity] = feature

        visit(bbox, root)
        if len(features) != int(root["numberMatched"]):
            raise ValueError("WFS tile union differs from complete root count")
        scoped = [
            f
            for _, f in sorted(features.items())
            if str(f["properties"].get("col_adm_se")) == "11680"
        ]
        if not scoped:
            raise ValueError("No Gangnam WFS features")
        return scoped, {
            "bbox": list(bbox),
            "root_matched": len(features),
            "leaf_tiles": len(tiles),
            "scoped_features": len(scoped),
            "requests_this_run": self.requests,
        }


def normalize_wfs(features, primary_gis_ids, snapshot, raw_path):
    raw = []
    for feature in features:
        raw.append(
            feature["properties"]
            | {
                "feature_id": feature["id"],
                "geometry_json": json.dumps(feature["geometry"], separators=(",", ":")),
            }
        )
    frame = pd.DataFrame(raw)
    from ingest.seoul_transit import write_frame

    write_frame(frame, raw_path)
    candidates = []
    with duckdb.connect() as connection:
        connection.execute("LOAD spatial")
        for row in raw:
            if row["ufid"] in primary_gis_ids:
                continue
            if not re.fullmatch(r"11680[0-9]{14}", str(row["pnu"])):
                raise ValueError("Unverified WFS jurisdiction/PNU")
            height, kind, estimated = height_contract(
                row["height"], row["grnd_flr"], row["usability"]
            )
            geometry = connection.execute(
                "select ST_AsWKB(ST_GeomFromGeoJSON(?))", [row["geometry_json"]]
            ).fetchone()[0]
            candidates.append(
                {
                    "id": "wfs:" + row["feature_id"],
                    "source_id": row["feature_id"],
                    "gis_id": None if row["ufid"] == "NN" else row["ufid"],
                    "pnu": row["pnu"],
                    "source": WFS_SOURCE,
                    "source_version": snapshot,
                    "source_register_pk": None,
                    "candidate_register_pk": None,
                    "source_height_m": positive_number(row["height"]),
                    "floors_above": positive_number(row["grnd_flr"]),
                    "floors_below": row["ugrnd_flr"],
                    "main_use_code": row["usability"],
                    "main_use_name": None,
                    "height_m": height,
                    "height_source": kind,
                    "height_estimated": estimated,
                    "source_geometry_wkb": bytes(geometry),
                    "source_srid": 4326,
                }
            )
    return pd.DataFrame(candidates), {
        "raw_rows": len(raw),
        "missing_gis_id_candidates": len(candidates),
    }
