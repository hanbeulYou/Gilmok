"""Reproduce source proofs, coverage, R2 rereads, and local transit loading."""

import argparse
import calendar
import hashlib
import json
import math
import time
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from ingest import bus, subway
from ingest.common import ROOT, RawStore, Settings
from ingest.database import connect_database
from ingest.seoul_transit import download, hourly_values, read_frame, write_frame
from ingest.transit_database import load_snapshot, seoul_stops

MONTHS = ("2026-06", "2026-07", "2026-08")
SOURCES = {"subway": (subway, "CardSubwayTime", "subwayStationMaster"),
           "bus": (bus, "CardBusTimeNew", "busStopLocationXyInfo")}
MEASURES = [f"{direction}_{hour}" for direction in ("boarding", "alighting")
            for hour in range(24)]


class CoverageAlert(ValueError):
    """The user must be informed before ingestion continues below 90% coverage."""


def coverage(raw, normalized, scoped_ids: set[str]) -> dict:
    matched = normalized.stop_id.notna()
    seoul = normalized.stop_id.isin(scoped_ids)
    volume = normalized[MEASURES].sum(axis=1, min_count=len(MEASURES))
    # Unknown counts make volume coverage unknown; never quietly exclude them.
    total = float(volume.sum()) if volume.notna().all() else None
    matched_volume = float(volume[matched].sum()) if total is not None else None
    rate = matched_volume / total if total else None
    unmatched = normalized.loc[~matched, ["source_id"]].copy()
    unmatched["passengers"] = volume[~matched]
    unmatched = unmatched.groupby("source_id", as_index=False).passengers.sum(min_count=1)
    label = "SBWY_STNS_NM" if "SBWY_STNS_NM" in normalized else "STTN"
    names = normalized.groupby("source_id")[label].agg(
        lambda values: " | ".join(sorted(set(values))))
    unmatched["names"] = unmatched.source_id.map(names)
    unmatched["reason"] = "no unambiguous ID or same-line normalized-name coordinate match"
    identity_rate = normalized.loc[matched, "source_id"].nunique() / normalized.source_id.nunique()
    return {
        "raw_rows": len(raw), "exact_duplicate_rows": len(raw) - len(raw.drop_duplicates()),
        "distinct_rows": len(normalized), "unique_ids": normalized.source_id.nunique(),
        "matched_rows": int(matched.sum()), "matched_ids": normalized.loc[
            matched, "source_id"].nunique(),
        "row_join_rate": float(matched.mean()), "id_join_rate": identity_rate,
        "passengers": total, "matched_passengers": matched_volume,
        "passenger_join_rate": rate, "missing_count_rows": int(volume.isna().sum()),
        "seoul_matched_rows": int(seoul.sum()),
        "seoul_matched_passengers": float(volume[seoul].sum()),
        "matched_outside_seoul_rows": int((matched & ~seoul).sum()),
        "unlocated_rows": int((~matched).sum()),
        # Unlocated IDs cannot honestly be classified as Seoul or outside Seoul.
        "unmatched": unmatched.astype(object).where(unmatched.notna(), None).to_dict("records"),
        "denominator": "all distinct source observations before geographic exclusion",
    }


def require_coverage(report: dict) -> None:
    rate = report["passenger_join_rate"]
    if rate is None or rate < 0.9:
        raise CoverageAlert("Passenger join rate below 90% or unknown; report before continuing")


def aggregate_months(frames: list[pd.DataFrame], months=MONTHS) -> pd.DataFrame:
    if len(months) != 3 or len(set(months)) != 3:
        raise ValueError("Exactly three distinct months are required")
    dates = [date.fromisoformat(month + "-01") for month in months]
    if any(b.year * 12 + b.month != a.year * 12 + a.month + 1
           for a, b in zip(dates, dates[1:])):
        raise ValueError("Expected consecutive months in chronological order")
    incoming = pd.concat([frame[["stop_id", "month", *MEASURES]] for frame in frames],
                         ignore_index=True)
    if set(incoming.month) != set(months):
        raise ValueError("Snapshot months differ from requested period")
    days = sum(calendar.monthrange(d.year, d.month)[1] for d in dates)
    with duckdb.connect(config={"memory_limit": "512MB"}) as connection:
        connection.register("normalized", incoming)
        return connection.execute((ROOT / "ingest/sql/transit.sql").read_text(),
                                  {"period_days": days}).df()


