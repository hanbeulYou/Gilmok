"""Seoul transit retrieval and schema checks; never expose credential-bearing URLs."""

import json
import os
import re
import time
from pathlib import Path
from urllib.request import urlopen

import duckdb
import pandas as pd
from dotenv import dotenv_values

from ingest.common import ROOT


def fetch_json(service: str, start: int, end: int, argument: str = "") -> dict:
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    key = env.get("SEOUL_OPEN_DATA_API_KEY", "")
    if not key:
        raise ValueError("SEOUL_OPEN_DATA_API_KEY is required")
    base = env.get("SEOUL_TRANSIT_API_URL", "http://openapi.seoul.go.kr:8088")
    url = f"{base}/{key}/json/{service}/{start}/{end}/{argument}"
    for attempt in range(3):
        try:
            with urlopen(url, timeout=30) as response:
                return json.load(response)
        except Exception:
            if attempt == 2:
                raise RuntimeError(
                    f"Seoul request failed: {service}, rows {start}-{end}"
                ) from None
            time.sleep(attempt + 1)


def download(service: str, argument: str, directory: Path) -> Path:
    """Save a full API snapshot, checking every page against its declared total."""
    path = directory / f"{service}-{argument.replace('/', '_') or 'current'}.parquet"
    if path.exists():
        return path
    rows = []
    total = None
    start = 1
    while total is None or start <= total:
        data = fetch_json(service, start, start + 999, argument)
        result = data.get(service, {})
        if result.get("RESULT", {}).get("CODE") != "INFO-000":
            raise ValueError(f"Unsuccessful or missing response for {service}")
        count = result["list_total_count"]
        if total is not None and total != count:
            raise ValueError("Source changed during pagination")
        total = count
        page = result["row"]
        if len(page) != min(1000, total - start + 1):
            raise ValueError("Incomplete API page")
        rows.extend(page)
        start += 1000
    if not rows:
        raise ValueError("Empty source snapshot")
    with duckdb.connect() as connection:
        connection.register("incoming", pd.DataFrame(rows))
        temporary = path.with_suffix(".tmp.parquet")
        connection.table("incoming").write_parquet(str(temporary), compression="zstd")
        temporary.replace(path)
    print(service, argument, len(rows), flush=True)
    return path


def read_frame(path: Path) -> pd.DataFrame:
    with duckdb.connect() as connection:
        return connection.read_parquet(str(path)).df()


def write_frame(frame: pd.DataFrame, path: Path) -> None:
    with duckdb.connect() as connection:
        connection.register("incoming", frame)
        connection.table("incoming").write_parquet(str(path), compression="zstd")


def hourly_values(raw: pd.DataFrame) -> pd.DataFrame:
    """Accept the observed NOPE/TNOPE spelling, but require exactly 48 measures."""
    columns = {}
    for column in raw.columns:
        match = re.fullmatch(r"HR_(\d+)_GET_(ON|OFF)_(?:TNOPE|NOPE)", column)
        if match:
            hour, direction = match.groups()
            target = f"{'boarding' if direction == 'ON' else 'alighting'}_{int(hour)}"
            if target in columns.values():
                raise ValueError("Ambiguous hourly columns")
            columns[column] = target
    expected = {f"{direction}_{hour}" for direction in ("boarding", "alighting")
                for hour in range(24)}
    if set(columns.values()) != expected:
        raise ValueError("Expected all 24 boarding and alighting hours")
    values = raw[list(columns)].rename(columns=columns).apply(pd.to_numeric, errors="raise")
    # Empty/disclosed NULL stays missing, never zero. Reject non-finite/negative counts.
    if ((values < 0) | (values == float("inf")) | (values == -float("inf"))
            | (values.notna() & (values % 1 != 0))).any().any():
        raise ValueError("Invalid passenger counts")
    return values


def check_month(raw: pd.DataFrame, column: str, month: str) -> None:
    if raw.empty or set(raw[column]) != {month.replace("-", "")}:
        raise ValueError("Empty or wrong-month snapshot")


def check_stops(stops: pd.DataFrame) -> pd.DataFrame:
    if stops.empty or stops.stop_id.duplicated().any():
        raise ValueError("Empty or duplicate stop identities")
    stops = stops.copy()
    for column in ("lng", "lat"):
        stops[column] = pd.to_numeric(stops[column], errors="raise")
    if not (stops.lng.between(124, 132) & stops.lat.between(33, 39)).all():
        raise ValueError("Expected Korean EPSG:4326 longitude/latitude")
    return stops
