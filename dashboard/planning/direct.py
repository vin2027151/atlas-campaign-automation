"""Direct controls: a human's one-click change on the Campaigns page, as real API requests.

No LLM. A click (pause / enable, a new daily budget, a new bid) becomes the same
API-shaped operations a Plan & Adapt changeset uses, checked by the same validator and
guardrails (planning.changeset), rendered as the exact HTTP request(s)
(planning.api_requests), sent through the platform adapter (sample: applied to
data/state.json through store; live: sent, behind the unchanged live gate), and logged.

    controls(snapshot=None) -> {entity_id: {"kind", "platform", "status", "budget", "bid"}}
    apply(actions, confirm=False, undo_token=None) -> result

action = {"kind": "campaign"|"adset"|"ad", "id": dashboard id,
          "action": "status"|"budget"|"bid", "value": "ACTIVE"|"PAUSED"|dollars,
          "expected": current value the user saw (optional; a mismatch is a conflict)}
result = {"ok", "applied": bool, "needs_confirm", "conflict", "warnings", "requests": [rendered],
          "responses", "changes": [{entity, field, before, after}], "undo": {"actions": [...], "token"},
          "pacing": {"before", "after"} (effective daily budgets, account), "mode"}

Guardrails are switched by ``direct_controls.guardrails`` in config/platforms.yaml
(:func:`guardrails_on`). Off (Vin, 2026-11-06, until he sets rules himself): every
change applies on the first click; only data-validity errors (not a number, zero or
negative, unknown id, wrong kind) and the stale-``expected`` 409 conflict refuse one.
Nothing ever needs a confirm. Plan & Adapt changesets keep their guardrails regardless.

When on, guardrails (planning.changeset) and when they ask for a confirm:
- A budget or bid edit runs every guardrail; a warning needs ``confirm``.
- A status-only batch (pause / enable) skips the "total daily budget rises >10%"
  check. Enabling something spends the budget it already has, which nobody is
  changing; pausing never asked for a confirm, so asking on the way back made a
  re-enable silently not happen. The pacing move is still reported in ``pacing``.
- An undo (``undo_token`` from an applied result, with exactly its actions) restores
  values the account held moments ago, so it skips the budget guardrails too (an
  undo of a -40% cut is +67%, which the per-change limit would refuse). The stale
  check still applies: if the value moved since, the undo is a 409 conflict.
  ``undo`` is only offered for a change that was applied.

Never imports planning.llm, planning.llm_worker, planning.prompts or anthropic.
"""

import json
import threading
import uuid
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

import planning
import store
from planning import adapters, api_requests, changeset, snapshot
from planning.adapters.base import outputs_from_response

KINDS = ("campaign", "adset", "ad")
ACTIONS = ("status", "budget", "bid")
MAX_ACTIONS = 40
MAX_VALUE = 1000000  # "implausibly large" dollars: a guardrail, applied only when guardrails are on
UNDO_KEEP = 500
_undo_lock = threading.Lock()
_undo_tokens = OrderedDict()  # type: OrderedDict
META_BID_STRATEGIES = {"COST_CAP": "Cost cap", "LOWEST_COST_WITH_BID_CAP": "Bid cap"}


def _money(v):
    # type: (Any) -> Optional[float]
    if v is None:
        return None
    return round(float(v), 2)


def _dash_status(s):
    # type: (Any) -> str
    s = str(s or "").upper()
    return "ACTIVE" if s in ("ENABLED", "ACTIVE") else s


# ----------------------------------------------------------------- controls

def _google_campaign_bid(c):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    b = c.get("bidding") or {}
    st = b.get("strategy")
    if st == "TARGET_CPA":
        return {"label": "Target CPA", "value": _money(b.get("target_cpa")), "editable": True,
                "field": "target_cpa.target_cpa_micros", "level": "campaign"}
    if st == "MAXIMIZE_CONVERSIONS":
        return {"label": "Target CPA (max. conversions)", "value": _money(b.get("target_cpa")), "editable": True,
                "field": "maximize_conversions.target_cpa_micros", "level": "campaign"}
    label = {"TARGET_IMPRESSION_SHARE": "Target impression share", "MANUAL_CPC": "Manual CPC (bid on ad groups)",
             "MAXIMIZE_CONVERSION_VALUE": "Maximize conversion value"}.get(st, st or "")
    return {"label": label, "value": None, "editable": False, "level": "campaign",
            "note": "no bid target to edit for this strategy"}


