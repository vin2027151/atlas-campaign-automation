"""Stress test for the Campaigns-page direct controls (POST /api/campaigns/actions).

Random sequences (fixed seeds) of status / budget / bid changes on campaigns, ad sets /
ad groups / asset groups and ads / assets on both platforms (legacy Meta campaigns and
PMax included), with rapid toggles, undo of the latest step, undo out of order, stale
``expected`` values (409), the needs_confirm -> confirm path and invalid values. After
every step the invariants below are checked through the HTTP endpoints, against what
is on disk in state.json:

1. Status agrees across /api/campaigns/ (campaign, ad set and ad rows), the summary
   counts, a campaign detail, Reporting, Management, Plan & Adapt facts and the Quick
   Chat context document.
2. Pacing: projected month-end = MTD spend + days_remaining x sum of effective daily
   budgets, where a campaign's effective budget is 0 unless it is ACTIVE and at least
   one ad set delivers (ACTIVE with an ACTIVE ad, if it has ads); a Meta campaign with
   ad-set budgets (ABO) counts only its delivering ad sets' budgets. Money is summed in
   whole cents. The same figures show on Campaigns, Home, Reporting, Management,
   Plan & Adapt facts and Quick Chat.
3. Ad metrics add up to their ad set, ad sets to their campaign, metric by metric.
4. Every applied change has an "api request" activity entry per rendered request, the
   request carries the change's new value, and anything not applied leaves state.json
   byte-identical.

Plus: undoing everything restores state.json (apart from the activity log) byte for
byte; concurrent posts leave state.json valid and consistent; a Plan & Adapt draft made
before a direct edit is refused at publish for drift.

All of it runs on temp copies (tests.test_planning_core.sandbox); data/state.json is
never written. ATLAS_LLM_MODE=stub: no LLM call is ever made.
Run from dashboard/: .venv/bin/python -m unittest tests.test_control_stress -v
Longer run: ATLAS_STRESS_STEPS=600 .venv/bin/python -m unittest tests.test_control_stress
"""

import calendar
import copy
import json
import os
import random
import re
import sys
import tempfile
import threading
import time
import unittest
from datetime import date
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ["ATLAS_LLM_MODE"] = "stub"

import store  # noqa: E402
from planning import api_requests, direct, llm  # noqa: E402
from tests.test_planning_core import sandbox  # noqa: E402

STEPS = int(os.environ.get("ATLAS_STRESS_STEPS", "160"))
SEEDS = (20261106, 7, 1234)


def cents(v):
    return int(round(float(v or 0) * 100))


def usd0(v):
    return "${:,.0f}".format(float(v))


# ---------------------------------------------------------- independent model
# What the invariants expect, computed straight from state.json on disk (not via store).

def disk():
    with open(store.STATE_PATH, "rb") as fh:
        raw = fh.read()
    return raw, json.loads(raw.decode("utf-8"))


def model(state):
    sets_by_c, ads_by_s = {}, {}
    for a in state["adsets"]:
        sets_by_c.setdefault(a["campaign_id"], []).append(a)
    for ad in state["ads"]:
        ads_by_s.setdefault(ad["adset_id"], []).append(ad)

    def delivers(s):
        ads = ads_by_s.get(s["id"], [])
        return s["status"] == "ACTIVE" and (not ads or any(x["status"] == "ACTIVE" for x in ads))

    eff = {}
    for c in state["campaigns"]:
        sets = sets_by_c.get(c["id"], [])
        abo = c["platform"] == "meta" and any(s.get("daily_budget") is not None for s in sets)
        live = [s for s in sets if delivers(s)]
        if c["status"] != "ACTIVE" or (sets and not live):
            eff[c["id"]] = 0
        elif abo:
            eff[c["id"]] = sum(cents(s["daily_budget"]) for s in live)
        else:
            eff[c["id"]] = cents(c["daily_budget"])
    today = state["meta"]["today"]
    t = date(int(today[:4]), int(today[5:7]), int(today[8:10]))
    remaining = calendar.monthrange(t.year, t.month)[1] - t.day
    out = {"remaining": remaining, "eff": eff}
    for pl in (None, "google", "meta"):
        ids = set(c["id"] for c in state["campaigns"] if pl is None or c["platform"] == pl)
        mtd = sum(cents(r["spend"]) for r in state["daily"]
                  if r["campaign_id"] in ids and today[:8] + "01" <= r["date"] <= today)
        daily = sum(eff[i] for i in ids)
        out[pl or "account"] = {"daily": daily / 100.0, "mtd": mtd / 100.0,
                                "projected": (mtd + daily * remaining) / 100.0}
    return out


def strip_activity(state):
    s = copy.deepcopy(state)
    s.pop("activity", None)
    return json.dumps(s, indent=1, ensure_ascii=False)


# ------------------------------------------------------------- request values

