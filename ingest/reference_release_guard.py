"""Reject promotion exports whose operational record disagrees with the distribution."""


def validate_reference_metadata(active, run, row_groups):
    if not active or not run:
        raise ValueError("Reference set or refresh snapshot missing")
    manifest = run.get("manifest")
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError("Reference refresh manifest is empty")
    snapshot = active["snapshot"]
    if run["snapshot"] != snapshot or manifest.get("snapshot") != snapshot:
        raise ValueError("Reference distribution/refresh/manifest snapshot mismatch")
    if len(row_groups) != 1 or row_groups[0][0] != snapshot:
        raise ValueError("Reference rows have a different or mixed snapshot")
    if manifest.get("row_count") != row_groups[0][1]:
        raise ValueError("Reference manifest row count mismatch")
    if manifest.get("source_fingerprint") != active["source_fingerprint"]:
        raise ValueError("Reference manifest fingerprint mismatch")
    if manifest.get("preset", {}).get("id") != active["preset_id"]:
        raise ValueError("Reference manifest preset mismatch")
    return dict(snapshot=snapshot, rows=row_groups[0][1],
                source_fingerprint=active["source_fingerprint"])


def validate_reference_release(db, preset_id="academy_v0"):
    active = db.execute(
        "select to_jsonb(s) from public.score_reference_sets s where preset_id=%s",
        (preset_id,),
    ).fetchone()
    run = db.execute(
        "select to_jsonb(s) from ingest_private.refresh_snapshots s "
        "where source='score_reference'"
    ).fetchone()
    rows = db.execute(
        "select snapshot,count(*) from public.score_reference "
        "where preset_id=%s group by snapshot order by snapshot", (preset_id,),
    ).fetchall()
    return validate_reference_metadata(active[0] if active else None,
                                       run[0] if run else None, rows)