def _meta_sets_with_budget(c):
    return [s for s in c.get("ad_sets") or [] if s.get("daily_budget") is not None]


def _common(values):
    vals = [v for v in values if v is not None]
    if vals and all(abs(float(v) - float(vals[0])) < 0.005 for v in vals):
        return _money(vals[0])
    return None


def controls(snap=None):
    # type: (Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]
    """What each campaign, ad set / ad group and ad can change from the dashboard, with the
    current values (dollars) the controls start from."""
    snap = snap or snapshot.build()
    out = {}  # type: Dict[str, Dict[str, Any]]
    for c in (snap.get("google") or {}).get("campaigns", []):
        b = c.get("budget") or {}
        out[c["id"]] = {"kind": "campaign", "platform": "google", "status": _dash_status(c.get("status")),
                        "budget": {"value": _money(b.get("daily")), "editable": True, "level": "campaign",
                                   "shared": bool(b.get("shared"))},
                        "bid": _google_campaign_bid(c)}
        manual = (c.get("bidding") or {}).get("strategy") == "MANUAL_CPC"
        for ag in c.get("ad_groups") or []:
            bid = None
            if manual or ag.get("cpc_bid") is not None:
                bid = {"label": "Max CPC", "value": _money(ag.get("cpc_bid")), "editable": True,
                       "field": "cpc_bid_micros", "level": "ad_group"}
            out[ag["id"]] = {"kind": "adset", "platform": "google", "status": _dash_status(ag.get("status")),
                             "budget": None, "bid": bid}
            for a in ag.get("ads") or []:
                out[a["id"]] = {"kind": "ad", "platform": "google", "status": _dash_status(a.get("status")),
                                "budget": None, "bid": None}
        for ag in c.get("asset_groups") or []:
            out[ag["id"]] = {"kind": "adset", "platform": "google", "status": _dash_status(ag.get("status")),
                             "budget": None, "bid": None}
            for a in ag.get("assets") or []:
                out[a["id"]] = {"kind": "ad", "platform": "google", "status": _dash_status(a.get("status")),
                                "budget": None, "bid": None}
    for c in (snap.get("meta") or {}).get("campaigns", []):
        cbo = c.get("daily_budget") is not None
        sets = c.get("ad_sets") or []
        if cbo:
            budget = {"value": _money(c["daily_budget"]), "editable": True, "level": "campaign"}
        else:
            live = [s for s in _meta_sets_with_budget(c) if s.get("status") == "ACTIVE"]
            budget = {"value": _money(sum(float(s["daily_budget"]) for s in live)), "editable": bool(live),
                      "level": "ad_sets", "note": "ad set budgets (ABO): a change scales the active ad sets proportionally"}
        strat = c.get("bid_strategy")
        cbid = None
        if strat in META_BID_STRATEGIES:
            cbid = {"label": META_BID_STRATEGIES[strat], "value": _common([s.get("bid_amount") for s in sets]),
                    "editable": bool(sets), "level": "ad_sets", "note": "set on every ad set in the campaign"}
        else:
            cbid = {"label": "Lowest cost (no cap)" if strat == "LOWEST_COST_WITHOUT_CAP" else (strat or ""),
                    "value": None, "editable": False, "level": "campaign", "note": "no bid to edit for this strategy"}
        out[c["id"]] = {"kind": "campaign", "platform": "meta", "status": _dash_status(c.get("status")),
                        "budget": budget, "bid": cbid}
        for s in sets:
            sb = None
            if not cbo and s.get("daily_budget") is not None:
                sb = {"value": _money(s["daily_budget"]), "editable": True, "level": "ad_set"}
            sbid = None
            if strat in META_BID_STRATEGIES:
                sbid = {"label": META_BID_STRATEGIES[strat], "value": _money(s.get("bid_amount")), "editable": True,
                        "field": "bid_amount", "level": "ad_set"}
            out[s["id"]] = {"kind": "adset", "platform": "meta", "status": _dash_status(s.get("status")),
                            "budget": sb, "bid": sbid}
            for a in s.get("ads") or []:
                out[a["id"]] = {"kind": "ad", "platform": "meta", "status": _dash_status(a.get("status")),
                                "budget": None, "bid": None}
    return out