def req_value(q):
    """(field, value) a rendered direct-control request carries, in dashboard units."""
    body = q["body"]
    if "googleads.googleapis.com" in q["url"]:
        upd = body["operations"][0]["update"]
        if "status" in upd:
            return "status", "ACTIVE" if upd["status"] == "ENABLED" else upd["status"]
        if "amountMicros" in upd:
            return "budget", int(str(upd["amountMicros"])) / 1e6
        if "cpcBidMicros" in upd:
            return "bid", int(str(upd["cpcBidMicros"])) / 1e6
        for k in ("targetCpa", "maximizeConversions"):
            if k in upd:
                m = int(str(upd[k]["targetCpaMicros"]))
                return "bid", (m / 1e6) if m else None
        raise AssertionError("unknown google request %s" % q)
    if "status" in body:
        return "status", body["status"]
    if "daily_budget" in body:
        return "budget", int(str(body["daily_budget"])) / 100.0
    if "bid_amount" in body:
        return "bid", int(str(body["bid_amount"])) / 100.0
    raise AssertionError("unknown meta request %s" % q)


class Harness(object):
    def __init__(self, tc, client):
        self.tc = tc
        self.client = client
        self.from_plan = None

    # ------------------------------------------------------------ http
    def index(self):
        r = self.client.get("/api/campaigns/?window=mtd")
        self.tc.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def post(self, body):
        return self.client.post("/api/campaigns/actions", json=body)

    def entities(self, idx=None):
        idx = idx or self.index()
        out = []
        for c in idx["campaigns"]:
            out.append(("campaign", c))
            for a in c["adsets"]:
                out.append(("adset", a))
                for ad in a["ads"]:
                    out.append(("ad", ad))
        return out

    # ------------------------------------------------------- invariants
    def check(self, where=""):
        tc = self.tc
        raw, state = disk()
        m = model(state)
        idx = self.index()
        msg = " (%s)" % where

        # 1. status everywhere ------------------------------------------------
        camp = dict((c["id"], c) for c in state["campaigns"])
        sets = dict((a["id"], a) for a in state["adsets"])
        ads = dict((a["id"], a) for a in state["ads"])
        rows = dict((c["id"], c) for c in idx["campaigns"])
        tc.assertEqual(set(rows), set(camp), msg)
        for cid, row in rows.items():
            tc.assertEqual(row["status"], camp[cid]["status"], cid + msg)
            for a in row["adsets"]:
                tc.assertEqual(a["status"], sets[a["id"]]["status"], a["id"] + msg)
                for ad in a["ads"]:
                    tc.assertEqual(ad["status"], ads[ad["id"]]["status"], ad["id"] + msg)
        n_active = sum(1 for c in camp.values() if c["status"] == "ACTIVE")
        s = idx["summary"]
        tc.assertEqual((s["active"], s["paused"]), (n_active, len(camp) - n_active), msg)
        for pl in ("google", "meta"):
            mine = [c for c in camp.values() if c["platform"] == pl]
            p = s["platforms"][pl]
            tc.assertEqual(p["active"], sum(1 for c in mine if c["status"] == "ACTIVE"), pl + msg)
            tc.assertEqual(p["paused"], sum(1 for c in mine if c["status"] == "PAUSED"), pl + msg)
        one = random.Random(len(raw)).choice(sorted(camp))
        det = self.client.get("/api/campaigns/%s" % one).json()
        tc.assertEqual(det["campaign"]["status"], camp[one]["status"], one + msg)
        tc.assertEqual([a["status"] for a in det["adsets"]], [sets[a["id"]]["status"] for a in det["adsets"]], msg)

        rep = self.client.get("/api/reporting/").json()
        for r in rep["campaigns"]:
            tc.assertEqual(r["status"], camp[r["id"]]["status"], "reporting " + r["id"] + msg)
        mg = self.client.get("/api/management/").json()["in_play"]
        in_play = set(c["id"] for g in mg["groups"] for c in g["campaigns"])
        paused = set(c["id"] for c in mg["paused"])
        tc.assertEqual(in_play, set(i for i, c in camp.items() if c["status"] == "ACTIVE"), "management" + msg)
        tc.assertEqual(paused, set(i for i, c in camp.items() if c["status"] != "ACTIVE"), "management" + msg)

        facts = self.client.get("/api/planning/facts").json()
        if self.from_plan is None:
            from planning import plan_compare
            plan = plan_compare.load_plan()
            names = set(pc["name"] for k in ("google_campaigns", "meta_campaigns") for pc in plan.get(k) or [])
            self.from_plan = set(i for i, c in camp.items() if c["name"] in names)
        flagged = set(f["campaign_id"] for f in facts["facts"]
                      if f["kind"] == "status_mismatch" and f["note"] == "planned to run; paused in the account")
        tc.assertEqual(flagged, set(i for i in self.from_plan if camp[i]["status"] == "PAUSED"), "facts" + msg)

        ctx = self.client.get("/api/chat/context").text
        for c in camp.values():
            shown = "ENABLED" if (c["platform"] == "google" and c["status"] == "ACTIVE") else c["status"]
            pat = r"\| %s \| %s(?: \(legacy\))? \| %s \|" % ("Google" if c["platform"] == "google" else "Meta",
                                                            re.escape(c["name"]), shown)
            tc.assertRegex(ctx, pat, "quick chat status " + c["id"] + msg)

        # 2. pacing everywhere ------------------------------------------------
        for key, pl in (("account", None), ("google", "google"), ("meta", "meta")):
            exp = m[key]
            blk = s["account"] if key == "account" else s["platforms"][key]
            tc.assertAlmostEqual(blk["projected_month_end"], exp["projected"], places=2, msg=key + msg)
            tc.assertAlmostEqual(blk["month_to_date_spend"], exp["mtd"], places=2, msg=key + msg)
            tc.assertEqual(blk["days_remaining"], m["remaining"], msg)
            tc.assertAlmostEqual(blk["pacing_daily_budget"], exp["daily"], places=2, msg=key + msg)
            tc.assertAlmostEqual(blk["active_daily_budget"], exp["daily"], places=2, msg=key + msg)
            rp = [p for p in rep["pacing"] if p["key"] == (pl or "total")][0]
            tc.assertAlmostEqual(rp["active_daily_budget"], exp["daily"], places=2, msg="reporting " + key + msg)
            tc.assertAlmostEqual(rp["projected_month_end"], exp["projected"], places=2, msg="reporting " + key + msg)
            fk = "all" if key == "account" else key
            tc.assertAlmostEqual(facts["totals"][fk]["daily_budget"], exp["daily"], places=2, msg="facts " + key + msg)
            tc.assertAlmostEqual(facts["pacing"][fk]["projected_month_end"], exp["projected"], places=2,
                                 msg="facts " + key + msg)
            qline = {"account": "All", "google": "Google", "meta": "Meta"}[key]
            tc.assertIn("- %s: MTD spend %s" % (qline, usd0(exp["mtd"])), ctx, msg)
            tc.assertRegex(ctx, r"- %s: .*projected month end at current daily budgets %s \(enabled daily budgets %s/day\)"
                           % (qline, re.escape(usd0(exp["projected"])), re.escape(usd0(exp["daily"]))), key + msg)
        for g in mg["groups"]:
            tc.assertAlmostEqual(g["totals"]["daily_budget"], m[g["platform"]]["daily"], places=2, msg="mgmt" + msg)
        for c in idx["campaigns"]:
            tc.assertAlmostEqual(c["effective_daily_budget"], m["eff"][c["id"]] / 100.0, places=2, msg=c["id"] + msg)
            ctl = (c.get("controls") or {}).get("budget")
            if ctl:
                tc.assertAlmostEqual(ctl["value"], c["daily_budget"], places=2, msg=c["id"] + msg)
        home = self.client.get("/").text
        tc.assertIn("%s projected month-end" % usd0(m["account"]["projected"]), home, msg)
        for pl, label in (("google", "Google"), ("meta", "Meta")):
            row = re.search(r"</span> %s</td>(.*?)</tr>" % label, home, re.S).group(1)
            nums = re.findall(r'class="num"[^>]*>([^<]+)</td>', row)
            tc.assertEqual(nums[1:3], [usd0(m[pl]["daily"]), usd0(m[pl]["projected"])], "home " + pl + msg)

        # 3. metrics add up -------------------------------------------------
        for c in idx["campaigns"]:
            if not c["adsets"]:
                continue
            for k in ("spend", "clicks", "trials", "paid", "platform_conversions", "impressions"):
                total = sum(cents(a[k]) for a in c["adsets"])
                tc.assertEqual(total, cents(c[k]), "%s %s sets%s" % (c["id"], k, msg))
            for a in c["adsets"]:
                if not a["ads"]:
                    continue
                for k in ("spend", "clicks", "trials", "paid", "platform_conversions", "impressions"):
                    total = sum(cents(ad["metrics"][k]) for ad in a["ads"])
                    tc.assertEqual(total, cents(a[k]), "%s %s ads%s" % (a["id"], k, msg))
        return raw, state

    def check_applied(self, res, before_activity_len):
        """Invariant 4 for an applied result."""
        r = res["result"]
        _raw, state = disk()
        new = state["activity"][before_activity_len:] if before_activity_len <= len(state["activity"]) else state["activity"]
        api_lines = [a["detail"] for a in new if a["action"] == "api request"]
        self.tc.assertEqual(api_lines, [api_requests.log_line(q) for q in r["requests"]])
        self.tc.assertEqual(len(r["requests"]), len(r["changes"]))
        for q, ch in zip(r["requests"], r["changes"]):
            field, val = req_value(q)
            self.tc.assertEqual(field, ch["field"])
            if isinstance(val, float) or isinstance(ch["after"], float):
                self.tc.assertAlmostEqual(val, ch["after"], places=2)
            else:
                self.tc.assertEqual(val, ch["after"])
            self.tc.assertTrue(r["verified"], r)


