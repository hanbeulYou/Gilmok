"""Real local GoTrue deletion/refresh and stale-JWT write proof (no token output)."""

import json
import subprocess
from datetime import datetime, timedelta, timezone

import requests

from ingest.cleanup_anonymous import apply_manifest, manifest_hash


def test_deleted_local_anonymous_session_cannot_refresh_or_write(db):
    local = json.loads(
        subprocess.check_output(
            ["supabase", "status", "-o", "json"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    )
    assert local["API_URL"].startswith(("http://127.0.0.1:", "http://localhost:"))
    headers = {"apikey": local["ANON_KEY"]}
    response = requests.post(
        local["API_URL"] + "/auth/v1/signup", headers=headers, json={}, timeout=15
    )
    assert response.status_code == 200
    session = response.json()
    uid = session["user"]["id"]
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=31)
    try:
        db.execute(
            "update auth.users set created_at=%s,last_sign_in_at=%s where id=%s", (old, old, uid)
        )
        db.execute(
            "insert into app_private.user_activity(user_id,last_active_at) values(%s,%s)",
            (uid, old),
        )
        manifest = {"as_of": now.isoformat(), "ids": [uid]}
        result = apply_manifest(db, manifest, manifest_hash(manifest["as_of"], [uid]), enabled=True)
        assert result["deleted_users"] == 1
        stale = {**headers, "Authorization": "Bearer " + session["access_token"]}
        touch = requests.post(
            local["API_URL"] + "/rest/v1/rpc/touch_user_activity",
            headers=stale,
            json={},
            timeout=15,
        )
        assert touch.status_code in (401, 403)
        refresh = requests.post(
            local["API_URL"] + "/auth/v1/token?grant_type=refresh_token",
            headers=headers,
            json={"refresh_token": session["refresh_token"]},
            timeout=15,
        )
        assert refresh.status_code in (400, 401)
    finally:
        db.execute("delete from auth.users where id=%s", (uid,))
        db.commit()
