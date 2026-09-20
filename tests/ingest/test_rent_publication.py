"""Synthetic survey metadata must never activate unproved district/region geography."""

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from ingest.common import RawStore, Settings, StorageError
from ingest.publish_rent_survey import build_scopes, run
from ingest.rent_survey import TABLES, normalize_survey

SNAPSHOT = "20260920T150000Z"
INTERSECTIONS = [[444, "테헤란로", "2024", 1787144.04], [700, "서초역", "2024", 0]]


def source_rows():
    rows = []
    for index, (table, (_, metric)) in enumerate(TABLES.items()):
        for cls, name, hierarchy in [
            (510004, "강남", "서울>강남"),
            (520100 + index, "테헤란로", "서울>강남>테헤란로"),
            (530100 + index, "서초역", "서울>강남>서초역"),
            (540100 + index, "강남구", "서울>강남구"),
        ]:
            rows.append({"STATBL_ID": table, "DTACYCLE_CD": "QY", "WRTTIME_IDTFR_ID": "202602",
                         "CLS_ID": cls, "CLS_NM": name, "CLS_FULLNM": hierarchy,
                         "ITM_ID": 100001, "UI_NM": "천원/㎡" if metric == "rent" else "%",
                         "DTA_VAL": 50 if metric == "rent" else 7,
                         "original_extra": "preserve me"})
    return pd.DataFrame(rows)


def metadata():
    table = next(iter(TABLES))
    return [{"statblId": table, "datano": 510004, "itmId": 61029200,
             "viewItmFullnm": "서울>강남"},
            {"statblId": table, "datano": 520100, "itmId": 61029510,
             "viewItmFullnm": "서울>강남>테헤란로"}]


def scopes(raw=None, meta=None):
    return build_scopes(source_rows() if raw is None else raw, INTERSECTIONS,
                        metadata() if meta is None else meta,
                        quarter="2026-Q2", snapshot=SNAPSHOT)


def test_exact_region_is_not_gu_and_only_positive_overlap_district_facts_are_selected():
    mappings, areas = scopes()
    assert len(mappings) == 16  # Two scopes in eight independent source tables.
    assert set(areas.area_code) == {"61029200", "61029510"}
    assert set(areas.level) == {"region", "district"}
    assert not areas.mapping_verified.any()
    assert areas.wkt.isna().all()
    assert "서초역" not in set(areas.area_name)
    assert "강남구" not in set(areas.area_name)
    region = areas[areas.level == "region"].iloc[0]
    assert "official_region_definition_missing" in region.mapping_evidence
    assert "Gangnam region is not Gangnam-gu" in region.mapping_evidence
    district = areas[areas.level == "district"].iloc[0]
    assert "2024_boundary_applicability" in district.mapping_evidence
    facts = normalize_survey(source_rows(), mappings, source_version=SNAPSHOT)
    assert len(facts) == 8
    assert set(facts.rent_per_m2) == {50000}
    assert set(facts.vacancy_rate) == {7}
    assert facts.rent_cls_id.notna().all()
    assert facts.vacancy_cls_id.notna().all()


def test_missing_metadata_uses_explicit_full_path_identity_and_never_activates_geometry():
    _, areas = scopes(meta=[])
    assert set(areas.area_code) == {"61029200", "rone:서울>강남>테헤란로"}
    assert not areas.mapping_verified.any()
    assert areas.wkt.isna().all()


def test_missing_hierarchy_stays_raw_only_and_conflicting_metadata_fails():
    raw = source_rows()
    raw.loc[raw.CLS_NM == "테헤란로", "CLS_FULLNM"] = None
    _, areas = scopes(raw)
    assert set(areas.area_code) == {"61029200"}
    conflicting = metadata() + [{"statblId": "other", "datano": 999, "itmId": 61029999,
                               "viewItmFullnm": "서울>강남>테헤란로"}]
    with pytest.raises(ValueError, match="Ambiguous"):
        scopes(meta=conflicting)


@pytest.mark.parametrize("fault", ["leaf", "region_cls", "metadata_cls", "scope_collision"])
def test_unverified_source_identity_is_rejected(fault):
    raw, meta = source_rows(), metadata()
    if fault == "leaf":
        raw.loc[0, "CLS_NM"] = "강남구"
    elif fault == "region_cls":
        raw.loc[0, "CLS_ID"] = 1234
    elif fault == "metadata_cls":
        meta[1]["viewItmFullnm"] = "서울>강남>다른상권"
    else:
        # Two eligible identities cannot share one source-table classification key.
        raw.loc[1, "CLS_ID"] = raw.loc[0, "CLS_ID"]
        meta = []
    with pytest.raises(ValueError):
        scopes(raw, meta)


