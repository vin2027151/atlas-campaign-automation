"""Link Accounts tests: storage permissions, write-only secrets, admin passphrase,
rate limit, OAuth state, data mode. Uses a temp ATLAS_SECRETS_DIR; never the real one.
Run from dashboard/: .venv/bin/python -m unittest tests.test_accounts -v
"""

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from accounts import platforms as P  # noqa: E402
from accounts import store as S  # noqa: E402
import api.accounts as A  # noqa: E402

PASS = "correct horse battery staple"
SECRET = "sk-very-secret-value-123456"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="atlas-acct-test-")
        self.dir = os.path.join(self.tmp, "secrets")
        self.env = mock.patch.dict(os.environ, {"ATLAS_SECRETS_DIR": self.dir})
        self.env.start()
        self.iters = mock.patch.object(S, "PBKDF2_ITERS", 1000)
        self.iters.start()
        A._fails.clear()
        A._states.clear()
        app = FastAPI()
        app.include_router(A.router)
        self.c = TestClient(app)

    def tearDown(self):
        self.env.stop()
        self.iters.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def hdr(self, key=PASS, ip="1.2.3.4"):
        return {"X-Admin-Key": key, "CF-Connecting-IP": ip}


class StorageTests(Base):
    def test_permissions_and_atomic_write(self):
        S.save_fields("google", {"client_secret": SECRET})
        self.assertEqual(stat.S_IMODE(os.stat(self.dir).st_mode), 0o700)
        f = os.path.join(self.dir, "credentials.json")
        self.assertEqual(stat.S_IMODE(os.stat(f).st_mode), 0o600)
        self.assertEqual([n for n in os.listdir(self.dir) if n.startswith(".")], [])
        self.assertFalse(self.dir.startswith(ROOT))

    def test_mask_and_public_status(self):
        self.assertEqual(S.mask("1234567890"), "••••7890")
        S.save_fields("google", {"client_secret": SECRET, "customer_id": "4445556666"})
        st = S.public_status("google", P.BY_ID["google"]["fields"])
        self.assertTrue(st["fields"]["client_secret"]["set"])
        self.assertIsNone(st["fields"]["client_secret"]["masked"])
        self.assertTrue(st["fields"]["customer_id"]["masked"].endswith("6666"))
        self.assertNotIn(SECRET, json.dumps(st))

    def test_passphrase_hash(self):
        with self.assertRaises(ValueError):
            S.set_admin_passphrase("short")
        S.set_admin_passphrase(PASS)
        raw = open(os.path.join(self.dir, "admin.json")).read()
        self.assertNotIn(PASS, raw)
        self.assertTrue(S.check_admin_passphrase(PASS))
        self.assertFalse(S.check_admin_passphrase("wrong passphrase!!"))
        self.assertFalse(S.check_admin_passphrase(None))

    def test_data_mode(self):
        self.assertEqual(S.get_data_mode(), "sample")
        with self.assertRaises(PermissionError):
            S.set_data_mode("live")
        S.set_status("meta", linked=True, tested_ok=True)
        S.set_data_mode("live")
        self.assertEqual(S.get_data_mode(), "live")
        S.unlink("meta")
        self.assertEqual(S.get_data_mode(), "sample")

    def test_oauth1_signature_rfc5849(self):
        # Example from RFC 5849 section 1.2 style inputs: signature must be stable and well-formed.
        h = P.oauth1_header("GET", "https://ads-api.x.com/12/accounts", {}, "ck", "cs", "at", "ats", nonce="n", ts="1")
        self.assertTrue(h.startswith("OAuth "))
        self.assertIn('oauth_signature="', h)
        self.assertEqual(h, P.oauth1_header("GET", "https://ads-api.x.com/12/accounts", {}, "ck", "cs", "at", "ats", nonce="n", ts="1"))


