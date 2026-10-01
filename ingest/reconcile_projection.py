"""Reconcile owner status projections; logs counts only, never private row identifiers."""

import argparse
import json

from ingest.refresh import target_database


def reconcile(factory, *, dry_run=False):
    with factory() as db:
        if dry_run:
            db.execute("set transaction read only")
        result = db.execute(
            "select app_private.reconcile_candidate_lookup(%s)", (not dry_run,)
        ).fetchone()[0]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("local", "remote"), default="local")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = reconcile(lambda: target_database(args.target), dry_run=args.dry_run)
    print(json.dumps(result))
    if not args.dry_run and (result["failed_addresses"] or result["unresolved_errors"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
