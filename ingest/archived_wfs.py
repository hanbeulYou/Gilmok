"""Replay approved immutable R2 WFS originals; never call Vworld or publish data."""

import hashlib
import json
from pathlib import Path

import duckdb
import pandas as pd

from ingest.common import RawStore, Settings

# The S1 restore manifest pins both original bytes and their acquisition date.
SNAPSHOT = "2026-09-20"
ARCHIVES = {
    "legal_boundaries": (
        "raw/legal_boundaries/2026-09.parquet",
        "8253b39f923001a8874ee08f74c7543156a8822a99fbc674a513d0506fc4340f",
        68,
    ),
    "vworld_building_footprints": (
        "raw/vworld_building_footprints/2026-09.parquet",
        "6cda38773a28f479dcdcde157ab1be68c1bf208dbcc40eb60c247a9c93ba7ae5",
        33345,
    ),
}


def archived_frame(source, directory, *, environ=None):
    # Import lazily: refresh_sources also uses this replay adapter.
    from ingest.refresh_sources import restore_object

    key, expected, count = ARCHIVES[source]
    path = Path(directory) / (source + ".parquet")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary = path.with_suffix(".download")
        try:
            restore_object(RawStore(Settings.from_env(environ)), key, temporary, expected)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    with path.open("rb") as f:
        if hashlib.file_digest(f, "sha256").hexdigest() != expected:
            raise ValueError("Archived WFS checksum mismatch; no provider fallback")
    with duckdb.connect() as db:
        relation = db.read_parquet(str(path))
        frame = pd.DataFrame(relation.fetchall(), columns=relation.columns)
    if len(frame) != count:
        raise ValueError("Archived WFS row count mismatch")
    return frame


def archived_legal_collection(directory, *, environ=None):
    frame = archived_frame("legal_boundaries", directory, environ=environ)
    metadata = frame.collection_metadata_json.unique()
    if len(metadata) != 1:
        raise ValueError("Archived boundary metadata differs across rows")
    collection = json.loads(metadata[0])
    collection["features"] = [json.loads(value) for value in frame.feature_json]
    return collection


def archived_building_features(directory, *, environ=None):
    frame = archived_frame("vworld_building_footprints", directory, environ=environ)
    return [
        dict(
            type="Feature",
            id=row["feature_id"],
            geometry=json.loads(row["geometry_json"]),
            properties={k: v for k, v in row.items() if k not in ("feature_id", "geometry_json")},
        )
        for row in frame.to_dict("records")
    ]
