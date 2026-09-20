from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from ingest.common import RawStore, Settings, StorageError
from ingest.seoul_transit import write_frame
from ingest.verify_rent import assert_trade_contract, publish_verified, read_published, run_trades


def store_at(path):
    return RawStore(Settings(local_root=path))


def test_published_provider_decimal_does_not_round_through_float(tmp_path):
    value = Decimal("52.461579869605234567")
    path = tmp_path / "provider.parquet"
    write_frame(pd.DataFrame({"DTA_VAL": [value]}), path)
    store = store_at(tmp_path / "storage")
    manifest = publish_verified(store, "rent_survey", "2026-06", path)
    reread = read_published(store, [manifest])
    assert reread.iloc[0].DTA_VAL == value
    assert isinstance(reread.iloc[0].DTA_VAL, Decimal)


def test_revision_immutability_and_duplicate_bag_reread(tmp_path):
    store = store_at(tmp_path / "storage")
    path = tmp_path / "raw.parquet"
    frame = pd.DataFrame({"raw": ["same", "same", "other"], "page": [1, 1, 2]})
    write_frame(frame, path)
    manifest = publish_verified(
        store, "commercial_trades", "2024-09", path, snapshot="20260920T120000Z"
    )
    assert manifest["rows"] == 3
    assert manifest["reread_mismatches"] == 0
    assert "/revisions/20260920T120000Z/" in manifest["key"]
    pd.testing.assert_frame_equal(read_published(store, [manifest]), frame)
    publish_verified(store, "commercial_trades", "2024-09", path, snapshot="20260920T120000Z")
    write_frame(frame.iloc[:1], path)
    with pytest.raises(StorageError):
        publish_verified(store, "commercial_trades", "2024-09", path, snapshot="20260920T120000Z")


def test_original_requires_explicit_revision(tmp_path):
    store = store_at(tmp_path / "storage")
    path = tmp_path / "raw.parquet"
    write_frame(pd.DataFrame({"value": [1]}), path)
    manifest = publish_verified(store, "commercial_trades", "2024-09", path)
    write_frame(pd.DataFrame({"value": [2]}), path)
    with pytest.raises(StorageError, match="revision"):
        publish_verified(store, "commercial_trades", "2024-09", path)
    assert read_published(store, [manifest]).iloc[0].value == 1


def test_bag_comparison_detects_removed_duplicate(tmp_path):
    store = store_at(tmp_path / "storage")
    path = tmp_path / "raw.parquet"
    write_frame(pd.DataFrame({"value": [1, 1, 2]}), path)
    original = store.publish_file

    def corrupt(source, month, local_path):
        manifest = original(source, month, local_path)
        write_frame(pd.DataFrame({"value": [1, 2]}), Path(store.location(source, month)))
        return manifest

    store.publish_file = corrupt
    with pytest.raises(ValueError, match="differs"):
        publish_verified(store, "commercial_trades", "2024-09", path)


def test_publication_failure_prevents_database_access(tmp_path, monkeypatch):
    import ingest.verify_rent as module

    monkeypatch.setattr(module, "prepare_legal_boundaries", lambda *a, **kw: pd.DataFrame())
    monkeypatch.setattr(
        module,
        "collect_months",
        lambda *a: pd.DataFrame(
            {"request_month": ["202409"], "request_page": [1], "request_row": [1], "raw": ["x"]}
        ),
    )

    def fail(*args, **kwargs):
        raise StorageError("publication failed")

    monkeypatch.setattr(module, "publish_verified", fail)
    args = SimpleNamespace(
        snapshot="20260920T120000Z",
        directory=tmp_path,
        start_month="202409",
        end_month="202409",
        revision=False,
    )
    with pytest.raises(StorageError):
        run_trades(
            args,
            store=store_at(tmp_path / "storage"),
            database_factory=lambda: pytest.fail("database accessed before proof"),
        )


def payload(count=7, median=10):
    return {
        "meta": {"legal_dong_code": "11680106"},
        "trade_by_building_type": [
            {"trade_kind": "general", "sample_count": 5},
            {"trade_kind": "collective", "sample_count": count},
        ],
        "trade_building_type": "collective",
        "trade_sample_count": count,
        "trade_median_per_m2": median,
        "rent_level": None,
    }


def test_contract_rejects_smaller_default_and_under_five_value():
    assert_trade_contract(payload())
    invalid = payload()
    invalid["trade_building_type"] = "general"
    with pytest.raises(ValueError, match="largest"):
        assert_trade_contract(invalid)
    invalid = payload(4)
    invalid["trade_by_building_type"] = [{"trade_kind": "collective", "sample_count": 4}]
    with pytest.raises(ValueError, match="Under-five"):
        assert_trade_contract(invalid)
    invalid["trade_median_per_m2"] = None
    assert_trade_contract(invalid)
