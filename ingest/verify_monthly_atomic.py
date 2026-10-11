"""Local real snapshot monthly version-change replay; no upstream APIs or remote writes."""

import argparse
import json
import re
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import psycopg
from psycopg import sql

from ingest.common import RawStore, Settings
from ingest.refresh import AUTO, TABLES
from ingest.refresh_monthly import execute_monthly
from ingest.score_reference import collect_inputs, fingerprint, publish_reference, source_state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"gilmok_s3_replay_[a-z0-9_]+", args.database):
        raise ValueError("Only disposable local gilmok_s3_replay_* databases are allowed")
    out = args.directory
    out.mkdir(parents=True, exist_ok=True)
    dsn = "postgresql://postgres:postgres@127.0.0.1:54322/" + args.database

    @contextmanager
    def factory():
        with psycopg.connect(dsn) as db:
            yield db

    def pair():
        with factory() as db:
            db.execute("set transaction isolation level repeatable read read only")
            state = fingerprint(source_state(db))
            ref = db.execute(
                "select snapshot,source_fingerprint from public.score_reference_sets "
                "where preset_id='academy_v0'"
            ).fetchone()
            versions = db.execute(
                "select source,snapshot from ingest_private.refresh_snapshots order by source"
            ).fetchall()
            return {"source": state, "reference": ref[1], "snapshot": ref[0], "versions": versions}

    results = []
    original = pair()
    assert original["source"] == original["reference"]
    for failure in ["collection", "reference", "reference_copy", None]:
        label = failure or "success"
        folder = out / ("simulation-" + label)
        folder.mkdir(exist_ok=True)
        observations = []

        def prepare(source, db):
            if failure == "collection" and source == "trades":
                raise ConnectionError("Simulated October upstream failure")

            def loader(connection):
                for table in TABLES[source]:
                    exists = connection.execute(
                        "select 1 from information_schema.columns where table_schema='public' "
                        "and table_name=%s and column_name='ingested_at'",
                        (table,),
                    ).fetchone()
                    if exists:
                        connection.execute(
                            sql.SQL(
                                "update public.{} set ingested_at='2026-11-10T00:00:00Z'"
                            ).format(sql.Identifier(table))
                        )
                if source in ("academies", "schools"):
                    connection.execute(
                        "update ingest_private.place_snapshots "
                        "set ingested_at='2026-11-10T00:00:00Z' "
                        "where target_table=%s",
                        (source,),
                    )
                observations.append(pair())

            return (
                date(2026, 11, 30),
                {"simulation": True, "data": "10/10 values, new ingestion metadata"},
                loader,
            )

        def reference(db):
            assert fingerprint(source_state(db)) != original["source"]
            observations.append(pair())
            if failure == "reference":
                raise ValueError("Simulated bridge or publication failure")
            if failure == "reference_copy":

                def broken(connection):
                    connection.execute(
                        "delete from public.score_reference where preset_id='academy_v0'"
                    )
                    raise ValueError("Simulated distribution copy failure")

                return date(2026, 12, 1), {"simulation": True}, broken
            collected = collect_inputs(db, folder, uncommitted_refresh=True)
            prepared = publish_reference(
                RawStore(Settings(local_root=(out / "simulation-objects").resolve())),
                folder,
                "20261201T000000Z",
                collected,
            )
            observations.append(pair())
            return prepared

        start = time.monotonic()
        report = execute_monthly(AUTO, "20261201T000000Z", factory, prepare, reference)
        current = pair()
        assert all(x == original for x in observations), (label, "reader saw pending release")
        if failure:
            assert not report["committed"] and current == original, (label, report)
        else:
            assert (
                report["committed"]
                and current["source"] == current["reference"]
                and current["source"] != original["source"]
            ), report
        results.append(
            {
                "case": label,
                "seconds": time.monotonic() - start,
                "report": report,
                "before": original,
                "after": current,
                "reader_observations": len(observations),
                "reader_old_pair_only": True,
            }
        )
        (out / "simulation.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(label, report["status"], report["committed"], flush=True)


if __name__ == "__main__":
    main()
