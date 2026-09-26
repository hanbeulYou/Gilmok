"""Explicit post-approval Auth / Vault / webhook activation (never part of migration push)."""

import argparse
import json
import os
from urllib.request import Request, urlopen

from dotenv import dotenv_values

from ingest.common import ROOT
from ingest.refresh import target_database
from ingest.restore_manifest import sha256


def configure(step, manifest_path, approved_manifest_sha256):
    if sha256(manifest_path) != approved_manifest_sha256:
        raise ValueError("Expected the approved restore manifest SHA256")
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    # Validate remote project/TLS/explicit activation before either DB or Auth writes.
    with target_database("remote") as db:
        if step == "webhook":
            token = env.get("GITHUB_DISPATCH_TOKEN")
            if not token:
                raise ValueError("GITHUB_DISPATCH_TOKEN is required in .env")
            db.execute("create extension if not exists pg_net with schema extensions")
            secret = db.execute("select id from vault.secrets where name=%s",
                                ("gilmok_github_dispatch_token",)).fetchone()
            if secret:
                db.execute("select vault.update_secret(%s,%s)", (secret[0], token))
            else:
                db.execute("select vault.create_secret(%s,%s)",
                           (token, "gilmok_github_dispatch_token"))
            # The reviewed manual SQL owns its transaction; commit the Vault change first.
            db.commit()
            db.execute((ROOT / "docs/operations/sql/enable-address-dispatch.sql").read_text())
            return
    if step != "auth":
        raise ValueError("Expected auth or webhook")
    ref = env["SUPABASE_PROJECT_REF"]
    request = Request(f"https://api.supabase.com/v1/projects/{ref}/config/auth", method="PATCH",
        data=json.dumps(dict(external_anonymous_users_enabled=True,
                             security_manual_linking_enabled=True,
                             mailer_autoconfirm=False)).encode(),
        headers={"Authorization": "Bearer " + env["SUPABASE_ACCESS_TOKEN"],
                 "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
        if not (result["external_anonymous_users_enabled"]
                and result["security_manual_linking_enabled"]):
            raise ValueError("Auth settings were not enabled")
    except Exception:
        raise RuntimeError("Remote Auth configuration failed; inspect settings without tokens") \
            from None


if __name__ == "__main__":
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step", choices=("auth", "webhook"), required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--approved-manifest-sha256", required=True)
    args = parser.parse_args()
    configure(args.step, args.manifest, args.approved_manifest_sha256)
    print(args.step + " configured")
