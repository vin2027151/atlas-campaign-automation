"""Campaigns page API: the centralized control surface.

Lists every campaign on every platform with trailing metrics, drills into ad
sets / ad groups / asset groups and their ads, and exposes the mutations a
media buyer needs (status, budget, ad set and ad status, negative keywords).
All mutations go through the store helpers, which persist and log activity.

Ad sets have no daily rows in the sample data, so ad set metrics are the
campaign's window totals apportioned by ad set budget share (equal split when
the ad sets carry no budget of their own, as Google ad groups do).
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

import store

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

def _metrics(campaign_id):
    # type: (str) -> Dict[str, Any]
    w7 = store.window_totals(campaign_id, 7)
    w3 = store.window_totals(campaign_id, 3)
    return {
        "spend_7d": w7["spend"], "trials_7d": w7["trials"], "cpt_7d": w7["cost_per_trial"],
        "clicks_7d": w7["clicks"], "impressions_7d": w7["impressions"], "ctr_7d": w7["ctr"],
        "spend_3d": w3["spend"], "trials_3d": w3["trials"], "cpt_3d": w3["cost_per_trial"],
    }


def _campaign_row(c):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    row = dict(c)
    row.update(_metrics(c["id"]))
    row["adset_count"] = len(store.adsets_for(c["id"]))
    row["recommended_negatives"] = sum(
        1 for st in store.get_state()["search_terms"]
        if st["campaign_id"] == c["id"] and st.get("recommend_negative") and not st.get("negated"))
    return row


def _activity():
    # type: () -> List[Dict[str, Any]]
    return store.recent_activity(ACTIVITY_SHOWN)


def _summary():
    # type: () -> Dict[str, Any]
    cs = store.campaigns()
    by_platform = {}
    for pl in ("google", "meta"):
        mine = [c for c in cs if c["platform"] == pl]
        active_daily = round(sum(float(c["daily_budget"] or 0) for c in mine if c["status"] == "ACTIVE"), 2)
        budget = store.platform_budget(pl)
        target = round(budget / 30.0, 2)
        by_platform[pl] = {
            "active_daily_budget": active_daily,
            "monthly_budget": budget,
            "daily_target": target,
            "pct_of_target": store.safe_div(active_daily, target, 100.0, 1),
            "active": sum(1 for c in mine if c["status"] == "ACTIVE"),
            "paused": sum(1 for c in mine if c["status"] == "PAUSED"),
        }
    changes = sum(1 for a in store.get_state().get("activity", []) if a.get("ts", "") >= SESSION_START)
    return {
        "active": sum(1 for c in cs if c["status"] == "ACTIVE"),
        "paused": sum(1 for c in cs if c["status"] == "PAUSED"),
        "legacy": sum(1 for c in cs if c.get("legacy")),
        "platforms": by_platform,
        "changes_this_session": changes,
        "session_start": SESSION_START,
    }


def _adsets_detail(c, metrics):
    # type: (Dict[str, Any], Dict[str, Any]) -> List[Dict[str, Any]]
    adsets = store.adsets_for(c["id"])
    budgets = [float(a["daily_budget"]) if a.get("daily_budget") else 0.0 for a in adsets]
    total = sum(budgets)
    out = []
    for a, b in zip(adsets, budgets):
        if total > 0:
            share, basis = b / total, "budget share"
        else:
            share, basis = (1.0 / len(adsets)) if adsets else 0.0, "equal split"
        spend = round(metrics["spend_7d"] * share, 2)
        trials = round(metrics["trials_7d"] * share, 1)
        row = dict(a)
        row.update({
            "share": round(share * 100.0, 1),
            "apportion_basis": basis,
            "spend_7d": spend,
            "trials_7d": trials,
            "cpt_7d": store.safe_div(spend, trials),
            "ads": [dict(ad) for ad in store.ads_for(a["id"])],
        })
        out.append(row)
    return out


def _search_terms(campaign_id):
    # type: (str) -> List[Dict[str, Any]]
    rows = []
    for st in store.get_state()["search_terms"]:
        if st["campaign_id"] != campaign_id:
            continue
        r = dict(st)
        r["cpt"] = store.safe_div(st["cost"], st["trials"])
        rows.append(r)
    rows.sort(key=lambda r: -float(r["cost"]))
    return rows


def _negatives(campaign_id):
    # type: (str) -> List[Dict[str, Any]]
    rows = [dict(n) for n in store.get_state()["negatives"] if n["campaign_id"] == campaign_id]
    rows.sort(key=lambda n: (n["added"], n["text"]), reverse=True)
    return rows


def _detail(campaign_id):
    # type: (str) -> Dict[str, Any]
    c = store.campaign(campaign_id)
    row = _campaign_row(c)
    is_google = c["platform"] == "google"
    return {
        "ok": True,
        "campaign": row,
        "adsets": _adsets_detail(c, row),
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
def index():
    rows = [_campaign_row(c) for c in store.campaigns()]
    return {
        "ok": True,
        "today": store.today(),
        "cpa_target": store.get_state()["meta"].get("cpa_target", [250, 280]),
        "campaigns": rows,
        "summary": _summary(),
        "activity": _activity(),
    }


@router.get("/activity")
def activity():
    return {"ok": True, "activity": _activity(), "summary": _summary()}


@router.get("/{campaign_id}")
def detail(campaign_id):
    # type: (str) -> Dict[str, Any]
    return _detail(campaign_id)


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
