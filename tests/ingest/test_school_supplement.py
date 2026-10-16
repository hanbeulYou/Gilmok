import pytest

from ingest.supplement_school_coordinates import build_plan


def school(id="1", **changes):
    return dict(
        neis_id=id,
        name="학교" + id,
        status="address_match",
        juso_status="ready",
        inside_seoul=True,
        distance_m=72,
        standard=dict(
            SCHOOL_ID="B" + id, LONGITUDE="127.0", LATITUDE="37.5", REFERENCE_DATE="2026-10-01"
        ),
        **changes,
    )


def test_only_missing_matched_inside_schools_are_filled():
    existing = school()
    missing = {**school("2"), "juso_status": "not_found"}
    outside = {**school("3"), "juso_status": "not_found", "inside_seoul": False}
    mismatch = {**school("4"), "juso_status": "not_found", "status": "address_diff"}
    plan = build_plan([existing, missing, outside, mismatch])
    assert [r["id"] for r in plan["fills"]] == ["2"]
    assert plan["holds"] == []


def test_review_flags_preserve_ready_juso_instead_of_replacing_it():
    plan = build_plan(
        [{**school(), "inside_seoul": False}, {**school("2"), "distance_m": 538}, school("3")]
    )
    assert plan["fills"] == []
    assert [r["reason"] for r in plan["holds"]] == [
        "coordinate_verification_pending:standard_outside_seoul",
        "coordinate_verification_pending:standard_juso_distance_gt_500m",
    ]


def test_reject_duplicate_identity_crosswalk_or_invalid_coordinate():
    with pytest.raises(ValueError, match="Duplicate NEIS"):
        build_plan([school(), school()])
    with pytest.raises(ValueError, match="one-to-one"):
        build_plan([school(), {**school("2"), "standard": school()["standard"]}])
    invalid = school()
    invalid["standard"]["LONGITUDE"] = "nan"
    with pytest.raises(ValueError, match="Invalid degree"):
        build_plan([invalid])
