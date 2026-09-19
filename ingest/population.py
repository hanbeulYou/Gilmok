"""Normalize the verified MOIS monthly single-year age CSV (all resident categories)."""

import re
from pathlib import Path

import pandas as pd

BANDS = {"5_9": range(5, 10), "10_14": range(10, 15), "15_18": range(15, 19)}


def normalize_residents(path: Path, month: str) -> pd.DataFrame:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise ValueError("Month must use YYYY-MM")
    year, number = month.split("-")
    frame = pd.read_csv(path, encoding="cp949", dtype=str, keep_default_na=False)
    columns = {age: f"{year}년{number}월_계_{age}세" for age in range(5, 19)}
    if not {"행정구역", *columns.values()}.issubset(frame.columns):
        raise ValueError("Expected MOIS single-year age columns for the requested month")
    output = []
    seen = set()
    for row in frame.to_dict("records"):
        match = re.search(r"\((\d{10})\)\s*$", row["행정구역"])
        if not match:
            raise ValueError("Missing MOIS administrative code")
        code = match[1]
        if not code.startswith("11") or code[5:8] == "000":
            continue
        if not code.endswith("00") or code in seen:
            raise ValueError("Invalid or duplicate Seoul dong code")
        seen.add(code)
        values = {}
        for age, column in columns.items():
            value = row[column].replace(",", "").strip()
            if not re.fullmatch(r"[0-9]+|\*", value):
                raise ValueError("Invalid population value")
            values[age] = None if value == "*" else int(value)
        for band, ages in BANDS.items():
            selected = [values[age] for age in ages]
            output.append({"adm_cd": code[:8], "age_band": band,
                           "population": None if None in selected else sum(selected),
                           "ref_month": f"{month}-01"})
    if not output:
        raise ValueError("No Seoul dong population rows")
    return pd.DataFrame(output).astype({"population": "Int64"})
