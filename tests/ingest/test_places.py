from zipfile import ZipFile

import duckdb
import pandas as pd
import pytest

from ingest import academies, schools, stores
from ingest.seoul_transit import write_frame


def academy(**updates):
    row = {key: "" for key in academies.MAPPING}
    row.update(
        PEI_DSGN_NO="001",
        PEI_NM="학원",
        PEI_TRNG_NM="학원",
        REG_STTS_NM="개원",
        FLD_NM="입시.검정 및 보습",
        TRNG_AFLT_NM="보통교과",
        TRNG_CRS_NM="보습·논술",
        TRNG_CRS_LIST_NM="국어, 논술(초등)",
        ROAD_NM_ADDR=" 서울  삼성로 212 ",
    )
    row.update(updates)
    return row


def test_academy_raw_text_no_subject_inference():
    frame = academies.normalize(
        pd.DataFrame(
            [
                academy(),
                academy(PEI_DSGN_NO="002", FLD_NM=""),
                academy(PEI_DSGN_NO="003", REG_STTS_NM="폐원"),
            ]
        )
    )
    assert len(frame) == 2
    assert frame.field.tolist() == ["입시.검정 및 보습", ""]
    assert frame.course.tolist() == ["보습·논술"] * 2
    assert frame.course_list.tolist() == ["국어, 논술(초등)"] * 2
    assert frame.address.tolist() == ["서울 삼성로 212"] * 2
    assert not any("subject" in c for c in frame)


@pytest.mark.parametrize("rows", [[academy(), academy()], [academy(REG_STTS_NM="unknown")]])
def test_ambiguous_academy_contract_rejected(rows):
    with pytest.raises(ValueError):
        academies.normalize(pd.DataFrame(rows))


def test_explicit_school_grades_only():
    raw = pd.DataFrame(
        [
            dict(
                ATPT_OFCDC_SC_CODE="B10",
                SD_SCHUL_CODE=str(i),
                SCHUL_NM="학교",
                SCHUL_KND_SC_NM=kind,
                ORG_RDNMA="서울 삼성로 212",
            )
            for i, kind in enumerate(["초등학교", "중학교", "고등학교", "특수학교", "각종학교(고)"])
        ]
    )
    assert schools.normalize(raw).level.tolist() == ["elem", "mid", "high"]
    raw.loc[0, "ATPT_OFCDC_SC_CODE"] = "C10"
    with pytest.raises(ValueError):
        schools.normalize(raw)


def test_csv_raw_empty_strings_and_minimal_store_projection(tmp_path):
    archive = tmp_path / "source.zip"
    with ZipFile(archive, "w") as z:
        z.writestr(
            "소상공인_서울_202606.csv",
            "상가업소번호,시도코드,상권업종대분류코드,"
            "상권업종중분류코드,상권업종소분류코드,층정보,경도,위도,상호명,도로명주소,"
            "표준산업분류코드\n001,11,P1,P105,P10501,,127.05,37.5,원문상호,주소,P85501\n",
        )
    path = stores.extract_raw(archive, tmp_path, "2026-06")
    with duckdb.connect() as d:
        raw = d.read_parquet(str(path)).df()
    assert raw.loc[0, "층정보"] == ""
    assert raw.loc[0, "상호명"] == "원문상호"
    frame = stores.normalize(path)
    assert frame.store_id.tolist() == ["001"]
    assert pd.isna(frame.floor.iloc[0])
    assert set(frame) == {"store_id", "inds_lcls", "inds_mcls", "inds_scls", "floor", "lng", "lat"}
    raw.loc[0, "상권업종중분류코드"] = "I201"
    write_frame(raw, path)
    with pytest.raises(ValueError, match="hierarchy"):
        stores.normalize(path)
