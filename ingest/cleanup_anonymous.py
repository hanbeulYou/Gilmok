"""Conservative anonymous retention. Read-only by default; never logs identities/inputs."""

import argparse
import hashlib
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg.conninfo import conninfo_to_dict

from ingest.common import ROOT
from ingest.database import LOCAL_DB_URL

# to_jsonb permits the read-only report before PR C's comparison updated_at migration.
# auth.users.updated_at is deliberately absent: token refresh is not foreground activity.
RETENTION_SQL = """
with activity as (
 select u.id,u.is_anonymous,
   greatest(u.created_at,u.last_sign_in_at,a.last_active_at,c.latest,p.latest) last_active_at,
   coalesce(c.n,0)::int candidates,coalesce(p.n,0)::int comparisons,
   case when coalesce(c.n,0)>0 or coalesce(p.n,0)>0 then 90 else 30 end keep_days,
   nullif(u.email,'') is not null or nullif(u.phone,'') is not null
     or nullif(u.email_change,'') is not null or nullif(u.phone_change,'') is not null
     or nullif(u.email_change_token_new,'') is not null
     or nullif(u.email_change_token_current,'') is not null
     or exists(select 1 from auth.identities i where i.user_id=u.id and i.provider<>'anonymous')
     or exists(select 1 from auth.flow_state f where f.user_id=u.id) linked_or_linking,
   a.user_id is null untracked,
   exists(select 1 from app_private.projection_errors e
     where e.source_table='app_private.user_activity' and e.row_id=u.id::text
       and e.resolved_at is null) activity_record_failed
 from auth.users u left join app_private.user_activity a on a.user_id=u.id
 left join lateral (select count(*) n,max(greatest(created_at,updated_at)) latest
   from public.candidates where user_id=u.id) c on true
 left join lateral (select count(*) n,
   max(greatest(created_at,(to_jsonb(v)->>'updated_at')::timestamptz)) latest
   from public.comparisons v where user_id=u.id) p on true
), classified as (
 select *,case when is_anonymous is distinct from true then 'permanent'
   when linked_or_linking then 'linked_or_linking'
   when untracked then 'untracked_conservative_hold'
   when activity_record_failed then 'activity_record_failed'
   when last_active_at is null then 'unknown_activity'
   when last_active_at >= %(as_of)s::timestamptz-make_interval(days=>keep_days) then 'recent'
   else 'eligible' end reason from activity
) select * from classified order by id
"""


@contextmanager
def cleanup_database(target):
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    url = env.get("SUPABASE_DB_URL", LOCAL_DB_URL)
    info = conninfo_to_dict(url)
    if target == "local":
        if info.get("host") not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Local cleanup requires loopback database")
    else:
        ref = env.get("SUPABASE_PROJECT_REF", "")
        if (
            not re.fullmatch(r"[a-z0-9]{20}", ref)
            or not (
                info.get("host") == f"db.{ref}.supabase.co"
                or (
                    info.get("host", "").endswith(".pooler.supabase.com")
                    and info.get("user") == f"postgres.{ref}"
                )
            )
            or info.get("sslmode") not in {"require", "verify-ca", "verify-full"}
            or info.get("port", "5432") != "5432"
        ):
            raise ValueError("Remote cleanup requires matching project, TLS and session connection")
    with psycopg.connect(url, connect_timeout=15, keepalives=1, keepalives_idle=30) as db:
        yield db


def classify(db, as_of):
    with db.cursor(row_factory=psycopg.rows.dict_row) as cur:
        return cur.execute(RETENTION_SQL, {"as_of": as_of}).fetchall()


def manifest_hash(as_of, ids):
    value = json.dumps({"as_of": as_of, "ids": sorted(ids)}, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(value.encode()).hexdigest()


def report(db, as_of, limit=500):
    rows = classify(db, as_of)
    selected = [r for r in rows if r["reason"] == "eligible"][:limit]
    ids = [str(r["id"]) for r in selected]
    reasons = {}
    for row in rows:
        reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1
    activities = [r["last_active_at"] for r in selected]
    return {
        "dry_run": True,
        "as_of": as_of,
        "selected_users": len(ids),
        "candidate_rows": sum(r["candidates"] for r in selected),
        "comparison_rows": sum(r["comparisons"] for r in selected),
        "shared_cache_rows_to_delete": 0,
        "reason_counts": reasons,
        "activity_min": min(activities).isoformat() if activities else None,
        "activity_max": max(activities).isoformat() if activities else None,
        "selection_sha256": manifest_hash(as_of, ids),
    }, {"as_of": as_of, "ids": ids}


def apply_manifest(db, manifest, approved_hash, *, enabled=False):
    if not enabled:
        raise ValueError(
            (
                "AUTH_CLEANUP_ENABLED=true is required; INGEST_REMOTE_ENABLED "
                "does not authorize cleanup"
            )
        )
    ids, as_of = manifest["ids"], manifest["as_of"]
    cutoff = datetime.fromisoformat(as_of)
    if cutoff.tzinfo is None or cutoff > datetime.now(timezone.utc):
        raise ValueError("Retention manifest requires a past, timezone-aware reference time")
    if len(ids) > 500 or len(set(ids)) != len(ids) or manifest_hash(as_of, ids) != approved_hash:
        raise ValueError("Approved retention manifest mismatch")
    deleted = skipped = 0
    # Stable user order, at most 100/transaction. A rerun safely skips already deleted IDs.
    db.commit()
    for offset in range(0, len(ids), 100):
        with db.transaction():
            batch = sorted(ids)[offset : offset + 100]
            locked = db.execute(
                (
                    "select id from auth.users where id=any(%s::uuid[]) order by id "
                    "for update skip locked"
                ),
                (batch,),
            ).fetchall()
            locked_ids = {str(r[0]) for r in locked}
            eligible = {str(r["id"]) for r in classify(db, as_of) if r["reason"] == "eligible"}
            chosen = sorted(locked_ids & eligible)
            if chosen:
                deleted += db.execute(
                    "delete from auth.users where id=any(%s::uuid[])", (chosen,)
                ).rowcount
            skipped += len(batch) - len(chosen)
    return {
        "dry_run": False,
        "deleted_users": deleted,
        "skipped_after_recheck": skipped,
        "selection_sha256": approved_hash,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=["local", "remote"], default="local")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--manifest", type=Path, help="Private approval manifest; never publish user IDs"
    )
    parser.add_argument("--approved-sha256")
    args = parser.parse_args()
    with cleanup_database(args.target) as db:
        if args.apply:
            if not args.manifest or not args.approved_sha256:
                parser.error("--apply requires --manifest and --approved-sha256")
            result = apply_manifest(
                db,
                json.loads(args.manifest.read_text()),
                args.approved_sha256,
                enabled=os.environ.get("AUTH_CLEANUP_ENABLED") == "true",
            )
        else:
            db.execute("set transaction read only")
            result, manifest = report(db, datetime.now(timezone.utc).isoformat())
            if args.manifest:
                args.manifest.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(args.manifest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w") as f:
                    json.dump(manifest, f)
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