# --------------------------------------------------------------- operations

def _g_update(service, rn, fields, mask, reason):
    spec = changeset.GOOGLE_SERVICES[service]
    return {"platform": "google", "service": service, "method": spec["method"], "operation": "update",
            "resource_name": rn, "fields": fields, "update_mask": mask, "reason": reason}


def _m_post(node_id, params, reason):
    return {"platform": "meta", "method": "POST", "path": "/%s" % node_id, "params": params, "reason": reason}


def _micros(dollars):
    # type: (float) -> int
    return int(round(float(dollars) * 100)) * 10000


def _cents(dollars):
    # type: (float) -> int
    return int(round(float(dollars) * 100))


def _number(value, what):
    # type: (Any, str) -> float
    if isinstance(value, bool) or value is None:
        raise store.BadInput("%s must be a number" % what)
    try:
        v = round(float(str(value).replace(",", "").replace("$", "")), 2)
    except (TypeError, ValueError):
        raise store.BadInput("%s must be a number" % what)
    if v != v or v in (float("inf"), float("-inf")) or v <= 0:  # NaN, infinite or not positive
        raise store.BadInput("%s must be greater than 0" % what)
    return v


def guardrails_on(cfg=None):
    # type: (Optional[Dict[str, Any]]) -> bool
    """config/platforms.yaml ``direct_controls.guardrails`` (YAML off/false/no -> False). Default on."""
    cfg = cfg if cfg is not None else adapters.load_config()
    v = (cfg.get("direct_controls") or {}).get("guardrails", True)
    if isinstance(v, str):
        return v.strip().lower() not in ("off", "false", "no", "0")
    return bool(v)


def _change(kind, eid, name, field, before, after, undo_value=None, undo_kind=None, undo_id=None, undo_action=None):
    return {"kind": kind, "id": eid, "name": name, "field": field, "before": before, "after": after,
            "undo": {"kind": undo_kind or kind, "id": undo_id or eid, "action": undo_action or field,
                     "value": before if undo_value is None else undo_value, "expected": after}}


