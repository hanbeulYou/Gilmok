"""OA-20528 field/affiliation/course strings are preserved, never subject-classified."""

import pandas as pd

from ingest.geocode import normalize_address
from ingest.seoul_transit import download

SOURCE = "seoul_neis_academies"
SERVICE = "neisAcademyInfo"
MAPPING = {
    "PEI_DSGN_NO": "id",
    "PEI_NM": "name",
    "PEI_TRNG_NM": "institution_type",
    "REG_STTS_NM": "registration_status",
    "FLD_NM": "field",
    "TRNG_AFLT_NM": "affiliation",
    "TRNG_CRS_LIST_NM": "course_list",
    "TRNG_CRS_NM": "course",
    "ROAD_NM_ADDR": "address",
}


def fetch(directory):
    return download(SERVICE, "", directory)


def normalize(raw: pd.DataFrame) -> pd.DataFrame:
    frame = raw[list(MAPPING)].rename(columns=MAPPING).copy()
    if frame.empty or frame.id.isna().any() or frame.id.eq("").any() or frame.id.duplicated().any():
        raise ValueError("Empty or duplicate academy identities")
    if not frame.registration_status.isin(["개원", "휴원", "폐원"]).all():
        raise ValueError("Unknown academy registration status; inspect raw distribution")
    frame = frame[frame.registration_status.eq("개원")].copy()
    if not frame.institution_type.isin(["학원", "교습소"]).all():
        raise ValueError("Unknown academy institution type")
    # NULL is not silently reclassified as a named field; actual empty strings stay empty.
    if frame[["field", "affiliation", "course_list", "course"]].isna().any().any():
        raise ValueError("Unexpected null raw classification; inspect source")
    frame["address"] = frame.address.map(normalize_address)
    return frame
