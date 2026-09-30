"""Local-only compact-reference replay; never downloads/stores new Kakao responses."""

import argparse
import json
import subprocess
from pathlib import Path
from time import perf_counter

import psycopg
from psycopg.types.json import Jsonb

from ingest.common import ROOT
from ingest.database import LOCAL_DB_URL


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    requests = args.output / "requests.json"
    runner = str(ROOT / "ingest/verify_registration_reference.mjs")
    subprocess.run(["node", runner, "raw", str(args.input), str(requests)], check=True)
    rows = []
    with psycopg.connect(LOCAL_DB_URL) as db:
        db.execute("set transaction isolation level repeatable read read only")
        db.execute("set local role authenticated")
        for request in json.loads(requests.read_text()):
            c = request["candidate"]
            started = perf_counter()
            reference = db.execute(
                "select public.score_reference_percentiles('academy_v0',800,%s)",
                (Jsonb(request["raw"]),),
            ).fetchone()[0]
            percentile_ms = (perf_counter() - started) * 1000
            started = perf_counter()
            context = db.execute(
                "select public.resolve_candidate_location(%s,%s,%s)",
                (c["lat"], c["lng"], request["pnu"]),
            ).fetchone()[0]
            rows.append(
                dict(
                    key=request["key"],
                    reference=reference,
                    context=context,
                    percentile_sql_ms=percentile_ms,
                    context_sql_ms=(perf_counter() - started) * 1000,
                )
            )
    rpc = args.output / "rpc.json"
    rpc.write_text(json.dumps(rows))
    subprocess.run(
        ["node", runner, "verify", str(args.input), str(args.output / "summary.json"), str(rpc)],
        check=True,
    )


if __name__ == "__main__":
    main()
