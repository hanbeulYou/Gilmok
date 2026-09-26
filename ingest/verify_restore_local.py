"""Create an isolated local replay database, apply migrations, restore and verify R2 data."""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from ingest.common import ROOT
from ingest.database import connect_database


def verify(database, manifest):
    if not re.fullmatch(r"gilmok_s3_replay_[a-z0-9_]+", database):
        raise ValueError("Use an isolated gilmok_s3_replay_* database")
    with connect_database(local_only=True) as source:
        source.autocommit = True
        if source.execute("select 1 from pg_database where datname=%s", (database,)).fetchone():
            raise ValueError("Refusing to replace an existing database")
        functions = source.execute("""select pg_get_functiondef(p.oid) from pg_proc p
            join pg_namespace n on n.oid=p.pronamespace
            where n.nspname='auth' and p.proname in ('uid','jwt','role')""").fetchall()
        params = source.info.get_parameters()
        params.update(dbname=database, password=source.pgconn.password.decode())
        # template0 avoids inheriting stale locale-dependent indexes from template1.
        source.execute(sql.SQL("create database {} template template0")
                       .format(sql.Identifier(database)))
    with psycopg.connect(**params) as db:
        # Database-only replay fixture; real Auth/email proof uses the local GoTrue service.
        db.execute("create schema extensions; create schema auth; "
                   "create table auth.users(id uuid primary key,is_anonymous boolean,email text)")
        for body, in functions:
            db.execute(body)
        db.execute("grant usage on schema auth,extensions to anon,authenticated,service_role")
        for path in sorted((ROOT / "supabase/migrations").glob("*.sql")):
            db.execute(path.read_text())
    env = {**os.environ, "SUPABASE_DB_URL": make_conninfo(**params)}
    for module, extra in [("ingest.restore_remote", []), ("ingest.verify_remote", ["--no-http"])]:
        subprocess.run([sys.executable, "-m", module, "--target", "local", "--manifest",
                        str(manifest), *extra], env=env, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    verify(args.database, args.manifest)
