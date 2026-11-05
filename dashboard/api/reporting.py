"""Reporting page API: the management / CEO view of the account.

GET /api/reporting/            everything the page needs, in one call
GET /api/reporting/export.csv  per-campaign month-to-date table as a CSV download

All derived numbers come from store helpers; anything store.py does not give
directly (prior-period deltas, shares, trust ratios, change list) is computed
here from store.get_state().
"""

import csv
import io
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import Response

import store

router = APIRouter(prefix="/api/reporting", tags=["reporting"])

PLATFORMS = ("google", "meta")
PLATFORM_LABELS = {"google": "Google Ads", "meta": "Meta", None: "Total"}
CPT_ALERT = 350.0
CPT_ALERT_MIN_SPEND = 1500.0
PACE_HIGH = 105.0
PACE_LOW = 85.0
TREND_DAYS = 30
PAID_LAG_DAYS = 14      # trials need ~7-14 days to become paid; younger cohorts are incomplete
COHORT_DAYS = 28        # matured-cohort window length for cost per paid / trial->paid


def _pct_change(cur, prev):
    # type: (Optional[float], Optional[float]) -> Optional[float]
    """Percent change cur vs prev, in percentage points; None when either side is missing or prev is 0."""
    if cur is None or prev is None or not prev:
        return None
    return round((cur - prev) / float(prev) * 100.0, 1)


def _totals(platform=None, campaign_id=None, start=None, end=None):
    # type: (Optional[str], Optional[str], str, str) -> Dict[str, Any]
    t = store.aggregate(store.daily_for(campaign_id, platform, start, end))
    t.update({"start": start, "end": end})
    return t


def _prior_mtd_window():
    # type: () -> Dict[str, str]
    """Same day-span in the previous month (Nov 1-5 -> Oct 1-5)."""
    t = store.parse_date(store.today())
    first = t.replace(day=1)
    prev_last = store.parse_date(store.shift(store.iso(first), -1))
    prev_first = prev_last.replace(day=1)
    day = min(t.day, prev_last.day)
    return {"start": store.iso(prev_first), "end": store.iso(prev_first.replace(day=day))}


def _kpis():
    # type: () -> Dict[str, Any]
    today = store.today()
    p = store.pacing()
    mtd = store.month_to_date()
    pw = _prior_mtd_window()
    prev = _totals(start=pw["start"], end=pw["end"])
    w7 = store.window_totals(None, 7)
    p7 = store.window_totals(None, 7, end=store.shift(today, -7))
    coh_end = store.shift(today, -PAID_LAG_DAYS)
    coh = store.window_totals(None, COHORT_DAYS, end=coh_end)
    coh_prev = store.window_totals(None, COHORT_DAYS, end=store.shift(coh_end, -COHORT_DAYS))
    return {
        "mtd_spend": {"value": mtd["spend"], "prev": prev["spend"], "delta": _pct_change(mtd["spend"], prev["spend"])},
        "projected": {"value": p["projected_month_end"], "budget": p["monthly_budget"], "pace_pct": p["pace_pct"]},
        "trials_mtd": {"value": mtd["trials"], "prev": prev["trials"], "delta": _pct_change(mtd["trials"], prev["trials"])},
        "cpt_mtd": {"value": mtd["cost_per_trial"], "prev": prev["cost_per_trial"],
                    "delta": _pct_change(mtd["cost_per_trial"], prev["cost_per_trial"])},
        "cpt_7d": {"value": w7["cost_per_trial"], "prev": p7["cost_per_trial"],
                   "delta": _pct_change(w7["cost_per_trial"], p7["cost_per_trial"]),
                   "trials": w7["trials"], "spend": w7["spend"]},
        "paid_mtd": {"value": mtd["paid"], "prev": prev["paid"], "delta": _pct_change(mtd["paid"], prev["paid"]),
                     "lag_days": PAID_LAG_DAYS, "paid_30d": store.window_totals(None, 30)["paid"]},
        "cost_per_paid": {"value": coh["cost_per_paid"], "prev": coh_prev["cost_per_paid"],
                          "delta": _pct_change(coh["cost_per_paid"], coh_prev["cost_per_paid"]),
                          "paid": coh["paid"], "trials": coh["trials"]},
        "trial_to_paid": {"value": coh["trial_to_paid"], "prev": coh_prev["trial_to_paid"],
                          "delta": (round(coh["trial_to_paid"] - coh_prev["trial_to_paid"], 1)
                                    if coh["trial_to_paid"] is not None and coh_prev["trial_to_paid"] is not None else None)},
        "cohort_window": {"start": coh["start"], "end": coh["end"]},
        "cohort_prior_window": {"start": coh_prev["start"], "end": coh_prev["end"]},
        "mtd_window": {"start": mtd["start"], "end": mtd["end"]},
        "prior_window": pw,
        "w7_window": {"start": w7["start"], "end": w7["end"]},
        "p7_window": {"start": p7["start"], "end": p7["end"]},
    }


