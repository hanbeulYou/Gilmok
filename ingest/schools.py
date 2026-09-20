"""NEIS Seoul schoolInfo, with explicit source school-type to level mapping."""

import json
import os
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd
from dotenv import dotenv_values

from ingest.common import ROOT
from ingest.geocode import normalize_address
from ingest.seoul_transit import write_frame

SOURCE = "neis_schools"
LEVELS = {"초등학교": "elem", "중학교": "mid", "고등학교": "high"}


def fetch(directory):
    path = directory / "schools.parquet"
    if path.exists():
        return path
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    if not env.get("NEIS_API_KEY"):
        raise ValueError("NEIS_API_KEY required")
    rows, total, page = [], None, 1
    while total is None or len(rows) < total:
        query = urlencode(
            {
                "KEY": env["NEIS_API_KEY"],
                "Type": "json",
                "pIndex": page,
                "pSize": 1000,
                "ATPT_OFCDC_SC_CODE": "B10",
            }
        )
        try:
            with urlopen("https://open.neis.go.kr/hub/schoolInfo?" + query, timeout=30) as response:
                data = json.load(response)["schoolInfo"]
        except Exception:
            raise RuntimeError(
                "NEIS schoolInfo request failed; inspect credentials/service"
            ) from None
        head = data[0]["head"]
        count = head[0]["list_total_count"]
        if head[1]["RESULT"]["CODE"] != "INFO-000" or (total is not None and count != total):
            raise ValueError("Unsuccessful or changing NEIS snapshot")
        total = count
        batch = data[1]["row"]
        if len(batch) != min(1000, total - len(rows)):
            raise ValueError("Incomplete NEIS page")
        rows.extend(batch)
        page += 1
    if not rows:
        raise ValueError("Empty NEIS snapshot")
    directory.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.parquet")
    write_frame(pd.DataFrame(rows), temporary)
    temporary.replace(path)
    return path


def normalize(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty or not raw.ATPT_OFCDC_SC_CODE.eq("B10").all():
        raise ValueError("Expected Seoul education office B10")
    if raw.SD_SCHUL_CODE.isna().any() or raw.SD_SCHUL_CODE.duplicated().any():
        raise ValueError("Duplicate or missing school identities")
    frame = (
        raw[raw.SCHUL_KND_SC_NM.isin(LEVELS)][
            ["SD_SCHUL_CODE", "SCHUL_NM", "SCHUL_KND_SC_NM", "ORG_RDNMA"]
        ]
        .rename(
            columns={
                "SD_SCHUL_CODE": "id",
                "SCHUL_NM": "name",
                "SCHUL_KND_SC_NM": "school_type",
                "ORG_RDNMA": "address",
            }
        )
        .copy()
    )
    frame["level"] = frame.school_type.map(LEVELS)
    frame["address"] = frame.address.map(normalize_address)
    return frame
