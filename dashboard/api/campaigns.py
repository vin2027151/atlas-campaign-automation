"""Campaigns page API: every campaign's numbers and its controls, in one place.

GET /api/campaigns/?window=3d|7d|14d|30d|mtd returns the campaign table (spend,
budget, pacing, 3-day / 7-day cost per trial, ad sets and their ads), the
pacing summary, and the search terms / negatives for review. The metrics come
from api/spend.py (the shared metrics layer of the former Spend page).

Mutations (campaign status and budget, ad set and ad status, negative
keywords) go through the store helpers, which persist and log activity.

Ad sets have no daily rows in the sample data, so ad set metrics are the
campaign's window totals apportioned by ad set budget share (equal split when
the ad sets carry no budget of their own, as Google ad groups do).
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

import store
from api import spend

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])

SESSION_START = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
ACTIVITY_SHOWN = 15


class StatusBody(BaseModel):
    status: str


class BudgetBody(BaseModel):
    daily_budget: Any = None


class NegativeBody(BaseModel):
    text: str = ""
    match: str = "phrase"
    source: str = "manual"


# ------------------------------------------------------------------ helpers

def _search_terms_all():
    # type: () -> List[Dict[str, Any]]
    return store.get_state()["search_terms"]


def _pending_negatives(campaign_id):
    # type: (str) -> int
    return sum(1 for st in _search_terms_all()
               if st["campaign_id"] == campaign_id and st.get("recommend_negative") and not st.get("negated"))


def _campaign_row(c, win=None):
    # type: (Dict[str, Any], Optional[Dict[str, Any]]) -> Dict[str, Any]
    """One table row: the spend metrics for the window plus the control fields.

    ``pace_pct`` is average spend per live day in the window as a share of the
    current daily budget (how fully the campaign is spending its budget).
    """
    win = win or spend.window_bounds("7d")
    row = spend.campaign_row(c, win)
    adsets = row.pop("adsets")
    ads_by_set = dict((a["id"], [dict(ad) for ad in store.ads_for(a["id"])]) for a in adsets)
    for a in adsets:
        a["ads"] = ads_by_set[a["id"]]
    row["adsets"] = adsets
    row["adset_count"] = len(adsets)
    row["recommended_negatives"] = _pending_negatives(c["id"]) if c["platform"] == "google" else 0
    row["supports_negatives"] = c["platform"] == "google"
    row["pace_pct"] = store.safe_div(row["spend_per_day"], c["daily_budget"], 100.0, 0) if row["spend_per_day"] is not None else None
    return row


def _activity():
    # type: () -> List[Dict[str, Any]]
    return store.recent_activity(ACTIVITY_SHOWN)


def _summary(win=None):
    # type: (Optional[Dict[str, Any]]) -> Dict[str, Any]
    """Pacing summary: window spend and CPT, active daily budget vs target, month pace."""
    win = win or spend.window_bounds("7d")
    cs = store.campaigns()
    account = spend.totals(store.daily_for(None, None, win["start"], win["end"]))
    blocks = {}
    for pl in (None, "google", "meta"):
        mine = [c for c in cs if pl is None or c["platform"] == pl]
        if pl:
            b = spend.platform_block(pl, win, account["spend"])
        else:
            b = {"platform": "account", "label": "Account", "spend": account["spend"], "share_pct": 100.0,
                 "trials": account["trials"], "cost_per_trial": account["cost_per_trial"],
                 "paid": account["paid"], "campaigns": len(cs)}
        active_daily = round(sum(float(c["daily_budget"] or 0) for c in mine if c["status"] == "ACTIVE"), 2)
        pace = store.pacing(pl)
        target = round(pace["monthly_budget"] / float(pace["days_in_month"]), 2)
        b.update({
            "active_daily_budget": active_daily,
            "daily_target": target,
            "pct_of_target": store.safe_div(active_daily, target, 100.0, 1),
            "active": sum(1 for c in mine if c["status"] == "ACTIVE"),
            "paused": sum(1 for c in mine if c["status"] == "PAUSED"),
            "month_pace_pct": pace["pace_pct"],
            "projected_month_end": pace["projected_month_end"],
            "month_to_date_spend": pace["month_to_date_spend"],
            "monthly_budget": pace["monthly_budget"],
        })
        blocks[pl or "account"] = b
    changes = sum(1 for a in store.get_state().get("activity", []) if a.get("ts", "") >= SESSION_START)
    return {
        "active": blocks["account"]["active"],
        "paused": blocks["account"]["paused"],
        "legacy": sum(1 for c in cs if c.get("legacy")),
        "platforms": {"google": blocks["google"], "meta": blocks["meta"]},
        "account": blocks["account"],
        "changes_this_session": changes,
        "session_start": SESSION_START,
    }


def _search_terms(campaign_id=None):
    # type: (Optional[str]) -> List[Dict[str, Any]]
    """Search terms (one campaign or all), recommended-and-pending first, then by cost."""
    names = dict((c["id"], c["name"]) for c in store.campaigns())
    rows = []
    for st in _search_terms_all():
        if campaign_id and st["campaign_id"] != campaign_id:
            continue
        r = dict(st)
        r["campaign_name"] = names.get(st["campaign_id"], st["campaign_id"])
        r["cpt"] = store.safe_div(st["cost"], st["trials"])
        r["pending"] = bool(st.get("recommend_negative") and not st.get("negated"))
        rows.append(r)
    rows.sort(key=lambda r: (0 if r["pending"] else 1, -float(r["cost"])))
    return rows


def _negatives(campaign_id=None):
    # type: (Optional[str]) -> List[Dict[str, Any]]
    names = dict((c["id"], c["name"]) for c in store.campaigns())
    rows = []
    for n in store.get_state()["negatives"]:
        if campaign_id and n["campaign_id"] != campaign_id:
            continue
        r = dict(n)
        r["campaign_name"] = names.get(n["campaign_id"], n["campaign_id"])
        rows.append(r)
    rows.sort(key=lambda n: (n["added"], n["text"]), reverse=True)
    return rows


def _detail(campaign_id, win=None):
    # type: (str, Optional[Dict[str, Any]]) -> Dict[str, Any]
    c = store.campaign(campaign_id)
    row = _campaign_row(c, win)
    is_google = c["platform"] == "google"
    return {
        "ok": True,
        "campaign": row,
        "adsets": row["adsets"],
        "search_terms": _search_terms(campaign_id) if is_google else [],
        "negatives": _negatives(campaign_id) if is_google else [],
        "supports_negatives": is_google,
        "match_types": list(store.NEGATIVE_MATCH_TYPES),
    }


def _mutation_response(**extra):
    # type: (Any) -> Dict[str, Any]
    out = {"ok": True, "summary": _summary(), "activity": _activity()}
    out.update(extra)
    return out


# -------------------------------------------------------------------- reads

@router.get("/")
def index(window: str = Query("7d")):
    """Everything the Campaigns page needs in one call (window: 3d|7d|14d|30d|mtd)."""
    win = spend.window_bounds(window)
    meta = store.get_state()["meta"]
    rows = [_campaign_row(c, win) for c in spend.ordered_campaigns()]
    return {
        "ok": True,
        "today": store.today(),
        "window": win,
        "windows": list(spend.WINDOWS),
        "cpa_target": meta.get("cpa_target", [250, 280]),
        "ratio_band": list(spend.RATIO_BAND),
        "campaigns": rows,
        "summary": _summary(win),
        "search_terms": _search_terms(),
        "negatives": _negatives(),
        "match_types": list(store.NEGATIVE_MATCH_TYPES),
        "notes": spend.NOTES,
        "activity": _activity(),
    }


@router.get("/activity")
def activity():
    return {"ok": True, "activity": _activity(), "summary": _summary()}


@router.get("/{campaign_id}")
def detail(campaign_id, window: str = Query("7d")):
    # type: (str, str) -> Dict[str, Any]
    return _detail(campaign_id, spend.window_bounds(window))


# ---------------------------------------------------------------- mutations

@router.post("/{campaign_id}/status")
def campaign_status(campaign_id, body: StatusBody):
    store.set_campaign_status(campaign_id, body.status)
    return _mutation_response(campaign=_campaign_row(store.campaign(campaign_id)))


@router.post("/{campaign_id}/budget")
def campaign_budget(campaign_id, body: BudgetBody):
    v = body.daily_budget
    if v is None or isinstance(v, bool):
        raise store.BadInput("daily_budget is required")
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise store.BadInput("daily_budget must be a number")
    if not v > 0:
        raise store.BadInput("daily_budget must be greater than 0")
    store.set_campaign_budget(campaign_id, daily_budget=v)
    return _mutation_response(campaign=_campaign_row(store.campaign(campaign_id)))


@router.post("/adsets/{adset_id}/status")
def adset_status(adset_id, body: StatusBody):
    a = store.set_adset_status(adset_id, body.status)
    return _mutation_response(adset=dict(a))


@router.post("/ads/{ad_id}/status")
def ad_status(ad_id, body: StatusBody):
    a = store.set_ad_status(ad_id, body.status)
    return _mutation_response(ad=dict(a))


@router.post("/{campaign_id}/negatives")
def add_negative(campaign_id, body: NegativeBody):
    source = body.source if body.source in ("manual", "recommended") else "manual"
    neg = store.add_negative(campaign_id, body.text, body.match, source)
    return _mutation_response(negative=neg, search_terms=_search_terms(campaign_id),
                              negatives=_negatives(campaign_id))