def setup_run(tmp_path, monkeypatch):
    import ingest.publish_rent_survey as module

    monkeypatch.setenv("RONE_API_KEY", "synthetic-secret")
    monkeypatch.setattr(module, "dotenv_values", lambda _: {})
    monkeypatch.setattr(module, "collect_survey", lambda *args: source_rows())
    (tmp_path / "boundary-intersections.json").write_text(json.dumps(INTERSECTIONS))
    (tmp_path / "rone-seoul-boundaries.json").write_text(
        json.dumps({"synthetic_provider_geometry": "preserve original response"})
    )
    (tmp_path / "rone-cls-office-names.json").write_text(json.dumps({"data": metadata()}))
    args = SimpleNamespace(quarter="2026-Q2", snapshot=SNAPSHOT, directory=str(tmp_path))
    store = RawStore(Settings(tmp_path / "published"))
    return module, args, store


def test_end_to_end_local_revision_reread_precedes_only_disabled_fact_load(tmp_path, monkeypatch):
    module, args, store = setup_run(tmp_path, monkeypatch)
    saved = {}

    @contextmanager
    def database():
        yield object()

    def load(connection, areas, surveys, **kwargs):
        saved.update(areas=areas, surveys=surveys)
        assert (tmp_path / SNAPSHOT / "rent-survey-publication.json").exists()
        assert not areas.mapping_verified.any()
        assert areas.wkt.isna().all()
        return {"survey_rows": len(surveys)}

    monkeypatch.setattr(module, "load_survey_snapshot", load)
    report = run(args, store=store, database_factory=database)
    assert report["raw_rows"] == 32
    assert report["survey_rows"] == 8
    assert report["activated_areas"] == 0
    assert report["raw_manifest"]["reread_mismatches"] == 0
    assert report["raw_manifest"]["key"] == (
        f"raw/rent_survey/revisions/{SNAPSHOT}/2026-06.parquet"
    )
    with store.connection() as connection:
        frame = connection.read_parquet(report["raw_manifest"]["location"]).df()
    assert len(frame) == 32
    assert set(frame.original_extra) == {"preserve me"}
    for filename in ("rent-survey-evidence.json", "rent-survey-publication.json",
                     "rent-survey-report.json"):
        assert "synthetic-secret" not in (tmp_path / SNAPSHOT / filename).read_text()
    assert set(saved["surveys"].area_code) == {"61029200", "61029510"}
    assert report["scope_manifest"]["key"] == (
        f"raw/rent_survey_scope/revisions/{SNAPSHOT}/2026-06.parquet"
    )
    assert report["scope_manifest"]["reread_mismatches"] == 0
    with store.connection() as connection:
        scope_frame = connection.read_parquet(report["scope_manifest"]["location"]).df()
    evidence = json.loads(scope_frame.iloc[0].evidence_json)
    assert evidence["classification_metadata"] == metadata()
    assert evidence["intersections"] == INTERSECTIONS
    assert evidence["raw_geometry_response"] == {
        "synthetic_provider_geometry": "preserve original response"
    }
    assert all(not area["mapping_verified"] for area in evidence["areas"])


def test_failed_publication_never_opens_database(tmp_path, monkeypatch):
    module, args, store = setup_run(tmp_path, monkeypatch)
    database = Mock(side_effect=AssertionError("Must not connect before verified publication"))
    monkeypatch.setattr(module, "publish_verified", Mock(side_effect=StorageError("failed")))
    with pytest.raises(StorageError):
        run(args, store=store, database_factory=database)
    database.assert_not_called()


def test_key_gate_and_partial_table_snapshot_never_open_database(tmp_path, monkeypatch):
    module, args, store = setup_run(tmp_path, monkeypatch)
    database = Mock()
    monkeypatch.delenv("RONE_API_KEY")
    with pytest.raises(ValueError, match="RONE_API_KEY"):
        run(args, store=store, database_factory=database)
    monkeypatch.setenv("RONE_API_KEY", "synthetic-secret")
    monkeypatch.setattr(module, "collect_survey", lambda *args: source_rows().iloc[:4])
    with pytest.raises(ValueError, match="eight complete"):
        run(args, store=store, database_factory=database)
    database.assert_not_called()


def test_scope_publication_failure_after_raw_success_never_opens_database(tmp_path, monkeypatch):
    module, args, store = setup_run(tmp_path, monkeypatch)
    database = Mock()
    original = module.publish_verified
    calls = []

    def publish(store, source, *args, **kwargs):
        calls.append(source)
        if source == "rent_survey_scope":
            raise StorageError("synthetic evidence publication failure")
        return original(store, source, *args, **kwargs)

    monkeypatch.setattr(module, "publish_verified", publish)
    with pytest.raises(StorageError, match="evidence publication"):
        run(args, store=store, database_factory=database)
    assert calls == ["rent_survey", "rent_survey_scope"]
    database.assert_not_called()


def test_scope_reread_mismatch_never_opens_database(tmp_path, monkeypatch):
    module, args, store = setup_run(tmp_path, monkeypatch)
    database = Mock()
    original = module.read_published

    def reread(store, manifests):
        if "rent_survey_scope" in manifests[0]["key"]:
            return pd.DataFrame([{"evidence_json": "{}"}])
        return original(store, manifests)

    monkeypatch.setattr(module, "read_published", reread)
    with pytest.raises(ValueError, match="scope evidence differs"):
        run(args, store=store, database_factory=database)
    database.assert_not_called()