# ------------------------------------------------------------------- the tests

class RandomSequences(unittest.TestCase):
    def setUp(self):
        self.assertEqual(llm.mode(), "stub")

    def _walk(self, seed, steps):
        from fastapi.testclient import TestClient
        import app as app_module
        rng = random.Random(seed)
        h = Harness(self, TestClient(app_module.app))
        start_raw, start_state = h.check("start")
        # the comparison below is a true byte comparison: state.json is written this way
        self.assertEqual(json.dumps(start_state, indent=1, ensure_ascii=False) + "\n", start_raw.decode("utf-8"))
        overlay0 = json.load(open(os.path.join(sorted_planning_dir(), "account_overlay.json")))
        stack = []  # applied, not yet undone: {"actions", "token", "fields"}
        stats = dict.fromkeys(("applied", "confirm", "conflict", "invalid", "undo", "undo_ooo", "undo_409",
                               "rapid", "noop", "refused"), 0)

        def current(eid, field):
            ctl = direct.controls().get(eid) or {}
            return ctl.get("status") if field == "status" else (ctl.get(field) or {}).get("value")

        def unchanged(raw_before, resp, code):
            self.assertEqual(resp.status_code, code, resp.text)
            self.assertEqual(disk()[0], raw_before, "a refused request changed state.json")

        def send(body, confirm_rate=0.7, label=""):
            """Post one change; follow needs_confirm; record what applied. Returns the result or None."""
            raw0, st0 = disk()
            n0 = len(st0["activity"])
            r = h.post(body)
            if r.status_code == 409:
                unchanged(raw0, r, 409)
                stats["conflict"] += 1
                return None
            if r.status_code in (400, 404):
                unchanged(raw0, r, r.status_code)
                stats["refused"] += 1
                return None
            self.assertEqual(r.status_code, 200, r.text)
            res = r.json()
            out = res["result"]
            if out.get("needs_confirm"):
                self.assertTrue(self.guarded, "guardrails off: a change must apply on the first click")
                self.assertFalse(out["applied"])
                self.assertEqual(out["undo"]["actions"], [], "an unapplied change must not offer an undo")
                self.assertTrue(out["warnings"])
                self.assertEqual(disk()[0], raw0, "needs_confirm changed state.json")
                if rng.random() > confirm_rate:
                    return None
                stats["confirm"] += 1
                r = h.post(dict(body, confirm=True))
                self.assertEqual(r.status_code, 200, r.text)
                res = r.json()
                out = res["result"]
            if not out["applied"]:
                self.assertEqual(out.get("message"), "nothing to change", out)
                self.assertEqual(disk()[0], raw0)
                stats["noop"] += 1
                return None
            h.check_applied(res, n0)
            stats["applied"] += 1
            if out["undo"]["actions"]:
                stack.append({"actions": out["undo"]["actions"], "token": out["undo"]["token"],
                              "fields": set((a["id"], a["action"]) for a in out["undo"]["actions"])})
            return out

        def undo(i):
            e = stack[i]
            later = stack[i + 1:]
            overlap = any(e["fields"] & x["fields"] for x in later)
            if overlap and all(direct._same(current(a["id"], a["action"]), a["expected"]) for a in e["actions"]):
                return  # values coincide by chance; undoing it now would break the final round trip
            raw0, st0 = disk()
            r = h.post({"actions": e["actions"], "confirm": True, "undo_token": e["token"]})
            if overlap:
                unchanged(raw0, r, 409)   # a later change moved it: stale, refused
                stats["undo_409"] += 1
                return
            self.assertEqual(r.status_code, 200, r.text)
            res = r.json()
            self.assertTrue(res["result"]["applied"], res["result"])
            self.assertFalse(res["result"]["needs_confirm"], "undo must never wait for a confirm")
            h.check_applied(res, len(st0["activity"]))
            stack.pop(i)
            stats["undo" if i == len(stack) else "undo_ooo"] += 1

        for step in range(steps):
            ents = h.entities()
            roll = rng.random()
            kind, ent = rng.choice(ents)
            ctl = ent.get("controls") or {}
            if roll < 0.32:  # status toggle, sometimes with a stale expected
                nxt = "PAUSED" if ent["status"] == "ACTIVE" else "ACTIVE"
                stale = rng.random() < 0.12
                send({"kind": kind, "id": ent["id"], "action": "status", "value": nxt,
                      "expected": nxt if stale else ent["status"]})
                if stale:
                    self.assertEqual(current(ent["id"], "status"), ent["status"])
            elif roll < 0.40:  # rapid toggles: several flips back to back, no checks between
                stats["rapid"] += 1
                st = ent["status"]
                for _ in range(rng.randint(2, 5)):
                    nxt = "PAUSED" if st == "ACTIVE" else "ACTIVE"
                    if send({"kind": kind, "id": ent["id"], "action": "status", "value": nxt, "expected": st}):
                        st = nxt
                self.assertEqual(current(ent["id"], "status"), st)
            elif roll < 0.62:  # budget
                b = ctl.get("budget")
                cands = [(k, e) for k, e in ents if ((e.get("controls") or {}).get("budget") or {}).get("editable")]
                if not cands:
                    continue
                kind, ent = rng.choice(cands)
                b = ent["controls"]["budget"]
                val = round(b["value"] * rng.choice([0.05, 0.45, 0.7, 0.85, 0.95, 1.05, 1.1, 1.15, 1.3, 1.45, 1.6, 3.0]), 2)
                stale = rng.random() < 0.08
                send({"kind": kind, "id": ent["id"], "action": "budget", "value": val,
                      "expected": round(b["value"] + 1, 2) if stale else b["value"]})
            elif roll < 0.72:  # bid
                cands = [(k, e) for k, e in ents if ((e.get("controls") or {}).get("bid") or {}).get("editable")]
                kind, ent = rng.choice(cands)
                bid = ent["controls"]["bid"]
                base = bid["value"] or 200.0
                val = round(base * rng.choice([0.6, 0.85, 0.95, 1.1, 1.3]), 2)
                send({"kind": kind, "id": ent["id"], "action": "bid", "value": val, "expected": bid["value"]})
            elif roll < 0.82:  # invalid input: refused, nothing written
                stats["invalid"] += 1
                bad = rng.choice([
                    {"kind": kind, "id": ent["id"], "action": "budget", "value": rng.choice([-5, 0, "abc", None, True, "nan"])},
                    {"kind": kind, "id": ent["id"], "action": "bid", "value": rng.choice([-1, "x", 0])},
                    {"kind": kind, "id": ent["id"], "action": "status", "value": rng.choice(["MAYBE", "", None, "REMOVED"])},
                    {"kind": "ad", "id": ent["id"], "action": "budget", "value": 50} if kind == "ad" else
                    {"kind": "campaign", "id": "nope_%d" % step, "action": "status", "value": "PAUSED"},
                    {"kind": "thing", "id": ent["id"], "action": "status", "value": "PAUSED"},
                    {"kind": kind, "id": ent["id"], "action": "explode", "value": 1},
                    {"actions": [], "confirm": True},
                ])
                raw0 = disk()[0]
                r = h.post(bad)
                self.assertIn(r.status_code, (400, 404, 409), r.text)
                self.assertEqual(disk()[0], raw0)
            elif stack:
                if rng.random() < 0.6:
                    undo(len(stack) - 1)
                else:
                    undo(rng.randrange(len(stack)))
            h.check("seed %s step %d" % (seed, step))

        # undo whatever is left, newest first: state.json is back byte for byte (apart from activity)
        while stack:
            undo(len(stack) - 1)
        end_raw, end_state = h.check("after full undo")
        self.assertEqual(strip_activity(end_state), strip_activity(start_state))
        self.assertEqual(json.load(open(os.path.join(sorted_planning_dir(), "account_overlay.json"))), overlay0)
        for k in ("applied", "undo", "invalid"):
            self.assertGreater(stats[k], 0, stats)
        return stats

    def test_random_sequences(self):
        """As configured (guardrails off: nothing waits for a confirm), then one seed with the
        guardrail layer switched on (needs_confirm -> confirm path, step-limit refusals)."""
        total = {}
        for seed in SEEDS:
            with sandbox():
                self.guarded = False
                st = self._walk(seed, STEPS)
            self.assertEqual(st["confirm"], 0, "guardrails off: nothing may wait for a confirm")
            for k, v in st.items():
                total[k] = total.get(k, 0) + v
        for k in ("conflict", "undo_ooo", "undo_409", "rapid", "invalid"):
            self.assertGreater(total[k], 0, total)
        with sandbox(), mock.patch.object(direct, "guardrails_on", lambda cfg=None: True):
            self.guarded = True
            on = self._walk(SEEDS[0] + 1, STEPS)
        self.assertGreater(on["confirm"], 0, on)
        self.assertGreater(on["refused"], 0, on)  # step-limit / minimum refusals when guardrails are on
        print("\n  control stress: guardrails off %d seeds x %d steps %s; guardrails on 1 x %d %s"
              % (len(SEEDS), STEPS, total, STEPS, on))


