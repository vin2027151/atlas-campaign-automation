"""Spend metrics: where the money goes, by platform, campaign and day.

The Spend page itself is gone (it became /campaigns, and its two charts moved
to /reporting). This module stays as the shared metrics layer: api/campaigns.py
and api/reporting.py import its helpers, and GET /api/spend/?window=... still
returns the old one-call payload for any external caller.

All windows are trailing and inclusive, ending today (meta.today); "mtd" runs
from the 1st of today's month.

The 3-day and 7-day cost per trial on each campaign row are always the
trailing 3 / 7 days ending today, whatever the window: they are the active
monitor, not window totals.

The sample data has no ad-set-level daily rows, so ad set totals are the
campaign's window totals split by ad set daily budget (Meta) or evenly (Google
ad groups / asset groups, which have no own budget). Each ad set says so in
``allocation``.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

import store

router = APIRouter(prefix="/api/spend", tags=["spend"])

WINDOWS = ("3d", "7d", "14d", "30d", "mtd")
PLATFORMS = ("google", "meta")
PLATFORM_LABELS = {"google": "Google Ads", "meta": "Meta"}
# platform-reported conversions vs PostHog trials: outside this band is flagged
RATIO_BAND = (80.0, 120.0)
METRIC_KEYS = ("spend", "impressions", "clicks", "platform_conversions", "trials", "paid")
NOTES = {
    "paid_lag": "Paid memberships lag trials by about 7-14 days, so recent days and short windows understate paid.",
    "adset_allocation": "No ad-set-level daily data in the sample: ad set totals are the campaign total split by ad set budget, or evenly where ad groups have no budget of their own.",
    "monitor": "3-day and 7-day CPT are trailing windows ending today, independent of the selected window.",
}


def _window_bounds(window):
    # type: (str) -> Dict[str, Any]
    w = str(window or "7d").lower()
    if w not in WINDOWS:
        raise store.BadInput("window must be one of %s" % ", ".join(WINDOWS))
    end = store.today()
    if w == "mtd":
        start = end[:8] + "01"
    else:
        start = store.shift(end, -(int(w[:-1]) - 1))
    days = len(store.date_range(start, end))
    label = "Month to date" if w == "mtd" else "Last %d days" % days
    return {"key": w, "start": start, "end": end, "days": days, "label": label}


def _totals(rows):
    # type: (List[Dict[str, Any]]) -> Dict[str, Any]
    t = store.aggregate(rows)
    t["platform_vs_posthog_pct"] = store.safe_div(t["platform_conversions"], t["trials"], 100.0, 1)
    return t


def _ratio_flag(platform_conv, trials):
    # type: (float, int) -> Optional[str]
    """'under' / 'over' when the platform claims <80% / >120% of PostHog trials."""
    if not trials:
        return "over" if platform_conv > 0 else None
    r = platform_conv / float(trials) * 100.0
    if r < RATIO_BAND[0]:
        return "under"
    if r > RATIO_BAND[1]:
        return "over"
    return None


def _active_days(c, win):
    # type: (Dict[str, Any], Dict[str, Any]) -> int
    """Days in the window on or after the campaign's start date."""
    first = max(win["start"], c.get("start_date") or win["start"])
    if first > win["end"]:
        return 0
    return len(store.date_range(first, win["end"]))


