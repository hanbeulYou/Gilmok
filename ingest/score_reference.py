"""S2-1 reference batch: v1.2 RPC -> shared TS raw formulas -> verified R2 -> atomic COPY."""

import argparse
import hashlib
import json
import math
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import duckdb
from psycopg import sql
from psycopg.types.json import Jsonb

from ingest.common import ROOT, RawStore, Settings
from ingest.refresh import execute_refresh, target_database
from ingest.refresh_sources import restore_object
from ingest.verify_rent import publish_verified

SOURCE = "score_reference"
RADII = (800, 1000)
SOURCES = (
    "admin_boundaries",
    "resident_population",
    "population_grid",
    "living_population",
    "subway_positions",
    "bus_positions",
    "transit_counts",
    "stores",
    "academies",
    "schools",
)
SOURCE_TABLES = (
    "academies",
    "admin_dongs",
    "living_pop",
    "population_age",
    "population_cells",
    "schools",
    "stores",
    "transit_boardings",
    "transit_stops",
)
BRIDGE = ROOT / ".local/scoring-build/ingest/score_reference_raw.js"


def source_state(db):
    all_sources = db.execute("select score_internal.sources()").fetchone()[0]
    sources = {key: all_sources[key] for key in SOURCES}
    # S1's LIMIT 1 can return either bus or subway; preserve both source versions.
    sources["transit_counts"] = db.execute(
        """select coalesce(jsonb_agg(v order by
      v::text),'[]'::jsonb) from (select distinct %s::jsonb || jsonb_build_object(
      'source',source,'source_version',source_version,'reference_date',null,
      'period_start',period_start,'period_end',period_end,'ingested_at',ingested_at)
      v from public.transit_boardings) versions""",
        (Jsonb(all_sources["transit_counts"]),),
    ).fetchone()[0]
    if not sources["transit_counts"]:
        sources["transit_counts"] = [all_sources["transit_counts"]]
    count, digest = db.execute("""select count(*),md5(string_agg(
        cell_id||':'||encode(extensions.st_asbinary(geom),'hex'), '|' order by cell_id))
        from public.population_cells where resolution_m=250""").fetchone()
    return dict(sources=sources, grid=dict(resolution_m=250, cell_count=count, geometry_md5=digest))


def sources_match(actual, expected):
    return all(
        actual[key] in expected[key] if key == "transit_counts" else actual[key] == expected[key]
        for key in SOURCES
    )


