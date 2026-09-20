"""Gangnam building register snapshots, exact keys, and resumable page collection."""

import argparse
import hashlib
import json
import math
import os
import re
import time
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen

import pandas as pd
from dotenv import dotenv_values

from ingest.common import ROOT
from ingest.seoul_transit import write_frame

OPERATIONS = {"titles": "getBrTitleInfo", "floors": "getBrFlrOulnInfo"}
ENDPOINT = "https://apis.data.go.kr/1613000/BldRgstHubService"
PAGE_SIZE = 100


def text_id(value):
    """Never recover identifiers from floating point or round a 22-digit PK."""
    if value is None or value == "":
        return None
    if isinstance(value, (float, bool)):
        raise ValueError("A register identifier must be an exact integer or string")
    return str(value).strip() or None


def current_pk(old_pk):
    value = text_id(old_pk)
    if value is None:
        return None
    if not re.fullmatch(r"[0-9]+", value):
        raise ValueError("Invalid original register identifier")
    if len(value) == 22:
        return value
    if len(value) >= 22:
        raise ValueError("Unexpected original register identifier length")
    # Official conversion: Gangnam integration code + active ledger kind + old serial.
    return "10241" + value


def pnu_parts(pnu):
    if not isinstance(pnu, str) or not re.fullmatch(r"11680[0-9]{14}", pnu):
        raise ValueError("Expected a 19-digit Gangnam PNU")
    if pnu[10] not in "12":
        raise ValueError("Unsupported PNU land type; no guessed conversion")
    return {
        "sigunguCd": pnu[:5],
        "bjdongCd": pnu[5:10],
        "platGbCd": {"1": "0", "2": "1"}[pnu[10]],
        "bun": pnu[11:15],
        "ji": pnu[15:19],
    }


def record_pnu(row):
    land = {"0": "1", "1": "2"}.get(str(row.get("platGbCd", "")))
    parts = [str(row.get(k, "")).strip() for k in ("sigunguCd", "bjdongCd", "bun", "ji")]
    if (
        land is None
        or not all(p.isdigit() for p in parts)
        or len(parts[0]) != 5
        or len(parts[1]) != 5
        or len(parts[2]) > 4
        or len(parts[3]) > 4
    ):
        return None
    return parts[0] + parts[1] + land + parts[2].zfill(4) + parts[3].zfill(4)


def parse_page(payload):
    response = payload.get("response", {})
    code = str(response.get("header", {}).get("resultCode", ""))
    if code not in {"00", "0000"}:
        raise ValueError("Building register API returned an unsuccessful result code")
    body = response.get("body", {})
    total = int(body["totalCount"])
    page = int(body["pageNo"])
    size = int(body["numOfRows"])
    container = body.get("items") or {}
    items = container.get("item", []) if isinstance(container, dict) else []
    if isinstance(items, dict):
        items = [items]
    if total < 0 or page < 1 or size < 1 or len(items) > size:
        raise ValueError("Malformed building register page")
    for row in items:
        row["mgmBldrgstPk"] = text_id(row.get("mgmBldrgstPk"))
        if not row["mgmBldrgstPk"]:
            raise ValueError("Missing building register PK")
    return items, total, page, size


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


class RegisterClient:
    def __init__(self, directory, snapshot, *, request_limit=5000, fetch=None):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", snapshot):
            raise ValueError("Snapshot must be an explicit YYYY-MM-DD date")
        self.directory = Path(directory) / snapshot
        self.request_limit = request_limit
        self.request_count = 0
        self.fetch = fetch or self._fetch

    def _fetch(self, operation, parameters):
        env = {**dotenv_values(ROOT / ".env"), **os.environ}
        key = unquote(env.get("DATA_GO_KR_SERVICE_KEY") or "")
        if not key:
            raise ValueError("DATA_GO_KR_SERVICE_KEY is required")
        query = urlencode(parameters | {"serviceKey": key, "_type": "json"})
        try:
            request = Request(
                f"{ENDPOINT}/{operation}?{query}", headers={"User-Agent": "Gilmok-ingest/1.0"}
            )
            with urlopen(request, timeout=45) as response:
                raw = response.read()
            # Credentials must not enter cache files even if reflected by a provider.
            if key.encode() in raw:
                raise ValueError("Provider response reflected credentials")
            if not raw.strip():
                raise ConnectionError("Register empty HTTP 200 body")
            if raw.lstrip().startswith(b"<"):
                raise ValueError("Register returned an XML/HTML application error")
            return json.loads(raw)
        except HTTPError as error:
            raise ConnectionError(f"Register HTTP {error.code}") from None
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise ConnectionError(f"Register transport failed: {type(error).__name__}") from None

    def page(self, operation, group, number):
        parameters = group | {"pageNo": number, "numOfRows": PAGE_SIZE}
        identity = {"operation": operation, "parameters": parameters}
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        path = self.directory / operation / f"{key}.json"
        if path.exists():
            cached = json.loads(path.read_text())
            if cached["request"] != identity:
                raise ValueError("Cache request identity differs")
            return parse_page(cached["response"])
        for attempt in range(8):
            if self.request_count >= self.request_limit:
                raise RuntimeError("Register request budget reached; resume saved pages")
            self.request_count += 1
            try:
                response = self.fetch(operation, parameters)
                parsed = parse_page(response)
                atomic_json(path, {"request": identity, "response": response})
                return parsed
            except ConnectionError as error:
                # Only transient transport failures retry; auth/quota/application errors stop.
                message = str(error)
                atomic_json(
                    path.with_suffix(".error.json"),
                    {"request": identity, "attempt": attempt + 1, "error": message},
                )
                if "HTTP 4" in message or attempt == 7:
                    raise
                time.sleep(min(1 + attempt, 5))
        raise AssertionError("Unreachable retry state")

    def group(self, operation, group):
        rows, total, page, size = self.page(operation, group, 1)
        if page != 1 or size != PAGE_SIZE:
            raise ValueError("Unexpected register page number or page size")
        expected_pages = max(1, math.ceil(total / size))
        result = []
        for number in range(1, expected_pages + 1):
            if number > 1:
                rows, actual_total, actual_page, actual_size = self.page(operation, group, number)
                if (actual_total, actual_page, actual_size) != (total, number, size):
                    raise ValueError("Register snapshot changed during pagination")
            if len(rows) != min(size, max(0, total - (number - 1) * size)):
                raise ValueError("Incomplete register page")
            for ordinal, row in enumerate(rows):
                if int(row.get("rnum", -1)) != (number - 1) * size + ordinal + 1:
                    raise ValueError("Register row sequence differs from requested page")
                if any(str(row.get(k)) != str(v) for k, v in group.items()):
                    raise ValueError("Register response escaped requested jurisdiction/land type")
                result.append(row | {"request_page": number, "request_row": ordinal})
        return result


