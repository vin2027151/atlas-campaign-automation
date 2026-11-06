"""Planning API tests (llm agent): job lifecycle, draft/revise/publish, guards.

Runs with ATLAS_LLM_MODE=stub against temp copies of data/state.json, data/planning and
data/media.json; the real files are never written.
Run from dashboard/: .venv/bin/python -m unittest tests.test_planning_api -v   (or pytest)
"""

import json
import os
import shutil
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ["ATLAS_LLM_MODE"] = "stub"

import store  # noqa: E402

REAL_DATA = os.path.join(ROOT, "data")
_TMP = tempfile.mkdtemp(prefix="atlas-planning-test-")
TMP_DATA = os.path.join(_TMP, "data")


def _repoint(mod):
    """Point every module-level path constant under data/ at the temp copy."""
    for k, v in list(vars(mod).items()):
        if k.isupper() and isinstance(v, str) and v.startswith(REAL_DATA + os.sep):
            setattr(mod, k, TMP_DATA + v[len(REAL_DATA):])


def _setup_data():
    os.makedirs(TMP_DATA, exist_ok=True)
    shutil.copy(os.path.join(REAL_DATA, "state.json"), os.path.join(TMP_DATA, "state.json"))
    for name in ("planning", "plan"):
        src = os.path.join(REAL_DATA, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(TMP_DATA, name),
                            ignore=shutil.ignore_patterns("analyses.json", "changesets.json", "jobs.json",
                                                          "durations.json", "llm_calls.json"))
    if os.path.exists(os.path.join(REAL_DATA, "media.json")):
        shutil.copy(os.path.join(REAL_DATA, "media.json"), os.path.join(TMP_DATA, "media.json"))
    store.STATE_PATH = os.path.join(TMP_DATA, "state.json")
    store.reload_state()


_setup_data()

import planning  # noqa: E402
from planning import jobs, llm, records  # noqa: E402

for _m in [planning, records] + [m for n, m in list(sys.modules.items())
                                 if m is not None and (n.startswith("planning.") or n == "media" or n.startswith("media."))]:
    _repoint(_m)

from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402

# import-time module constants of anything app.py pulled in
for _n, _m in list(sys.modules.items()):
    if _m is not None and (_n.startswith("planning.") or _n == "media" or _n.startswith("media.")):
        _repoint(_m)

client = TestClient(app_module.app)
API = "/api/planning"


def wait_job(job_id, timeout=30.0):
    jobs.wait(job_id, timeout)
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = client.get("%s/jobs/%s" % (API, job_id)).json()["job"]
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.05)
    raise AssertionError("job %s did not finish" % job_id)


def fresh_records():
    """Empty planning records (jobs, analyses, changesets) between tests."""
    for name in (records.ANALYSES_FILE, records.CHANGESETS_FILE, records.JOBS_FILE, records.DURATIONS_FILE,
                 records.CALLS_FILE):
        p = records.path(name)
        if os.path.exists(p):
            os.unlink(p)


class PlanningApiTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        assert store.STATE_PATH.startswith(_TMP), store.STATE_PATH
        assert records.DATA_DIR.startswith(_TMP), records.DATA_DIR
        assert app_module.ROUTER_ERRORS.get("planning") is None, app_module.ROUTER_ERRORS.get("planning")

    def setUp(self):
        fresh_records()
        llm.STUB_DELAY_S = 0.2
        os.environ["ATLAS_LLM_MODE"] = "stub"

    # ------------------------------------------------------------ analyze

    def test_analyze_job_lifecycle(self):
        idx = client.get(API + "/").json()
        self.assertTrue(idx["ok"])
        self.assertEqual(idx["eta"], {"analyze": 20, "draft": 30, "revise": 25})
        self.assertIsNone(idx["busy"])
        self.assertEqual(idx["limits"]["max_chars"], 4000)

        r = client.post(API + "/analyze")
        self.assertEqual(r.status_code, 200, r.text)
        job = r.json()["job"]
        self.assertEqual(job["kind"], "analyze")
        self.assertIn(job["status"], ("queued", "running"))
        self.assertEqual(job["eta_seconds"], 20)

        done = wait_job(job["id"])
        self.assertEqual(done["status"], "done", done.get("error"))
        aid = done["result"]["analysis_id"]

        a = client.get(API + "/analyses/latest").json()["analysis"]
        self.assertEqual(a["id"], aid)
        self.assertEqual(client.get("%s/analyses/%s" % (API, aid)).json()["analysis"]["id"], aid)
        for key in ("items", "notes", "test_reads", "recommendations", "facts"):
            self.assertIsInstance(a[key], list, key)
        self.assertTrue(a["items"] and a["recommendations"])
        for it in a["items"]:
            for f in ("title", "plan", "running", "testing", "evidence", "recommendation"):
                self.assertIn(f, it)
        for rec in a["recommendations"]:
            self.assertIn(rec["priority"], ("high", "medium", "low"))
            self.assertIn(rec["platform"], ("google", "meta", "both"))
        self.assertEqual(a["effort"], "medium")
        self.assertTrue(a["snapshot_id"])
        self.assertEqual(client.get("%s/snapshots/%s" % (API, a["snapshot_id"])).json()["snapshot"]["id"],
                         a["snapshot_id"])
        y = client.get("%s/snapshots/%s/yaml" % (API, a["snapshot_id"]))
        self.assertEqual(y.status_code, 200)
        self.assertIn("yaml", y.headers["content-type"])

        idx = client.get(API + "/").json()
        self.assertEqual(idx["latest_analysis"]["id"], aid)
        self.assertLess(idx["eta"]["analyze"], 20)  # measured now
        self.assertEqual(idx["latest_snapshot"]["id"], a["snapshot_id"])
        self.assertEqual(client.get(API + "/analyses/AN-9999").status_code, 404)
        self.assertEqual(client.get(API + "/jobs/JOB-nope").status_code, 404)

    def test_busy_returns_409(self):
        llm.STUB_DELAY_S = 1.5
        first = client.post(API + "/analyze").json()["job"]
        r = client.post(API + "/analyze")
        self.assertEqual(r.status_code, 409)
        self.assertFalse(r.json()["ok"])
        r = client.post(API + "/changesets", json={"directive": "pause something", "media_ids": []})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(client.get(API + "/").json()["busy"]["id"], first["id"])
        self.assertEqual(wait_job(first["id"])["status"], "done")
        self.assertIsNone(client.get(API + "/").json()["busy"])

    def test_llm_not_configured(self):
        env = {k: v for k, v in os.environ.items() if k not in ("ATLAS_LLM_MODE", "ATLAS_LLM_CMD", "ANTHROPIC_API_KEY")}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(llm.mode(), "none")
            r = client.post(API + "/analyze")
            self.assertEqual(r.status_code, 200)
            j = wait_job(r.json()["job"]["id"])
            self.assertEqual(j["status"], "error")
            self.assertIn("LLM not configured", j["error"])
            r = client.post(API + "/changesets", json={"directive": "trim brand", "media_ids": []})
            j = wait_job(r.json()["job"]["id"])
            self.assertEqual(j["status"], "error")
            cs = client.get("%s/changesets/%s" % (API, r.json()["changeset"]["id"])).json()["changeset"]
            self.assertEqual(cs["status"], "invalid")
            self.assertIn("LLM not configured", cs["last_error"])
        self.assertIsNone(client.get(API + "/").json()["busy"])

    def test_input_limits_and_daily_cap(self):
        r = client.post(API + "/changesets", json={"directive": "x" * 4001})
        self.assertEqual(r.status_code, 400)
        r = client.post(API + "/changesets", json={"directive": "   "})
        self.assertEqual(r.status_code, 400)
        with mock.patch.object(jobs, "MAX_CALLS_PER_DAY", 0):
            r = client.post(API + "/analyze")
            self.assertEqual(r.status_code, 429)
            self.assertEqual(client.get(API + "/").json()["limits"]["calls_left_today"], 0)

    # --------------------------------------------- draft / revise / publish

    def _draft(self, directive="Trim Brand 10%, pause the worst Meta ad, add a negative, test IMG-0001"):
        media_ids = [a["id"] for a in jobs.approved_media() if a.get("kind") == "image"][:1]
        r = client.post(API + "/changesets", json={"directive": directive, "media_ids": media_ids})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["changeset"]["status"], "drafting")
        j = wait_job(body["job"]["id"])
        self.assertEqual(j["status"], "done", j.get("error"))
        self.assertEqual(j["result"], {"changeset_id": body["changeset"]["id"], "version": 1})
        return client.get("%s/changesets/%s" % (API, body["changeset"]["id"])).json()["changeset"]

    def test_draft_ready_revise_publish(self):
        cs = self._draft()
        v1 = cs["versions"][0]
        errors = [x for x in v1["validation"] if x["level"] == "error"]
        self.assertEqual(errors, [], v1["validation"])
        self.assertEqual(cs["status"], "ready")
        self.assertEqual(cs["current_version"], 1)
        self.assertNotIn("yaml", v1)
        self.assertEqual(json.loads(v1["changeset_json"])["changeset"]["based_on_snapshot"], v1["snapshot_id"])
        # every op is rendered as the exact HTTP request, numbered in run order
        reqs = v1["requests"]
        n_ops = len(json.loads(v1["changeset_json"])["operations"])
        self.assertEqual([q["step"] for q in reqs], list(range(1, n_ops + 1)))
        for q in reqs:
            self.assertEqual(q["method"], "POST")
            self.assertTrue(q["url"].startswith(("https://googleads.googleapis.com/v26/customers/4445556666/",
                                                 "https://graph.facebook.com/v27.0/")), q["url"])
            self.assertEqual(q["headers"]["Authorization"], "Bearer \u2039redacted\u203a")
            self.assertNotIn("EXAMPLE", json.dumps(q))
            self.assertIn("curl -X POST", q["curl"])
        self.assertTrue(v1["diff"]["rows"])
        self.assertNotIn("after", v1["diff"])
        self.assertTrue(v1["summary"])
        summ = client.get(API + "/changesets").json()["changesets"][0]
        self.assertEqual((summ["id"], summ["status"], summ["errors"]), (cs["id"], "ready", 0))

        # revise -> v2
        r = client.post("%s/changesets/%s/revise" % (API, cs["id"]), json={"text": "Cut brand a bit more."})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["changeset"]["status"], "drafting")
        j = wait_job(r.json()["job"]["id"])
        self.assertEqual(j["status"], "done", j.get("error"))
        self.assertEqual(j["result"]["version"], 2)
        cs = client.get("%s/changesets/%s" % (API, cs["id"])).json()["changeset"]
        self.assertEqual(cs["current_version"], 2)
        self.assertEqual(len(cs["versions"]), 2)
        self.assertEqual(cs["versions"][1]["revision_note"], "Cut brand a bit more.")
        self.assertEqual(cs["status"], "ready", cs["versions"][1]["validation"])
        self.assertNotEqual(cs["versions"][0]["changeset_json"], cs["versions"][1]["changeset_json"])
        self.assertNotEqual(cs["versions"][0]["requests"], cs["versions"][1]["requests"])

        url = "%s/changesets/%s/publish" % (API, cs["id"])
        # refusals: no confirm, confirm false, stale version, string version
        self.assertEqual(client.post(url, json={"version": 2}).status_code, 400)
        self.assertEqual(client.post(url, json={"version": 2, "confirm": False}).status_code, 400)
        self.assertEqual(client.post(url, json={"version": 2, "confirm": "yes"}).status_code, 400)
        r = client.post(url, json={"version": 1, "confirm": True})
        self.assertEqual(r.status_code, 400)
        self.assertIn("current version", r.json()["error"])
        self.assertEqual(client.post(url, json={"version": "2", "confirm": True}).status_code, 400)
        self.assertEqual(client.get("%s/changesets/%s" % (API, cs["id"])).json()["changeset"]["status"], "ready")

        r = client.post(url, json={"version": 2, "confirm": True})
        self.assertEqual(r.status_code, 200, r.text)
        pub = r.json()
        self.assertTrue(pub["ok"], pub["publish"])
        self.assertEqual(pub["publish"]["drift"], [])
        self.assertTrue(all(x["status"] == "applied" for x in pub["publish"]["results"]), pub["publish"]["results"])
        # what ran is what was reviewed (refs filled in from earlier responses)
        reviewed = cs["versions"][1]["requests"]
        for q, res in zip(reviewed, pub["publish"]["results"]):
            self.assertEqual((res["request"]["method"], res["request"]["url"]), (q["method"], q["url"]))
            if not q["depends_on"]:
                self.assertEqual(res["request"]["body"], q["body"])
        self.assertEqual(pub["changeset"]["status"], "published")
        self.assertEqual(pub["changeset"]["published"]["version"], 2)
        acts = [a["action"] for a in store.get_state()["activity"][-20:]]
        self.assertIn("planning.publish", acts)

        # published: no second publish, no revise, no discard
        self.assertEqual(client.post(url, json={"version": 2, "confirm": True}).status_code, 400)
        self.assertEqual(client.post("%s/changesets/%s/revise" % (API, cs["id"]), json={"text": "more"}).status_code, 400)
        self.assertEqual(client.post("%s/changesets/%s/discard" % (API, cs["id"])).status_code, 400)

    def test_publish_refuses_invalid_and_discarded(self):
        cs = self._draft("Trim brand")
        cs_id = cs["id"]
        # force the stored version invalid: publish must refuse
        stored = records.get_changeset(cs_id)
        stored["versions"][0]["validation"].append({"op": None, "level": "error", "message": "forced"})
        jobs._settle_status(stored)
        records.save_changeset(stored)
        self.assertEqual(stored["status"], "invalid")
        url = "%s/changesets/%s/publish" % (API, cs_id)
        self.assertEqual(client.post(url, json={"version": 1, "confirm": True}).status_code, 400)
        r = client.post("%s/changesets/%s/discard" % (API, cs_id))
        self.assertEqual(r.json()["changeset"]["status"], "discarded")
        self.assertEqual(client.post(url, json={"version": 1, "confirm": True}).status_code, 400)
        self.assertEqual(client.post(API + "/changesets/CS-9999/publish", json={"version": 1, "confirm": True}).status_code, 404)

    def test_repair_round_on_validation_errors(self):
        from planning import fixtures
        real = fixtures.changeset
        calls = {"n": 0}

        def flaky(*a, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps({"changeset": {"title": "bad", "based_on_snapshot": "SNAP-x"},
                                   "operations": [{"ref": "op1", "platform": "google", "service": "NopeService",
                                                   "method": "mutateNope", "operation": "update",
                                                   "resource_name": "customers/0/nope/1", "fields": {"x": 1}}],
                                   "summary": ["bad"], "assumptions": [], "questions": []})
            return real(*a, **kw)

        with mock.patch.object(fixtures, "changeset", flaky):
            cs = self._draft("Trim brand")
        self.assertEqual(calls["n"], 2)
        v = cs["versions"][0]
        self.assertTrue(v["repaired"])
        self.assertEqual(cs["status"], "ready", v["validation"])

    def test_llm_never_imports_anthropic_in_server(self):
        self.assertNotIn("anthropic", sys.modules)
        self.assertEqual(llm.parse_json('x ```json\n{"a": 1}\n``` y'), {"a": 1})
        self.assertIsNone(llm.parse_json("no json"))


if __name__ == "__main__":
    unittest.main()
