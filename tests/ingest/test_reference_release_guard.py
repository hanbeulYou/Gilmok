from copy import deepcopy
from types import SimpleNamespace

import pytest

from ingest.reference_release_guard import validate_reference_metadata
from ingest.verify_academy_transition import rollback_probe


def release():
    snapshot = "20261016T040000Z"
    active = dict(preset_id="academy_v0", snapshot=snapshot, source_fingerprint="a" * 64)
    run = dict(snapshot=snapshot, manifest=dict(
        snapshot=snapshot, row_count=162032, source_fingerprint="a" * 64,
        preset=dict(id="academy_v0"),
    ))
    return active, run, [(snapshot, 162032)]


def test_original_noop_probe_cannot_be_frozen_as_a_release():
    active, run, rows = release()
    run.update(snapshot="20261018T091000Z", manifest={})
    with pytest.raises(ValueError, match="manifest is empty"):
        validate_reference_metadata(active, run, rows)


@pytest.mark.parametrize("field,value", [
    ("snapshot", "20261018T091000Z"), ("row_count", 162031),
    ("source_fingerprint", "b" * 64), ("preset", {"id": "other"}),
])
def test_manifest_must_describe_actual_distribution(field, value):
    active, run, rows = release()
    run["manifest"][field] = value
    with pytest.raises(ValueError):
        validate_reference_metadata(active, run, rows)


def test_mixed_reference_rows_and_stale_operational_id_are_rejected():
    active, run, rows = release()
    with pytest.raises(ValueError, match="mixed snapshot"):
        validate_reference_metadata(active, run, rows + [("20261018T091000Z", 1)])
    run["snapshot"] = "20261018T091000Z"
    with pytest.raises(ValueError, match="snapshot mismatch"):
        validate_reference_metadata(active, run, rows)


def test_canonical_metadata_passes_without_mutating_inputs():
    args = release()
    before = deepcopy(args)
    assert validate_reference_metadata(*args) == dict(
        snapshot="20261016T040000Z", rows=162032, source_fingerprint="a" * 64,
    )
    assert args == before


@pytest.mark.parametrize("host,dbname", [
    ("remote.example", "gilmok_academy_transition_probe"),
    ("127.0.0.1", "postgres"),
])
def test_release_probe_rejects_remote_or_shared_database_before_any_sql(host, dbname):
    db = SimpleNamespace(info=SimpleNamespace(host=host, dbname=dbname))
    with pytest.raises(ValueError, match="isolated loopback"):
        with rollback_probe(db):
            pytest.fail("Must reject before a transaction or SQL call")
