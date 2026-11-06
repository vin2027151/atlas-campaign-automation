"""Campaigns page API: every campaign's numbers and its controls, in one place.

GET /api/campaigns/?window=3d|7d|14d|30d|mtd returns the campaign table (spend,
budget, pacing, 3-day / 7-day cost per trial, ad sets and their ads), the
pacing summary, and the search terms / negatives for review. The metrics come
from api/spend.py (the shared metrics layer of the former Spend page).

Direct controls (pause / enable a campaign, ad set / ad group or ad; a new daily
budget; a new bid) go through POST /api/campaigns/actions -> planning.direct: the
change becomes the exact Google Ads / Meta API request(s), checked by the same
validator and guardrails as Plan & Adapt, applied through the platform adapter
(sample: store -> data/state.json, so every browser sees it), and logged with the
request. The older per-entity status/budget routes use the same path.
Negative keywords still go through the store helper.

Ad sets have no daily rows in the sample data, so ad set metrics are the
campaign's window totals apportioned by ad set budget share (equal split when
the ad sets carry no budget of their own, as Google ad groups do). Ads split
their ad set's totals by a seeded per-ad share saved once in state.json
(store.ensure_ad_splits), so ads add up to their ad set.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import store
from api import spend
from planning import direct

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])

SESSION_START = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
ACTIVITY_SHOWN = 15


class StatusBody(BaseModel):
    status: str


class BudgetBody(BaseModel):
    daily_budget: Any = None


class ActionBody(BaseModel):
    kind: Optional[str] = None
    id: Optional[str] = None
    action: Optional[str] = None
    value: Any = None
    expected: Any = None
    actions: Any = None
    confirm: Any = False
    undo_token: Any = None


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


AD_METRIC_KEYS = ("spend", "impressions", "clicks", "ctr", "trials", "paid", "cost_per_trial", "cost_per_paid",
                  "platform_conversions", "cpc")


def _ads_with_metrics(row, adset):
    # type: (Dict[str, Any], Dict[str, Any]) -> List[Dict[str, Any]]
    """The ad set's ads, each with its own window metrics (its seeded share of the ad set)."""
    raw = dict((k, adset.get(k) or 0) for k in store.AD_SPLIT_KEYS)  # the ad set's own (rounded) totals
    ads = [dict(ad) for ad in store.ads_for(adset["id"])]
    for ad, m in zip(ads, store.split_ad_metrics(raw, ads)):
        ad.pop("metrics_split", None)
        ad["metrics"] = dict((k, m.get(k)) for k in AD_METRIC_KEYS)
        ad["metrics_basis"] = "seeded share of the ad set (sample data)"
    return ads


def _with_controls(item, ctl):
    # type: (Dict[str, Any], Optional[Dict[str, Any]]) -> None
    ctl = ctl or {}
    item["controls"] = {"budget": ctl.get("budget"), "bid": ctl.get("bid")}


def _campaign_row(c, win=None, ctl=None):
    # type: (Dict[str, Any], Optional[Dict[str, Any]], Optional[Dict[str, Any]]) -> Dict[str, Any]
    """One table row: the spend metrics for the window plus the control fields.

    ``pace_pct`` is average spend per live day in the window as a share of the
    current daily budget (how fully the campaign is spending its budget).
    ``controls`` (on the campaign, each ad set and each ad) say what the direct
    budget / bid editors can change and their current values.
    """
    win = win or spend.window_bounds("7d")
    ctl = ctl if ctl is not None else _controls()
    row = spend.campaign_row(c, win)
    adsets = row.pop("adsets")
    for a in adsets:
        a["ads"] = _ads_with_metrics(row, a)
        _with_controls(a, ctl.get(a["id"]))
        for ad in a["ads"]:
            _with_controls(ad, ctl.get(ad["id"]))
    _with_controls(row, ctl.get(c["id"]))
    row["adsets"] = adsets
    row["adset_count"] = len(adsets)
    row["recommended_negatives"] = _pending_negatives(c["id"]) if c["platform"] == "google" else 0
    row["supports_negatives"] = c["platform"] == "google"
    row["pace_pct"] = store.safe_div(row["spend_per_day"], row["daily_budget"], 100.0, 0) if row["spend_per_day"] is not None else None
    return row