def _ops_for(snap, act):
    # type: (Dict[str, Any], Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]
    """Operations and per-entity changes for one action."""
    kind, eid, action = act.get("kind"), str(act.get("id") or ""), act.get("action")
    if kind not in KINDS:
        raise store.BadInput("kind must be one of %s" % ", ".join(KINDS))
    if action not in ACTIONS:
        raise store.BadInput("action must be one of %s" % ", ".join(ACTIONS))
    hit = changeset.find_entity(snap, eid)
    if not hit:
        raise store.NotFound("unknown %s: %s" % (kind, eid))
    etype, ent, par = hit
    want = {"campaign": ("campaign",), "adset": ("ad_group", "asset_group", "ad_set"),
            "ad": ("ad", "asset_group_asset")}[kind]
    if etype not in want:
        raise store.BadInput("%s is a %s, not a %s" % (eid, etype.replace("_", " "), kind))
    platform = par.get("platform")
    name = ent.get("name") or eid
    reason = "Campaigns page: %s %s" % (action, name)

    if action == "status":
        new = str(act.get("value") or "").upper()
        if new not in ("ACTIVE", "PAUSED"):
            raise store.BadInput("status must be ACTIVE or PAUSED")
        before = _dash_status(ent.get("status"))
        if platform == "google":
            gs = "ENABLED" if new == "ACTIVE" else "PAUSED"
            service = {"campaign": "CampaignService", "ad_group": "AdGroupService", "asset_group": "AssetGroupService",
                       "ad": "AdGroupAdService", "asset_group_asset": "AssetGroupAssetService"}[etype]
            ops = [_g_update(service, ent["resource_name"], {"status": gs}, ["status"], reason)]
        else:
            ops = [_m_post(ent["meta_id"], {"status": new}, reason)]
        return ops, [_change(kind, eid, name, "status", before, new)]

    if kind == "ad":
        raise store.BadInput("ads have no budget or bid of their own")

    if action == "budget":
        new = _number(act.get("value"), "daily budget")
        if platform == "google":
            if etype != "campaign":
                raise store.BadInput("Google ad groups use the campaign budget; change it on the campaign")
            b = ent["budget"]
            ops = [_g_update("CampaignBudgetService", b["resource_name"], {"amount_micros": _micros(new)},
                             ["amount_micros"], reason)]
            return ops, [_change(kind, eid, name, "budget", _money(b["daily"]), new)]
        if etype == "ad_set":
            if par["campaign"].get("daily_budget") is not None or ent.get("daily_budget") is None:
                raise store.BadInput("%s is under a campaign budget (CBO); change the campaign budget" % name)
            ops = [_m_post(ent["meta_id"], {"daily_budget": _cents(new)}, reason)]
            return ops, [_change(kind, eid, name, "budget", _money(ent["daily_budget"]), new)]
        # meta campaign
        if ent.get("daily_budget") is not None:  # CBO
            ops = [_m_post(ent["meta_id"], {"daily_budget": _cents(new)}, reason)]
            return ops, [_change(kind, eid, name, "budget", _money(ent["daily_budget"]), new)]
        live = [s for s in _meta_sets_with_budget(ent) if s.get("status") == "ACTIVE"]
        if not live:
            raise store.BadInput("%s has no active ad set with a budget to scale" % name)
        old_total = round(sum(float(s["daily_budget"]) for s in live), 2)
        if not old_total:
            raise store.BadInput("%s's active ad sets have no budget" % name)
        # scale each active ad set; cents remainder on the largest so the total is exact
        cents = [int(round(float(s["daily_budget"]) * new / old_total * 100)) for s in live]
        diff = _cents(new) - sum(cents)
        big = max(range(len(live)), key=lambda i: float(live[i]["daily_budget"]))
        cents[big] += diff
        ops, changes = [], []
        for s, c in zip(live, cents):
            ops.append(_m_post(s["meta_id"], {"daily_budget": c}, "%s (scaled with %s)" % (reason, s["name"])))
            changes.append(_change("adset", s["id"], s["name"], "budget", _money(s["daily_budget"]), round(c / 100.0, 2)))
        return ops, changes

    # bid
    if platform == "google" and etype == "campaign":
        ctl = _google_campaign_bid(ent)
        if not ctl.get("editable"):
            raise store.BadInput("%s uses %s; there is no bid target to edit" % (name, ctl.get("label")))
        top = ctl["field"].split(".")[0]
        if act.get("value") is None and top == "maximize_conversions":
            new, micros = None, 0  # clear the optional target (how an undo restores "no target")
        else:
            new = _number(act.get("value"), "bid")
            micros = _micros(new)
        ops = [_g_update("CampaignService", ent["resource_name"], {top: {"target_cpa_micros": micros}},
                         [ctl["field"]], reason)]
        return ops, [_change(kind, eid, name, "bid", _money((ent.get("bidding") or {}).get("target_cpa")), new)]
    new = _number(act.get("value"), "bid")
    if platform == "google":
        if etype != "ad_group":
            raise store.BadInput("asset groups have no bid of their own")
        ops = [_g_update("AdGroupService", ent["resource_name"], {"cpc_bid_micros": _micros(new)},
                         ["cpc_bid_micros"], reason)]
        return ops, [_change(kind, eid, name, "bid", _money(ent.get("cpc_bid")), new)]
    camp = ent if etype == "campaign" else par["campaign"]
    if camp.get("bid_strategy") not in META_BID_STRATEGIES:
        raise store.BadInput("%s bids %s; a bid needs a cost cap or bid cap campaign" % (
            camp["name"], camp.get("bid_strategy")))
    sets = (ent.get("ad_sets") or []) if etype == "campaign" else [ent]
    if not sets:
        raise store.BadInput("%s has no ad sets" % name)
    ops, changes = [], []
    for s in sets:
        ops.append(_m_post(s["meta_id"], {"bid_amount": _cents(new)}, reason if etype != "campaign"
                           else "%s (ad set %s)" % (reason, s["name"])))
        changes.append(_change("adset", s["id"], s["name"], "bid", _money(s.get("bid_amount")), new))
    return ops, changes


