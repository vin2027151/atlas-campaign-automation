"""Deterministic comparison of the 30-day plan with a state document.

    load_plan() -> dict                    # data/plan/plan.yaml
    compare(plan, snapshot) -> [fact]

fact = {"kind", "platform", "campaign", "planned", "actual", "note"} (+ "campaign_id" when the
campaign exists in the snapshot). Kinds: budget_gap, missing_campaign, unplanned_campaign,
status_mismatch, cpa_out_of_band, precondition_open, checklist_overdue, pacing.

Budget gaps compare plan monthly budget / days_in_month with the snapshot daily budget
(±5% tolerance). The checklist comes from store state (the 30-day checklist).
"""

import calendar
import os
import re
from typing import Any, Dict, List, Optional

import yaml

import planning
import store
from planning.snapshot import meta_campaign_daily

PLAN_PATH = os.path.join(planning.BASE_DIR, "data", "plan", "plan.yaml")
BUDGET_TOLERANCE = 0.05
PACING_TOLERANCE = 0.05
STOPWORDS = set("the and every under before after into once with from that this when only than does dollar spends "
                "known flat back beside match week run".split())

STRATEGY_NAMES = {"maximize conversions": "MAXIMIZE_CONVERSIONS", "target cpa": "TARGET_CPA",
                  "target roas": "TARGET_ROAS", "manual cpc": "MANUAL_CPC",
                  "lowest_cost_without_cap": "LOWEST_COST_WITHOUT_CAP", "cost_cap": "COST_CAP"}