def _pacing_rows():
    # type: () -> List[Dict[str, Any]]
    rows = []
    for pl in PLATFORMS + (None,):
        p = dict(store.pacing(pl))
        p["key"] = pl or "total"
        p["label"] = PLATFORM_LABELS[pl]
        p["today_marker_pct"] = store.safe_div(p["days_elapsed"], p["days_in_month"], 100.0, 1)
        p["mtd_pct_of_budget"] = store.safe_div(p["month_to_date_spend"], p["monthly_budget"], 100.0, 1)
        pace = p["pace_pct"]
        p["status"] = ("none" if pace is None else "over" if pace > PACE_HIGH else
                       "under" if pace < PACE_LOW else "watch" if (pace > 102 or pace < 95) else "on")
        rows.append(p)
    return rows


def _trends():
    # type: () -> Dict[str, Any]
    end = store.today()
    start = store.shift(end, -(TREND_DAYS - 1))
    series = store.daily_series(None, None, start, end)
    roll = {}
    for key, pl in (("total", None), ("google", "google"), ("meta", "meta")):
        roll[key] = [r["cost_per_trial"] for r in store.rolling_cost_per_trial(None, 7, pl, start, end)]
    return {
        "dates": [r["date"] for r in series],
        "spend": [r["spend"] for r in series],
        "trials": [r["trials"] for r in series],
        "cpt_7d": roll,
        "cpa_target": store.get_state()["meta"]["cpa_target"],
    }


def _accounts():
    # type: () -> List[Dict[str, Any]]
    total = store.month_to_date()
    coh_end = store.shift(store.today(), -PAID_LAG_DAYS)
    out = []
    for pl in PLATFORMS + (None,):
        t = store.month_to_date(None, pl) if pl else total
        coh = store.window_totals(None, COHORT_DAYS, pl, end=coh_end)
        out.append({
            "key": pl or "total", "label": PLATFORM_LABELS[pl],
            "spend": t["spend"], "trials": t["trials"], "cost_per_trial": t["cost_per_trial"],
            "paid": t["paid"], "cost_per_paid": t["cost_per_paid"], "trial_to_paid": t["trial_to_paid"],
            "clicks": t["clicks"], "ctr": t["ctr"],
            "share_spend": store.safe_div(t["spend"], total["spend"], 100.0, 1),
            "share_trials": store.safe_div(t["trials"], total["trials"], 100.0, 1),
            "cohort_paid": coh["paid"], "cohort_trials": coh["trials"],
            "cohort_cost_per_paid": coh["cost_per_paid"], "cohort_trial_to_paid": coh["trial_to_paid"],
        })
    return out


def _trust_note(platform, ratio):
    # type: (str, Optional[float]) -> Dict[str, str]
    name = PLATFORM_LABELS[platform]
    if ratio is None:
        return {"tone": "idle", "note": "%s: no PostHog trials in the window, so no ratio." % name}
    r = int(round(ratio))
    if platform == "meta" and ratio < 80:
        return {"tone": "bad", "note": "Meta reports %d%% of actual trials: the Meta trial event has under-counted since "
                "Sep 22 and is under repair. Judge Meta on PostHog trials, not Ads Manager." % r}
    if ratio < 80:
        return {"tone": "bad", "note": "%s reports %d%% of actual: under-counting, check the conversion tag." % (name, r)}
    if ratio > 120:
        return {"tone": "watch", "note": "%s claims %d%% of actual: over-counting (likely duplicate or modelled "
                "conversions). Use PostHog for cost per trial." % (name, r)}
    return {"tone": "good", "note": "%s reports %d%% of actual: close enough to trust for daily steering." % (name, r)}


