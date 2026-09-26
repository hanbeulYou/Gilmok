"""Warm the six acceptance RPC cases after a successful monthly refresh."""

import json
import time

from ingest.refresh import target_database
from ingest.verify_score_inputs import QUERY, cases


def warm():
    results = []
    with target_database("remote") as db:
        db.execute("set transaction read only")
        db.execute("set local role authenticated")
        # SET ROLE does not apply rolconfig as PostgREST does; match the product limit.
        db.execute("set local statement_timeout='15s'")
        for case in cases():
            started = time.monotonic()
            payload = db.execute(QUERY, case).fetchone()[0]
            results.append({"name": case["name"], "radius_m": case["radius_m"],
                            "roundtrip_ms": round((time.monotonic() - started) * 1000, 3),
                            "bundle_ms": payload["meta"]["bundle_ms"]})
    return results


if __name__ == "__main__":
    print(json.dumps(warm(), ensure_ascii=False))