def _current(snap, change, ctl_all=None):
    # type: (Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]) -> Any
    ctl = (ctl_all if ctl_all is not None else controls(snap)).get(change["id"]) or {}
    if change["field"] == "status":
        return ctl.get("status")
    return (ctl.get(change["field"]) or {}).get("value")


def _same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 0.005
    return a == b


# -------------------------------------------------------------------- apply

def _undo_key(actions):
    # type: (List[Dict[str, Any]]) -> str
    norm = [{"kind": a.get("kind"), "id": str(a.get("id") or ""), "action": a.get("action"),
             "value": a.get("value"), "expected": a.get("expected")} for a in actions]
    return json.dumps(norm, sort_keys=True)


def _issue_undo(actions):
    # type: (List[Dict[str, Any]]) -> Optional[str]
    if not actions:
        return None
    token = uuid.uuid4().hex
    with _undo_lock:
        _undo_tokens[token] = _undo_key(actions)
        while len(_undo_tokens) > UNDO_KEEP:
            _undo_tokens.popitem(last=False)
    return token


def _is_undo(token, actions):
    # type: (Any, List[Dict[str, Any]]) -> bool
    if not token or not isinstance(token, str):
        return False
    with _undo_lock:
        return _undo_tokens.get(token) == _undo_key(actions)


def _spend_undo(token):
    with _undo_lock:
        _undo_tokens.pop(token, None)


def apply(actions, confirm=False, undo_token=None):
    # type: (Any, bool, Optional[str]) -> Dict[str, Any]
    """Validate, render and run one or more direct actions as one batch (see module doc)."""
    if isinstance(actions, dict):
        actions = [actions]
    if not isinstance(actions, list) or not actions:
        raise store.BadInput("give at least one action")
    if len(actions) > MAX_ACTIONS:
        raise store.BadInput("too many actions in one request (%d > %d)" % (len(actions), MAX_ACTIONS))
    for act in actions:
        if not isinstance(act, dict):
            raise store.BadInput("each action must be an object")
    with planning.ACCOUNT_LOCK:
        undo = _is_undo(undo_token, actions)
        res = _apply(actions, bool(confirm), undo)
        if undo and res.get("applied"):
            _spend_undo(undo_token)
        res["is_undo"] = undo
        return res


