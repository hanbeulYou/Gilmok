from pathlib import Path
from unittest.mock import Mock

import duckdb
import pandas as pd
import pytest

from ingest.aggregate import aggregate
from ingest.common import R2_VARIABLES, ROOT, RawStore, Settings, StorageError, raw_key


def test_missing_or_empty_r2_configuration_uses_local_storage():
    for env in ({}, dict.fromkeys(R2_VARIABLES, "")):
        settings = Settings.from_env(env)
        assert not settings.uses_r2
        assert settings.local_root == ROOT / ".local/ingest"


@pytest.mark.parametrize("configured", R2_VARIABLES)
def test_partial_r2_configuration_fails_without_exposing_values(configured):
    with pytest.raises(ValueError, match="Incomplete R2 configuration") as error:
        Settings.from_env({configured: "private-test-value"})
    assert "private-test-value" not in str(error.value)


def test_settings_select_r2_and_hide_credentials(tmp_path):
    env = dict(zip(R2_VARIABLES, ["account", "private-id", "private-secret", "raw-bucket"]))
    env["INGEST_LOCAL_ROOT"] = str(tmp_path)
    settings = Settings.from_env(env)
    assert settings.uses_r2
    assert "private-id" not in repr(settings)
    assert "private-secret" not in repr(settings)
    assert RawStore(settings).location("sample", "2026-01") == (
        "s3://raw-bucket/raw/sample/2026-01.parquet"
    )


@pytest.mark.parametrize(
    ("source", "month"),
    [("../escape", "2026-01"), ("/tmp/escape", "2026-01"),
     ("sample", "2026-13"), ("sample", "2026-1"), ("sample", "../../escape")],
)
def test_invalid_raw_paths_are_rejected(source, month):
    with pytest.raises(ValueError):
        raw_key(source, month)


def test_symlink_cannot_escape_local_root(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "raw").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="within INGEST_LOCAL_ROOT"):
        RawStore(Settings(root)).write_parquet("sample", "2026-01", pd.DataFrame({"x": [1]}))
    assert list(outside.iterdir()) == []


def test_local_round_trip_preserves_raw_codes_and_missing_values(tmp_path):
    store = RawStore(Settings(tmp_path))
    frame = pd.DataFrame({"code": ["001", "002", "003"], "value": ["*", None, "123"]})
    path = store.write_parquet("sample", "2026-01", frame)
    with duckdb.connect() as connection:
        rows = connection.read_parquet(path).fetchall()
    assert rows == [("001", "*"), ("002", None), ("003", "123")]


def test_repeat_write_replaces_snapshot_without_duplicate_rows(tmp_path):
    store = RawStore(Settings(tmp_path))
    frame = pd.DataFrame({"code": ["001", "002"], "value": [10, 20]})
    store.write_parquet("sample", "2026-01", frame)
    path = store.write_parquet("sample", "2026-01", frame)
    with duckdb.connect() as connection:
        assert connection.read_parquet(path).count("*").fetchone() == (2,)
    assert list(Path(path).parent.iterdir()) == [Path(path)]


def test_failed_publish_keeps_previous_snapshot(tmp_path, monkeypatch):
    store = RawStore(Settings(tmp_path))
    path = store.write_parquet("sample", "2026-01", pd.DataFrame({"value": [1]}))
    monkeypatch.setattr("ingest.common.os.replace", Mock(side_effect=OSError("disk error")))
    with pytest.raises(OSError, match="disk error"):
        store.write_parquet("sample", "2026-01", pd.DataFrame({"value": [2]}))
    with duckdb.connect() as connection:
        assert connection.read_parquet(path).fetchall() == [(1,)]
    assert list(Path(path).parent.iterdir()) == [Path(path)]


def test_duckdb_reaggregates_existing_raw_without_resaving(tmp_path):
    store = RawStore(Settings(tmp_path))
    path = store.write_parquet("sample", "2026-01", pd.DataFrame({"value": [10, 20, None]}))
    original = Path(path).read_bytes()
    sql_path = tmp_path / "aggregate.sql"
    sql_path.write_text("select avg(value) as result from raw_data")
    assert aggregate(store, "sample", "2026-01", sql_path).iloc[0]["result"] == 15
    sql_path.write_text("select sum(value) as result from raw_data")
    assert aggregate(store, "sample", "2026-01", sql_path).iloc[0]["result"] == 30
    assert Path(path).read_bytes() == original


def test_r2_upload_uses_same_parquet_key_without_a_local_copy(tmp_path, monkeypatch):
    settings = Settings.from_env({
        **dict(zip(R2_VARIABLES, ["account", "id", "secret", "raw-bucket"])),
        "INGEST_LOCAL_ROOT": str(tmp_path / "unused"),
    })
    uploaded = []

    def upload(path, bucket, key):
        with duckdb.connect() as connection:
            uploaded.append((bucket, key, connection.read_parquet(path).fetchall()))

    monkeypatch.setattr("ingest.common.boto3.client", Mock(return_value=Mock(upload_file=upload)))
    RawStore(settings).write_parquet("sample", "2026-01", pd.DataFrame({"value": [1]}))
    assert uploaded == [("raw-bucket", "raw/sample/2026-01.parquet", [(1,)])]
    assert not settings.local_root.exists()


def test_r2_failure_does_not_fallback_or_leak_credentials(tmp_path, monkeypatch):
    settings = Settings.from_env({
        **dict(zip(R2_VARIABLES, ["account", "id", "private-secret", "raw-bucket"])),
        "INGEST_LOCAL_ROOT": str(tmp_path / "unused"),
    })
    client = Mock()
    client.upload_file.side_effect = RuntimeError("private-secret")
    monkeypatch.setattr("ingest.common.boto3.client", Mock(return_value=client))
    with pytest.raises(StorageError, match="local fallback was not used") as error:
        RawStore(settings).write_parquet("sample", "2026-01", pd.DataFrame({"value": [1]}))
    assert "private-secret" not in str(error.value)
    assert not settings.local_root.exists()