def fingerprint(state):
    return hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def collect_inputs(db, directory, *, expected_cells=10127):
    """One read-only MVCC snapshot; never enqueue addresses or alter S1 source rows."""
    started = time.monotonic()
    path = directory / "inputs.ndjson"
    durations = {radius: [] for radius in RADII}
    with db.transaction():
        db.execute("set transaction isolation level repeatable read read only")
        db.execute("set local statement_timeout='30s'")
        state = source_state(db)
        cells = db.execute("""select cell_id,extensions.st_y(p),extensions.st_x(p),
            exists(select 1 from public.admin_dongs d where extensions.st_covers(d.geom,p))
            from (select cell_id, extensions.st_transform(extensions.st_centroid(
              extensions.st_transform(geom,5179)),4326) p
              from public.population_cells where resolution_m=250) q order by cell_id""").fetchall()
        if len(cells) != expected_cells or len(cells) != state["grid"]["cell_count"]:
            raise ValueError("Grid population differs from the approved complete snapshot")
        with path.open("x") as output:
            for index, (cell_id, lat, lng, inside) in enumerate(cells, 1):
                responses = {}
                for radius in RADII:
                    tick = time.perf_counter()
                    payload = db.execute(
                        "select public.score_inputs(%s,%s,%s,2)", (lat, lng, radius)
                    ).fetchone()[0]
                    durations[radius].append((time.perf_counter() - tick) * 1000)
                    if (
                        payload["meta"]["schema_version"] != "1.2"
                        or payload["meta"]["radius_m"] != radius
                        or payload["meta"]["floor"] != 2
                    ):
                        raise ValueError("RPC input contract mismatch")
                    if not sources_match(payload["meta"]["sources"], state["sources"]):
                        raise ValueError("RPC and reference source manifest differ")
                    responses[radius] = payload
                for radius in RADII:
                    output.write(
                        json.dumps(
                            dict(
                                cell_id=cell_id,
                                inside_seoul=inside,
                                primary=responses[radius],
                                school=responses[1000],
                            ),
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
                if index % 500 == 0 or index == len(cells):
                    print(
                        json.dumps(
                            dict(
                                stage="collect",
                                cells=index,
                                calls=index * 2,
                                seconds=round(time.monotonic() - started, 3),
                            )
                        ),
                        flush=True,
                    )
    summary = {
        str(radius): dict(
            calls=len(values),
            mean_ms=sum(values) / len(values),
            p95_ms=sorted(values)[math.ceil(len(values) * 0.95) - 1],
            max_ms=max(values),
        )
        for radius, values in durations.items()
    }
    return path, [row[0] for row in cells], state, summary


def bridge(input_path, output_path, metadata_path):
    # Compile once in CLI/workflow. S2-2 imports exactly this TS module as well.
    result = subprocess.run(
        ["node", str(BRIDGE), str(input_path), str(output_path), str(metadata_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise ValueError("Shared TypeScript raw extraction failed")
    return json.loads(metadata_path.read_text())


def to_parquet(source, destination, *, inputs=False):
    columns = (
        {"cell_id": "VARCHAR", "inside_seoul": "BOOLEAN", "primary": "JSON", "school": "JSON"}
        if inputs
        else {
            "cell_id": "VARCHAR",
            "radius_m": "INTEGER",
            "axis_key": "VARCHAR",
            "raw_value": "DOUBLE",
            "notes": "VARCHAR[]",
        }
    )
    with duckdb.connect() as connection:
        connection.read_json(
            str(source), columns=columns, format="newline_delimited"
        ).write_parquet(str(destination), compression="zstd")


def export_inputs(path, destination):
    with duckdb.connect() as connection:
        # Parameter binding is used for paths, never string interpolation into SQL.
        connection.execute(
            'copy (select cell_id,inside_seoul,"primary"::json as "primary",school::json as school '
            "from read_parquet($input_file)) to $output_file (format json, array false)",
            {"input_file": str(path), "output_file": str(destination)},
        )


def validate_distribution(path, cells, metadata):
    preset, keys = metadata["preset"], metadata["keys"]
    if (
        preset["id"] != "academy_v0"
        or preset["version"] != "0.1.1"
        or preset["schema_version"] != "1.2"
    ):
        raise ValueError("Unexpected reference preset/schema")
    if preset["radii"] != list(RADII) or not keys or len(keys) != len(set(keys)):
        raise ValueError("Invalid reference dimensions")
    with duckdb.connect() as c:
        c.read_parquet(str(path)).create_view("raw")
        actual = c.execute("select cell_id,radius_m,axis_key,raw_value from raw").fetchall()
        expected = {(cell, radius, key) for cell in cells for radius in RADII for key in keys}
        seen = set()
        for cell, radius, key, value in actual:
            identity = (cell, radius, key)
            if identity in seen or identity not in expected:
                raise ValueError("Duplicate or unexpected reference row")
            seen.add(identity)
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError("Invalid reference value")
        if seen != expected:
            raise ValueError("Incomplete reference grid/radius/key matrix")
        rows = c.execute("""select radius_m,axis_key,count(*),count(raw_value),
            min(raw_value),max(raw_value) from raw group by 1,2 order by 1,2""").fetchall()
    return [
        dict(
            radius_m=r,
            axis_key=k,
            cell_count=n,
            population_size=valid,
            missing_count=n - valid,
            coverage=valid / n,
            missing_ratio=(n - valid) / n,
            min=low,
            max=high,
        )
        for r, k, n, valid, low, high in rows
    ]


def verify_replay(inputs, distribution, directory):
    """Recompute all rows from the storage readback with the same shared TS formulas."""
    replay_in, replay_out = directory / "replay-inputs.ndjson", directory / "replay-raw.ndjson"
    export_inputs(inputs, replay_in)
    bridge(replay_in, replay_out, directory / "replay-metadata.json")
    replay = directory / "replay.parquet"
    to_parquet(replay_out, replay)
    with duckdb.connect() as c:
        c.read_parquet(str(distribution)).create_view("published")
        c.read_parquet(str(replay)).create_view("recomputed")
        mismatch = c.execute("""select count(*) from (
            (select * from published except all select * from recomputed) union all
            (select * from recomputed except all select * from published))""").fetchone()[0]
    if mismatch:
        raise ValueError("Published reference does not reproduce from published inputs")
    return mismatch


def load_snapshot(db, path, manifest, *, verify_sources=True):
    """Commit values, public metadata and private manifest together inside refresh.promote."""
    if verify_sources:
        db.execute(
            sql.SQL("lock table {} in share mode nowait").format(
                sql.SQL(",").join(sql.Identifier("public", table) for table in SOURCE_TABLES)
            )
        )
        if fingerprint(source_state(db)) != manifest["source_fingerprint"]:
            raise ValueError("Sources changed after reference collection")
    preset = manifest["preset"]
    db.execute("delete from public.score_reference where preset_id=%s", (preset["id"],))
    db.execute(
        """insert into public.score_reference_sets
        (preset_id,preset_version,snapshot,computed_at,inputs_schema_version,cell_count,
         source_fingerprint,source_versions,statistics) values(%s,%s,%s,%s,%s,%s,%s,%s,%s)
        on conflict(preset_id) do update set preset_version=excluded.preset_version,
         snapshot=excluded.snapshot,computed_at=excluded.computed_at,
         inputs_schema_version=excluded.inputs_schema_version,cell_count=excluded.cell_count,
         source_fingerprint=excluded.source_fingerprint,source_versions=excluded.source_versions,
         statistics=excluded.statistics""",
        (
            preset["id"],
            preset["version"],
            manifest["snapshot"],
            manifest["computed_at"],
            preset["schema_version"],
            manifest["cell_count"],
            manifest["source_fingerprint"],
            Jsonb(manifest["source_state"]),
            Jsonb(manifest["statistics"]),
        ),
    )
    with duckdb.connect() as c, db.cursor() as cursor:
        values = c.execute(
            "select cell_id,radius_m,axis_key,raw_value from read_parquet(?)", [str(path)]
        )
        with cursor.copy("""copy public.score_reference(preset_id,preset_version,snapshot,
            radius_m,cell_id,axis_key,raw_value,computed_at,inputs_schema_version)
            from stdin""") as copy:
            while rows := values.fetchmany(4096):
                for cell, radius, key, value in rows:
                    copy.write_row(
                        (
                            preset["id"],
                            preset["version"],
                            manifest["snapshot"],
                            radius,
                            cell,
                            key,
                            value,
                            manifest["computed_at"],
                            preset["schema_version"],
                        )
                    )
    count = db.execute(
        "select count(*) from public.score_reference where preset_id=%s", (preset["id"],)
    ).fetchone()[0]
    if count != manifest["row_count"]:
        raise ValueError("COPY row count differs from verified reference")


def prepare(db, store, directory, snapshot):
    previous = db.execute(
        "select period_end,manifest from ingest_private.refresh_snapshots "
        "where source=%s and snapshot=%s",
        (SOURCE, snapshot),
    ).fetchone()
    if previous:
        old = previous[1]
        active = db.execute(
            "select snapshot from public.score_reference_sets where preset_id=%s",
            (old["preset"]["id"],),
        ).fetchone()
        if (
            not active
            or active[0] != snapshot
            or fingerprint(source_state(db)) != old["source_fingerprint"]
        ):
            raise ValueError(
                "Existing reference no longer matches current sources; use a new snapshot"
            )
        return previous[0], old, lambda connection: None
    started = time.monotonic()
    collected = collect_inputs(db, directory)
    return publish_reference(store, directory, snapshot, collected, started=started)


def publish_reference(store, directory, snapshot, collected, *, started=None):
    """Publish a completed read snapshot; promotion still rechecks the live sources."""
    started = time.monotonic() if started is None else started
    input_json, cells, state, timings = collected
    raw_json = directory / "raw.ndjson"
    metadata = bridge(input_json, raw_json, directory / "metadata.json")
    inputs, distribution = directory / "inputs.parquet", directory / "reference.parquet"
    to_parquet(input_json, inputs, inputs=True)
    to_parquet(raw_json, distribution)
    statistics = validate_distribution(distribution, cells, metadata)
    month = snapshot[:4] + "-" + snapshot[4:6]
    published = {}
    restored = {}
    for name, path in (("score_reference_inputs", inputs), ("score_reference", distribution)):
        result = publish_verified(store, name, month, path, snapshot=snapshot)
        published[name] = {k: v for k, v in result.items() if k != "location"}
        restored[name] = restore_object(
            store, result["key"], directory / ("verified-" + name + ".parquet"), result["sha256"]
        )
    if validate_distribution(restored["score_reference"], cells, metadata) != statistics:
        raise ValueError("Published reference statistics mismatch")
    verify_replay(restored["score_reference_inputs"], restored["score_reference"], directory)
    manifest = dict(
        snapshot=snapshot,
        computed_at=datetime.now(UTC).isoformat(),
        preset=metadata["preset"],
        keys=metadata["keys"],
        cell_count=len(cells),
        row_count=len(cells) * len(RADII) * len(metadata["keys"]),
        source_state=state,
        source_fingerprint=fingerprint(state),
        statistics=statistics,
        call_timings=timings,
        preparation_seconds=time.monotonic() - started,
        reread_recompute_mismatches=0,
        git_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        objects=published,
    )
    manifest_path = directory / "manifest.parquet"
    with duckdb.connect() as c:
        c.sql(
            "select ?::varchar manifest_json", params=[json.dumps(manifest, ensure_ascii=False)]
        ).write_parquet(str(manifest_path))
    saved = publish_verified(
        store, "score_reference_manifest", month, manifest_path, snapshot=snapshot
    )
    manifest["manifest_key"] = saved["key"]
    return (
        datetime.strptime(snapshot, "%Y%m%dT%H%M%SZ").date(),
        manifest,
        lambda connection: load_snapshot(connection, restored["score_reference"], manifest),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("local", "remote"), default="local")
    parser.add_argument("--snapshot", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--directory", type=Path, default=ROOT / ".local/score-reference")
    args = parser.parse_args()
    datetime.strptime(args.snapshot, "%Y%m%dT%H%M%SZ")
    if not BRIDGE.exists():
        parser.error("Run pnpm score:reference:build first")
    directory = args.directory / args.snapshot
    directory.mkdir(parents=True, exist_ok=True)
    store = RawStore(Settings.from_env())
    if args.target == "remote" and not store.settings.uses_r2:
        raise ValueError("Remote reference requires R2")
    started = time.monotonic()
    report = execute_refresh(
        SOURCE,
        args.snapshot,
        lambda: target_database(args.target),
        lambda db: prepare(db, store, directory, args.snapshot),
    )
    report["elapsed_seconds"] = time.monotonic() - started
    (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "manifest"}), flush=True)
    if report["status"] in ("refresh_failed", "maintenance_failed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
