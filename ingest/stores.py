"""Latest-quarter Seoul CSV; full source in Parquet, six business columns in DB."""

import csv
from pathlib import Path
from zipfile import ZipFile

import duckdb
import pandas as pd


def extract_raw(archive: Path, directory: Path, month: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"stores-{month}.parquet"
    if target.exists():
        return target
    with ZipFile(archive) as package:
        matches = []
        for entry in package.infolist():
            name = entry.filename
            if not entry.flag_bits & 0x800:
                try:
                    name = name.encode("cp437").decode("cp949")
                except UnicodeError:
                    pass  # Some members already carry a decoded Unicode path extra field.
            if f"_서울_{month.replace('-', '')}.csv" in name:
                matches.append(entry)
        if len(matches) != 1:
            raise ValueError("Expected exactly one Seoul CSV for requested quarter")
        csv_path = directory / "stores-source.csv"
        with package.open(matches[0]) as source, csv_path.open("wb") as output:
            import shutil

            shutil.copyfileobj(source, output)
    try:
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            columns = next(csv.reader(handle))
        with duckdb.connect() as connection:
            relation = connection.sql(
                "select * from read_csv(?, all_varchar=true, force_not_null=?)",
                params=[str(csv_path), columns],
            )
            temporary = target.with_suffix(".tmp.parquet")
            relation.write_parquet(str(temporary), compression="zstd")
            temporary.replace(target)
    finally:
        csv_path.unlink(missing_ok=True)
    return target


def normalize(path: Path) -> pd.DataFrame:
    with duckdb.connect() as connection:
        connection.read_parquet(str(path)).create_view("raw_stores")
        if connection.execute(
            "select count(*) from raw_stores where \"시도코드\" is distinct from '11'"
        ).fetchone()[0]:
            raise ValueError("Source includes non-Seoul stores")
        frame = connection.execute("""select "상가업소번호" as store_id,
            "상권업종대분류코드" as inds_lcls, "상권업종중분류코드" as inds_mcls,
            "상권업종소분류코드" as inds_scls, nullif("층정보",'') as floor,
            cast("경도" as double) as lng, cast("위도" as double) as lat from raw_stores""").df()
    if frame.empty or frame.store_id.duplicated().any() or frame.store_id.eq("").any():
        raise ValueError("Empty or duplicate store identities")
    for column, pattern in [
        ("inds_lcls", r"[A-Z]\d"),
        ("inds_mcls", r"[A-Z]\d{3}"),
        ("inds_scls", r"[A-Z]\d{5}"),
    ]:
        if not frame[column].str.fullmatch(pattern).fillna(False).all():
            raise ValueError("Invalid commercial classification code")
    if not (
        frame.inds_mcls.str[:2].eq(frame.inds_lcls) & frame.inds_scls.str[:4].eq(frame.inds_mcls)
    ).all():
        raise ValueError("Inconsistent classification hierarchy")
    if not (frame.lng.between(124, 132) & frame.lat.between(33, 39)).all():
        raise ValueError("Invalid EPSG:4326 store coordinate")
    return frame
