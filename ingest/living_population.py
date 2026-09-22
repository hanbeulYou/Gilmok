"""Local preparation and audit of Seoul OA-22784 monthly CSV archives.

No API requests: archive downloads and cloud publication are separate operations.
Raw Parquet retains the provider's columns, including suppressed values and dong splits.
"""

import calendar
import csv
import io
import json
import re
import shutil
import tempfile
from datetime import date, timedelta
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

import duckdb

AGE_BANDS = ["0~9세", *[f"{age}~{age + 4}세" for age in range(10, 70, 5)], "70세 이상"]
COLUMNS = ["일자", "시간", "행정동코드", "250M격자", "생활인구합계"] + [
    f"{sex} {age}" for sex in ("남자", "여자") for age in AGE_BANDS
]
SQL_PATH = Path(__file__).parent / "sql/living_population.sql"
COARSE_BANDS = {
    "age_10_14": ["10~14세"],
    "age_15_19": ["15~19세"],
    "age_20_29": ["20~24세", "25~29세"],
    "age_30_39": ["30~34세", "35~39세"],
    "age_40_49": ["40~44세", "45~49세"],
    "age_50_59": ["50~54세", "55~59세"],
    "age_60_plus": ["60~64세", "65~69세", "70세 이상"],
}
POPULATION_COLUMNS = ["total", "age_0_4", "age_5_9", *COARSE_BANDS]


def prepare_month(archive: Path, month: str, destination: Path) -> dict:
    """Validate a complete monthly archive and atomically write its raw Parquet."""
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("Month must use YYYY-MM")
    year, number = map(int, month.split("-"))
    days = calendar.monthrange(year, number)[1]
    expected = {f"250_LOCAL_RESD_{year}{number:02}{day:02}.csv" for day in range(1, days + 1)}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        directory = Path(temporary)
        with ZipFile(archive) as bundle:
            folder = f"250_LOCAL_RESD_{year}{number:02}/"
            names = [name for name in bundle.namelist() if name != folder]
            basenames = [PurePosixPath(name).name for name in names]
            if (len(names) != len(expected) or set(basenames) != expected
                    or any(name not in {base, folder + base}
                           for name, base in zip(names, basenames))):
                raise ValueError("Archive must contain exactly one CSV per day of the month")
            for name in sorted(names):
                with bundle.open(name) as raw, io.TextIOWrapper(raw, encoding="cp949") as source:
                    header = source.readline()
                    if next(csv.reader([header])) != COLUMNS:
                        raise ValueError("Unverified living population CSV columns")
                    with (directory / PurePosixPath(name).name).open(
                        "w", encoding="utf-8", newline=""
                    ) as output:
                        output.write(header)
                        shutil.copyfileobj(source, output)
        with duckdb.connect(config={"memory_limit": "512MB", "threads": 2}) as connection:
            connection.read_csv(str(directory / "*.csv"), all_varchar=True).create_view("raw")
            report = validate_rows(connection, month)
            connection.table("raw").write_parquet(
                str(directory / "raw.parquet"), compression="zstd"
            )
        (directory / "raw.parquet").replace(destination)
    return {**report, "month": month, "parquet_bytes": destination.stat().st_size}


def validate_rows(connection: duckdb.DuckDBPyConnection, month: str) -> dict:
    """Validate raw records before any aggregation; do not guess changed schemas."""
    numeric_columns = ["생활인구합계", *COLUMNS[5:]]
    predicates = [
        f"(\"{name}\" IS NULL OR NOT regexp_full_match(trim(\"{name}\"), "
        "'[0-9]+(\\.[0-9]*)?|\\*'))" for name in numeric_columns
    ]
    invalid = connection.execute(
        'select count(*) from raw where '
        'try_strptime("일자", \'%Y%m%d\') IS NULL '
        'or strftime(try_strptime("일자", \'%Y%m%d\'), \'%Y-%m\') <> ? '
        'or NOT regexp_full_match("시간", \'[01][0-9]|2[0-3]\') '
        'or "시간" IS NULL or "행정동코드" IS NULL or "250M격자" IS NULL '
        'or NOT regexp_full_match(trim("행정동코드"), \'11[0-9]{6}\') '
        'or trim("250M격자") = \'\' or ' + " or ".join(predicates), [month]
    ).fetchone()[0]
    if invalid:
        raise ValueError(f"Invalid source rows: {invalid}")
    duplicates = connection.execute(
        'select count(*) from (select "일자", "시간", trim("행정동코드"), trim("250M격자") '
        'from raw group by all having count(*) > 1)'
    ).fetchone()[0]
    if duplicates:
        raise ValueError(f"Duplicate date/hour/dong/cell keys: {duplicates}")
    rows, cells, dates, hours = connection.execute(
        'select count(*), count(distinct trim("250M격자")), '
        'count(distinct "일자"), count(distinct "시간") from raw'
    ).fetchone()
    year, number = map(int, month.split("-"))
    if dates != calendar.monthrange(year, number)[1] or hours != 24:
        raise ValueError("Source is missing dates or hours")
    return {"rows": rows, "cells": cells, "dates": dates, "hours": hours}