class ApiTests(Base):
    def test_read_side_open_and_readonly_without_passphrase(self):
        r = self.c.get("/api/accounts/")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertFalse(d["admin_set"])
        self.assertEqual(len(d["platforms"]), 5)
        self.assertTrue(all(p["requirements"] and p["docs"].startswith("https://") for p in d["platforms"]))
        r = self.c.post("/api/accounts/google/save", json={"fields": {"client_id": "x"}}, headers=self.hdr())
        self.assertEqual(r.status_code, 403)
        self.assertIn("set_admin_key", r.json()["error"])

    def test_write_requires_passphrase_and_secret_never_returned(self):
        S.set_admin_passphrase(PASS)
        r = self.c.post("/api/accounts/meta/save", json={"fields": {"app_secret": SECRET}}, headers=self.hdr("bad"))
        self.assertEqual(r.status_code, 401)
        r = self.c.post("/api/accounts/meta/save", json={"fields": {"app_secret": SECRET, "bogus": "x"}}, headers=self.hdr())
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(SECRET, r.text)
        self.assertNotIn(SECRET, self.c.get("/api/accounts/").text)
        self.assertNotIn("bogus", json.dumps(S._all()))

    def test_example_values_refused(self):
        S.set_admin_passphrase(PASS)
        r = self.c.post("/api/accounts/meta/save", json={"fields": {"app_secret": "EXAMPLE-APP-SECRET"}}, headers=self.hdr())
        self.assertEqual(r.status_code, 400)

    def test_rate_limit_per_cf_ip(self):
        S.set_admin_passphrase(PASS)
        for _ in range(A.FAIL_LIMIT):
            self.assertEqual(self.c.post("/api/accounts/verify", headers=self.hdr("nope", "9.9.9.9")).status_code, 401)
        self.assertEqual(self.c.post("/api/accounts/verify", headers=self.hdr(PASS, "9.9.9.9")).status_code, 429)
        self.assertEqual(self.c.post("/api/accounts/verify", headers=self.hdr(PASS, "8.8.8.8")).status_code, 200)

    def test_test_error_is_scrubbed(self):
        S.set_admin_passphrase(PASS)
        S.save_fields("meta", {"access_token": SECRET, "ad_account_id": "act_123"})
        S.set_status("meta", linked=True)
        with mock.patch.object(P, "_http", side_effect=P.LinkError("bad token %s" % SECRET)):
            r = self.c.post("/api/accounts/meta/test", headers=self.hdr())
        self.assertEqual(r.status_code, 400)
        self.assertNotIn(SECRET, r.text)
        self.assertNotIn(SECRET, self.c.get("/api/accounts/").text)

    def test_test_ok_unlocks_live_mode(self):
        S.set_admin_passphrase(PASS)
        S.save_fields("meta", {"access_token": SECRET, "ad_account_id": "act_123"})
        S.set_status("meta", linked=True)
        self.assertEqual(self.c.post("/api/accounts/mode", json={"mode": "live"}, headers=self.hdr()).status_code, 400)
        with mock.patch.object(P, "_http", return_value={"name": "Search Atlas", "account_status": 1}):
            r = self.c.post("/api/accounts/meta/test", headers=self.hdr())
        self.assertEqual(r.status_code, 200, r.text)
        r = self.c.post("/api/accounts/mode", json={"mode": "live"}, headers=self.hdr())
        self.assertEqual(r.json()["data_mode"], "live")
        self.assertEqual(self.c.post("/api/accounts/mode", json={"mode": "live"}).status_code, 401)

    def test_oauth_state_checked_against_session(self):
        S.set_admin_passphrase(PASS)
        S.save_fields("google", {"client_id": "abc.apps.googleusercontent.com", "client_secret": SECRET})
        r = self.c.post("/api/accounts/google/oauth/start", headers=self.hdr())
        self.assertEqual(r.status_code, 200)
        url = r.json()["url"]
        self.assertNotIn(SECRET, url)
        state = url.split("state=")[1].split("&")[0]
        sid = r.cookies.get(A.COOKIE)
        self.assertTrue(sid)
        # wrong session cookie -> refused, and the state is spent
        self.assertFalse(A.check_state(state, "other-session", "google"))
        self.assertFalse(A.check_state(state, sid, "google"))
        # fresh state, correct cookie, callback exchanges the code
        r = self.c.post("/api/accounts/google/oauth/start", headers=self.hdr())
        state = r.json()["url"].split("state=")[1].split("&")[0]
        with mock.patch.object(P, "_http", return_value={"refresh_token": "rt-123456789"}):
            r = self.c.get("/link-accounts/callback/google?code=c&state=" + state, allow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertIn("linked=1", r.headers["location"])
        self.assertTrue(S._platform("google").get("linked"))

    def test_oauth_state_expires(self):
        A._states["s1"] = {"platform": "meta", "sid": "x", "exp": 0}
        self.assertFalse(A.check_state("s1", "x", "meta"))


if __name__ == "__main__":
    unittest.main()
