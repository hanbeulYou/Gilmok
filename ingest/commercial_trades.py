"""Gangnam commercial sales: complete monthly XML census and lossless normalization."""

import argparse
import os
import re
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote, unquote, urlencode
from urllib.request import urlopen

import pandas as pd
from dotenv import dotenv_values

from ingest.common import ROOT
from ingest.seoul_transit import write_frame

ENDPOINT = "https://apis.data.go.kr/1613000/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade"


def months_between(start, end):
    for value in (start, end):
        if not re.fullmatch(r"\d{6}", value):
            raise ValueError("Month must be YYYYMM")
        date(int(value[:4]), int(value[4:]), 1)
    if start > end:
        raise ValueError("Month range is reversed")
    year, month = int(start[:4]), int(start[4:])
    while f"{year:04d}{month:02d}" <= end:
        yield f"{year:04d}{month:02d}"
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def parse_page(raw):
    """Retain every provider field as text, including whitespace and masked addresses."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise ValueError("Invalid commercial transaction XML") from None
    if root.findtext("header/resultCode", "").strip() not in {"00", "000"}:
        raise ValueError("Commercial transaction API returned an application error")
    body = root.find("body")
    if body is None:
        raise ValueError("Missing commercial transaction body")
    try:
        total, page, size = (
            int(body.findtext(k, "")) for k in ("totalCount", "pageNo", "numOfRows")
        )
    except ValueError:
        raise ValueError("Invalid commercial transaction pagination") from None
    if total < 0 or page < 1 or size < 1:
        raise ValueError("Invalid commercial transaction pagination")
    rows = []
    for item in body.findall("items/item"):
        row = {field.tag: field.text or "" for field in item}
        if len(row) != len(item):
            raise ValueError("Duplicate XML field")
        rows.append(row)
    return rows, total, page, size


class TradeClient:
    def __init__(self, cache_dir, *, page_size=1000, request_limit=100, fetch=None):
        self.cache_dir = Path(cache_dir)
        if page_size < 1 or request_limit < 0:
            raise ValueError("Invalid page size or request limit")
        self.page_size = page_size
        self.request_limit = request_limit
        self.request_count = 0
        self.fetch = fetch or self._fetch

    def _fetch(self, parameters):
        env = {**dotenv_values(ROOT / ".env"), **os.environ}
        key = unquote(env.get("DATA_GO_KR_SERVICE_KEY") or "")
        if not key:
            raise ValueError("DATA_GO_KR_SERVICE_KEY required")
        endpoint = env.get("COMMERCIAL_TRADES_API_URL") or ENDPOINT
        query = urlencode(parameters | {"serviceKey": key})
        try:
            with urlopen(f"{endpoint}?{query}", timeout=60) as response:
                raw = response.read()
        except Exception:
            raise ConnectionError("Commercial transaction API request failed") from None
        if any(value.encode() in raw for value in (key, quote(key, safe=""))):
            raise ValueError("Provider response reflected credentials")
        return raw

    def page(self, month, number):
        list(months_between(month, month))
        path = self.cache_dir / f"trades-{month}-p{number}.xml"
        cached = path.exists()
        if cached:
            raw = path.read_bytes()
        else:
            if self.request_count >= self.request_limit:
                raise RuntimeError("Commercial transaction request budget exhausted")
            self.request_count += 1
            raw = self.fetch(
                {
                    "LAWD_CD": "11680",
                    "DEAL_YMD": month,
                    "pageNo": number,
                    "numOfRows": self.page_size,
                }
            )
        rows, total, page, size = parse_page(raw)
        if page != number or size != self.page_size:
            raise ValueError("Commercial transaction response pagination mismatch")
        expected = min(size, max(0, total - (number - 1) * size))
        if len(rows) != expected:
            raise ValueError("Incomplete commercial transaction page")
        for row in rows:
            if row.get("sggCd", "").strip() != "11680":
                raise ValueError("Transaction escaped requested jurisdiction")
            try:
                row_month = f"{int(row['dealYear']):04d}{int(row['dealMonth']):02d}"
            except (KeyError, ValueError):
                raise ValueError("Invalid transaction contract month") from None
            if row_month != month:
                raise ValueError("Transaction escaped requested month")
        if not cached:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(raw)
            temporary.replace(path)
        return rows, total

    def month(self, month):
        rows, total = self.page(month, 1)
        result = []
        pages = max(1, (total + self.page_size - 1) // self.page_size)
        for number in range(1, pages + 1):
            if number > 1:
                rows, next_total = self.page(month, number)
                if next_total != total:
                    raise ValueError("Commercial transaction census changed during pagination")
            result.extend(
                row | {"request_month": month, "request_page": number, "request_row": ordinal}
                for ordinal, row in enumerate(rows, start=1)
            )
        return result


def collect_months(start_month, end_month, cache_dir, *, client=None):
    client = client or TradeClient(cache_dir)
    rows = [row for month in months_between(start_month, end_month) for row in client.month(month)]
    return pd.DataFrame(rows).fillna("")


def _text(value):
    return "" if value is None or pd.isna(value) else str(value).strip()


def _positive_decimal(value):
    try:
        number = Decimal(_text(value).replace(",", ""))
    except InvalidOperation:
        return None
    return number if number.is_finite() and number > 0 else None


def _cancel_date(value):
    text = _text(value)
    if not text:
        return None
    if not re.fullmatch(r"\d{2}\.\d{2}\.\d{2}", text):
        raise ValueError("Unexpected cancellation date format")
    year, month, day = map(int, text.split("."))
    return date(2000 + year, month, day)


def normalize_trades(raw, legal_dongs=None):
    """Keep raw text; never infer legal dong from an administrative-dong code.

    buildingAr is building area (m²). General/collective remain separate; a more
    specific gross/exclusive definition is not assumed from ambiguous metadata.
    """
    records = []
    for source in raw.to_dict("records"):
        kind = {"일반": "general", "집합": "collective"}.get(_text(source.get("buildingType")))
        if kind is None:
            raise ValueError("Unknown commercial building type")
        cancel_type = _text(source.get("cdealType"))
        if cancel_type not in {"", "O"}:
            raise ValueError("Unknown commercial cancellation marker")
        cancelled = cancel_type == "O"
        cancel_date = _cancel_date(source.get("cdealDay"))
        if cancelled != (cancel_date is not None):
            raise ValueError("Cancellation marker/date mismatch")
        share = _text(source.get("shareDealingType"))
        if share not in {"", "지분"}:
            raise ValueError("Unknown share transaction marker")
        amount = _positive_decimal(source.get("dealAmount"))
        area = _positive_decimal(source.get("buildingAr"))
        amount_won = amount * 10000 if amount is not None else None
        floor = _text(source.get("floor"))
        if floor and not re.fullmatch(r"-?\d+", floor):
            raise ValueError("Unexpected commercial floor value")
        reasons = []
        if cancelled:
            reasons.append("cancelled")
        if share:
            reasons.append("share")
        if amount is None:
            reasons.append("invalid_amount")
        if area is None:
            reasons.append("invalid_area")
        dong_name = _text(source.get("umdNm"))
        dong_code = legal_dongs.get(dong_name) if legal_dongs is not None else None
        if legal_dongs is not None and not re.fullmatch(r"11680\d{3}", dong_code or ""):
            raise ValueError("Unmatched Gangnam legal dong")
        records.append(
            source
            | {
                "trade_kind": kind,
                "area_basis": "building_area",
                "deal_date": date(*(int(source[k]) for k in ("dealYear", "dealMonth", "dealDay"))),
                "cancel_date": cancel_date,
                "cancelled": cancelled,
                "is_share": bool(share),
                "deal_amount_won": amount_won,
                "building_area_m2": area,
                "price_per_m2_won": amount_won / area if amount_won is not None and area else None,
                "floor_number": int(floor) if floor else None,
                "legal_dong_name": dong_name,
                "legal_dong_code": dong_code,
                "exclusion_reason": ";".join(reasons) or None,
                "eligible": not reasons,
            }
        )
    result = pd.DataFrame(records)
    if records:
        result["floor_number"] = pd.array(result["floor_number"], dtype="Int64")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-month", required=True)
    parser.add_argument("--end-month", required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = collect_months(args.start_month, args.end_month, args.cache_dir)
    write_frame(raw, args.output)
    print(f"Commercial raw snapshot: {len(raw)} rows")


if __name__ == "__main__":
    main()
