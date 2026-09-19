"""OA-12252 monthly counts joined to OA-21212 line/station coordinates."""

import re

import pandas as pd

from ingest.seoul_transit import check_month, check_stops, hourly_values

LINE_NAMES = {"9호선2~3단계": "9호선(연장)", "경의선": "경의중앙선",
              "공항철도 1호선": "공항철도1호선"}


def station_name(value: str) -> str:
    return re.sub(r"\([^)]*\)", "", value).replace(" ", "")


def stops(raw: pd.DataFrame) -> pd.DataFrame:
    result = raw.rename(columns={"BLDN_NM": "name", "ROUTE": "line",
                                 "LAT": "lat", "LOT": "lng"}).copy()
    result["stop_id"] = "subway:" + result.BLDN_ID
    result["type"] = "subway"
    result["match_name"] = result.name.map(station_name)
    result["source_id"] = result.BLDN_ID
    if result.duplicated(["line", "match_name"]).any():
        raise ValueError("Ambiguous normalized subway station name within a line")
    return check_stops(result)


def normalize(raw: pd.DataFrame, master: pd.DataFrame, month: str) -> pd.DataFrame:
    check_month(raw, "USE_MM", month)
    raw = raw.drop_duplicates().reset_index(drop=True)
    if raw.duplicated(["SBWY_ROUT_LN_NM", "STTN"]).any():
        raise ValueError("Duplicate subway line/station observation")
    result = pd.concat([raw[["SBWY_ROUT_LN_NM", "STTN"]].copy(), hourly_values(raw)], axis=1)
    result["source_id"] = raw.SBWY_ROUT_LN_NM + ":" + raw.STTN
    result["line"] = raw.SBWY_ROUT_LN_NM.replace(LINE_NAMES)
    result["match_name"] = raw.STTN.map(station_name)
    result["month"] = month
    result = result.merge(master[["line", "match_name", "stop_id"]],
                          on=["line", "match_name"], how="left", validate="many_to_one")
    if result.loc[result.stop_id.notna(), "stop_id"].duplicated().any():
        raise ValueError("Subway observations collapse onto the same station/line")
    return result
