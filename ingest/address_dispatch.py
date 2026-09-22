"""Repository dispatch wake-up/sweep entry; event payload never contains work or secrets."""

import argparse
import json
import os
from pathlib import Path

from ingest.building_on_demand import process_one
from ingest.common import ROOT, Settings
from ingest.refresh import target_database

EVENT_TYPE = "gilmok_address_pending"


def validate_event(event_name, event):
    if event_name == "repository_dispatch":
        if event.get("action") != EVENT_TYPE:
            raise ValueError("Unexpected repository dispatch event")
    elif event_name not in ("schedule", "workflow_dispatch", "local"):
        raise ValueError("Unsupported worker trigger")
    # client_payload is intentionally ignored: no addresses, refs, commands or credentials.


def drain(factory, directory, limit=10, processor=process_one):
    if not 1 <= limit <= 100:
        raise ValueError("Address budget must be 1..100")
    processed = 0
    with factory() as db:
        db.autocommit = True
        for _ in range(limit):
            if processor(db, directory) is None:
                break
            processed += 1
        remaining = db.execute(
            "select count(*) from ingest_private.building_address_requests where status='pending'"
        ).fetchone()[0]
        failed = db.execute(
            "select count(*) from ingest_private.building_address_requests "
            "where status in ('failed','processing')"
        ).fetchone()[0]
    return dict(processed=processed, pending=remaining, needs_review=failed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("local", "remote"), default="local")
    parser.add_argument("--directory", type=Path, default=ROOT / ".local/address-dispatch")
    parser.add_argument("--max-requests", type=int, default=10)
    parser.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME", "local"))
    parser.add_argument("--event-file", type=Path, default=os.environ.get("GITHUB_EVENT_PATH"))
    args = parser.parse_args()
    event = json.loads(args.event_file.read_text()) if args.event_file else {}
    validate_event(args.event_name, event)
    if args.target == "remote" and not Settings.from_env().uses_r2:
        raise ValueError("Remote worker requires persistent R2 storage")
    result = drain(lambda: target_database(args.target), args.directory, args.max_requests)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