def _trust():
    # type: () -> List[Dict[str, Any]]
    rows = []
    for pl in PLATFORMS:
        w = store.window_totals(None, 7, pl)
        ratio = store.safe_div(w["platform_conversions"], w["trials"], 100.0, 1)
        row = {"platform": pl, "label": PLATFORM_LABELS[pl], "start": w["start"], "end": w["end"],
               "platform_conversions": w["platform_conversions"], "posthog_trials": w["trials"],
               "ratio_pct": ratio, "spend": w["spend"],
               "platform_cpa": w["platform_cost_per_conversion"], "true_cpt": w["cost_per_trial"]}
        row.update(_trust_note(pl, ratio))
        rows.append(row)
    return rows


def _status_changes_from_activity(start):
    # type: (str) -> Dict[str, str]
    """campaign_id -> date of the latest campaign.status change on/after start (activity ts are UTC ISO)."""
    out = {}
    for a in store.get_state().get("activity", []):
        if a.get("action") == "campaign.status" and str(a.get("ts", ""))[:10] >= start:
            out[a["target"]] = str(a["ts"])[:10]
    return out


def _changes():
    # type: () -> List[Dict[str, Any]]
    today = store.today()
    start = store.shift(today, -6)
    items = []  # type: List[Dict[str, Any]]
    changed = _status_changes_from_activity(start)
    launched = []
    for c in store.campaigns():
        sd = c.get("start_date") or ""
        if start <= sd <= today:
            launched.append(c)
        if c["status"] == "PAUSED":
            when = changed.get(c["id"])
            items.append({"kind": "paused", "tone": "idle", "platform": c["platform"], "date": when,
                          "text": "%s is paused%s." % (c["name"], (" (changed %s)" % when) if when else "")})
        elif c["id"] in changed:
            items.append({"kind": "resumed", "tone": "info", "platform": c["platform"], "date": changed[c["id"]],
                          "text": "%s was set ACTIVE on %s." % (c["name"], changed[c["id"]])})
    if launched:
        by_date = {}  # type: Dict[str, List[Dict[str, Any]]]
        for c in launched:
            by_date.setdefault(c["start_date"], []).append(c)
        for d in sorted(by_date):
            cs = by_date[d]
            items.append({"kind": "launched", "tone": "info", "platform": cs[0]["platform"] if len(set(x["platform"] for x in cs)) == 1 else None,
                          "date": d, "text": "Launched %d campaign%s on %s: %s." % (
                              len(cs), "" if len(cs) == 1 else "s", d, ", ".join(x["name"] for x in cs))})
    legacy = [c for c in store.campaigns() if c.get("legacy") and c["status"] == "ACTIVE"]
    if legacy:
        items.append({"kind": "legacy", "tone": "watch", "platform": "meta", "date": None,
                      "text": "%d legacy Meta campaign%s still running at reduced budget alongside the new build: %s." % (
                          len(legacy), "" if len(legacy) == 1 else "s", ", ".join(c["name"] for c in legacy))})
    for p in _pacing_rows():
        pace = p["pace_pct"]
        if pace is None:
            continue
        if pace > PACE_HIGH or pace < PACE_LOW:
            items.append({"kind": "pace", "tone": "bad", "platform": p["platform"], "date": None,
                          "text": "%s is projected at %.1f%% of budget ($%s vs $%s): %s." % (
                              p["label"], pace, "{:,.0f}".format(p["projected_month_end"]),
                              "{:,.0f}".format(p["monthly_budget"]),
                              "overspend risk, trim daily budgets" if pace > PACE_HIGH else "underspend, raise daily budgets")})
    pace_ok = all(PACE_LOW <= (p["pace_pct"] or 100) <= PACE_HIGH for p in _pacing_rows())
    if pace_ok:
        items.append({"kind": "pace", "tone": "good", "platform": None, "date": None,
                      "text": "All accounts project within %d%%-%d%% of budget." % (PACE_LOW, PACE_HIGH)})
    for c in store.campaigns():
        w = store.window_totals(c["id"], 7)
        cpt = w["cost_per_trial"]
        if w["spend"] >= CPT_ALERT_MIN_SPEND and (cpt is None or cpt > CPT_ALERT):
            items.append({"kind": "cpt", "tone": "bad", "platform": c["platform"], "date": None,
                          "campaign_id": c["id"],
                          "text": "%s: 7-day cost per trial %s on $%s spend (%d trials)." % (
                              c["name"], ("$%s" % "{:,.0f}".format(cpt)) if cpt is not None else "n/a (0 trials)",
                              "{:,.0f}".format(w["spend"]), w["trials"])})
    order = {"cpt": 0, "pace": 1, "paused": 2, "resumed": 3, "launched": 4, "legacy": 5}
    items.sort(key=lambda i: (0 if i["tone"] == "bad" else 1, order.get(i["kind"], 9), i.get("date") or ""))
    return items


