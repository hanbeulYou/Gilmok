from ingest.review_academy_coordinates import classify


def test_same_footprint_proves_only_coordinate_pair_membership():
    assert classify(True, ["a", "b"], ["b"]) == (
        "같은 건물",
        False,
        "same_loaded_footprint_contains_both_points",
    )


def test_different_footprints_do_not_prove_new_coordinate_wrong():
    assert classify(True, ["old"], ["new"]) == (
        "다른 건물",
        False,
        "different_footprints_correct_location_unresolved",
    )


def test_missing_footprints_cannot_prove_apartment_block_match():
    assert classify(True, [], ["new"])[0] == "판단 불가"
    assert classify(True, [], [])[0] == "판단 불가"


def test_original_road_mismatch_rejected_even_with_shared_polygon():
    assert classify(False, ["complex"], ["complex"]) == (
        "다른 건물",
        True,
        "source_road_identity_mismatch",
    )