def prove_first_month(directory: Path) -> dict:
    """Cross-check 30 daily totals with hourly monthly totals, including repeated stops."""
    results = {}
    for kind, route in (("subway", ""), ("bus", "100"), ("bus", "5511")):
        service = "CardSubwayStatsNew" if kind == "subway" else "CardBusStatisticsServiceNew"
        paths = [download(service, f"202606{day:02d}" + (f"/{route}" if route else ""),
                          directory) for day in range(1, 31)]
        daily = pd.concat([read_frame(path) for path in paths], ignore_index=True)
        if set(daily.USE_YMD) != {f"202606{day:02d}" for day in range(1, 31)}:
            raise ValueError("Daily proof does not cover all June dates")
        monthly = read_frame(directory / f"{SOURCES[kind][1]}-202606.parquet")
        if route:
            monthly = monthly[monthly.RTE_NO == route].reset_index(drop=True)
        values = hourly_values(monthly)
        keys = ["SBWY_ROUT_LN_NM", "STTN"] if kind == "subway" else ["STOPS_ID"]
        if kind == "subway":
            daily = daily.rename(columns={"SBWY_STNS_NM": "STTN"})
        result = {"days": 30, "daily_rows": len(daily), "monthly_rows": len(monthly)}
        for measure, source in (("boarding", "GTON_TNOPE"), ("alighting", "GTOFF_TNOPE")):
            totals = monthly[keys].copy()
            totals["value"] = values[[f"{measure}_{hour}" for hour in range(24)]].sum(
                axis=1, min_count=24)
            daily[source] = pd.to_numeric(daily[source], errors="raise")
            comparison = totals.groupby(keys).value.sum(min_count=1).to_frame().join(
                daily.groupby(keys)[source].sum(min_count=1), how="outer")
            # Monthly zero-only rows may be absent from the daily API; nonzero cannot.
            mismatch = comparison.value.fillna(0) != comparison[source].fillna(0)
            if mismatch.any():
                raise ValueError(f"Daily/monthly mismatch: {kind} {route} {measure}")
            result[measure] = float(comparison.value.sum())
            result[f"{measure}_mismatches"] = int(mismatch.sum())
        results[kind + route] = result
    return results


def publish_verified(store: RawStore, source: str, month: str, path: Path) -> dict:
    result = store.publish_file(source, month, path)
    # Read actual selected storage, not the input file, and compare duplicate multiplicity too.
    with store.connection() as connection:
        connection.read_parquet(str(path)).create_view("original")
        connection.read_parquet(store.location(source, month)).create_view("published")
        mismatch = connection.execute(
            "select count(*) from ((select * from original except all select * from published) "
            "union all (select * from published except all select * from original))"
        ).fetchone()[0]
        if mismatch:
            raise ValueError("Published transit snapshot differs from input")
        result["rows"] = connection.execute("select count(*) from published").fetchone()[0]
        result["reread_mismatches"] = mismatch
    return result


def measure_queries(connection) -> dict:
    query = (ROOT / "ingest/sql/transit_radius.sql").read_text()
    coordinates = connection.execute(
        "select s.name,extensions.st_x(s.geom),extensions.st_y(s.geom) "
        "from public.transit_stops s where s.name in ('대치','한티','학여울') "
        "and exists(select 1 from public.admin_dongs d where d.name like '%%대치%%' "
        "and extensions.st_covers(d.geom,s.geom)) order by s.name"
    ).fetchall()
    if len(coordinates) != 3:
        raise ValueError("Expected three verified Daechi coordinates")
    output = {"db": connection.execute("select version()").fetchone()[0],
              "postgis": connection.execute(
                  "select extensions.postgis_full_version()").fetchone()[0],
              "warmups": 3, "repeats": 30, "http_ms": None,
              "limitation": "Transit SQL only; score_inputs RPC and HTTP not implemented",
              "measurements": []}
    for name, lng, lat in coordinates:
        for radius in (500, 1000):
            args = (lng, lat, radius)
            for _ in range(output["warmups"]):
                connection.execute(query, args).fetchall()
            db_times, wall_times = [], []
            for _ in range(output["repeats"]):
                start = time.perf_counter()
                plan = connection.execute(
                    "explain (analyze,format json) " + query, args).fetchone()[0]
                wall_times.append((time.perf_counter() - start) * 1000)
                db_times.append(plan[0]["Execution Time"])
            cursor = connection.execute(query, args)
            values = dict(zip([col.name for col in cursor.description], cursor.fetchone()))
            output["measurements"].append({
                "name": name, "lat": lat, "lng": lng, "radius_m": radius,
                "db_p95_ms": sorted(db_times)[math.ceil(len(db_times) * .95) - 1],
                "db_roundtrip_p95_ms": sorted(wall_times)[math.ceil(len(wall_times) * .95) - 1],
                "result": values,
            })
    output["bytes"] = dict(connection.execute(
        "select 'database',pg_database_size(current_database()) union all "
        "select 'transit_stops',pg_total_relation_size('public.transit_stops') union all "
        "select 'transit_boardings',pg_total_relation_size('public.transit_boardings')"
    ).fetchall())
    return output


