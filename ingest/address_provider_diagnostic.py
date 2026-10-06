"""Read-only provider diagnosis for the fixed public D5 address; no DB or queue access."""

import json
import os
import re
from urllib.error import HTTPError

from ingest.geocode import parse_vworld, request_vworld
from ingest.juso import matches_address, parse_search, request_search

ADDRESS = "서울특별시 강남구 강남대로92길 33"


def safe_code(value, keys):
    value = str(value or "")
    if any(key and key in value for key in keys):
        return "redacted"
    return value if re.fullmatch(r"[A-Za-z0-9_-]{1,40}", value) else "unclassified"


def diagnose(env, *, search=request_search, coordinate=request_vworld):
    keys = [env.get("JUSO_API_KEY"), env.get("VWORLD_API_KEY")]
    result = {
        "read_only": True,
        "search_provider": "juso",
        "coordinate_provider": "vworld",
        "juso_key_present": bool(keys[0]),
        "vworld_key_present": bool(keys[1]),
        "steps": [],
    }
    steps = result["steps"]
    if not all(keys):
        steps.append({"stage": "preflight", "status": "missing_key"})
        return result
    try:
        raw = search(ADDRESS, keys[0])
        code = raw["results"]["common"]["errorCode"]
        if str(code) != "0":
            steps.append(
                {"stage": "juso_search", "status": "business_error", "code": safe_code(code, keys)}
            )
            return result
        count, items = parse_search(raw)
        exact = [item for item in items if matches_address(item, ADDRESS)]
        if count != len(items) or len(exact) != 1:
            steps.append({"stage": "juso_search", "status": "no_unique_exact_match"})
            return result
        steps.append({"stage": "juso_search", "status": "ok"})
    except Exception:
        steps.append({"stage": "juso_search", "status": "transport_or_schema_error"})
        return result
    try:
        raw = coordinate(exact[0]["roadAddrPart1"], keys[1])
        response = raw["response"]
        if response["status"] not in {"OK", "NOT_FOUND"}:
            steps.append(
                {
                    "stage": "vworld_coordinate",
                    "status": "business_error",
                    "code": safe_code(response.get("error", {}).get("code"), keys),
                }
            )
            return result
        status, _, _ = parse_vworld(raw, exact[0]["roadAddrPart1"])
        steps.append({"stage": "vworld_coordinate", "status": status})
    except HTTPError as error:
        steps.append(
            {"stage": "vworld_coordinate", "status": "http_error", "http_status": error.code}
        )
    except Exception:
        steps.append({"stage": "vworld_coordinate", "status": "transport_or_schema_error"})
    return result


if __name__ == "__main__":
    print(json.dumps(diagnose(os.environ)))
