"""R-ONE quarterly commercial rents, authenticated complete census, explicit scopes."""

import json
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import urlopen

import pandas as pd
from dotenv import dotenv_values

from ingest.common import ROOT

ENDPOINT = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"
# Only table identities actually verified in the planning evidence are enabled.
TABLES = {
    "TT249843134237374": ("office", "rent"),
    "T244363134858603": ("medium_large", "rent"),
    "T248223134698125": ("small", "rent"),
    "T244913134948657": ("collective", "rent"),
    "T249633134845544": ("medium_large", "vacancy"),
    "TT244763134428698": ("office", "vacancy"),
    "T241833134686576": ("small", "vacancy"),
    "T243283134931290": ("collective", "vacancy"),
}
MISSING_VALUES = {"", "-", "--", "…", "...", "*", "**", "***", "X", "x", "N/A"}
KEY_FIELDS = ("STATBL_ID", "DTACYCLE_CD", "WRTTIME_IDTFR_ID", "CLS_ID", "ITM_ID")


def quarter_id(quarter):
    if not re.fullmatch(r"\d{4}-Q[1-4]", quarter):
        raise ValueError("Quarter must be YYYY-Q1 through YYYY-Q4")
    return quarter[:4] + "0" + quarter[-1]


def parse_page(payload):
    if isinstance(payload, (bytes, str)):
        try:
            payload = json.loads(payload, parse_float=Decimal)
        except (ValueError, UnicodeDecodeError):
            raise ValueError("Invalid R-ONE JSON response") from None
    try:
        sections = payload["SttsApiTblData"]
        head = next(section["head"] for section in sections if "head" in section)
        total = next(entry["list_total_count"] for entry in head if "list_total_count" in entry)
        result = next(entry["RESULT"] for entry in head if "RESULT" in entry)
        rows = next(section["row"] for section in sections if "row" in section)
        if result["CODE"] != "INFO-000" or isinstance(total, bool):
            raise ValueError
        total = int(total)
        if total < 0 or not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise ValueError
    except (KeyError, TypeError, ValueError, StopIteration):
        raise ValueError("R-ONE application error or malformed page") from None
    return rows, total


class RoneClient:
    def __init__(self, cache_dir, *, page_size=1000, request_limit=100, fetch=None):
        if page_size < 1 or request_limit < 0:
            raise ValueError("Invalid page size or request budget")
        self.cache_dir = Path(cache_dir)
        self.page_size = page_size
        self.request_limit = request_limit
        self.request_count = 0
        self.fetch = fetch or self._fetch

    def _fetch(self, parameters):
        env = {**dotenv_values(ROOT / ".env"), **os.environ}
        key = env.get("RONE_API_KEY") or ""
        if not key:
            raise ValueError("RONE_API_KEY required for a full census; sample mode forbidden")
        endpoint = env.get("RONE_API_URL") or ENDPOINT
        query = urlencode(parameters | {"KEY": key, "Type": "json"})
        try:
            with urlopen(f"{endpoint}?{query}", timeout=60) as response:
                raw = response.read()
        except Exception:
            raise ConnectionError("R-ONE authenticated API request failed") from None
        if any(secret.encode() in raw for secret in (key, quote(key, safe=""))):
            raise ValueError("Provider response reflected credentials")
        return raw

    def table(self, statbl_id, quarter):
        if statbl_id not in TABLES:
            raise ValueError("Unverified R-ONE table")
        period = quarter_id(quarter)
        total, number, result, seen = None, 1, [], set()
        while total is None or len(result) < total:
            path = self.cache_dir / f"rone-{statbl_id}-{period}-p{number}.json"
            cached = path.exists()
            if cached:
                raw = path.read_bytes()
            else:
                if self.request_count >= self.request_limit:
                    raise RuntimeError("R-ONE request budget exhausted")
                self.request_count += 1
                raw = self.fetch(
                    {
                        "STATBL_ID": statbl_id,
                        "DTACYCLE_CD": "QY",
                        "WRTTIME_IDTFR_ID": period,
                        "pIndex": number,
                        "pSize": self.page_size,
                    }
                )
            rows, page_total = parse_page(raw)
            if total is None:
                total = page_total
            if page_total != total:
                raise ValueError("R-ONE total changed during pagination")
            if len(rows) != min(self.page_size, max(0, total - len(result))):
                raise ValueError("Incomplete R-ONE page; sample responses cannot form a census")
            for ordinal, row in enumerate(rows, start=1):
                if any(
                    str(row.get(field)) != expected
                    for field, expected in (
                        ("STATBL_ID", statbl_id),
                        ("DTACYCLE_CD", "QY"),
                        ("WRTTIME_IDTFR_ID", period),
                    )
                ):
                    raise ValueError("R-ONE row escaped requested table/quarter")
                if any(row.get(k) in (None, "") for k in KEY_FIELDS):
                    raise ValueError("Missing R-ONE row identity")
                identity = tuple(str(row[k]) for k in KEY_FIELDS)
                if identity in seen:
                    raise ValueError("Duplicate R-ONE row identity")
                seen.add(identity)
                result.append(
                    row
                    | {"request_page": number, "request_row": ordinal, "request_quarter": quarter}
                )
            if not cached:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp")
                if isinstance(raw, dict):
                    raw = json.dumps(raw, ensure_ascii=False, default=str).encode()
                elif isinstance(raw, str):
                    raw = raw.encode()
                temporary.write_bytes(raw)
                temporary.replace(path)
            number += 1
        return result