def run(directory: Path, *, load: bool = False) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    report = {"period_start": "2026-06-01", "period_end": "2026-08-31",
              "days": 92, "unit": "persons_per_day", "sources": {}}
    masters, scoped, paths = {}, {}, {}
    with connect_database(local_only=True) as database:
        for kind, (adapter, _, master_service) in SOURCES.items():
            path = download(master_service, "", directory)
            paths[f"{kind}_stops"] = path
            masters[kind] = adapter.stops(read_frame(path))
            scoped[kind] = seoul_stops(database, masters[kind])
    frames = {kind: [] for kind in SOURCES}
    for month in MONTHS:
        for kind, (adapter, service, _) in SOURCES.items():
            path = download(service, month.replace("-", ""), directory)
            paths[f"{kind}_{month}"] = path
            raw = read_frame(path)
            normalized = adapter.normalize(raw, masters[kind], month)
            quality = coverage(raw, normalized, set(scoped[kind].stop_id))
            report["sources"].setdefault(kind, {})[month] = quality
            (directory / "coverage.json").write_text(json.dumps(report, ensure_ascii=False,
                                                                indent=2, allow_nan=False))
            missing = [{"source": source, "month": period, **row}
                       for source, months in report["sources"].items()
                       for period, value in months.items() for row in value["unmatched"]]
            pd.DataFrame(missing).to_csv(directory / "unmatched.csv", index=False)
            require_coverage(quality)
            frames[kind].append(normalized)
        if month == MONTHS[0]:
            report["first_month_proof"] = prove_first_month(directory)
    aggregates = {kind: aggregate_months(frames[kind]) for kind in SOURCES}
    report["unobserved_coordinate_units"] = {
        kind: scoped[kind].loc[~scoped[kind].stop_id.isin(set(aggregates[kind].stop_id)),
                               ["stop_id", "name", "line"]].to_dict("records")
        for kind in SOURCES
    }
    report["coordinate_snapshot"] = {
        "retrieved_on": "2026-09-19", "historical_positions_verified": False,
        "scope": "427 validated Seoul dong polygons; unlocated IDs remain unclassified",
        "counts": {kind: {"all": len(masters[kind]), "seoul": len(scoped[kind])}
                   for kind in SOURCES},
    }
    report["missing_lines"] = ["신분당선: 승하차 미제공; 대체 추정 없음"]
    report["count_semantics"] = "boarding/alighting events; not unique people or transfers"
    report["storage"] = []
    if load:
        store = RawStore(Settings.from_env())
        for kind in SOURCES:
            report["storage"].append(publish_verified(
                store, f"{kind}_stops", "2026-09", paths[f"{kind}_stops"]))
            remote_frames = []
            for month in MONTHS:
                report["storage"].append(publish_verified(
                    store, f"{kind}_boardings", month, paths[f"{kind}_{month}"]))
                with store.connection() as connection:
                    raw = connection.read_parquet(store.location(f"{kind}_boardings", month)).df()
                    master_raw = connection.read_parquet(
                        store.location(f"{kind}_stops", "2026-09")).df()
                adapter = SOURCES[kind][0]
                remote_frames.append(adapter.normalize(raw, adapter.stops(master_raw), month))
            reread = aggregate_months(remote_frames)
            pd.testing.assert_frame_equal(aggregates[kind], reread)
            aggregates[kind] = reread
        all_stops = pd.concat(list(scoped.values()), ignore_index=True)
        all_counts = pd.concat(list(aggregates.values()), ignore_index=True)
        all_counts = all_counts[all_counts.stop_id.isin(set(all_stops.stop_id))]
        reports = {kind: {"months": report["sources"][kind],
                          "coordinates": report["coordinate_snapshot"],
                          "missing_lines": report["missing_lines"] if kind == "subway" else [],
                          "unobserved_coordinate_units": report[
                              "unobserved_coordinate_units"][kind],
                          "unit": report["unit"], "days": 92} for kind in SOURCES}
        with connect_database(local_only=True) as database:
            report["loaded"] = load_snapshot(database, all_stops, all_counts, reports,
                                              start="2026-06-01", end="2026-08-31",
                                              coordinate_version="2026-09-19")
            database.execute("analyze public.transit_stops")
            database.execute("analyze public.transit_boardings")
            report["queries"] = measure_queries(database)
        write_frame(all_counts, directory / "aggregated.parquet")
    report["sha256"] = {name: hashlib.sha256(path.read_bytes()).hexdigest()
                        for name, path in paths.items()}
    (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False,
                                                      indent=2, allow_nan=False))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / ".local/validation/pr3")
    parser.add_argument("--load", action="store_true", help="Publish and load local Supabase")
    args = parser.parse_args()
    result = run(args.directory, load=args.load)
    print(json.dumps({"loaded": result.get("loaded"),
                      "report": str(args.directory / "report.json")}, ensure_ascii=False))