def _split_adsets(c, totals):
    # type: (Dict[str, Any], Dict[str, Any]) -> List[Dict[str, Any]]
    adsets = store.adsets_for(c["id"])
    if not adsets:
        return []
    budgets = [a.get("daily_budget") for a in adsets]
    if all(b for b in budgets):
        total_b = float(sum(budgets))
        weights = [b / total_b for b in budgets]
        method = "budget_share"
    else:
        weights = [1.0 / len(adsets)] * len(adsets)
        method = "even"
    out = []
    for a, w in zip(adsets, weights):
        t = {k: totals[k] * w for k in METRIC_KEYS}
        t["spend"] = round(t["spend"], 2)
        t["platform_conversions"] = round(t["platform_conversions"], 1)
        for k in ("impressions", "clicks"):
            t[k] = int(round(t[k]))
        for k in ("trials", "paid"):
            t[k] = round(t[k], 1)
        store.derive(t)
        out.append({
            "id": a["id"], "name": a["name"], "kind": a.get("kind"), "status": a["status"],
            "daily_budget": a.get("daily_budget"), "targeting": a.get("targeting"),
            "share_pct": round(w * 100.0, 1), "allocation": method,
            "spend": t["spend"], "clicks": t["clicks"], "trials": t["trials"], "paid": t["paid"],
            "cost_per_trial": t["cost_per_trial"], "cost_per_paid": t["cost_per_paid"],
            "trial_to_paid": t["trial_to_paid"], "ctr": t["ctr"],
        })
    return out


def _campaign_row(c, win):
    # type: (Dict[str, Any], Dict[str, Any]) -> Dict[str, Any]
    t = _totals(store.daily_for(c["id"], None, win["start"], win["end"]))
    w3 = store.window_totals(c["id"], 3)
    w7 = store.window_totals(c["id"], 7)
    active = _active_days(c, win)
    return {
        "id": c["id"], "platform": c["platform"], "name": c["name"], "country": c["country"],
        "type": c["type"], "status": c["status"], "legacy": bool(c.get("legacy")),
        "start_date": c.get("start_date"), "daily_budget": c["daily_budget"],
        "monthly_budget": c["monthly_budget"], "bid_strategy": c.get("bid_strategy"),
        "active_days": active,
        "spend": t["spend"], "spend_per_day": store.safe_div(t["spend"], active),
        "impressions": t["impressions"], "clicks": t["clicks"], "ctr": t["ctr"], "cpc": t["cpc"],
        "trials": t["trials"], "paid": t["paid"],
        "cost_per_trial": t["cost_per_trial"], "cost_per_paid": t["cost_per_paid"],
        "click_to_trial": t["click_to_trial"], "trial_to_paid": t["trial_to_paid"],
        "cpt_3d": w3["cost_per_trial"], "trials_3d": w3["trials"], "spend_3d": w3["spend"],
        "cpt_7d": w7["cost_per_trial"], "trials_7d": w7["trials"], "spend_7d": w7["spend"],
        "platform_conversions": t["platform_conversions"],
        "platform_vs_posthog_pct": t["platform_vs_posthog_pct"],
        "ratio_flag": _ratio_flag(t["platform_conversions"], t["trials"]),
        "adsets": _split_adsets(c, t),
    }


def _platform_block(platform, win, total_spend):
    # type: (str, Dict[str, Any], float) -> Dict[str, Any]
    t = _totals(store.daily_for(None, platform, win["start"], win["end"]))
    return {
        "platform": platform, "label": PLATFORM_LABELS[platform],
        "spend": t["spend"], "share_pct": store.safe_div(t["spend"], total_spend, 100.0, 1),
        "clicks": t["clicks"], "trials": t["trials"], "paid": t["paid"],
        "cost_per_trial": t["cost_per_trial"], "cost_per_paid": t["cost_per_paid"],
        "trial_to_paid": t["trial_to_paid"], "click_to_trial": t["click_to_trial"],
        "platform_conversions": t["platform_conversions"],
        "platform_vs_posthog_pct": t["platform_vs_posthog_pct"],
        "monthly_budget": store.platform_budget(platform),
        "campaigns": len(store.campaigns(platform)),
    }


def ordered_campaigns():
    # type: () -> List[Dict[str, Any]]
    """Google first, then Meta new build, then Meta legacy; seed order within each."""
    order = {"google": 0, "meta": 1}
    return sorted(store.campaigns(), key=lambda c: (order.get(c["platform"], 9), bool(c.get("legacy"))))