def _apply(actions, confirm, is_undo=False):
    cfg = adapters.load_config()
    snap = snapshot.build()
    ctl_now = controls(snap)
    ops, changes, conflicts = [], [], []
    for act in actions:
        o, ch = _ops_for(snap, act)
        if "expected" in act and act["expected"] is not None:
            # the value the user saw: the control's current value for this action (for a Meta
            # ABO campaign budget that is the sum of its active ad sets, not any single change)
            seen = _current(snap, {"id": str(act.get("id") or ""), "field": act.get("action")}, ctl_now)
            if not _same(act["expected"], seen):
                conflicts.append({"id": str(act.get("id")), "name": ch[0]["name"] if ch else act.get("id"),
                                  "field": act.get("action"), "expected": act["expected"], "actual": seen})
        ops.extend(o)
        changes.extend(ch)
    for i, op in enumerate(ops):
        op["ref"] = "op%d" % (i + 1)
    title = "; ".join("%s %s -> %s" % (c["name"], c["field"], c["after"]) for c in changes)[:200]
    doc = {"changeset": {"title": title or "direct change", "based_on_snapshot": snap["id"],
                         "rationale": ["Campaigns page direct control"]}, "operations": ops}
    requests = api_requests.render_all(doc, snap, cfg)
    pace_before = store.active_daily_budget()
    base = {"ok": False, "applied": False, "mode": cfg["mode"], "requests": requests, "changes": changes,
            "warnings": [], "needs_confirm": False, "conflict": False, "responses": [],
            "undo": {"actions": [], "token": None},  # filled in only once the change is applied
            "pacing": {"before": pace_before, "after": pace_before}}
    undo_actions = [c["undo"] for c in changes if not _same(c["before"], c["after"])]
    if conflicts:
        base.update(conflict=True, conflicts=conflicts, error="%s changed since you loaded the page (now %s)" % (
            conflicts[0]["name"], conflicts[0]["actual"]))
        return base
    noop = [c for c in changes if _same(c["before"], c["after"])]
    if len(noop) == len(changes):
        base.update(ok=True, error=None, message="nothing to change")
        return base
    status_only = all(c["field"] == "status" for c in changes)
    guarded = guardrails_on(cfg) and not is_undo
    base["guardrails"] = guarded
    if guarded:
        for c in changes:
            if c["field"] in ("budget", "bid") and c["after"] is not None and c["after"] > MAX_VALUE:
                raise store.BadInput("%s %s is implausibly large" % (c["name"], c["field"]))
    issues = changeset.validate(doc, snap, guardrails=guarded, total_rise=not status_only)
    errors = [i for i in issues if i["level"] == "error"]
    if errors:
        raise store.BadInput("; ".join(i["message"] for i in errors))
    warnings = [i["message"] for i in issues if i["level"] == "warn" and "based on" not in i["message"]
                and "shared budget" not in i["message"]]
    base["warnings"] = warnings
    if warnings and not confirm and guarded:
        base.update(needs_confirm=True, error="confirm this change: " + "; ".join(warnings))
        return base
    for r in requests:
        if r.get("error"):
            raise store.BadInput("request could not be built: %s" % r["error"])

    outputs = {}  # type: Dict[str, Dict[str, Any]]
    sent = []
    for op, req in zip(ops, requests):
        adapter = adapters.get_adapter(op["platform"], cfg)
        ctx = {"mode": cfg["mode"], "config": cfg, "snapshot": snap, "outputs": outputs}
        real = api_requests.resolve(req, outputs)
        try:
            resp = adapter.execute_request(req, ctx)
        except adapters.LiveRefused as exc:
            base.update(error=str(exc), responses=base["responses"], sent=sent)
            if sent:  # part of the batch went out: offer the undo for what did
                base["undo"] = {"actions": undo_actions, "token": _issue_undo(undo_actions)}
            return base
        except Exception as exc:
            store.log_activity("api request failed", changes[0]["id"], "%s: %s" % (api_requests.log_line(real), exc))
            raise store.BadInput("request %s failed: %s%s" % (
                req.get("step"), exc, " (earlier requests in this batch were applied)" if sent else ""))
        outputs[op["ref"]] = outputs_from_response(op, resp)
        sent.append(real)
        base["responses"].append(resp)
        store.log_activity("api request", _target(op, changes), api_requests.log_line(real), actor="vin")
    after = snapshot.build()
    ctl_after = controls(after)
    for c in changes:
        c["now"] = _current(after, c, ctl_after)
    base["undo"] = {"actions": undo_actions, "token": _issue_undo(undo_actions)}
    base["pacing"]["after"] = store.active_daily_budget()
    base.update(ok=True, applied=True, error=None,
                verified=all(_same(c["now"], c["after"]) for c in changes))
    return base


def _target(op, changes):
    # type: (Dict[str, Any], List[Dict[str, Any]]) -> str
    i = int(str(op.get("ref", "op1"))[2:] or 1) - 1
    if 0 <= i < len(changes):
        return changes[i]["id"]
    return changes[0]["id"] if changes else ""
