"""Local HTTP proof: two anonymous identities, owner RLS, and email identity upgrade."""

import argparse
import html
import json
import re
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from uuid import uuid4

from ingest.common import ROOT


def verify(output):
    status = json.loads(subprocess.run(["supabase", "status", "-o", "json"],
                                      capture_output=True, text=True, check=True).stdout)
    url = status["API_URL"]
    if urlparse(url).hostname not in ("127.0.0.1", "localhost"):
        raise ValueError("Auth verification is local-only")
    key, admin = status["ANON_KEY"], status["SERVICE_ROLE_KEY"]

    def api(path, token=None, *, method="GET", body=None):
        request = Request(url + path, method=method,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={"apikey": key, "Authorization": "Bearer " + (token or key),
                                   "Content-Type": "application/json",
                                   "Prefer": "return=representation"})
        with urlopen(request, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else None

    users = []
    try:
        for _ in range(2):
            users.append(api("/auth/v1/signup", method="POST", body={}))
        owner, other = users
        uid, token = owner["user"]["id"], owner["access_token"]
        assert owner["user"]["is_anonymous"] is True
        candidate = api("/rest/v1/candidates", token, method="POST", body=dict(
            user_id=uid, geom="SRID=4326;POINT(127.057585738094 37.5025724504279)", floor=3))[0]
        comparison = api("/rest/v1/comparisons", token, method="POST", body=dict(
            candidate_ids=[candidate["id"]], weights={}, preset_id="academy_v0"))[0]
        for table, row in [("candidates", candidate), ("comparisons", comparison)]:
            path = f"/rest/v1/{table}?id=eq.{row['id']}"
            assert len(api(path, token)) == 1
            assert api(path, other["access_token"]) == []
            assert api(path, other["access_token"], method="DELETE") == []
        rpc = api("/rest/v1/rpc/score_inputs", token, method="POST", body=dict(
            lat=37.5025724504279, lng=127.057585738094, radius_m=800, floor=3))
        assert rpc["meta"]["schema_version"] == "1.3"
        mailbox = "s3-" + uuid4().hex
        email = mailbox + "@example.test"
        api("/auth/v1/user", token, method="PUT", body=dict(email=email))
        mail_url = status["MAILPIT_URL"]
        if urlparse(mail_url).hostname not in ("127.0.0.1", "localhost"):
            raise ValueError("Email verification must use local Mailpit")
        message = None
        for _ in range(30):
            with urlopen(mail_url + "/api/v1/search?query=" + quote("to:" + email),
                         timeout=5) as response:
                messages = json.load(response)["messages"]
            if messages:
                with urlopen(mail_url + "/api/v1/message/" + messages[0]["ID"],
                             timeout=5) as response:
                    message = json.load(response)
                break
            time.sleep(0.2)
        if message is None:
            raise ValueError("No local verification email")
        body = html.unescape(message.get("Text", "") + message.get("HTML", ""))
        link = re.search(r'https?://[^\s"<>]+/auth/v1/verify\?[^\s"<>]+', body)
        if not link or urlparse(link[0]).hostname not in ("localhost", "127.0.0.1"):
            raise ValueError("Expected local email verification link")

        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        try:
            build_opener(NoRedirect).open(link[0], timeout=20).close()
        except HTTPError as error:
            if error.code not in (302, 303):
                raise
        refreshed = api("/auth/v1/token?grant_type=refresh_token", method="POST",
                        body=dict(refresh_token=owner["refresh_token"]))
        assert refreshed["user"]["id"] == uid
        assert refreshed["user"]["email"] == email
        assert refreshed["user"]["is_anonymous"] is False
        for table, row in [("candidates", candidate), ("comparisons", comparison)]:
            assert api(f"/rest/v1/{table}?id=eq.{row['id']}",
                       refreshed["access_token"])[0]["user_id"] == uid
        result = dict(anonymous_sign_in=True, owner_rls=True, other_uid_denied=True,
                      score_inputs_schema="1.3", email_link_verified=True,
                      same_uid_after_upgrade=True, candidate_and_comparison_preserved=True,
                      scope="local Auth HTTP + Mailpit, not remote")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2))
        return result
    finally:
        for user in users:
            api("/auth/v1/admin/users/" + user["user"]["id"], admin, method="DELETE")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / ".local/validation/s3-1-auth.json")
    args = parser.parse_args()
    print(json.dumps(verify(args.output)))
