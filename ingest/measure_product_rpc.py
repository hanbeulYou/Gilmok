"""Measure product RPC SQL first-in-session/warm latency and retain partial evidence."""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

from ingest.refresh import target_database
from ingest.verify_remote import comparison_payload
from ingest.verify_score_inputs import QUERY, cases, equivalent, percentile


def save(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def sql_measure(target, output):
    report = {
        "target": target,
        "started_at": datetime.now(UTC).isoformat(),
        "role": "authenticated",
        "method": "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON); one new connection per case",
        "first_run_note": "Shared PostgreSQL/OS caches are not evicted; "
                          "first-in-session is not a physical cold-cache test.",
        "measurement_timeout": "60s transaction-local only; persistent role settings unchanged",
        "capture_note": "set_config stores this same RPC invocation's payload in a "
                        "transaction-local GUC; EXPLAIN includes this small capture overhead.",
        "warm_samples_per_case": 30,
        "cases": [],
        "status": "running",
    }
    started = time.monotonic()
    save(output, report)
    expression = QUERY.strip().removeprefix("select ").rstrip(";")
    statement = (
        "explain (analyze, buffers, format json) select "
        "set_config('gilmok.validation_payload', (" + expression + ")::text, true)"
    )
    try:
        for case in cases():
            record = {**case, "warm": []}
            report["cases"].append(record)
            with target_database(target) as db:
                db.execute("set transaction read only")
                record["role_config"] = db.execute(
                    "select rolconfig from pg_roles where rolname='authenticated'"
                ).fetchone()[0]
                db.execute("set local role authenticated")
                db.execute("set local statement_timeout='60s'")
                for index in range(31):
                    plan = db.execute(statement, case).fetchone()[0][0]
                    payload = db.execute(
                        "select current_setting('gilmok.validation_payload')::jsonb"
                    ).fetchone()[0]
                    sample = {
                        "execution_ms": plan["Execution Time"],
                        "planning_ms": plan["Planning Time"],
                        "bundle_ms": payload["meta"]["bundle_ms"],
                        "total_ms": payload["meta"]["total_ms"],
                        "buffers": {k: v for k, v in plan["Plan"].items()
                                    if "Blocks" in k},
                    }
                    if index == 0:
                        record["first"] = sample
                    else:
                        record["warm"].append(sample)
                    save(output, report)
                record["warm_p95_ms"] = percentile(
                    [sample["execution_ms"] for sample in record["warm"]]
                )
                record["warm_max_ms"] = max(s["execution_ms"] for s in record["warm"])
                record["bundle_warm_p95_ms"] = {
                    key: percentile([s["bundle_ms"][key] for s in record["warm"]])
                    for key in record["first"]["bundle_ms"]
                }
                print(json.dumps({"name": case["name"], "radius_m": case["radius_m"],
                                  "first_ms": record["first"]["execution_ms"],
                                  "warm_p95_ms": record["warm_p95_ms"],
                                  "first_bundle_ms": record["first"]["bundle_ms"]},
                                 ensure_ascii=False), flush=True)
            save(output, report)
        report["warm_gate_passed"] = all(r["warm_p95_ms"] < 1000 for r in report["cases"])
        report["status"] = "success"
    except Exception as error:
        report["status"] = "failed"
        report["error_type"] = type(error).__name__
        raise
    finally:
        report["seconds"] = round(time.monotonic() - started, 3)
        save(output, report)
    return report


def http_measure(url, public_key, access_token, baseline, output):
    """The public apikey identifies the project; the user JWT selects authenticated."""
    report = {"role": "authenticated", "anonymous_session": True,
              "first_run_note": "First HTTP request per case; shared caches are not evicted",
              "started_at": datetime.now(UTC).isoformat(), "cases": [], "status": "running"}
    started = time.monotonic()
    try:
        for case, expected in zip(cases(), baseline["cases"], strict=True):
            if case != expected["case"]:
                raise ValueError("Baseline cases differ")
            record = {**case, "warm": []}
            report["cases"].append(record)
            for index in range(31):
                request = Request(url + "/rest/v1/rpc/score_inputs",
                                  data=json.dumps({k: case[k] for k in
                                                   ("lat", "lng", "radius_m", "floor")}).encode(),
                                  headers={"apikey": public_key,
                                           "Authorization": "Bearer " + access_token,
                                           "Content-Type": "application/json"})
                call_started = time.monotonic()
                with urlopen(request, timeout=30) as response:
                    payload = json.load(response)
                sample = {"roundtrip_ms": (time.monotonic() - call_started) * 1000,
                          "bundle_ms": payload["meta"]["bundle_ms"],
                          "total_ms": payload["meta"]["total_ms"]}
                if not equivalent(comparison_payload(payload),
                                  comparison_payload(expected["result"])):
                    raise ValueError("HTTP RPC differs from frozen baseline")
                if index == 0:
                    record["first"] = sample
                else:
                    record["warm"].append(sample)
                save(output, report)
            record["warm_p95_ms"] = percentile([s["roundtrip_ms"] for s in record["warm"]])
            record["baseline_matches"] = True
            save(output, report)
            print(json.dumps({"name": case["name"], "radius_m": case["radius_m"],
                              "http_first_ms": record["first"]["roundtrip_ms"],
                                  "http_warm_p95_ms": record["warm_p95_ms"]},
                                 ensure_ascii=False), flush=True)
        report["status"] = "success"
    except Exception as error:
        report.update(status="failed", error_type=type(error).__name__,
                      http_status=getattr(error, "code", None))
        raise
    finally:
        report["seconds"] = round(time.monotonic() - started, 3)
        save(output, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("local", "remote"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = sql_measure(args.target, args.output)
    if not result["warm_gate_passed"]:
        raise SystemExit("Warm SQL p95 exceeds the 1000ms acceptance gate")