def load_plan():
    # type: () -> Dict[str, Any]
    with open(PLAN_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _fact(kind, platform, campaign, planned, actual, note, campaign_id=None):
    f = {"kind": kind, "platform": platform, "campaign": campaign, "planned": planned,
         "actual": actual, "note": note}
    if campaign_id:
        f["campaign_id"] = campaign_id
    return f


def _money(x):
    return "$%s" % "{:,.0f}".format(float(x)) if x is not None else "n/a"


def _tokens(s):
    return set(w for w in re.findall(r"[a-z0-9+\-]{3,}", str(s).lower()) if w not in STOPWORDS)


def _days(plan, snapshot):
    # type: (Dict[str, Any], Dict[str, Any]) -> int
    dim = (plan.get("account") or {}).get("days_in_month")
    if dim:
        return int(dim)
    d = store.parse_date(snapshot.get("as_of") or store.today())
    return calendar.monthrange(d.year, d.month)[1]


def compare(plan, snapshot):
    # type: (Dict[str, Any], Dict[str, Any]) -> List[Dict[str, Any]]
    facts = []  # type: List[Dict[str, Any]]
    acct = plan.get("account") or {}
    dim = _days(plan, snapshot)
    band = acct.get("cpa_band") or [None, None]
    ceiling = acct.get("campaign_cpa_ceiling")
    as_of = snapshot.get("as_of") or store.today()
    elapsed = int(as_of[8:10])

    snap = {"google": dict((c["name"], c) for c in (snapshot.get("google") or {}).get("campaigns", [])),
            "meta": dict((c["name"], c) for c in (snapshot.get("meta") or {}).get("campaigns", []))}
    planned = {"google": plan.get("google_campaigns") or [], "meta": plan.get("meta_campaigns") or []}
    plan_ads = plan.get("meta_ads") or {}
    cut = set(plan.get("cut") or [])

    for platform in ("google", "meta"):
        names = set()
        for pc in planned[platform]:
            name = pc["name"]
            names.add(name)
            sc = snap[platform].get(name)
            plan_daily = round(float(pc.get("budget") or 0) / dim, 2)
            if sc is None:
                facts.append(_fact("missing_campaign", platform, name, "%s/month (%s/day)" % (
                    _money(pc.get("budget")), _money(plan_daily)), None, "in the plan, not in the account"))
                continue
            cid = sc["id"]
            # budget
            actual_daily = float(sc["budget"]["daily"]) if platform == "google" else meta_campaign_daily(sc)
            if plan_daily and abs(actual_daily - plan_daily) / plan_daily > BUDGET_TOLERANCE:
                facts.append(_fact("budget_gap", platform, name, plan_daily, round(actual_daily, 2),
                                   "plan %s/month = %s/day; account %s/day (%+.0f%%)" % (
                                       _money(pc["budget"]), _money(plan_daily), _money(actual_daily),
                                       (actual_daily / plan_daily - 1) * 100), cid))
            if platform == "google" and (sc.get("budget") or {}).get("shared"):
                facts.append(_fact("status_mismatch", platform, name, "own budget", "shared budget",
                                   "plan gives every campaign its own budget (F3)", cid))
            # status
            live = "ENABLED" if platform == "google" else "ACTIVE"
            if sc.get("status") != live:
                facts.append(_fact("status_mismatch", platform, name, live, sc.get("status"),
                                   "planned to run; paused in the account", cid))
            # bidding
            if platform == "google":
                want = STRATEGY_NAMES.get(str(pc.get("bid_strategy") or "").lower())
                bid = sc.get("bidding") or {}
                if want and bid.get("strategy") != want:
                    facts.append(_fact("status_mismatch", platform, name, want, bid.get("strategy"),
                                       "bid strategy differs from plan", cid))
                tgt = pc.get("target_cpa")
                if tgt is not None and bid.get("target_cpa") is not None and abs(float(bid["target_cpa"]) - float(tgt)) > 0.5:
                    facts.append(_fact("cpa_out_of_band", platform, name, float(tgt), float(bid["target_cpa"]),
                                       "target CPA differs from plan", cid))
                if ceiling and bid.get("target_cpa") and float(bid["target_cpa"]) > float(ceiling):
                    facts.append(_fact("cpa_out_of_band", platform, name, float(ceiling), float(bid["target_cpa"]),
                                       "target CPA above the %s campaign ceiling" % _money(ceiling), cid))
            else:
                # planned ads paused (e.g. UGC_Founder_v2: "scaled, not paused")
                ads = [a for s in sc.get("ad_sets", []) for a in s.get("ads", [])]
                for key in pc.get("ads") or []:
                    hits = [a for a in ads if a["name"].startswith(key)]
                    if hits and all(a["status"] != "ACTIVE" for a in hits):
                        facts.append(_fact("status_mismatch", platform, name, "%s ACTIVE" % key, "PAUSED",
                                           "planned ad paused: %s" % ", ".join(a["name"] for a in hits), cid))
            # CPA vs band / expectation
            mt = sc.get("metrics") or {}
            cpt, trials, spend = mt.get("cpt_7d"), mt.get("trials_7d") or 0, mt.get("spend_7d") or 0
            exp = pc.get("expected_cpa")
            if cpt is not None and trials >= 3:
                high = max(float(exp) * 1.2 if exp else 0, float(band[1] or 0))
                if (ceiling and cpt > float(ceiling)) or (high and cpt > high):
                    facts.append(_fact("cpa_out_of_band", platform, name, exp or band, cpt,
                                       "7-day cost per trial %s on %d trials (plan expects %s, band %s-%s)" % (
                                           _money(cpt), trials, _money(exp), _money(band[0]), _money(band[1])), cid))
            elif trials == 0 and ceiling and spend > float(ceiling):
                facts.append(_fact("cpa_out_of_band", platform, name, exp or band, None,
                                   "%s spent in 7 days with zero trials" % _money(spend), cid))
        for name, sc in sorted(snap[platform].items()):
            if name in names:
                continue
            daily = float(sc["budget"]["daily"]) if platform == "google" else meta_campaign_daily(sc)
            note = "not in the plan"
            if sc.get("legacy"):
                note = "legacy campaign, not in the plan (runs one week beside the relaunch)"
            if name in cut:
                note = "on the plan's cut list"
            facts.append(_fact("unplanned_campaign", platform, name, None, "%s %s/day" % (sc.get("status"), _money(daily)),
                               note, sc["id"]))
        if platform == "google":
            for sc in snap["google"].values():
                bname = (sc.get("budget") or {}).get("name")
                if bname in cut:
                    facts.append(_fact("status_mismatch", "google", sc["name"], "removed", bname,
                                       "budget %s is on the plan's cut list" % bname, sc["id"]))

    # preconditions vs done checklist items
    checklist = store.get_state().get("checklist") or []
    done_items = [it for day in checklist for it in day["items"] if it.get("done")]
    for pre in plan.get("preconditions") or []:
        pt = _tokens(pre)
        best, score = None, 0
        for it in done_items:
            s = len(pt & _tokens(it["text"]))
            if s > score:
                best, score = it, s
        if score >= 2:
            continue
        facts.append(_fact("precondition_open", "both", None, pre, "open",
                           "no completed checklist item confirms it" +
                           (" (closest: %s)" % best["text"] if best else "")))

    for day in checklist:
        if day["date"] >= as_of:
            continue
        for it in day["items"]:
            if not it.get("done"):
                facts.append(_fact("checklist_overdue", "both", None, day["date"], "open",
                                   "Day %s: %s [%s]" % (day["day"], it["text"], it["id"])))

    # pacing: MTD spend + days remaining x current daily budgets of what is enabled (reacts at once)
    totals = snapshot.get("totals") or {}
    plats = plan.get("platforms") or {}
    remaining = max(0, dim - elapsed)
    for platform in ("google", "meta"):
        target = (plats.get(platform) or {}).get("declared_total")
        mtd = (totals.get(platform) or {}).get("spend_mtd")
        if not target or mtd is None or not elapsed:
            continue
        daily_sum = (totals.get(platform) or {}).get("daily_budget") or 0
        proj = round(float(mtd) + float(daily_sum) * remaining, 2)
        if abs(proj / float(target) - 1) > PACING_TOLERANCE:
            facts.append(_fact("pacing", platform, None, float(target), proj,
                               "projected month-end at current daily budgets: MTD %s + %d days x %s/day = %s vs plan %s (%+.0f%%)" % (
                                   _money(mtd), remaining, _money(daily_sum), _money(proj), _money(target),
                                   (proj / float(target) - 1) * 100)))
    total = acct.get("total_budget")
    mtd_all = (totals.get("all") or {}).get("spend_mtd")
    if total and mtd_all is not None and elapsed:
        daily_all = (totals.get("all") or {}).get("daily_budget") or 0
        proj = round(float(mtd_all) + float(daily_all) * remaining, 2)
        if abs(proj / float(total) - 1) > PACING_TOLERANCE:
            facts.append(_fact("pacing", "both", None, float(total), proj,
                               "account projects %s at current daily budgets vs %s plan (%+.0f%%), reserve %s" % (
                                   _money(proj), _money(total), (proj / float(total) - 1) * 100,
                                   _money(acct.get("reserve")))))
    return facts