def sorted_planning_dir():
    import planning
    return planning.DATA_DIR


class ReportedBug(unittest.TestCase):
    """Vin: paused campaigns cut pacing, re-enabling did not bring it back."""

    def test_reenable_and_undo_restore_pacing_without_confirm(self):
        from fastapi.testclient import TestClient
        import app as app_module
        with sandbox():
            c = TestClient(app_module.app)
            p0 = c.get("/api/campaigns/").json()["summary"]["account"]
            r = c.post("/api/campaigns/actions", json={"kind": "campaign", "id": "m_prospecting_core",
                                                      "action": "status", "value": "PAUSED", "expected": "ACTIVE"}).json()
            self.assertTrue(r["result"]["applied"])
            self.assertAlmostEqual(r["result"]["pacing"]["before"] - r["result"]["pacing"]["after"], 733.34, places=2)
            p1 = r["summary"]["account"]
            self.assertAlmostEqual(p0["projected_month_end"] - p1["projected_month_end"], 733.34 * p1["days_remaining"], places=2)
            # re-enable is a status flip: no total-rise confirm, pacing comes back exactly
            r2 = c.post("/api/campaigns/actions", json={"kind": "campaign", "id": "m_prospecting_core",
                                                       "action": "status", "value": "ACTIVE", "expected": "PAUSED"}).json()
            self.assertTrue(r2["result"]["applied"], r2["result"])
            self.assertFalse(r2["result"]["needs_confirm"])
            self.assertEqual(r2["summary"]["account"]["projected_month_end"], p0["projected_month_end"])
            # pause again, then Undo (the toast's token): pacing back, no confirm
            r3 = c.post("/api/campaigns/actions", json={"kind": "campaign", "id": "m_prospecting_core",
                                                       "action": "status", "value": "PAUSED", "expected": "ACTIVE"}).json()
            u = r3["result"]["undo"]
            r4 = c.post("/api/campaigns/actions", json={"actions": u["actions"], "undo_token": u["token"], "confirm": True}).json()
            self.assertTrue(r4["result"]["applied"])
            self.assertEqual(r4["summary"]["account"]["projected_month_end"], p0["projected_month_end"])
            # the 1-cent case: one figure for Meta's daily budgets on every key
            m = r4["summary"]["platforms"]["meta"]
            self.assertEqual(m["active_daily_budget"], m["pacing_daily_budget"])
            row = [x for x in c.get("/api/campaigns/").json()["campaigns"] if x["id"] == "m_prospecting_core"][0]
            self.assertEqual(row["daily_budget"], 733.34)   # = 366.67 + 366.67, the ad sets are the truth
            self.assertEqual(row["controls"]["budget"]["value"], 733.34)

    def test_undo_restores_even_past_the_step_limit_and_clears_a_new_target(self):
        from fastapi.testclient import TestClient
        import app as app_module
        with sandbox(), mock.patch.object(direct, "guardrails_on", lambda cfg=None: True):
            c = TestClient(app_module.app)
            raw0 = disk()[1]
            r = c.post("/api/campaigns/actions", json={"kind": "campaign", "id": "g_search_brand_us", "action": "budget",
                                                      "value": 120, "expected": 200, "confirm": True}).json()["result"]
            self.assertTrue(r["applied"])
            # without the token the +67% way back is refused by the per-change limit...
            plain = c.post("/api/campaigns/actions", json={"actions": r["undo"]["actions"], "confirm": True})
            self.assertEqual(plain.status_code, 400)
            # ...a forged token does not help...
            forged = c.post("/api/campaigns/actions", json={"actions": r["undo"]["actions"], "confirm": True,
                                                           "undo_token": "0" * 32})
            self.assertEqual(forged.status_code, 400)
            # ...the issued token for exactly these actions restores it, once
            ok = c.post("/api/campaigns/actions", json={"actions": r["undo"]["actions"], "confirm": True,
                                                       "undo_token": r["undo"]["token"]}).json()["result"]
            self.assertTrue(ok["applied"])
            # first-ever target CPA on a Maximize conversions campaign: undo clears it again
            r = c.post("/api/campaigns/actions", json={"kind": "campaign", "id": "g_search_nonbrand_uk", "action": "bid",
                                                      "value": 250, "confirm": True}).json()["result"]
            self.assertEqual(store.campaign("g_search_nonbrand_uk")["bid_strategy"], "Maximize conversions (target CPA $250)")
            ok = c.post("/api/campaigns/actions", json={"actions": r["undo"]["actions"], "confirm": True,
                                                       "undo_token": r["undo"]["token"]}).json()["result"]
            self.assertTrue(ok["applied"], ok)
            self.assertIsNone(direct.controls()["g_search_nonbrand_uk"]["bid"]["value"])
            self.assertEqual(strip_activity(disk()[1]), strip_activity(raw0))

    def test_full_control_applies_on_first_click(self):
        """Guardrails off (config/platforms.yaml, Vin 2026-11-06): +200% budget and a re-enable
        apply at once with no confirm; only invalid data and stale values are refused."""
        from fastapi.testclient import TestClient
        import app as app_module
        with sandbox():
            self.assertFalse(direct.guardrails_on())
            c = TestClient(app_module.app)
            r = c.post("/api/campaigns/actions", json={"kind": "campaign", "id": "g_search_brand_us", "action": "budget",
                                                      "value": 600, "expected": 200}).json()["result"]
            self.assertTrue(r["applied"] and not r["needs_confirm"], r)
            self.assertEqual(store.campaign("g_search_brand_us")["daily_budget"], 600.0)
            for kind, eid in (("campaign", "m_prospecting_core"), ("adset", "g_pmax_us__as1")):
                c.post("/api/campaigns/actions", json={"kind": kind, "id": eid, "action": "status", "value": "PAUSED"})
                r = c.post("/api/campaigns/actions", json={"kind": kind, "id": eid, "action": "status",
                                                          "value": "ACTIVE", "expected": "PAUSED"}).json()["result"]
                self.assertTrue(r["applied"] and not r["needs_confirm"], r)
            # below the old $10 minimum, a bid +100%: applied
            r = direct.apply({"kind": "campaign", "id": "g_search_brand_uk", "action": "budget", "value": 5})
            self.assertTrue(r["applied"], r)
            r = direct.apply({"kind": "adset", "id": "m_retargeting_agency_14d__as1", "action": "bid", "value": 440})
            self.assertTrue(r["applied"] and not r["warnings"], r)
            # data validity and the stale-value conflict still refuse
            for bad in (0, -5, "abc", None, "nan"):
                self.assertEqual(c.post("/api/campaigns/actions", json={"kind": "campaign", "id": "g_search_brand_us",
                                                                       "action": "budget", "value": bad}).status_code, 400)
            self.assertEqual(c.post("/api/campaigns/actions", json={"kind": "campaign", "id": "nope", "action": "status",
                                                                   "value": "PAUSED"}).status_code, 404)
            self.assertEqual(c.post("/api/campaigns/actions", json={"kind": "campaign", "id": "g_search_brand_us",
                                                                   "action": "budget", "value": 700,
                                                                   "expected": 200}).status_code, 409)

    def test_budget_edit_still_guarded_when_switched_on(self):
        with sandbox(), mock.patch.object(direct, "guardrails_on", lambda cfg=None: True):
            res = direct.apply({"kind": "campaign", "id": "m_prospecting_core", "action": "budget", "value": 900})
            self.assertTrue(res["needs_confirm"] and not res["applied"])
            self.assertEqual(res["undo"]["actions"], [])
            # enable + budget raise in one batch: the total-rise check still runs
            direct.apply({"kind": "campaign", "id": "m_prospecting_core", "action": "status", "value": "PAUSED"})
            res = direct.apply([{"kind": "campaign", "id": "m_prospecting_core", "action": "status", "value": "ACTIVE"},
                                {"kind": "campaign", "id": "g_search_brand_us", "action": "budget", "value": 230}])
            self.assertTrue(res["needs_confirm"], res)
            self.assertTrue(any("total daily budget rises" in w for w in res["warnings"]))

    def test_stale_expected_on_meta_abo_campaign_budget_is_a_conflict(self):
        with sandbox():
            res = direct.apply({"kind": "campaign", "id": "m_prospecting_core", "action": "budget", "value": 760,
                                "expected": 700})
            self.assertTrue(res["conflict"], res)
            self.assertEqual(store.adset("m_prospecting_core__as1")["daily_budget"], 366.67)


