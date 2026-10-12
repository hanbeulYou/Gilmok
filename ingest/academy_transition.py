"""Local-only address transition journal. Never writes a database or an object store."""

import argparse
import fcntl
import hashlib
import json
import os
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg.conninfo import conninfo_to_dict

from ingest.common import ROOT
from ingest.geocode import GeocodeStopped, normalize_address
from ingest.juso import (
    COORD_URL,
    IDENTIFIERS,
    SEARCH_URL,
    JusoCoordinates,
    api_json,
    matches_address,
    parse_search,
)
from ingest.score_reference import fingerprint, source_state


def local_connection(url):
    info = conninfo_to_dict(url)
    if info.get("host") not in {"127.0.0.1", "localhost", "::1"} or info.get("hostaddr") not in {
        None,
        "127.0.0.1",
        "::1",
    }:
        raise ValueError("Transition requires an explicit local database")
    return psycopg.connect(url)


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def inventory(db, legacy, directory):
    """Pin current public source rows and original Kakao address inventory separately."""
    directory.mkdir(parents=True, exist_ok=True)
    db.execute("set transaction isolation level repeatable read read only")
    legacy.execute("set transaction isolation level repeatable read read only")
    rows = {}
    for table in ("academies", "schools"):
        # Table names are this fixed allowlist, not CLI input.
        rows[table] = db.execute(
            f"select id,address,source_version,geocode_provider,geocode_failed,"
            f"extensions.st_x(geom),extensions.st_y(geom) from public.{table} order by id"
        ).fetchall()
    old = sorted(
        {
            normalize_address(r[0])
            for r in legacy.execute(
                "select address from public.geocode_cache where provider='kakao' order by address"
            )
        }
    )
    current = sorted({normalize_address(r[1]) for group in rows.values() for r in group})
    if not old or not current or "" in current:
        raise ValueError("Empty transition inventory")
    result = dict(
        observed_at=datetime.now(UTC).isoformat(),
        source_fingerprint=fingerprint(source_state(db)),
        baseline_reference=db.execute(
            "select snapshot from public.score_reference_sets"
        ).fetchone()[0],
        original_count=len(old),
        current_count=len(current),
        union_count=len(set(old) | set(current)),
        added_count=len(set(current) - set(old)),
        removed_count=len(set(old) - set(current)),
        institution_counts={k: len(v) for k, v in rows.items()},
        addresses=sorted(set(old) | set(current)),
        current_addresses=current,
        legacy_addresses=old,
        rows=rows,
    )
    path = directory / "inventory.json"
    if path.exists():
        existing = json.loads(path.read_text())
        for key in ("source_fingerprint", "addresses", "rows"):
            if json.dumps(existing[key], sort_keys=True) != json.dumps(result[key], sort_keys=True):
                raise ValueError("Inventory changed; use a new directory")
        return existing
    write_json(path, result)
    return result