def audit_grid(parquets: list[Path], shapefile: Path) -> dict:
    """Measure matching and source granularity; this function does not invent boundaries."""
    with duckdb.connect(config={"memory_limit": "512MB", "threads": 2}) as connection:
        connection.execute("LOAD spatial")
        connection.execute("create table grid as select * from ST_Read(?)", [str(shapefile)])
        connection.read_parquet([str(path) for path in parquets]).create_view("raw")
        boundary_count, distinct_count, min_area, max_area = connection.execute(
            "select count(*), count(distinct CELL_ID), min(ST_Area(geom)), "
            "max(ST_Area(geom)) from grid"
        ).fetchone()
        if boundary_count != distinct_count or min_area != 62500 or max_area != 62500:
            raise ValueError("Grid IDs must be unique 250m square boundaries")
        cells, rows, first, last = connection.execute(
            'select count(distinct trim("250M격자")),count(*),min("일자"),max("일자") from raw'
        ).fetchone()
        missing = connection.execute(
            'select distinct trim("250M격자") as cell_id from raw '
            'except select CELL_ID from grid order by cell_id'
        ).fetchall()
        splits = connection.execute(
            'select count(*) from (select "일자","시간",trim("250M격자") '
            'from raw group by all having count(*)>1)'
        ).fetchone()[0]
        return {"boundary_cells": boundary_count, "observed_cells": cells, "rows": rows,
                "period_start": first, "period_end": last, "cell_hour_dong_splits": splits,
                "unmatched_cells": [row[0] for row in missing],
                "boundary_area_m2": [min_area, max_area]}


