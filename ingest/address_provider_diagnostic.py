"""One public-address Juso diagnosis, no DB/cache writes or sensitive response logging."""

import json
import math
import os
import re
from urllib.error import HTTPError

from ingest.juso import (
    COORD_URL,
    IDENTIFIERS,
    api_json,
    matches_address,
    parse_search,
    request_search,
)

ADDRESS = "서울특별시 강남구 강남대로92길 33"


def safe_code(value, keys):
    value = str(value or "")
    if any(key and key in value for key in keys):
        return "redacted"
    return value if re.fullmatch(r"[A-Za-z0-9_-]{1,40}", value) else "unclassified"


def request_coordinate(item, key):
    return api_json(
        COORD_URL, dict(confmKey=key, resultType="json", **{k: item[k] for k in IDENTIFIERS})
    )


def diagnose(env, *, search=request_search, coordinate=request_coordinate):
    keys = [env.get("JUSO_API_KEY"), env.get("JUSO_COORD_API_KEY")]
    result = dict(
        read_only=True,
        search_provider="juso",
        coordinate_provider="juso",
        juso_key_present=bool(keys[0]),
        juso_coord_key_present=bool(keys[1]),
        steps=[],
    )
    steps = result["steps"]
    if not all(keys):
        steps.append(dict(stage="preflight", status="missing_key"))
        return result
    try:
        raw = search(ADDRESS, keys[0])
        code = raw["results"]["common"]["errorCode"]
        if str(code) != "0":
            steps.append(
                dict(stage="juso_search", status="business_error", code=safe_code(code, keys))
            )
            return result
        count, items = parse_search(raw)
        exact = [item for item in items if matches_address(item, ADDRESS)]
        if count != len(items) or len(exact) != 1:
            steps.append(dict(stage="juso_search", status="no_unique_exact_match"))
            return result
        steps.append(dict(stage="juso_search", status="ok"))
    except Exception:
        steps.append(dict(stage="juso_search", status="transport_or_schema_error"))
        return result
    try:
        raw = coordinate(exact[0], keys[1])["results"]
        common = raw["common"]
        if str(common["errorCode"]) != "0":
            steps.append(
                dict(
                    stage="juso_coordinate",
                    status="business_error",
                    code=safe_code(common["errorCode"], keys),
                )
            )
            return result
        count = int(common["totalCount"])
        if count == 0 and not raw.get("juso"):
            steps.append(dict(stage="juso_coordinate", status="missing"))
            return result
        if count != 1 or len(raw["juso"]) != 1:
            raise ValueError("Coordinate result not unique")
        point = raw["juso"][0]
        if point["bdMgtSn"] != exact[0]["bdMgtSn"]:
            raise ValueError("Building identifier mismatch")
        x, y = float(point["entX"]), float(point["entY"])
        if not all(math.isfinite(v) and v > 0 for v in (x, y)):
            raise ValueError("Invalid EPSG:5179 coordinate")
        steps.append(
            dict(
                stage="juso_coordinate",
                status="ready",
                building_identifier_match=True,
                source_crs="EPSG:5179",
            )
        )
    except HTTPError as error:
        steps.append(dict(stage="juso_coordinate", status="http_error", http_status=error.code))
    except Exception:
        steps.append(dict(stage="juso_coordinate", status="transport_or_schema_error"))
    return result


if __name__ == "__main__":
    print(json.dumps(diagnose(os.environ)))
