"""Local-only real-data interruption/restart proof against the frozen manifest."""

import argparse
import json
from pathlib import Path

from ingest.common import ROOT
from ingest.database import connect_database
from ingest.restore_remote import Replay, run, verify_tables
from ingest.verify_remote import verify


def verify_resume(manifest):
    with connect_database(local_only=True) as db:
        if not db.info.dbname.startswith("gilmok_s3_replay_"):
            raise ValueError("Resume proof requires an isolated replay database")
    directory = ROOT / ".local/restore/s3-1"
    run(manifest, directory, "local", stop_after="transit")
    original = Replay.places

    def fail_after_copy(self, db):
        original(self, db)
        raise RuntimeError("injected_stage_failure_after_places_load")

    Replay.places = fail_after_copy
    try:
        try:
            run(manifest, directory, "local")
        except RuntimeError as error:
            assert str(error) == "injected_stage_failure_after_places_load"
        else:
            raise AssertionError("Expected injected failure")
    finally:
        Replay.places = original
    with connect_database(local_only=True) as db:
        assert db.execute("select count(*) from ingest_private.restore_stages").fetchone()[0] == 3
        assert db.execute("select count(*) from public.stores").fetchone()[0] == 0
        assert db.execute("select count(*) from public.geocode_cache").fetchone()[0] == 0
    resumed = run(manifest, directory, "local")
    assert [s["status"] for s in resumed["stages"]] == ["skipped"] * 3 + ["committed"] * 4
    (directory / "local-resumed-restore-report.json").write_text(json.dumps(resumed, indent=2))
    repeated = run(manifest, directory, "local")
    assert repeated["already_restored"]
    with connect_database(local_only=True) as db:
        assert len(verify_tables(db, json.loads(manifest.read_text())["expected_tables"])) == 18
    report = dict(injected_failure_rolled_back=True, completed_stages_preserved=3,
                  resumed_stages=4, tables_verified=18, all_completed_retry_skipped=True)
    (directory / "local-resume-proof.json").write_text(json.dumps(report, indent=2))
    verify("local", manifest, directory, http=False)
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    verify_resume(args.manifest)
