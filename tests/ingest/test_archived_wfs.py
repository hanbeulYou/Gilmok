import hashlib
import json

import duckdb
import pytest

from ingest import archived_wfs
from ingest.geocode import GeocodeStopped, request_vworld
from tests.ingest.test_legal_boundaries import collection


def test_verified_original_replay_preserves_metadata_and_rejects_corruption(tmp_path, monkeypatch):
    data = collection()
    path = tmp_path / 'legal_boundaries.parquet'
    import pandas as pd
    frame = pd.DataFrame([dict(feature_json=json.dumps(f),
                              collection_metadata_json=json.dumps({k:v for k,v in data.items()
                                                                   if k != 'features'}))
                          for f in data['features']])
    with duckdb.connect() as db:
        db.register('frame',frame)
        db.execute('copy frame to ? (format parquet)',[str(path)])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setitem(archived_wfs.ARCHIVES,'legal_boundaries',
                        ('raw/legal_boundaries/2026-09.parquet',digest,len(frame)))
    assert archived_wfs.archived_legal_collection(tmp_path,environ={}) == data
    path.write_bytes(path.read_bytes()+b'corrupt')
    with pytest.raises(ValueError,match='checksum'):
        archived_wfs.archived_legal_collection(tmp_path,environ={})


def test_retired_vworld_transport_cannot_be_reenabled_with_key():
    with pytest.raises(GeocodeStopped,match='retired'):
        request_vworld('공개 주소','secret')