class RoundTrip(unittest.TestCase):
    def test_undo_everything_in_any_order_is_byte_identical(self):
        with sandbox():
            _raw, start = disk()
            rng = random.Random(99)
            undos = []
            plan = [
                ({"kind": "campaign", "id": "g_search_nonbrand_us", "action": "budget", "value": 1100}, True),
                ({"kind": "campaign", "id": "g_search_brand_uk", "action": "budget", "value": 40.01}, True),
                ({"kind": "campaign", "id": "m_prospecting_test", "action": "budget", "value": 300.01}, True),
                ({"kind": "adset", "id": "m_prospecting_core__as2", "action": "budget", "value": 401.5}, True),
                ({"kind": "campaign", "id": "m_retargeting_agency_14d", "action": "bid", "value": 199.99}, True),
                ({"kind": "campaign", "id": "g_pmax_us", "action": "bid", "value": 280}, True),
                ({"kind": "campaign", "id": "g_search_nonbrand_uk", "action": "bid", "value": 260}, True),
                ({"kind": "adset", "id": "g_pmax_us__as2", "action": "status", "value": "PAUSED"}, False),
                ({"kind": "campaign", "id": "m_prospecting_broad", "action": "status", "value": "PAUSED"}, False),
                ({"kind": "ad", "id": store.ads_for("g_pmax_us__as1")[0]["id"], "action": "status", "value": "PAUSED"}, False),
            ]
            for act, conf in plan:
                r = direct.apply(act, confirm=conf)
                self.assertTrue(r["applied"], r)
                undos.append(r["undo"])
            rng.shuffle(undos)  # disjoint entities: any order works
            for u in undos:
                r = direct.apply(u["actions"], confirm=False, undo_token=u["token"])
                self.assertTrue(r["applied"], r)
            self.assertEqual(strip_activity(disk()[1]), strip_activity(start))