def _campaign_rows():
    # type: () -> List[Dict[str, Any]]
    rows = []
    for c in store.campaigns():
        t = store.month_to_date(c["id"])
        w = store.window_totals(c["id"], 7)
        rows.append({
            "id": c["id"], "platform": c["platform"], "name": c["name"], "country": c.get("country"),
            "type": c.get("type"), "status": c["status"], "legacy": bool(c.get("legacy")),
            "start_date": c.get("start_date"), "monthly_budget": c.get("monthly_budget"),
            "spend": t["spend"], "impressions": t["impressions"], "clicks": t["clicks"], "ctr": t["ctr"],
            "platform_conversions": t["platform_conversions"], "trials": t["trials"],
            "cost_per_trial": t["cost_per_trial"], "paid": t["paid"], "cost_per_paid": t["cost_per_paid"],
            "trial_to_paid": t["trial_to_paid"],
            "cpt_7d": w["cost_per_trial"], "spend_7d": w["spend"],
        })
    rows.sort(key=lambda r: (r["platform"], -r["spend"]))
    return rows


@router.get("/")
def index():
    # type: () -> Dict[str, Any]
    meta = store.get_state()["meta"]
    p = store.pacing()
    return {
        "ok": True,
        "as_of": store.today(),
        "month": p["month"],
        "days_elapsed": p["days_elapsed"],
        "days_in_month": p["days_in_month"],
        "monthly_budget": meta["monthly_budget"],
        "cpa_target": meta["cpa_target"],
        "kpis": _kpis(),
        "pacing": _pacing_rows(),
        "trends": _trends(),
        "accounts": _accounts(),
        "trust": _trust(),
        "changes": _changes(),
        "campaigns": _campaign_rows(),
    }


CSV_COLUMNS = [
    ("platform", "Platform"), ("name", "Campaign"), ("status", "Status"), ("type", "Type"), ("country", "Country"),
    ("legacy", "Legacy"), ("start_date", "Start date"), ("monthly_budget", "Monthly budget"),
    ("spend", "Spend MTD"), ("impressions", "Impressions"), ("clicks", "Clicks"), ("ctr", "CTR %"),
    ("platform_conversions", "Platform conversions"), ("trials", "Trials (PostHog)"),
    ("cost_per_trial", "Cost per trial"), ("paid", "Paid"), ("cost_per_paid", "Cost per paid"),
    ("trial_to_paid", "Trial to paid %"), ("spend_7d", "Spend 7d"), ("cpt_7d", "Cost per trial 7d"),
]


@router.get("/export.csv")
def export_csv():
    rows = _campaign_rows()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([label for _, label in CSV_COLUMNS])
    for r in rows:
        w.writerow(["" if r.get(k) is None else r.get(k) for k, _ in CSV_COLUMNS])
    t = store.month_to_date()
    w.writerow(["total", "All campaigns", "", "", "", "", "", sum(float(r["monthly_budget"] or 0) for r in rows),
                t["spend"], t["impressions"], t["clicks"], t["ctr"], t["platform_conversions"], t["trials"],
                "" if t["cost_per_trial"] is None else t["cost_per_trial"], t["paid"],
                "" if t["cost_per_paid"] is None else t["cost_per_paid"],
                "" if t["trial_to_paid"] is None else t["trial_to_paid"], "", ""])
    fname = "atlas-reporting-mtd-%s.csv" % store.today()
    return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="%s"' % fname})
