"""Exercise real local Parquet and DuckDB without API keys or a database."""

import argparse
import json
from pathlib import Path

import pandas as pd

from ingest.aggregate import aggregate
from ingest.common import ROOT, RawStore, Settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-root", type=Path, default=ROOT / ".local/ingest")
    args = parser.parse_args()
    # This sample deliberately uses local storage even if the user's .env has R2 keys.
    store = RawStore(Settings(local_root=args.local_root.resolve()))
    frame = pd.DataFrame({"code": ["001", "001", "002"], "value": [10, 20, None]})
    location = store.write_parquet("sample", "2026-01", frame)
    result = aggregate(store, "sample", "2026-01", ROOT / "ingest/sql/sample.sql")
    rows = json.loads(result.to_json(orient="records"))
    print(json.dumps({"storage": "local", "raw": location, "rows": rows}, allow_nan=False))


if __name__ == "__main__":
    main()
