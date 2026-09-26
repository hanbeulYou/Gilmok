import json

import pandas as pd
import pytest

from ingest.common import RawStore, Settings
from ingest.living_population import POPULATION_COLUMNS
from ingest.restore_manifest import cached_object, selected, sha256
from ingest.restore_provenance import verify_living_profile
from ingest.restore_remote import run
from ingest.verify_remote import comparison_payload


def test_manifest_excludes_user_addresses_and_old_reference():
    assert not selected("raw/address_building_1168010600109120013/2026-09.parquet")
    assert not selected("raw/score_reference/revisions/20260923T101705Z/2026-09.parquet")
    assert selected("raw/score_reference/revisions/20260923T111436Z/2026-09.parquet")
    assert not selected("raw/academies/../2026-09.parquet")


def test_download_rejects_changed_original_and_keeps_verified_cache(tmp_path):
    raw = tmp_path / "original/raw/stores/2026-06.parquet"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"original")
    store = RawStore(Settings(local_root=tmp_path / "original"))
    entry = dict(key="raw/stores/2026-06.parquet", sha256=sha256(raw))
    cache = tmp_path / "cache"
    path = cached_object(store, entry, cache)
    raw.write_bytes(b"changed upstream")
    assert cached_object(store, entry, cache).read_bytes() == b"original"
    path.write_bytes(b"corrupted cache")
    with pytest.raises(ValueError, match="checksum"):
        cached_object(store, entry, cache)
    assert path.read_bytes() == b"corrupted cache"  # Never promote unverified bytes.


def test_remote_restore_requires_exact_reviewed_manifest_before_network(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(dict(version=1)))
    with pytest.raises(ValueError, match="approved manifest"):
        run(manifest, tmp_path, "remote", "different")


@pytest.mark.parametrize("key", ["../outside", "raw/../../outside", "raw\\outside"])
def test_cache_path_cannot_escape_directory(tmp_path, key):
    with pytest.raises(ValueError, match="object key"):
        cached_object(RawStore(Settings(local_root=tmp_path)),
                      dict(key=key, sha256="0" * 64), tmp_path / "cache")


def test_living_replay_preserves_nulls_and_rejects_material_value_changes():
    row = dict(cell_id="fixture", dow_type="weekday", hour=1, sample_days=30,
               period_start="2026-06-01", period_end="2026-08-31")
    row.update({name: 10.0 for name in POPULATION_COLUMNS})
    row["age_0_4"] = None
    expected = pd.DataFrame([row])
    actual = expected.copy()
    actual.loc[0, "total"] += 1e-11
    assert verify_living_profile(actual, expected)["rows"] == 1
    actual.loc[0, "total"] += 0.01
    with pytest.raises(ValueError, match="values differ"):
        verify_living_profile(actual, expected)
    actual = expected.copy()
    actual.loc[0, "age_0_4"] = 0
    with pytest.raises(ValueError, match="NULL mask"):
        verify_living_profile(actual, expected)


def test_rpc_comparison_only_normalizes_the_known_two_source_metadata_choice():
    def payload(source, value=10):
        return dict(transit=dict(boardings=value), meta=dict(sources=dict(
            transit_counts=dict(source=source, source_version="2026-06/2026-08"))))

    bus = payload("seoul_bus_boardings")
    subway = payload("seoul_subway_boardings")
    assert comparison_payload(bus) == comparison_payload(subway)
    assert bus["meta"]["sources"]["transit_counts"]["source"] == "seoul_bus_boardings"
    assert comparison_payload(bus) != comparison_payload(payload("seoul_subway_boardings", 11))
    with pytest.raises(ValueError, match="Unexpected transit"):
        comparison_payload(payload("different_source"))
