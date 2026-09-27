"""Compare six RPC cases with the frozen baseline, without writing to the database."""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import duckdb
from dotenv import dotenv_values

from ingest.common import ROOT, RawStore, Settings
from ingest.refresh import target_database
from ingest.restore_manifest import cached_object, sha256
from ingest.restore_remote import verify_tables
from ingest.verify_score_inputs import QUERY, cases, equivalent, percentile, stable_payload


def comparison_payload(payload):
    timing = dict.fromkeys(("computed_at", "bundle_ms", "sources_ms", "total_ms"))
    result = stable_payload({**payload, "meta": {**timing, **payload["meta"]}})
    # Existing sources() uses LIMIT 1 across both boarding sources. Verify its allowed
    # set and compare every other field; physical row order must not fail a migration.
    source = result["meta"]["sources"]["transit_counts"]
    if source["source"] not in {"seoul_bus_boardings", "seoul_subway_boardings"}:
        raise ValueError("Unexpected transit source metadata")
    source["source"] = "seoul_bus_boardings|seoul_subway_boardings"
    return result


def http_credentials(target):
    if target == "local":
        result = subprocess.run(["supabase", "status", "-o", "json"], capture_output=True,
                                text=True, check=True)
        settings = json.loads(result.stdout)
        if urlparse(settings["API_URL"]).hostname not in ("localhost", "127.0.0.1"):
            raise ValueError("Expected local HTTP endpoint")
        return settings["API_URL"], settings["ANON_KEY"]
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    ref = env["SUPABASE_PROJECT_REF"]
    request = Request(f"https://api.supabase.com/v1/projects/{ref}/api-keys",
                      headers={"Authorization": "Bearer " + env["SUPABASE_ACCESS_TOKEN"]})
    try:
        with urlopen(request, timeout=30) as response:
            keys = json.load(response)
        key = next(k["api_key"] for k in keys if k["name"] == "anon")
    except Exception:
        raise RuntimeError("Cannot obtain remote anonymous API credential") from None
    return f"https://{ref}.supabase.co", key


def verify(target, manifest_path, directory, *, http=True):
    manifest = json.loads(manifest_path.read_text())
    entry, = [e for e in manifest["supplements"] if "/restore_provenance/" in e["key"]]
    path = cached_object(RawStore(Settings.from_env()), entry, directory)
    with duckdb.connect() as source:
        baseline = json.loads(source.read_parquet(str(path)).fetchone()[0])
    report = dict(target=target, manifest_sha256=sha256(manifest_path), cases=[],
                  comparison_note="Normalize only meta.sources.transit_counts.source: "
                  "existing LIMIT 1 may select either verified bus or subway source")
    with target_database(target) as db:
        db.execute("set transaction isolation level repeatable read read only")
        report["tables"] = verify_tables(db, baseline["tables"])
        for case, expected in zip(cases(), baseline["cases"], strict=True):
            if case != expected["case"]:
                raise ValueError("Baseline cases differ")
            db.execute("set local role anon")
            for _ in range(3):
                db.execute(QUERY, case).fetchone()
            elapsed = []
            for _ in range(30):
                plan = db.execute("explain(analyze,format json) " + QUERY, case).fetchone()[0][0]
                elapsed.append(plan["Execution Time"])
            result = db.execute(QUERY, case).fetchone()[0]
            if not equivalent(comparison_payload(result), comparison_payload(expected["result"])):
                raise ValueError(f"RPC baseline differs: {case['name']}/{case['radius_m']}")
            p95 = percentile(elapsed)
            if p95 >= 1000:
                raise ValueError("RPC DB p95 must be <1000ms")
            report["cases"].append(dict(**case, db_ms=elapsed, db_p95_ms=p95,
                baseline_matches=True,
                transit_metadata_source=result["meta"]["sources"]["transit_counts"]["source"]))
            db.execute("reset role")
    if http:
        url, key = http_credentials(target)
        for record, expected in zip(report["cases"], baseline["cases"], strict=True):
            args = {k: record[k] for k in ("lat", "lng", "radius_m", "floor")}
            elapsed = []
            for _ in range(30):
                request = Request(url + "/rest/v1/rpc/score_inputs",
                                  data=json.dumps(args).encode(), headers={
                                      "apikey": key, "Authorization": "Bearer " + key,
                                      "Content-Type": "application/json"})
                started = time.monotonic()
                with urlopen(request, timeout=30) as response:
                    payload = json.load(response)
                elapsed.append((time.monotonic() - started) * 1000)
                if not equivalent(comparison_payload(payload),
                                  comparison_payload(expected["result"])):
                    raise ValueError("HTTP RPC baseline differs")
            record.update(http_ms=elapsed, http_p95_ms=percentile(elapsed), http_matches=True)
    report["http_measured"] = http
    (directory / (target + "-rpc-report.json")).write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("local", "remote"), required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--directory", type=Path, default=ROOT / ".local/restore/s3-1")
    parser.add_argument("--no-http", action="store_true",
                        help="Isolated local replay DB has no HTTP server")
    args = parser.parse_args()
    if args.target == "remote" and args.no_http:
        parser.error("Remote verification requires HTTP measurements")
    result = verify(args.target, args.manifest, args.directory, http=not args.no_http)
    print(json.dumps([dict(name=r["name"], radius_m=r["radius_m"], db_p95_ms=r["db_p95_ms"])
                      for r in result["cases"]], ensure_ascii=False))
