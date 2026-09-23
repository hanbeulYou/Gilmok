import json
import subprocess

import duckdb
import pytest

from ingest.common import ROOT, RawStore, Settings
from ingest.refresh_sources import restore_object
from ingest.score_reference import (
    bridge,
    fingerprint,
    to_parquet,
    validate_distribution,
    verify_replay,
)
from ingest.verify_rent import publish_verified


def sample(radius=800):
    return dict(
        demand=dict(pop_5_9=100, pop_10_14=200, pop_15_18=300, schools=dict(elem=1, mid=2, high=3)),
        flow=dict(weekday=dict(golden_avg_pop=80), weekend=dict(golden_avg_pop=None)),
        transit=dict(nearest_subway_m=None, subway_boardings_golden=1000, bus_stops=5),
        compete=dict(academies_by_field={"입시.검정 및 보습": 10}),
        market=dict(stores_total=0),
        meta=dict(
            schema_version="1.2",
            radius_m=radius,
            floor=2,
            sources=dict(subway_positions=dict(available=True)),
        ),
    )


@pytest.fixture(scope="module", autouse=True)
def build_bridge():
    subprocess.run(["pnpm", "score:reference:build"], cwd=ROOT, capture_output=True, check=True)


def make_input(tmp_path):
    path = tmp_path / "input.ndjson"
    with path.open("w") as handle:
        for radius in (800, 1000):
            handle.write(
                json.dumps(
                    dict(
                        cell_id="fixture",
                        inside_seoul=True,
                        primary=sample(radius),
                        school=sample(1000),
                    )
                )
                + "\n"
            )
    return path


def test_storage_readback_recomputes_every_row_with_shared_typescript(tmp_path):
    incoming = make_input(tmp_path)
    output = tmp_path / "raw.ndjson"
    metadata = bridge(incoming, output, tmp_path / "metadata.json")
    inputs, raw = tmp_path / "inputs.parquet", tmp_path / "raw.parquet"
    to_parquet(incoming, inputs, inputs=True)
    to_parquet(output, raw)
    stats = validate_distribution(raw, ["fixture"], metadata)
    assert len(stats) == 2 * len(metadata["keys"])
    assert all(x["cell_count"] == 1 and x["population_size"] == 1 for x in stats)
    store = RawStore(Settings(local_root=tmp_path / "store"))
    restored = []
    for source, path in (("reference_inputs", inputs), ("reference_values", raw)):
        saved = publish_verified(store, source, "2026-09", path, snapshot="20260923T000000Z")
        restored.append(
            restore_object(
                store, saved["key"], tmp_path / (source + "-verified.parquet"), saved["sha256"]
            )
        )
    assert verify_replay(*restored, tmp_path) == 0


@pytest.mark.parametrize("damage", ["missing", "duplicate", "negative", "nonfinite"])
def test_matrix_validation_rejects_incomplete_or_invalid_distribution(tmp_path, damage):
    output = tmp_path / "raw.ndjson"
    metadata = bridge(make_input(tmp_path), output, tmp_path / "metadata.json")
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    if damage == "missing":
        rows.pop()
    elif damage == "duplicate":
        rows.append(rows[0])
    elif damage == "negative":
        rows[0]["raw_value"] = -1
    else:
        rows[0]["raw_value"] = float("inf")
    path = tmp_path / "damaged.parquet"
    import pandas as pd

    with duckdb.connect() as c:
        c.register("incoming", pd.DataFrame(rows))
        c.table("incoming").write_parquet(str(path))
    with pytest.raises(ValueError):
        validate_distribution(path, ["fixture"], metadata)


def test_explicit_null_is_preserved_in_population_and_coverage(tmp_path):
    path = make_input(tmp_path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        row["primary"]["demand"]["pop_15_18"] = None
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    output = tmp_path / "raw.ndjson"
    metadata = bridge(path, output, tmp_path / "metadata.json")
    raw = tmp_path / "raw.parquet"
    to_parquet(output, raw)
    stats = validate_distribution(raw, ["fixture"], metadata)
    assert all(
        r["population_size"] == 0 and r["coverage"] == 0 for r in stats if r["axis_key"] == "demand"
    )


def test_fingerprint_ignores_mapping_order_but_not_source_revision():
    assert fingerprint(dict(a=1, b=2)) == fingerprint(dict(b=2, a=1))
    assert fingerprint(dict(a=1)) != fingerprint(dict(a=2))


def test_prepare_publishes_manifest_only_after_complete_replay(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from ingest.score_reference import prepare
    from ingest.seoul_transit import read_frame

    path = make_input(tmp_path)
    monkeypatch.setattr(
        "ingest.score_reference.collect_inputs",
        lambda db, directory: (path, ["fixture"], dict(sources={}, grid=dict(cell_count=1)), {}),
    )
    db = Mock()
    db.execute.return_value.fetchone.return_value = None
    store = RawStore(Settings(local_root=tmp_path / "store"))
    period, manifest, loader = prepare(db, store, tmp_path, "20260923T000000Z")
    assert str(period) == "2026-09-23"
    assert manifest["row_count"] == len(manifest["keys"]) * 2
    assert manifest["reread_recompute_mismatches"] == 0
    assert callable(loader)
    saved = read_frame(store.settings.local_root / manifest["manifest_key"])
    assert (
        json.loads(saved.manifest_json.iloc[0])["source_fingerprint"]
        == manifest["source_fingerprint"]
    )


def test_successful_snapshot_retry_does_not_recollect(tmp_path, monkeypatch):
    from datetime import date
    from unittest.mock import Mock

    from ingest.score_reference import prepare

    state = dict(sources={}, grid=dict(cell_count=1))
    old = dict(preset=dict(id="academy_v0"), source_fingerprint=fingerprint(state))
    db = Mock()
    db.execute.return_value.fetchone.side_effect = [(date(2026, 9, 23), old), ("20260923T000000Z",)]
    monkeypatch.setattr("ingest.score_reference.source_state", lambda db: state)
    collector = Mock(side_effect=AssertionError("must not collect"))
    monkeypatch.setattr("ingest.score_reference.collect_inputs", collector)
    assert prepare(db, None, tmp_path, "20260923T000000Z")[:2] == (date(2026, 9, 23), old)
    collector.assert_not_called()


def test_transit_metadata_accepts_either_verified_source_but_not_other_versions():
    from ingest.score_reference import SOURCES, sources_match

    base = {key: {"source": key} for key in SOURCES}
    expected = dict(
        base,
        transit_counts=[
            {"source": "bus", "source_version": "2026-08"},
            {"source": "subway", "source_version": "2026-08"},
        ],
    )
    for source in expected["transit_counts"]:
        assert sources_match(dict(base, transit_counts=source), expected)
    assert not sources_match(
        dict(
            base,
            transit_counts={
                "source": "bus",
                "source_version": "2026-07",
            },
        ),
        expected,
    )
