"""OA-12913 counts: retain route/stop-sequence/name segments, join internal ID."""

import pandas as pd

from ingest.seoul_transit import check_month, check_stops, hourly_values


def stops(raw: pd.DataFrame) -> pd.DataFrame:
    # Despite their names, STOPS_NO is internal ID and NODE_ID is the ARS code.
    result = raw.rename(columns={"STOPS_NM": "name", "XCRD": "lng", "YCRD": "lat"}).copy()
    result["stop_id"] = "bus:" + result.STOPS_NO
    result["source_id"] = result.STOPS_NO
    result["type"] = "bus"
    result["line"] = ""
    return check_stops(result)


def normalize(raw: pd.DataFrame, master: pd.DataFrame, month: str) -> pd.DataFrame:
    check_month(raw, "USE_YM", month)
    raw = raw.drop_duplicates().reset_index(drop=True)
    dimensions = ["TRFC_MNS_TYPE_CD", "RTE_NO", "RTE_NM", "STOPS_ID",
                  "STOPS_ARS_NO", "SBWY_STNS_NM"]
    if raw.duplicated(dimensions).any():
        raise ValueError("Duplicate bus observation dimensions; refusing double counting")
    result = pd.concat([raw[dimensions].copy(), hourly_values(raw)], axis=1)
    result["source_id"] = raw.STOPS_ID
    result["month"] = month
    return result.merge(master[["source_id", "stop_id"]], on="source_id", how="left",
                        validate="many_to_one")
