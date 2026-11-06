"""Exact API requests, Campaigns-page direct controls, pacing and per-ad metrics.

Every test runs on a temp copy of data/state.json (tests.test_planning_core.sandbox),
so the real data is never written.
Run from dashboard/: .venv/bin/python -m unittest tests.test_direct_controls -v
"""

import copy
import json
import os
import sys
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("ATLAS_LLM_MODE", "stub")

import store  # noqa: E402
from planning import adapters, api_requests, changeset, direct, executor, snapshot  # noqa: E402
from tests.test_planning_core import _gc, _mc, _sample_changeset, sandbox  # noqa: E402

REDACTED = "Bearer ‹redacted›"


def _ad(kind_prefix):
    return [a for a in store.get_state()["ads"] if a["adset_id"].startswith(kind_prefix) and a["status"] == "ACTIVE"][0]


class RequestRendering(unittest.TestCase):
    def test_render_and_round_trip(self):
        with sandbox():
            snap = snapshot.build()
            doc, errs = changeset.parse(_sample_changeset(snap)[0])
            self.assertFalse(errs)
            reqs = api_requests.render_all(doc, snap)
            self.assertEqual([r["step"] for r in reqs], [1, 2, 3, 4, 5, 6])
            r1 = reqs[0]
            self.assertEqual(r1["url"], "https://googleads.googleapis.com/v26/customers/4445556666/campaignBudgets:mutate")
            self.assertEqual(r1["headers"]["Authorization"], REDACTED)
            self.assertEqual(r1["content_type"], "application/json")
            op = r1["body"]["operations"][0]
            self.assertEqual(op["updateMask"], "amountMicros")
            self.assertTrue(op["update"]["resourceName"].endswith("/campaignBudgets/201"))
            self.assertIn("${GOOGLE_ADS_ACCESS_TOKEN}", r1["curl"])
            self.assertNotIn("EXAMPLE", json.dumps(reqs))
            m = reqs[4]
            self.assertEqual(m["url"], "https://graph.facebook.com/v27.0/act_7778889999/adcreatives")
            self.assertEqual(m["content_type"], "application/x-www-form-urlencoded")
            self.assertEqual(m["depends_on"], ["op4"])
            self.assertIn("--data-urlencode", m["curl"])
            # every rendered request parses back into the op it came from
            for op_in, req in zip(doc["operations"], reqs):
                back = api_requests.to_op(req)
                self.assertEqual(back["platform"], op_in["platform"])
                if op_in["platform"] == "google":
                    self.assertEqual(back["service"], op_in["service"])
                    self.assertEqual(back.get("resource_name"), op_in.get("resource_name"))
                    if op_in.get("update_mask"):
                        self.assertEqual(back["update_mask"], op_in["update_mask"])
                else:
                    self.assertEqual(back["path"], op_in["path"])
            self.assertEqual(api_requests.to_op(reqs[3])["params"], {"media_id": "IMG-0002"})

    def test_publish_refuses_when_request_differs_from_reviewed(self):
        with sandbox():
            base = snapshot.pull()
            doc, _e = changeset.parse(_sample_changeset(base)[0])
            rows = changeset.dry_run(doc, base)["rows"]
            reviewed = executor.preview_requests(doc, base)
            tampered = copy.deepcopy(reviewed)
            tampered[1]["body"]["operations"][0]["update"]["status"] = "ENABLED"
            res = executor.publish(doc, rows, base["id"], expected_requests=tampered)
            self.assertFalse(res["ok"])
            self.assertEqual([d["op"] for d in res["drift"]], ["op2"])
            self.assertEqual(res["results"], [])
            self.assertEqual(store.campaign("g_search_nonbrand_uk")["status"], "ACTIVE")
            # the untouched reviewed requests publish, and the executed requests are those
            res = executor.publish(doc, rows, base["id"], expected_requests=reviewed)
            self.assertTrue(res["ok"], res)
            for q, r in zip(reviewed, res["results"]):
                self.assertEqual((r["request"]["url"], r["step"]), (q["url"], q["step"]))
            logs = [a for a in store.get_state()["activity"] if a["action"] == "api publish"]
            self.assertIn("campaignBudgets:mutate", logs[-6]["detail"])