class Journal:
    """Durable pre-call claims: a lost response is never silently called again."""

    def __init__(self, path, requester=api_json, interval=0.6):
        self.db = sqlite3.connect(path)
        self.db.execute("pragma journal_mode=WAL")
        self.db.execute("pragma synchronous=FULL")
        self.db.executescript("""
            create table if not exists calls (
              kind text, identity text, status text not null, response text,
              started_at text not null, seconds real, error_type text,
              primary key(kind,identity));
            create table if not exists outcomes (
              address text primary key, status text not null, result text not null);
        """)
        self.requester = requester
        self.interval = interval
        self.last_coordinate = 0.0

    def call(self, kind, identity, url, params):
        prior = self.db.execute(
            "select status,response from calls where kind=? and identity=?", (kind, identity)
        ).fetchone()
        if prior:
            if prior[0] != "complete":
                raise GeocodeStopped("Unresolved journal claim; inspect before retry")
            return json.loads(prior[1])
        if kind == "coordinate":
            time.sleep(max(0, self.interval - (time.monotonic() - self.last_coordinate)))
            self.last_coordinate = time.monotonic()
        self.db.execute(
            "insert into calls(kind,identity,status,started_at) values (?,?,'started',?)",
            (kind, identity, datetime.now(UTC).isoformat()),
        )
        self.db.commit()
        start = time.monotonic()
        try:
            response = self.requester(url, params)
            encoded = json.dumps(response, ensure_ascii=False)
            if params.get("confmKey") and params["confmKey"] in encoded:
                raise GeocodeStopped("Provider echoed credential; response not persisted")
            self.db.execute(
                "update calls set status='complete',response=?,seconds=? "
                "where kind=? and identity=?",
                (encoded, time.monotonic() - start, kind, identity),
            )
            self.db.commit()
            return response
        except Exception as error:
            self.db.execute(
                "update calls set status='error',error_type=?,seconds=? "
                "where kind=? and identity=?",
                (type(error).__name__, time.monotonic() - start, kind, identity),
            )
            self.db.commit()
            raise GeocodeStopped("Address transition stopped; inspect local journal") from None

    def resolve(self, address, search_key, coordinate_key, project):
        prior = self.db.execute(
            "select result from outcomes where address=?", (address,)
        ).fetchone()
        if prior:
            return json.loads(prior[0])
        raw = self.call(
            "search",
            address,
            SEARCH_URL,
            dict(
                confmKey=search_key,
                currentPage=1,
                countPerPage=100,
                keyword=address,
                resultType="json",
            ),
        )
        count, items = parse_search(raw)
        exact = [item for item in items if matches_address(item, address)]
        result = dict(address=address, status="not_found")
        if count:
            if count != len(items) or len(exact) > 1:
                result["status"] = "ambiguous"
            elif not exact:
                result["status"] = "invalid"
            else:
                item = exact[0]
                identity = json.dumps({k: item[k] for k in IDENTIFIERS}, sort_keys=True)
                provider = JusoCoordinates(
                    coordinate_key,
                    project,
                    requester=lambda url, params: self.call(
                        "coordinate", identity, COORD_URL, params
                    ),
                )
                location, _ = provider.locate(item)
                result.update(status=location["status"], selection=item, location=location)
        self.db.execute(
            "insert into outcomes values (?,?,?)",
            (address, result["status"], json.dumps(result, ensure_ascii=False)),
        )
        self.db.commit()
        return result

    def summary(self):
        return dict(
            outcomes=dict(self.db.execute("select status,count(*) from outcomes group by status")),
            calls=[
                dict(kind=k, status=s, count=n)
                for k, s, n in self.db.execute(
                    "select kind,status,count(*) from calls group by kind,status"
                )
            ],
        )


def run(directory, url, limit=None):
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    if not all(env.get(k) for k in ("JUSO_API_KEY", "JUSO_COORD_API_KEY")):
        raise ValueError("Juso search/coordinate keys required")
    data = json.loads((directory / "inventory.json").read_text())
    with (directory / "run.lock").open("w") as lock, local_connection(url) as db:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        db.execute("set transaction read only")
        if fingerprint(source_state(db)) != data["source_fingerprint"]:
            raise ValueError("Source fingerprint changed before geocoding")
        journal = Journal(directory / "journal.sqlite3")

        def project(x, y):
            return db.execute(
                """select extensions.st_x(p),extensions.st_y(p) from
                (select extensions.st_transform(extensions.st_setsrid(
                extensions.st_makepoint(%s,%s),5179),4326) p) s""",
                (x, y),
            ).fetchone()

        start = time.monotonic()
        try:
            for i, address in enumerate(data["addresses"][:limit], 1):
                journal.resolve(address, env["JUSO_API_KEY"], env["JUSO_COORD_API_KEY"], project)
                if i % 100 == 0 or i == len(data["addresses"][:limit]):
                    report = dict(
                        journal.summary(),
                        processed=i,
                        total=len(data["addresses"]),
                        seconds=round(time.monotonic() - start, 3),
                    )
                    write_json(directory / "progress.json", report)
                    print(json.dumps(report), flush=True)
        finally:
            write_json(
                directory / "progress.json",
                dict(
                    journal.summary(),
                    total=len(data["addresses"]),
                    seconds=round(time.monotonic() - start, 3),
                ),
            )
            journal.db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("inventory", "geocode"))
    parser.add_argument("--database-url", required=True)
    parser.add_argument(
        "--legacy-url", default="postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    )
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("limit must be positive")
    if args.stage == "inventory":
        with local_connection(args.database_url) as db, local_connection(args.legacy_url) as legacy:
            value = inventory(db, legacy, args.directory)
        print(
            json.dumps(
                {
                    k: v
                    for k, v in value.items()
                    if k not in {"addresses", "current_addresses", "legacy_addresses", "rows"}
                },
                ensure_ascii=False,
            )
        )
        print(
            "inventory_sha256",
            hashlib.sha256((args.directory / "inventory.json").read_bytes()).hexdigest(),
        )
    else:
        run(args.directory, args.database_url, args.limit)


if __name__ == "__main__":
    main()