def aggregate_window(parquets: list[Path], start: date, end: date, destination: Path) -> dict:
    """Aggregate daily observations with equal day weights, never average monthly means."""
    if start > end:
        raise ValueError("Invalid aggregation period")
    paths = [str(path.resolve()) for path in parquets]
    if not paths or len(set(paths)) != len(paths) or str(destination.resolve()) in paths:
        raise ValueError("Use distinct monthly inputs and a separate output")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        with duckdb.connect(config={"memory_limit": "1GB", "threads": 2,
                                    "temp_directory": temporary}) as connection:
            connection.read_parquet(paths, filename=True).create_view("raw")
            overlap = connection.execute(
                'select count(*) from (select "일자" from raw group by "일자" '
                'having count(distinct filename)>1)'
            ).fetchone()[0]
            if overlap:
                raise ValueError("Monthly input files have overlapping dates")
            connection.execute(
                "create temp table calendar as select range::date as date "
                "from range(?::date, ?::date + interval 1 day, interval 1 day)", [start, end]
            )
            expressions = ['try_cast(nullif(trim("생활인구합계"),\'*\') as double) as total']
            bands = ["total", *COARSE_BANDS]
            for band, labels in COARSE_BANDS.items():
                terms = [f'try_cast(nullif(trim("{sex} {label}"),\'*\') as double)'
                         for label in labels for sex in ("남자", "여자")]
                expressions.append(
                    '(' + ' + '.join(terms) + f') as "{band}"'
                )
            # Trusted, fixed column identifiers only. Dates are bound separately below.
            connection.execute(
                'create temp view prepared as select strptime("일자",\'%Y%m%d\')::date as date, '
                '"일자" as raw_date, '
                'trim("250M격자") as cell_id, cast("시간" as smallint) as hour, '
                + ",".join(expressions) + ' from raw'
            )
            first, last, days = connection.execute(
                "select min(date), max(date), count(distinct date) from prepared"
            ).fetchone()
            if (first, last, days) != (start, end, (end - start).days + 1):
                raise ValueError("Raw files do not cover exactly the requested complete period")
            # Suppression is decided per entire cell/date/hour, before averaging.
            # Otherwise a valid dong fragment on an invalid date biases the numerator.
            daily = []
            for band in bands:
                daily += [
                    f'case when count(*)=count("{band}") then sum("{band}") '
                    f'else 0 end as "{band}_sum"',
                    f'(case when count(*)=count("{band}") then 1 else 0 end)'
                    f'::smallint as "{band}_days"',
                ]
            # Bound the first aggregation to one day (~206k cells/hours for Seoul).
            # Materializing all 92 days as an in-memory table exceeds the 1GB budget.
            daily_directory = Path(temporary) / "daily"
            daily_directory.mkdir()
            for offset in range((end - start).days + 1):
                day = start + timedelta(days=offset)
                connection.sql(
                    "select cell_id,date,hour," + ",".join(daily)
                    + " from prepared where raw_date=? group by cell_id,date,hour",
                    params=[day.strftime("%Y%m%d")],
                ).write_parquet(str(daily_directory / f"{day}.parquet"), compression="zstd")
            connection.read_parquet(str(daily_directory / "*.parquet")).create_view("daily")
            aggregates = []
            for band in bands:
                aggregates += [f'sum("{band}_sum") as "{band}_sum"',
                               f'sum("{band}_days") as "{band}_days"']
            connection.execute(
                "create temp table wide_summary as select cell_id, hour, "
                "case when isodow(date) in (6,7) then 'weekend' else 'weekday' end as dow_type, "
                "count(*)::smallint as observed_days,sum(total_days)::smallint as sample_days, "
                + ",".join(aggregates) + " from daily group by cell_id, hour, dow_type"
            )
            connection.sql(SQL_PATH.read_text()).write_parquet(
                str(Path(temporary) / "profile.parquet"), compression="zstd"
            )
            profile = connection.read_parquet(str(Path(temporary) / "profile.parquet"))
            profile.create_view("profile")
            rows, cells, nulls = connection.execute(
                "select count(*),count(distinct cell_id),count(*) filter(where total is null) "
                "from profile"
            ).fetchone()
        (Path(temporary) / "profile.parquet").replace(destination)
    return {"rows": rows, "cells": cells, "null_totals": nulls,
            "period_start": start.isoformat(), "period_end": end.isoformat(),
            "parquet_bytes": destination.stat().st_size}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("month")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare_month(args.archive, args.month, args.destination)))


def monthly_files(html):
    """Read actual monthly file IDs; daily ZIP IDs must not stand in for a month."""
    import re
    from html.parser import HTMLParser

    class Catalog(HTMLParser):
        files = None

        def __init__(self):
            super().__init__()
            self.files = {}

        def handle_starttag(self, tag, attributes):
            attrs = dict(attributes)
            name = re.fullmatch(r"250_LOCAL_RESD_([0-9]{4})([0-9]{2})\.zip", attrs.get("title", ""))
            action = re.search(r"downloadFile\('([0-9]+)'\)", attrs.get("onclick", ""))
            if name and action:
                month = name[1] + "-" + name[2]
                if month in self.files and self.files[month] != action[1]:
                    raise ValueError("Ambiguous monthly file ID")
                self.files[month] = action[1]

    catalog = Catalog()
    catalog.feed(html)
    return catalog.files


def fetch_catalog():
    from urllib.request import urlopen

    with urlopen(
        "https://data.seoul.go.kr/dataList/OA-22784/S/1/datasetView.do", timeout=90
    ) as response:
        return monthly_files(response.read().decode("utf-8"))


def fetch_month(month, destination):
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen

    files = fetch_catalog()
    if month not in files:
        raise ValueError("Requested completed month is not published in the official catalog")
    body = urlencode(dict(infId="OA-22784", infSeq="1", seq=files[month])).encode()
    request = Request(
        "https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?useCache=false",
        data=body,
        headers={"User-Agent": "Gilmok-ingest/1.0"},
    )
    destination = Path(destination)
    temporary = destination.with_suffix(".download")
    try:
        with urlopen(request, timeout=180) as source, temporary.open("wb") as target:
            shutil.copyfileobj(source, target)
        with ZipFile(temporary) as bundle:
            if not bundle.namelist():
                raise ValueError("Empty monthly archive")
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("Living population monthly download failed") from None
    return destination