class Concurrency(unittest.TestCase):
    def test_threads_hammering_the_endpoint(self):
        from fastapi.testclient import TestClient
        import app as app_module
        with sandbox():
            ids = [a["id"] for a in store.get_state()["ads"]][:8]
            shared = "m_prospecting_core__as1"
            applied = {"n": 0, "requests": 0, "shared": 0}
            errs = []
            lock = threading.Lock()

            def worker(n):
                c = TestClient(app_module.app)
                rng = random.Random(n)
                for i in range(10):
                    try:
                        if rng.random() < 0.5:
                            eid, kind = ids[n], "ad"
                        else:
                            eid, kind = shared, "adset"
                        cur = store.adset(eid)["status"] if kind == "adset" else store.ad(eid)["status"]
                        nxt = "PAUSED" if cur == "ACTIVE" else "ACTIVE"
                        r = c.post("/api/campaigns/actions", json={"kind": kind, "id": eid, "action": "status",
                                                                  "value": nxt, "expected": cur})
                        if r.status_code == 409:
                            continue
                        assert r.status_code == 200, r.text
                        res = r.json()["result"]
                        if res["applied"]:
                            with lock:
                                applied["n"] += 1
                                applied["requests"] += len(res["requests"])
                                if eid == shared:
                                    applied["shared"] += 1
                        if i % 3 == 0:
                            assert c.get("/api/campaigns/").status_code == 200
                    except Exception as exc:  # pragma: no cover
                        errs.append(exc)

            n0 = sum(1 for a in store.get_state()["activity"] if a["action"] == "api request")
            ts = [threading.Thread(target=worker, args=(n,)) for n in range(len(ids))]
            [t.start() for t in ts]
            [t.join() for t in ts]
            self.assertEqual(errs, [])
            with open(store.STATE_PATH) as fh:
                data = json.load(fh)          # valid JSON, not torn
            store.reload_state()
            n1 = sum(1 for a in data["activity"] if a["action"] == "api request")
            self.assertEqual(n1 - n0, applied["requests"])
            # every toggle that applied flipped the shared ad set once: its status is the parity
            want = "ACTIVE" if applied["shared"] % 2 == 0 else "PAUSED"
            self.assertEqual([a for a in data["adsets"] if a["id"] == shared][0]["status"], want)
            Harness(self, TestClient(app_module.app)).check("after threads")