def _controls():
    # type: () -> Dict[str, Dict[str, Any]]
    try:
        return direct.controls()
    except Exception:  # live mode has no account pull: show the rows without editors
        return {}


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
        pace = store.pacing(pl)
        # one figure: the effective daily budgets pacing projects (store.effective_daily_budget)
        active_daily = pace["active_daily_budget"]
        target = round(pace["monthly_budget"] / float(pace["days_in_month"]), 2)
        b.update({
            "active_daily_budget": active_daily,
            "daily_target": target,
            "pct_of_target": store.safe_div(active_daily, target, 100.0, 1),
            "active": sum(1 for c in mine if c["status"] == "ACTIVE"),
            "paused": sum(1 for c in mine if c["status"] == "PAUSED"),
            "month_pace_pct": pace["pace_pct"],
            "projected_month_end": pace["projected_month_end"],
            "projection_label": pace["projection_label"],
            "pacing_daily_budget": pace["active_daily_budget"],
            "days_remaining": pace["days_remaining"],
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
    store.ensure_ad_splits()
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
    store.ensure_ad_splits()
    meta = store.get_state()["meta"]
    ctl = _controls()
    rows = [_campaign_row(c, win, ctl) for c in spend.ordered_campaigns()]
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
        "mode": _mode(),
    }


def _mode():
    # type: () -> str
    try:
        from planning import adapters
        return adapters.mode()
    except Exception:
        return "sample"


@router.get("/activity")
def activity():
    return {"ok": True, "activity": _activity(), "summary": _summary()}


@router.get("/{campaign_id}")
def detail(campaign_id, window: str = Query("7d")):
    # type: (str, str) -> Dict[str, Any]
    return _detail(campaign_id, spend.window_bounds(window))


# ---------------------------------------------------------------- mutations

@router.post("/actions")
def actions(body: ActionBody):
    """Direct control: one action ({kind, id, action, value, expected}) or {actions: [...]}.

    200 {ok, summary, activity, result: {applied, requests, changes, undo: {actions, token}, ...}};
    when guardrails warn and ``confirm`` is not true: 200 with result {applied: false,
    needs_confirm: true, warnings, requests} (nothing applied, no undo); when the value
    moved since the page loaded: 409 conflict. An undo posts ``{actions, undo_token}``
    exactly as an applied result gave them (see planning.direct for what that skips).
    """
    acts = body.actions if body.actions is not None else [
        {"kind": body.kind, "id": body.id, "action": body.action, "value": body.value, "expected": body.expected}]
    res = direct.apply(acts, confirm=body.confirm is True, undo_token=body.undo_token)
    if res.get("conflict"):
        return JSONResponse(dict(res, summary=_summary()), status_code=409)
    if res.get("error") and not res.get("needs_confirm") and not res.get("applied"):
        return JSONResponse(res, status_code=400)
    return _mutation_response(result=res)


def _direct(kind, eid, action, value):
    res = direct.apply({"kind": kind, "id": eid, "action": action, "value": value}, confirm=True)
    if res.get("error") and not res.get("applied"):
        raise store.BadInput(res["error"])
    return res


@router.post("/{campaign_id}/status")
def campaign_status(campaign_id, body: StatusBody):
    res = _direct("campaign", campaign_id, "status", str(body.status or "").upper())
    return _mutation_response(campaign=_campaign_row(store.campaign(campaign_id)), result=res)


@router.post("/{campaign_id}/budget")
def campaign_budget(campaign_id, body: BudgetBody):
    v = body.daily_budget
    if v is None or isinstance(v, bool):
        raise store.BadInput("daily_budget is required")
    res = _direct("campaign", campaign_id, "budget", v)
    return _mutation_response(campaign=_campaign_row(store.campaign(campaign_id)), result=res)


@router.post("/adsets/{adset_id}/status")
def adset_status(adset_id, body: StatusBody):
    res = _direct("adset", adset_id, "status", str(body.status or "").upper())
    return _mutation_response(adset=dict(store.adset(adset_id)), result=res)


@router.post("/ads/{ad_id}/status")
def ad_status(ad_id, body: StatusBody):
    res = _direct("ad", ad_id, "status", str(body.status or "").upper())
    return _mutation_response(ad=dict(store.ad(ad_id)), result=res)


@router.post("/{campaign_id}/negatives")
def add_negative(campaign_id, body: NegativeBody):
    source = body.source if body.source in ("manual", "recommended") else "manual"
    neg = store.add_negative(campaign_id, body.text, body.match, source)
    return _mutation_response(negative=neg, search_terms=_search_terms(campaign_id),
                              negatives=_negatives(campaign_id))
