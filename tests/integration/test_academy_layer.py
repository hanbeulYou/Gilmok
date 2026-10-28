import json

import psycopg
import pytest

from tests.integration.academy_layer_fixture import FIELD, LAT, LNG, fetch, seed
from tests.integration.test_s3_auth import as_user, user


@pytest.fixture
def fixture(db):
    source = seed(db)
    uid = user(db)
    return source, uid


def test_full_radius_counts_public_allowlist_and_101_review_inventory(db, fixture):
    source, uid = fixture
    expected = db.execute(
        "select score_internal.compete("
        "extensions.st_setsrid(extensions.st_makepoint(%s,%s),4326),800,true)",
        (LNG, LAT),
    ).fetchone()[0]
    as_user(db, uid)
    result = fetch(db, source)
    assert result["status"] == "ready"
    assert result["center"] == [LNG, LAT]
    assert result["meta"]["source"] == source
    assert result["counts"]["by_field"] == expected["academies_by_field"]
    assert result["counts"]["radius_same_field"] == expected["academies_by_field"][FIELD] == 100
    assert result["counts"]["radius_all"] == expected["academies_total"] == 300
    assert result["counts"]["radius_pending"] == 99
    assert result["counts"]["radius_same_field_pending"] == 33
    assert result["meta"]["quality_inventory"] == dict(academy=99, school=2)
    features = result["collection"]["features"]
    assert len(features) == len({f["id"] for f in features}) == 300
    assert len({tuple(f["geometry"]["coordinates"]) for f in features[:10]}) == 1
    assert all("school" not in f["id"] for f in features)
    allowed = {
        "name",
        "field",
        "floor_label",
        "floor_status",
        "coordinate_verification_pending",
        "coordinate_review_reason",
        "coordinate_review_version",
    }
    assert all(set(f["properties"]) == allowed for f in features)
    text = json.dumps(result, ensure_ascii=False)
    assert "비공개 합성 상세주소" not in text and str(uid) not in text
    assert features[0]["properties"]["floor_label"] == "지하 1층"
    assert features[1]["properties"]["floor_label"] == "2~3층"
    assert features[2]["properties"]["floor_status"] == "ambiguous"
    assert features[3]["properties"]["floor_label"] is None


def test_boundary_closed_unlocated_and_zero_are_not_missing(db, fixture):
    source, uid = fixture
    # All source changes here are synthetic; keep source/release metadata synchronized.
    db.execute("update public.academies set registration_status='폐원' where id='synthetic-000001'")
    db.execute(
        "update public.academies set geom=null,geocode_failed=true where id='synthetic-000002'"
    )
    for identity, distance in [
        ("synthetic-000003", 799.999),
        ("synthetic-000004", 800.001),
        ("synthetic-000005", 999.999),
        ("synthetic-000006", 1000.001),
    ]:
        db.execute(
            "update public.academies set geom=extensions.st_project(extensions.st_setsrid("
            "extensions.st_makepoint(%s,%s),4326)::extensions.geography,%s,0)"
            "::extensions.geometry where id=%s",
            (LNG, LAT, distance, identity),
        )
    db.execute(
        "update ingest_private.place_snapshots set located_count=row_count-1 "
        "where target_table='academies'"
    )
    source = db.execute("select score_internal.sources()->'academies'").fetchone()[0]
    from psycopg.types.json import Jsonb

    db.execute("update app_private.academy_layer_release set academy_source=%s", (Jsonb(source),))
    as_user(db, uid)
    r800 = fetch(db, source)
    r1000 = fetch(db, source, radius=1000)
    ids800 = {f["id"] for f in r800["collection"]["features"]}
    ids1000 = {f["id"] for f in r1000["collection"]["features"]}
    assert "synthetic-000003" in ids800
    assert not ids800.intersection(
        {
            "synthetic-000001",
            "synthetic-000002",
            "synthetic-000004",
            "synthetic-000005",
            "synthetic-000006",
        }
    )
    assert {"synthetic-000004", "synthetic-000005"} <= ids1000
    assert "synthetic-000006" not in ids1000
    assert r800["meta"]["unlocated_count_seoul"] == 1
    empty = fetch(db, source, lat=37.65)
    assert empty["status"] == "ready" and empty["counts"]["radius_all"] == 0
    assert empty["collection"]["features"] == []
    outside = fetch(db, source, lat=35.0)
    assert outside["status"] == "outside_coverage" and outside["collection"] is None


@pytest.mark.parametrize(
    "change,reason",
    [
        ("delete from app_private.academy_layer_release", "release_missing"),
        ("delete from app_private.academy_display_release", "release_missing"),
        (
            "update app_private.academy_display_release set source_revision='old'",
            "release_mismatch",
        ),
        (
            "delete from app_private.academy_display where academy_id='synthetic-000001'",
            "display_mismatch",
        ),
        (
            "update app_private.academy_coordinate_reviews set source_revision='old' "
            "where entity_kind='academy'",
            "quality_review_mismatch",
        ),
        (
            "delete from app_private.academy_coordinate_reviews where entity_kind='school'",
            "quality_review_mismatch",
        ),
        (
            "update ingest_private.place_snapshots set source_version='new' "
            "where target_table='academies'",
            "source_changed",
        ),
        (
            "delete from ingest_private.place_snapshots where target_table='academies'",
            "source_missing",
        ),
    ],
)
def test_missing_or_mismatched_release_never_exposes_zero_or_points(db, fixture, change, reason):
    source, uid = fixture
    db.execute(change)
    as_user(db, uid)
    result = fetch(db, source)
    assert result["reason"] == reason and result["status"] != "ready"
    assert result["collection"] is None and result["counts"] is None


def test_pending_g_schema_can_be_absent(db, fixture):
    source, uid = fixture
    db.execute("drop table app_private.academy_display_release,app_private.academy_display")
    as_user(db, uid)
    assert fetch(db, source)["reason"] == "release_missing"


def test_authenticated_uid_equality_anon_denied_and_private_tables_denied(db, fixture):
    source, uid = fixture
    other = user(db)
    for table in ["academy_coordinate_reviews", "academy_layer_release"]:
        assert not db.execute(
            "select has_table_privilege('authenticated',%s,'SELECT')", ("app_private." + table,)
        ).fetchone()[0]
    as_user(db, uid)
    first = fetch(db, source)
    db.execute("reset role")
    as_user(db, other)
    assert fetch(db, source) == first
    db.execute("reset role")
    db.execute("set local role anon")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        fetch(db, source)


@pytest.mark.parametrize(
    "kwargs",
    [dict(radius=500), dict(lat=float("nan")), dict(lng=float("inf")), dict(field="x" * 201)],
)
def test_invalid_input_rejected(db, fixture, kwargs):
    source, uid = fixture
    as_user(db, uid)
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        fetch(db, source, **kwargs)


def test_dense_response_is_explicit_and_never_truncated(db):
    source = seed(db, 5001)
    as_user(db, user(db))
    result = fetch(db, source)
    assert result["status"] == "too_dense" and result["collection"] is None
    assert result["meta"]["radius_count"] == 5001