def collect_survey(quarter, cache_dir, *, client=None, table_ids=None):
    client = client or RoneClient(cache_dir)
    rows = [
        row
        for table in (TABLES if table_ids is None else table_ids)
        for row in client.table(table, quarter)
    ]
    return pd.DataFrame(rows)


def _metric(value, metric):
    if value is None or pd.isna(value) or str(value).strip() in MISSING_VALUES:
        return None
    try:
        number = Decimal(str(value).strip().replace(",", ""))
    except InvalidOperation:
        raise ValueError("Unknown R-ONE suppression or numeric value") from None
    if not number.is_finite() or number < 0 or (metric == "vacancy" and number > 100):
        raise ValueError("Invalid R-ONE metric range")
    return number * 1000 if metric == "rent" else number


def normalize_survey(raw, scope_mappings, *, source_version):
    """Use reviewed table+classification scopes only; never infer a region from names.

    Mapping entries require area_code, area_name, level, building_class, evidence.
    Geometry activation is a separate step: even mapped district rows do not imply
    a valid polygon or quarter-effective geography. Unmapped rows stay raw only.
    """
    result, seen = {}, set()
    for row in raw.to_dict("records"):
        table, cls = str(row["STATBL_ID"]), str(row["CLS_ID"])
        if table not in TABLES or str(row["DTACYCLE_CD"]) != "QY":
            raise ValueError("Unexpected R-ONE table or cycle")
        building_class, metric = TABLES[table]
        period = str(row["WRTTIME_IDTFR_ID"])
        if not re.fullmatch(r"\d{4}0[1-4]", period):
            raise ValueError("Unexpected R-ONE quarter")
        identity = tuple(str(row[k]) for k in KEY_FIELDS)
        if identity in seen:
            raise ValueError("Duplicate R-ONE row identity")
        seen.add(identity)
        scope = scope_mappings.get((table, cls))
        if scope is None:
            continue
        if (
            scope.get("level") not in {"district", "region"}
            or scope.get("building_class") != building_class
            or not all(scope.get(k) for k in ("area_code", "area_name", "evidence"))
        ):
            raise ValueError("Incomplete or inconsistent verified R-ONE scope")
        # Verified tables currently have one metric item; do not silently sum others.
        if str(row["ITM_ID"]) != "100001":
            raise ValueError("Unverified R-ONE metric item")
        unit = str(row.get("UI_NM", "")).strip()
        if unit != ("천원/㎡" if metric == "rent" else "%"):
            raise ValueError("Unexpected R-ONE metric unit")
        quarter = period[:4] + "-Q" + period[-1]
        key = (scope["area_code"], building_class, quarter)
        if key not in result:
            result[key] = {
                "area_code": scope["area_code"],
                "area_name": scope["area_name"],
                "level": scope["level"],
                "building_class": building_class,
                "quarter": quarter,
                "rent_per_m2": None,
                "vacancy_rate": None,
                "rent_statbl_id": None,
                "rent_cls_id": None,
                "vacancy_statbl_id": None,
                "vacancy_cls_id": None,
                "source": "R-ONE",
                "source_version": source_version,
            }
        target = result[key]
        if target["level"] != scope["level"] or target["area_name"] != scope["area_name"]:
            raise ValueError("Conflicting R-ONE scope metadata")
        if target[f"{metric}_statbl_id"] is not None:
            raise ValueError("Multiple R-ONE metrics mapped to one area/class/quarter")
        target["rent_per_m2" if metric == "rent" else "vacancy_rate"] = _metric(
            row.get("DTA_VAL"), metric
        )
        target[f"{metric}_statbl_id"] = table
        target[f"{metric}_cls_id"] = cls
    return pd.DataFrame(result.values())
