import json
from unittest.mock import Mock

import duckdb
import pandas as pd
import pytest
from botocore.exceptions import ClientError

from ingest.admin_boundaries import prepare_admin_boundaries
from ingest.common import RawStore, Settings, StorageError
from ingest.database import connect_database
from ingest.living_population import POPULATION_COLUMNS
from ingest.verify_population_storage import compare_profiles, read_back


def raw(tmp_path):
    return RawStore(Settings(tmp_path)).write_parquet(
        "sample", "2026-08", pd.DataFrame({"value": [1, None, 3]})
    )


@pytest.fixture(scope="module")
def spatial():
    with duckdb.connect() as connection:
        connection.execute("INSTALL spatial; LOAD spatial")


def test_local_publication_and_duckdb_readback(tmp_path):
    from pathlib import Path

    source = Path(raw(tmp_path / "source"))
    store = RawStore(Settings(tmp_path / "published"))
    report = store.publish_file("sample", "2026-08", source)
    assert report["bytes"] == source.stat().st_size
    destination = tmp_path / "readback.parquet"
    assert read_back(store, "sample", "2026-08", destination)["rows"] == 3
    with duckdb.connect() as connection:
        assert connection.read_parquet(str(destination)).fetchall() == [(1.0,), (None,), (3.0,)]


def test_r2_publish_verify_and_reuse(tmp_path, monkeypatch):
    from pathlib import Path

    source = Path(raw(tmp_path))
    store = RawStore(Settings(tmp_path / "unused", "account", "id", "secret", "bucket"))
    client = Mock()
    monkeypatch.setattr("ingest.common.boto3.client", Mock(return_value=client))
    import hashlib

    metadata = {"ContentLength": source.stat().st_size,
                "Metadata": {"sha256": hashlib.sha256(source.read_bytes()).hexdigest()}}
    missing = ClientError({"Error": {"Code": "404"}}, "HeadObject")
    client.head_object.side_effect = [missing, metadata, metadata, metadata]
    assert store.publish_file("sample", "2026-08", source)["status"] == "published"
    assert store.publish_file("sample", "2026-08", source)["status"] == "reused"
    assert client.upload_file.call_count == 1
    assert not store.settings.local_root.exists()


@pytest.mark.parametrize("failure", ["conflict", "denied", "read"])
def test_remote_failures_never_fallback_or_expose_secrets(tmp_path, monkeypatch, failure):
    from pathlib import Path

    source = Path(raw(tmp_path / "source"))
    store = RawStore(Settings(tmp_path / "unused", "account", "id", "secret", "bucket"))
    client = Mock()
    client.head_object.side_effect = RuntimeError("private-token")
    monkeypatch.setattr("ingest.common.boto3.client", Mock(return_value=client))
    if failure == "conflict":
        client.head_object.side_effect = None
        client.head_object.return_value = {"ContentLength": 0, "Metadata": {}}
    with pytest.raises(StorageError) as error:
        if failure == "read":
            monkeypatch.setattr(
                store, "connection", Mock(side_effect=RuntimeError("private-token"))
            )
            read_back(store, "sample", "2026-08", tmp_path / "readback.parquet")
        else:
            store.publish_file("sample", "2026-08", source)
    assert "private-token" not in str(error.value)
    client.upload_file.assert_not_called()
    assert not store.settings.local_root.exists()


def test_local_only_connection_rejects_remote_before_connecting(monkeypatch):
    connect = Mock()
    monkeypatch.setattr("ingest.database.psycopg.connect", connect)
    for url in ("postgresql://user:secret@remote.invalid/db",
                "postgresql://user:secret@localhost/db?hostaddr=192.0.2.1"):
        monkeypatch.setenv("SUPABASE_DB_URL", url)
        with pytest.raises(ValueError, match="local Supabase"), connect_database(local_only=True):
            pass
    connect.assert_not_called()


@pytest.mark.parametrize("failure", [None, "null", "count", "value", "missing", "duplicate"])
def test_profile_comparison_checks_values_nulls_counts_and_keys(tmp_path, failure):
    row = {"cell_id": "test", "dow_type": "weekday", "hour": 15, "sample_days": 2,
           "period_start": "2026-08-01", "period_end": "2026-08-03",
           **dict.fromkeys(POPULATION_COLUMNS, 12.0)}
    actual = row.copy()
    if failure == "null":
        actual["age_15_19"] = None
    elif failure == "count":
        actual["sample_days"] = 1
    elif failure == "value":
        actual["age_15_19"] = 13.0
    elif failure == "missing":
        actual["cell_id"] = "other"
    with duckdb.connect() as connection:
        for name, rows in (("expected", [row]), ("actual", [actual] * (2 if failure == "duplicate"
                                                                       else 1))):
            connection.register("input", pd.DataFrame(rows))
            connection.table("input").write_parquet(str(tmp_path / f"{name}.parquet"))
    args = (tmp_path / "expected.parquet", tmp_path / "actual.parquet")
    if failure:
        with pytest.raises(ValueError):
            compare_profiles(*args)
    else:
        assert compare_profiles(*args)["mismatched_rows"] == 0


@pytest.mark.parametrize("failure", [None, "code", "crs", "duplicate", "invalid"])
def test_boundary_uses_mois_code_and_rejects_unverified_geometry(tmp_path, failure, spatial):
    coordinates = [[[127, 37.5], [127.1, 37.5], [127.1, 37.6], [127, 37.6], [127, 37.5]]]
    if failure == "invalid":
        coordinates[0][1], coordinates[0][2] = coordinates[0][2], coordinates[0][1]
    feature = {"type": "Feature", "properties": {"sido": "11", "adm_cd": "11010530",
               "adm_cd2": "1111053000", "adm_nm": "서울특별시 종로구 사직동"},
               "geometry": {"type": "Polygon", "coordinates": coordinates}}
    data = {"type": "FeatureCollection", "crs": {"properties": {
        "name": "wrong" if failure == "crs" else "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": [feature] * (2 if failure == "duplicate" else 1)}
    path = tmp_path / "boundary.geojson"
    path.write_text(json.dumps(data))
    codes = {"11010530" if failure == "code" else "11110530"}
    if failure:
        with pytest.raises(ValueError):
            prepare_admin_boundaries(path, codes)
    else:
        assert prepare_admin_boundaries(path, codes).code.tolist() == ["11110530"]
