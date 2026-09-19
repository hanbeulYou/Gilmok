"""Run trusted batch SQL against a raw snapshot without another download."""

from pathlib import Path

import pandas as pd

from ingest.common import RawStore, StorageError


def aggregate(store: RawStore, source: str, month: str, sql_path: Path) -> pd.DataFrame:
    query = sql_path.read_text(encoding="utf-8")
    location = store.location(source, month)
    try:
        with store.connection() as connection:
            connection.read_parquet(location).create_view("raw_data")
            return connection.execute(query).fetchdf()
    except Exception:
        if store.settings.uses_r2:
            raise StorageError("R2 aggregation failed; local fallback was not used") from None
        raise