class PlanAdaptDrift(unittest.TestCase):
    def test_draft_before_a_direct_edit_is_refused_at_publish(self):
        from fastapi.testclient import TestClient
        import app as app_module
        import planning
        from planning import jobs, records
        with sandbox():
            with mock.patch.object(records, "DATA_DIR", planning.DATA_DIR):
                c = TestClient(app_module.app)
                media_ids = [a["id"] for a in jobs.approved_media() if a.get("kind") == "image"][:1]
                r = c.post("/api/planning/changesets", json={"directive": "Trim Brand 10%, pause the worst Meta ad",
                                                            "media_ids": media_ids})
                self.assertEqual(r.status_code, 200, r.text)
                job = r.json()["job"]["id"]
                jobs.wait(job, 30)
                for _ in range(300):
                    j = c.get("/api/planning/jobs/%s" % job).json()["job"]
                    if j["status"] in ("done", "error"):
                        break
                    time.sleep(0.05)
                self.assertEqual(j["status"], "done", j)
                cs = c.get("/api/planning/changesets/%s" % r.json()["changeset"]["id"]).json()["changeset"]
                rows = cs["versions"][-1]["diff"]["rows"]
                # a direct edit to something the draft changes
                target = [x for x in rows if x["field"] in ("status", "daily") and x["action"] == "update"][0]
                ctl = direct.controls()
                if target["field"] == "status":
                    eid = target["entity_id"]
                    cur = ctl[eid]["status"]
                    body = {"kind": ctl[eid]["kind"], "id": eid, "action": "status",
                            "value": "PAUSED" if cur == "ACTIVE" else "ACTIVE", "expected": cur}
                else:
                    camp = [cid for cid, v in ctl.items() if v["kind"] == "campaign" and v["platform"] == "google"
                            and target["entity_name"] in (store.campaign(cid)["name"], store.campaign(cid)["name"] + "_Budget")][0]
                    body = {"kind": "campaign", "id": camp, "action": "budget",
                            "value": round(ctl[camp]["budget"]["value"] * 1.05, 2), "expected": ctl[camp]["budget"]["value"]}
                ed = c.post("/api/campaigns/actions", json=body).json()["result"]
                self.assertTrue(ed["applied"], ed)
                url = "/api/planning/changesets/%s/publish" % cs["id"]
                pub = c.post(url, json={"version": cs["current_version"], "confirm": True}).json()
                self.assertFalse(pub["ok"])
                self.assertTrue(pub["publish"]["drift"], pub["publish"])
                self.assertEqual(pub["publish"]["results"], [])
                # undo the direct edit: the draft's "before" values hold again and it publishes
                u = ed["undo"]
                self.assertTrue(c.post("/api/campaigns/actions", json={"actions": u["actions"], "confirm": True,
                                                                      "undo_token": u["token"]}).json()["result"]["applied"])
                pub = c.post(url, json={"version": cs["current_version"], "confirm": True}).json()
                self.assertTrue(pub["ok"], pub["publish"])


if __name__ == "__main__":
    unittest.main()
