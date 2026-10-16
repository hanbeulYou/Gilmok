"""Local synthetic RPC benchmark. Reject remote DB/API URLs before any connection."""

import argparse
import gzip
import json
import math
import platform
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import requests
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from tests.integration.academy_layer_fixture import FIELD, LAT, LNG, seed
from tests.integration.test_s3_auth import as_user


def require_local(database_url, api_url):
    if conninfo_to_dict(database_url).get("host") not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Synthetic local DB only")
    if urlparse(api_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Synthetic local API only")


def p95(values):
    return sorted(values)[math.ceil(len(values) * 0.95) - 1]


def run(database_url, workdir, output):
    # Check DB first, before running status or querying any API.
    require_local(database_url, "http://127.0.0.1")
    status = json.loads(
        subprocess.check_output(
            ["supabase", "status", "--workdir", str(workdir), "-o", "json"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    )
    api = status["API_URL"]
    require_local(database_url, api)
    headers = {"apikey": status["ANON_KEY"], "Accept-Encoding": "identity"}
    sessions = []
    for _ in range(2):
        response = requests.post(api + "/auth/v1/signup", headers=headers, json={}, timeout=15)
        response.raise_for_status()
        sessions.append(response.json())
    output.mkdir(parents=True, exist_ok=False)
    report = dict(
        mode="synthetic_only",
        platform=platform.platform(),
        db_host=conninfo_to_dict(database_url)["host"],
        remote_db_or_r2_access=False,
        first_run="first SQL execution after synthetic seed; OS/Postgres buffers not flushed",
        gzip="offline gzip.compress(mtime=0), not claimed as wire compression",
        scenarios=[],
    )
    with psycopg.connect(database_url, autocommit=True) as db:
        for count in [300, 1500, 5000]:
            with db.transaction():
                source = seed(db, count)
            for radius in [800, 1000]:
                args = dict(
                    lat=LAT, lng=LNG, radius_m=radius, requested_field=FIELD, expected_source=source
                )
                with db.transaction():
                    as_user(db, sessions[0]["user"]["id"])
                    times = []
                    for _ in range(31):
                        plan = db.execute(
                            "explain (analyze,format json) "
                            "select public.academy_layer(%s,%s,%s,%s,%s)",
                            (LAT, LNG, radius, FIELD, Jsonb(source)),
                        ).fetchone()[0]
                        times.append(plan[0]["Execution Time"])
                    sql_value = db.execute(
                        "select public.academy_layer(%s,%s,%s,%s,%s)",
                        (LAT, LNG, radius, FIELD, Jsonb(source)),
                    ).fetchone()[0]
                    native = db.execute(
                        "select score_internal.compete("
                        "extensions.st_setsrid(extensions.st_makepoint(%s,%s),4326),%s,true)",
                        (LNG, LAT, radius),
                    ).fetchone()[0]
                http = []
                raws = []
                encodings = set()
                for _ in range(30):
                    began = time.perf_counter()
                    response = requests.post(
                        api + "/rest/v1/rpc/academy_layer",
                        headers={
                            **headers,
                            "Authorization": "Bearer " + sessions[0]["access_token"],
                        },
                        json=args,
                        timeout=15,
                    )
                    http.append((time.perf_counter() - began) * 1000)
                    response.raise_for_status()
                    assert response.json() == sql_value
                    raws.append(response.content)
                    encodings.add(response.headers.get("Content-Encoding", "identity"))
                other = requests.post(
                    api + "/rest/v1/rpc/academy_layer",
                    headers={**headers, "Authorization": "Bearer " + sessions[1]["access_token"]},
                    json=args,
                    timeout=15,
                )
                other.raise_for_status()
                assert other.json() == sql_value
                if sql_value["status"] == "ready":
                    assert sql_value["counts"]["by_field"] == native["academies_by_field"]
                    assert sql_value["counts"]["radius_all"] == native["academies_total"] == count
                else:
                    assert sql_value["status"] == "too_dense" and sql_value["collection"] is None
                key = f"{count}-{radius}"
                (output / f"{key}.json").write_text(
                    json.dumps(
                        dict(
                            request=dict(
                                lat=LAT,
                                lng=LNG,
                                radius_m=radius,
                                field=FIELD,
                                expected_source=source,
                                expected_same_field_count=native["academies_by_field"][FIELD],
                            ),
                            response=sql_value,
                        ),
                        ensure_ascii=False,
                    )
                )
                report["scenarios"].append(
                    dict(
                        institutions=count,
                        radius_m=radius,
                        status=sql_value["status"],
                        sql_first_ms=times[0],
                        sql_warm_p95_ms=p95(times[1:]),
                        sql_warm_max_ms=max(times[1:]),
                        sql_warm_runs=30,
                        http_p95_ms=p95(http),
                        http_max_ms=max(http),
                        http_runs=30,
                        response_raw_bytes=max(map(len, raws)),
                        offline_gzip_bytes=len(gzip.compress(raws[0], mtime=0)),
                        content_encoding=sorted(encodings),
                        two_uid_equal=True,
                        dense_details=sql_value["meta"]
                        if sql_value["status"] == "too_dense"
                        else None,
                    )
                )
                print(json.dumps(report["scenarios"][-1]), flush=True)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.database_url, args.workdir, args.output)
