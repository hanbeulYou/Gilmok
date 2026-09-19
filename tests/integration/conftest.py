import os

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from ingest.database import LOCAL_DB_URL


@pytest.fixture
def db():
    # Integration tests are deliberately local-only and always rolled back.
    url = os.environ.get("SUPABASE_DB_URL") or LOCAL_DB_URL
    if conninfo_to_dict(url).get("host") not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("Database tests require local Supabase; remote URLs are refused")
    connection = psycopg.connect(url, connect_timeout=5)
    try:
        connection.execute("select 1")  # Outer transaction: loader uses savepoints.
        yield connection
    finally:
        connection.rollback()
        connection.close()
