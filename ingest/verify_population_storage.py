"""Read published raw Parquet through DuckDB and compare a complete living profile."""

import argparse
import json
import tempfile
from datetime import date
from pathlib import Path

import duckdb

from ingest.common import RawStore, Settings, StorageError
from ingest.living_population import POPULATION_COLUMNS, aggregate_window


def read_back(store: RawStore, source: str, month: str, destination: Path) -> dict:
    """Materialize the selected backend only; remote failures never use local raw data."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        candidate = Path(temporary) / "readback.parquet"
        try:
            with store.connection(config={"memory_limit": "1GB", "threads": 2,
                                          "temp_directory": temporary}) as connection:
                connection.read_parquet(store.location(source, month)).write_parquet(
                    str(candidate), compression="zstd"
                )
                rows = connection.read_parquet(str(candidate)).count("*").fetchone()[0]
        except Exception:
            raise StorageError("Parquet readback failed; no alternate backend was used") from None
        candidate.replace(destination)
    return {"source": source, "month": month, "rows": rows,
            "backend": "r2" if store.settings.uses_r2 else "local"}


def compare_profiles(expected: Path, actual: Path) -> dict:
    """Compare every key, NULL, count, period, and population with float tolerance."""
    keys = "cell_id,dow_type,hour"
    with duckdb.connect(config={"memory_limit": "512MB", "threads": 2}) as connection:
        for name, path in (("expected", expected), ("actual", actual)):
            connection.read_parquet(str(path)).create_view(name)
            duplicates = connection.execute(
                f"select count(*) from (select {keys} from {name} "
                "group by all having count(*)>1)"
            ).fetchone()[0]
            if duplicates:
                raise ValueError("Profile contains duplicate keys")
        mismatches = ["e.cell_id is null", "a.cell_id is null"]
        for column in ["sample_days", "period_start", "period_end"]:
            mismatches.append(f"e.{column} is distinct from a.{column}")
        for column in POPULATION_COLUMNS:
            mismatches.extend([
                f"(e.{column} is null) <> (a.{column} is null)",
                f"abs(e.{column}-a.{column}) > 1e-8 + 1e-10*abs(e.{column})",
            ])
        rows, different, maximum = connection.execute(
            "select count(*), count(*) filter(where " + " or ".join(mismatches) + "), "
            "max(greatest(" + ",".join(
                f"abs(e.{column}-a.{column})" for column in POPULATION_COLUMNS
            ) + f")) from expected e full join actual a using({keys})"
        ).fetchone()
    report = {"rows_compared": rows, "mismatched_rows": different,
              "max_absolute_difference": maximum, "absolute_tolerance": 1e-8,
              "relative_tolerance": 1e-10}
    if not rows or different:
        raise ValueError(f"Population profiles differ: {report}")
    return report


def verify_window(store: RawStore, months: list[str], start: date, end: date,
                  expected: Path, directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    paths, reports = [], []
    for month in months:
        path = directory / f"{month}.parquet"
        reports.append(read_back(store, "living_population", month, path))
        paths.append(path)
        print(json.dumps(reports[-1]), flush=True)
    actual = directory / "profile.parquet"
    aggregation = aggregate_window(paths, start, end, actual)
    report = {"readbacks": reports, "aggregation": aggregation,
              "comparison": compare_profiles(expected, actual)}
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", nargs="+", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify_window(RawStore(Settings.from_env()), args.months,
                                  args.start, args.end, args.expected, args.directory), indent=2))