class DirectControls(unittest.TestCase):
    def test_pause_shows_and_persists_then_undo(self):
        with sandbox():
            before = store.pacing()
            res = direct.apply({"kind": "campaign", "id": "g_search_brand_us", "action": "status",
                                "value": "PAUSED", "expected": "ACTIVE"})
            self.assertTrue(res["ok"] and res["applied"] and res["verified"], res)
            q = res["requests"][0]
            self.assertEqual(q["url"], "https://googleads.googleapis.com/v26/customers/4445556666/campaigns:mutate")
            self.assertEqual(q["body"]["operations"][0], {"update": {"resourceName": "customers/4445556666/campaigns/101",
                                                                     "status": "PAUSED"}, "updateMask": "status"})
            # persisted to state.json: a fresh read (another browser / process) sees it
            store.reload_state()
            self.assertEqual(store.campaign("g_search_brand_us")["status"], "PAUSED")
            with open(store.STATE_PATH) as fh:
                self.assertEqual([c for c in json.load(fh)["campaigns"] if c["id"] == "g_search_brand_us"][0]["status"], "PAUSED")
            # pacing moves at once: the paused campaign's daily budget leaves the projection
            after = store.pacing()
            self.assertAlmostEqual(before["projected_month_end"] - after["projected_month_end"],
                                   200.0 * after["days_remaining"], places=2)
            log = store.recent_activity(3)
            self.assertTrue(any(a["action"] == "api request" and "campaigns:mutate" in a["detail"] for a in log))
            # undo restores exactly
            undo = direct.apply(res["undo"]["actions"], confirm=True)
            self.assertTrue(undo["applied"])
            self.assertEqual(store.campaign("g_search_brand_us")["status"], "ACTIVE")
            self.assertEqual(store.pacing()["projected_month_end"], before["projected_month_end"])

    def test_conflict_when_another_browser_changed_it(self):
        with sandbox():
            res = direct.apply({"kind": "ad", "id": _ad("m_")["id"], "action": "status", "value": "PAUSED",
                                "expected": "PAUSED"})
            self.assertTrue(res["conflict"])
            self.assertFalse(res["applied"])

    def test_ads_pause_on_both_platforms(self):
        with sandbox():
            live = [a for a in store.get_state()["ads"] if a["status"] == "ACTIVE"]
            g_ad = [a for a in live if a["adset_id"].startswith("g_search_")][0]
            pmax = [a for a in live if a["adset_id"].startswith("g_pmax_")][0]
            m_ad = _ad("m_prospecting_core")
            for ad, url_part in ((g_ad, "adGroupAds:mutate"), (pmax, "assetGroupAssets:mutate"), (m_ad, "graph.facebook.com/v27.0/1202")):
                res = direct.apply({"kind": "ad", "id": ad["id"], "action": "status", "value": "PAUSED"})
                self.assertTrue(res["applied"], res)
                self.assertIn(url_part, res["requests"][0]["url"])
                self.assertEqual(store.ad(ad["id"])["status"], "PAUSED")
            rn = res["requests"][0]
            self.assertEqual(rn["body"], {"status": "PAUSED"})
            pm = direct.apply({"kind": "ad", "id": pmax["id"], "action": "status", "value": "ACTIVE"})
            self.assertTrue(pm["requests"][0]["body"]["operations"][0]["update"]["resourceName"].split("~")[-1]
                            in ("MARKETING_IMAGE", "YOUTUBE_VIDEO"))

    def test_budget_and_bid_with_guardrails(self):
        with sandbox():
            # +10% Google budget: no confirm needed, micros in the request
            res = direct.apply({"kind": "campaign", "id": "g_search_brand_us", "action": "budget", "value": 220})
            self.assertTrue(res["applied"], res)
            self.assertEqual(res["requests"][0]["body"]["operations"][0]["update"]["amountMicros"], 220000000)
            self.assertEqual(store.campaign("g_search_brand_us")["daily_budget"], 220.0)
            # +23% needs a confirm; nothing changes until then
            res = direct.apply({"kind": "campaign", "id": "m_prospecting_core", "action": "budget", "value": 900})
            camp0 = dict(store.campaign("m_prospecting_core"))
            self.assertTrue(res["needs_confirm"] and not res["applied"])
            self.assertEqual(len(res["requests"]), 2)   # ABO: one request per active ad set
            self.assertEqual(store.campaign("m_prospecting_core"), camp0)
            sets0 = [dict(a) for a in store.adsets_for("m_prospecting_core")]
            res = direct.apply({"kind": "campaign", "id": "m_prospecting_core", "action": "budget", "value": 900}, confirm=True)
            self.assertTrue(res["applied"])
            self.assertEqual(sorted(r["body"]["daily_budget"] for r in res["requests"]), [45000, 45000])
            self.assertEqual(sum(a["daily_budget"] for a in store.adsets_for("m_prospecting_core")), 900.0)
            self.assertAlmostEqual(store.campaign("m_prospecting_core")["daily_budget"], 900.0, delta=0.011)
            # undo restores the ad sets and the campaign's daily and monthly figures exactly
            direct.apply(res["undo"]["actions"], confirm=True)
            self.assertEqual(store.campaign("m_prospecting_core"), camp0)
            self.assertEqual([dict(a) for a in store.adsets_for("m_prospecting_core")], sets0)
            # errors are refused outright
            for bad in (-5, 0, "abc", 5):
                with self.assertRaises(store.BadInput):
                    direct.apply({"kind": "campaign", "id": "g_search_brand_uk", "action": "budget", "value": bad}, confirm=True)
            # bids: tCPA on Google (micros), cost cap on Meta (cents)
            res = direct.apply({"kind": "campaign", "id": "g_search_nonbrand_us", "action": "bid", "value": 300})
            self.assertEqual(res["requests"][0]["body"]["operations"][0]["updateMask"], "targetCpa.targetCpaMicros")
            self.assertEqual(store.campaign("g_search_nonbrand_us")["bid_strategy"], "Target CPA $300")
            res = direct.apply({"kind": "adset", "id": "m_retargeting_agency_14d__as1", "action": "bid", "value": 210})
            self.assertEqual(res["requests"][0]["body"], {"bid_amount": 21000})
            self.assertEqual(direct.controls()["m_retargeting_agency_14d__as1"]["bid"]["value"], 210.0)
            with self.assertRaises(store.BadInput):   # target impression share has no bid target
                direct.apply({"kind": "campaign", "id": "g_search_brand_us", "action": "bid", "value": 3})

    def test_live_mode_never_sends_without_the_gate(self):
        with sandbox():
            cfg = adapters.load_config()
            cfg["mode"] = "live"
            os.environ.pop("ATLAS_ALLOW_LIVE", None)
            real = adapters.load_config
            adapters.load_config = lambda: copy.deepcopy(cfg)
            try:
                orig_build = snapshot.build
                snapshot.build = lambda mode=None: orig_build("sample")
                try:
                    res = direct.apply({"kind": "campaign", "id": "g_search_brand_us", "action": "status", "value": "PAUSED"})
                finally:
                    snapshot.build = orig_build
            finally:
                adapters.load_config = real
            self.assertFalse(res["applied"])
            self.assertIn("ATLAS_ALLOW_LIVE", res["error"])
            self.assertEqual(store.campaign("g_search_brand_us")["status"], "ACTIVE")

    def test_concurrent_edits_do_not_corrupt_state(self):
        with sandbox():
            ids = [a["id"] for a in store.get_state()["ads"]][:12]
            errs = []

            def work(ad_id):
                try:
                    direct.apply({"kind": "ad", "id": ad_id, "action": "status", "value": "PAUSED"})
                except Exception as exc:  # pragma: no cover
                    errs.append(exc)
            ts = [threading.Thread(target=work, args=(i,)) for i in ids]
            [t.start() for t in ts]
            [t.join() for t in ts]
            self.assertEqual(errs, [])
            with open(store.STATE_PATH) as fh:
                data = json.load(fh)
            self.assertEqual(sum(1 for a in data["ads"] if a["id"] in ids and a["status"] == "PAUSED"), len(ids))