def download(groups, directory, snapshot, *, client=None):
    client = client or RegisterClient(Path(directory) / "pages", snapshot)
    result = {"snapshot": snapshot, "groups": groups}
    for kind, operation in OPERATIONS.items():
        rows = []
        for group in groups:
            part = client.group(operation, group)
            rows.extend(part)
            print(
                json.dumps(
                    {
                        "source": kind,
                        "dong": group["bjdongCd"],
                        "land": group["platGbCd"],
                        "rows": len(part),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        if not rows:
            raise ValueError("Refusing an empty register snapshot")
        # Titles are unique by PK. A floor can have multiple source rows per floor number.
        if kind == "titles" and len({r["mgmBldrgstPk"] for r in rows}) != len(rows):
            raise ValueError("Duplicate title PK; source changed or pagination overlaps")
        path = Path(directory) / f"{kind}-{snapshot}.parquet"
        write_frame(pd.DataFrame(rows), path)
        result[kind] = {"rows": len(rows), "path": str(path)}
    result["requests_this_run"] = client.request_count
    atomic_json(Path(directory) / "register-manifest.json", result)
    return result


def normalize_titles(frame):
    rows = frame.to_dict("records")
    result = []
    for row in rows:
        result.append(
            {
                "register_pk": text_id(row["mgmBldrgstPk"]),
                "pnu": record_pnu(row),
                "name": row.get("bldNm"),
                "dong_name": row.get("dongNm"),
                "floors_above": row.get("grndFlrCnt"),
                "floors_below": row.get("ugrndFlrCnt"),
                "height_m": row.get("heit"),
                "main_use_code": row.get("mainPurpsCd"),
                "main_use_name": row.get("mainPurpsCdNm"),
                "other_use": row.get("etcPurps"),
                "gross_area": row.get("totArea"),
                "passenger_elevators": row.get("rideUseElvtCnt"),
                "emergency_elevators": row.get("emgenUseElvtCnt"),
                "use_approval_date": row.get("useAprDay"),
            }
        )
    return pd.DataFrame(result)


def normalize_floors(frame):
    result = []
    occurrences = Counter()
    ignored = {"rnum", "request_page", "request_row"}
    for row in frame.to_dict("records"):
        stable = {k: None if pd.isna(v) else v for k, v in row.items() if k not in ignored}
        digest = hashlib.sha256(
            json.dumps(stable, sort_keys=True, ensure_ascii=False, default=str).encode()
        ).hexdigest()
        occurrences[digest] += 1
        result.append(
            {
                "id": f"{digest}:{occurrences[digest]}",
                "register_pk": text_id(row["mgmBldrgstPk"]),
                "pnu": record_pnu(row),
                "floor_kind": row.get("flrGbCd"),
                "floor_kind_name": row.get("flrGbCdNm"),
                "floor_no": row.get("flrNo"),
                "floor_name": row.get("flrNoNm"),
                "use_code": row.get("mainPurpsCd"),
                "use_name": row.get("mainPurpsCdNm"),
                "other_use": row.get("etcPurps"),
                "area": row.get("area"),
                "main_attached_code": row.get("mainAtchGbCd"),
            }
        )
    return pd.DataFrame(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--groups-json", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--snapshot", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            download(json.loads(args.groups_json.read_text()), args.directory, args.snapshot)
        )
    )


if __name__ == "__main__":
    main()