def daily_spend_block(win, camps):
    # type: (Dict[str, Any], List[Dict[str, Any]]) -> Dict[str, Any]
    """Stacked daily spend: one series per campaign, aligned to the window's dates."""
    dates = store.date_range(win["start"], win["end"])
    by_key = {}  # type: Dict[Any, float]
    for r in store.daily_for(None, None, win["start"], win["end"]):
        by_key[(r["campaign_id"], r["date"])] = r["spend"]
    return {
        "dates": dates,
        "series": [{"campaign_id": c["id"], "name": c["name"], "platform": c["platform"],
                    "legacy": bool(c.get("legacy")),
                    "spend": [round(by_key.get((c["id"], d), 0.0), 2) for d in dates]}
                   for c in camps],
        "totals": [round(sum(by_key.get((c["id"], d), 0.0) for c in camps), 2) for d in dates],
    }


def rolling_cpt_block(win, camps):
    # type: (Dict[str, Any], List[Dict[str, Any]]) -> Dict[str, Any]
    """Rolling 3-day cost per trial per campaign over the window; None = no trials (gap)."""
    dates = store.date_range(win["start"], win["end"])
    rolling = {"days": 3, "dates": dates, "series": []}  # type: Dict[str, Any]
    for c in camps:
        pts = store.rolling_cost_per_trial(c["id"], 3, None, win["start"], win["end"])
        by_d = dict((p["date"], p) for p in pts)
        start_d = c.get("start_date") or win["start"]
        rolling["series"].append({
            "campaign_id": c["id"], "name": c["name"], "platform": c["platform"],
            "legacy": bool(c.get("legacy")),
            "cost_per_trial": [by_d[d]["cost_per_trial"] if (d in by_d and d >= start_d) else None
                               for d in dates],
        })
    acct_roll = store.rolling_cost_per_trial(None, 3, None, win["start"], win["end"])
    rolling["account"] = [p["cost_per_trial"] for p in acct_roll]
    return rolling


# Public names for the Campaigns and Reporting routers, which reuse these.
window_bounds = _window_bounds
campaign_row = _campaign_row
platform_block = _platform_block
totals = _totals


@router.get("/")
def index(window: str = Query("7d")):
    """Legacy one-call payload of the old Spend page (now Campaigns + Reporting)."""
    win = _window_bounds(window)
    meta = store.get_state()["meta"]
    camps = ordered_campaigns()
    rows = [_campaign_row(c, win) for c in camps]

    account = _totals(store.daily_for(None, None, win["start"], win["end"]))
    platforms = [_platform_block(p, win, account["spend"]) for p in PLATFORMS]

    funnel = {
        "spend": account["spend"], "impressions": account["impressions"],
        "clicks": account["clicks"], "trials": account["trials"], "paid": account["paid"],
        "ctr": account["ctr"], "cpc": account["cpc"],
        "click_to_trial": account["click_to_trial"], "trial_to_paid": account["trial_to_paid"],
        "cost_per_trial": account["cost_per_trial"], "cost_per_paid": account["cost_per_paid"],
    }

    return {
        "ok": True,
        "window": win,
        "windows": list(WINDOWS),
        "today": store.today(),
        "cpa_target": meta.get("cpa_target", [250, 280]),
        "ratio_band": list(RATIO_BAND),
        "new_build_start": meta.get("new_build_start"),
        "account": {
            "spend": account["spend"], "clicks": account["clicks"], "trials": account["trials"],
            "paid": account["paid"], "cost_per_trial": account["cost_per_trial"],
            "cost_per_paid": account["cost_per_paid"], "trial_to_paid": account["trial_to_paid"],
            "platform_conversions": account["platform_conversions"],
            "platform_vs_posthog_pct": account["platform_vs_posthog_pct"],
        },
        "platforms": platforms,
        "campaigns": rows,
        "daily": daily_spend_block(win, camps),
        "rolling_cpt": rolling_cpt_block(win, camps),
        "funnel": funnel,
        "notes": NOTES,
    }