class PacingAndAdMetrics(unittest.TestCase):
    def test_projection_uses_current_daily_budgets(self):
        with sandbox():
            for pl in (None, "google", "meta"):
                p = store.pacing(pl)
                self.assertEqual(p["projection_basis"], "current_daily_budgets")
                self.assertAlmostEqual(p["projected_month_end"],
                                       p["month_to_date_spend"] + p["active_daily_budget"] * p["days_remaining"], places=2)
            g = store.active_daily_budget("google")
            self.assertAlmostEqual(g, sum(c["daily_budget"] for c in store.campaigns("google") if c["status"] == "ACTIVE"), 2)
            m0 = store.pacing("meta")["projected_month_end"]
            direct.apply({"kind": "adset", "id": "m_prospecting_core__as1", "action": "status", "value": "PAUSED"})
            m1 = store.pacing("meta")["projected_month_end"]
            self.assertAlmostEqual(m0 - m1, 366.67 * store.pacing("meta")["days_remaining"], places=1)

    def test_ad_splits_sum_to_adset_and_are_saved_once(self):
        def strip(state):
            for a in state["ads"]:
                a.pop("metrics_split", None)
        with sandbox():
            saved = [a.get("metrics_split") for a in store.get_state()["ads"]]
            store.mutate(strip)
            self.assertEqual(store.ensure_ad_splits(), len(store.get_state()["ads"]))
            if all(saved):  # what is saved in data/state.json is exactly the seeded generation
                self.assertEqual([a["metrics_split"] for a in store.get_state()["ads"]], saved)
            self.assertEqual(store.ensure_ad_splits(), 0)
            first = copy.deepcopy([a["metrics_split"] for a in store.get_state()["ads"]])
            by_set = {}
            for a in store.get_state()["ads"]:
                by_set.setdefault(a["adset_id"], []).append(a)
            for ads in by_set.values():
                for k in store.AD_SPLIT_KEYS:
                    self.assertAlmostEqual(sum(a["metrics_split"][k] for a in ads), 1.0, places=4)
            totals = {"spend": 1234.56, "impressions": 40000, "clicks": 900, "platform_conversions": 12.0, "trials": 7.4, "paid": 2.1}
            ads = by_set["m_prospecting_core__as1"]
            out = store.split_ad_metrics(totals, ads)
            self.assertAlmostEqual(sum(o["spend"] for o in out), 1234.56, places=2)
            self.assertEqual(len(set(round(o["cost_per_trial"] or 0, 2) for o in out)), len(out))  # own CPL each
            # deterministic: a fresh copy generates the same shares
        with sandbox():
            store.mutate(strip)
            store.ensure_ad_splits()
            self.assertEqual([a["metrics_split"] for a in store.get_state()["ads"]], first)

    def test_campaigns_api_rows_carry_ad_metrics_and_controls(self):
        with sandbox():
            from fastapi.testclient import TestClient
            import app as app_module
            client = TestClient(app_module.app)
            d = client.get("/api/campaigns/?window=7d").json()
            c = [x for x in d["campaigns"] if x["id"] == "m_retargeting_agency_14d"][0]
            self.assertEqual(c["controls"]["bid"]["label"], "Cost cap")
            aset = c["adsets"][0]
            self.assertEqual(aset["controls"]["bid"]["value"], 220.0)
            ad_sum = round(sum(a["metrics"]["spend"] for a in aset["ads"]), 2)
            self.assertAlmostEqual(ad_sum, aset["spend"], places=2)
            self.assertIn("Projected month-end at current daily budgets", json.dumps(d["summary"]))
            r = client.post("/api/campaigns/actions", json={"kind": "ad", "id": aset["ads"][0]["id"], "action": "status",
                                                           "value": "PAUSED", "expected": "ACTIVE"})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertTrue(r.json()["result"]["applied"])
            r = client.post("/api/campaigns/actions", json={"kind": "ad", "id": aset["ads"][0]["id"], "action": "status",
                                                           "value": "PAUSED", "expected": "ACTIVE"})
            self.assertEqual(r.status_code, 409)
            r = client.post("/api/campaigns/actions", json={"kind": "campaign", "id": c["id"], "action": "budget", "value": -1})
            self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
