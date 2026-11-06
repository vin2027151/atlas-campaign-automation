"""State document (snapshot) of both ad accounts.

    pull(reason="analyze") -> doc        # saves DATA_DIR/snapshots/<id>.json, returns doc
    get(snapshot_id) -> doc              # store.NotFound if missing
    latest() -> doc | None
    list_snapshots(limit=20) -> [{id, taken_at, reason, counts}]
    to_yaml(doc) -> str                  # the human state document (download)
    compact(doc) -> dict                 # trimmed for prompts
    build(mode=None) -> doc              # the document without saving it
    recompute(doc) -> doc                # refresh totals + counts after an in-memory edit

Values use dashboard units (dollars); API units (micros, cents) appear only where the API
uses them (Google budget ``amount_micros``). In sample mode the account is store state +
data/planning/account_overlay.json (see planning.adapters.sample).
"""

import copy
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yaml

import planning
import store
from planning import adapters
from planning.adapters import sample

SNAPSHOT_SUBDIR = "snapshots"
ID_RE = re.compile(r"^SNAP-\d{8}-\d{6}(-\d+)?$")


def _dir():
    # type: () -> str
    return planning.ensure_dir(planning.data_path(SNAPSHOT_SUBDIR))


def _metrics(cid):
    # type: (str) -> Dict[str, Any]
    w = store.window_totals(cid, 7)
    mtd = store.month_to_date(cid)
    return {"spend_7d": w["spend"], "trials_7d": w["trials"], "cpt_7d": w["cost_per_trial"],
            "clicks_7d": w["clicks"], "impressions_7d": w["impressions"], "ctr_7d": w["ctr"],
            "spend_mtd": mtd["spend"], "trials_mtd": mtd["trials"], "cpt_mtd": mtd["cost_per_trial"],
            "paid_mtd": mtd["paid"]}


def _gstatus(s):
    # type: (str) -> str
    return "ENABLED" if s == "ACTIVE" else s


def _google(state, ov):
    # type: (Dict[str, Any], Dict[str, Any]) -> Dict[str, Any]
    g = ov["google"]
    cust = g["customer_id"]
    rn = lambda coll, *ids: "customers/%s/%s/%s" % (cust, coll, "~".join(str(i) for i in ids))
    out = []
    for c in state["campaigns"]:
        if c["platform"] != "google":
            continue
        oc = g["campaigns"][c["id"]]
        daily = round(float(c["daily_budget"]), 2)
        camp = {
            "id": c["id"], "resource_name": rn("campaigns", oc["num"]), "name": c["name"],
            "status": _gstatus(c["status"]), "channel": oc["channel"], "legacy": bool(c.get("legacy")),
            "bidding": copy.deepcopy(oc["bidding"]),
            "budget": {"resource_name": rn("campaignBudgets", oc["budget_num"]), "daily": daily,
                       "amount_micros": int(round(daily * 1e6)), "shared": bool(oc.get("shared")),
                       "name": oc["budget_name"], "delivery_method": "STANDARD"},
            "monthly_budget": c.get("monthly_budget"),
            "geo": list(oc["geo"]), "languages": list(oc.get("languages") or []),
            "start_date": c.get("start_date"), "metrics": _metrics(c["id"]),
            "negatives": [], "ad_groups": [],
        }
        for n in g["negatives"]:
            if n["campaign_id"] == c["id"]:
                camp["negatives"].append({"resource_name": rn("campaignCriteria", oc["num"], n["num"]),
                                          "text": n["text"], "match": n["match"].upper()})
        if oc["channel"] == "PERFORMANCE_MAX":
            camp["asset_groups"] = []
        for a in store.adsets_for(c["id"]):
            oa = g["ad_groups"][a["id"]]
            if oa["kind"] == "asset_group":
                ag = {"id": a["id"], "resource_name": rn("assetGroups", oa["num"]), "name": a["name"],
                      "status": _gstatus(a["status"]), "final_url": oa.get("final_url")}
                ag.update(copy.deepcopy(oa["copy"]))
                ag["assets"] = []
                for ad in store.ads_for(a["id"]):
                    od = g["ads"][ad["id"]]
                    # customers/{cid}/assetGroupAssets/{asset_group_id}~{asset_id}~{field_type}
                    field_type = "YOUTUBE_VIDEO" if od.get("asset_type") == "YOUTUBE_VIDEO" else "MARKETING_IMAGE"
                    ag["assets"].append({"id": ad["id"], "resource_name": rn("assetGroupAssets", oa["num"], od["num"], field_type),
                                         "field_type": field_type,
                                         "type": od.get("asset_type"), "name": ad["name"],
                                         "status": _gstatus(ad["status"])})
                camp.setdefault("asset_groups", []).append(ag)
                continue
            grp = {"id": a["id"], "resource_name": rn("adGroups", oa["num"]), "name": a["name"],
                   "status": _gstatus(a["status"]), "cpc_bid": oa.get("cpc_bid"), "keywords": [], "ads": []}
            for k in oa.get("keywords") or []:
                grp["keywords"].append({"resource_name": rn("adGroupCriteria", oa["num"], k["num"]),
                                        "text": k["text"], "match": k["match"], "status": k["status"]})
            for ad in store.ads_for(a["id"]):
                od = g["ads"][ad["id"]]
                grp["ads"].append({"id": ad["id"], "resource_name": rn("adGroupAds", oa["num"], od["num"]),
                                   "name": ad["name"], "type": od.get("type"), "status": _gstatus(ad["status"]),
                                   "headlines": list(od.get("headlines") or []),
                                   "descriptions": list(od.get("descriptions") or []),
                                   "final_url": od.get("final_url")})
            camp["ad_groups"].append(grp)
        out.append(camp)
    assets = [{"resource_name": rn("assets", a["num"]), "name": a["name"], "type": a["type"],
               "media_id": a.get("media_id")} for a in g.get("assets") or []]
    return {"customer_id": cust, "campaigns": out, "assets": assets}


def _meta(state, ov):
    # type: (Dict[str, Any], Dict[str, Any]) -> Dict[str, Any]
    m = ov["meta"]
    out = []
    for c in state["campaigns"]:
        if c["platform"] != "meta":
            continue
        oc = m["campaigns"][c["id"]]
        camp = {
            "id": c["id"], "meta_id": oc["meta_id"], "name": c["name"], "status": c["status"],
            "objective": oc["objective"], "buying_type": oc["buying_type"], "legacy": bool(c.get("legacy")),
            "daily_budget": round(float(c["daily_budget"]), 2) if oc.get("cbo") else None,
            "bid_strategy": oc["bid_strategy"], "monthly_budget": c.get("monthly_budget"),
            "start_date": c.get("start_date"), "metrics": _metrics(c["id"]), "ad_sets": [],
        }
        for a in store.adsets_for(c["id"]):
            oa = m["ad_sets"][a["id"]]
            t = copy.deepcopy(oa["targeting"])
            t.pop("sample_derived", None)
            fc = copy.deepcopy(oa.get("frequency_cap"))
            if isinstance(fc, dict):
                fc.pop("sample_derived", None)
            s = {"id": a["id"], "meta_id": oa["meta_id"], "name": a["name"], "status": a["status"],
                 "daily_budget": None if oc.get("cbo") or a.get("daily_budget") is None else round(float(a["daily_budget"]), 2),
                 "optimization_goal": oa["optimization_goal"], "billing_event": oa["billing_event"],
                 "promoted_object": copy.deepcopy(oa.get("promoted_object")),
                 "bid_amount": oa.get("bid_amount"), "targeting": t, "frequency_cap": fc, "ads": []}
            for ad in store.ads_for(a["id"]):
                od = m["ads"][ad["id"]]
                s["ads"].append({"id": ad["id"], "meta_id": od["meta_id"], "name": ad["name"], "status": ad["status"],
                                 "format": ad.get("format"), "title": od.get("title"), "body": od.get("body"),
                                 "cta": od.get("cta"), "media_id": od.get("media_id"),
                                 "creative_id": od.get("creative_id")})
            camp["ad_sets"].append(s)
        out.append(camp)
    return {"ad_account_id": m["ad_account_id"], "page_id": m.get("page_id"), "campaigns": out,
            "images": copy.deepcopy(m.get("images") or []), "videos": copy.deepcopy(m.get("videos") or []),
            "creatives": copy.deepcopy(m.get("creatives") or [])}


def meta_campaign_daily(c):
    # type: (Dict[str, Any]) -> float
    """A Meta campaign's effective daily budget: CBO budget, else its active ad sets' budgets."""
    if c.get("daily_budget") is not None:
        return store.money_sum([c["daily_budget"]])
    return store.money_sum(s.get("daily_budget") for s in c.get("ad_sets", []) if s.get("status") == "ACTIVE")


def _group_delivers(grp, on):
    # type: (Dict[str, Any], str) -> bool
    """Same rule as store.adset_delivers: enabled and, if it has ads / assets, one of them enabled."""
    if grp.get("status") != on:
        return False
    ads = grp.get("ads") if "ads" in grp else grp.get("assets")
    return not ads or any(a.get("status") == on for a in ads)


def google_campaign_effective_daily(c):
    # type: (Dict[str, Any]) -> float
    """store.effective_daily_budget in state-document shape (Google)."""
    if c.get("status") != "ENABLED":
        return 0.0
    groups = list(c.get("ad_groups") or []) + list(c.get("asset_groups") or [])
    if groups and not any(_group_delivers(g, "ENABLED") for g in groups):
        return 0.0
    return store.money_sum([(c.get("budget") or {}).get("daily")])


def meta_campaign_effective_daily(c):
    # type: (Dict[str, Any]) -> float
    """store.effective_daily_budget in state-document shape (Meta): CBO budget, or the
    delivering ad sets' budgets (ABO); 0 when paused or when no ad set delivers."""
    if c.get("status") != "ACTIVE":
        return 0.0
    sets = c.get("ad_sets") or []
    live = [s for s in sets if _group_delivers(s, "ACTIVE")]
    if sets and not live:
        return 0.0
    if c.get("daily_budget") is not None:
        return store.money_sum([c["daily_budget"]])
    return store.money_sum(s.get("daily_budget") for s in live)


def recompute(doc):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    """Refresh ``totals`` and ``counts`` in place (active campaigns only count toward daily budget)."""
    g = doc.get("google") or {"campaigns": []}
    m = doc.get("meta") or {"campaigns": []}
    seen = set()
    g_parts = []
    for c in g["campaigns"]:
        b = c.get("budget") or {}
        eff = google_campaign_effective_daily(c)
        if eff and b.get("resource_name") not in seen:  # a shared budget counts once
            seen.add(b.get("resource_name"))
            g_parts.append(eff)
    g_daily = store.money_sum(g_parts)
    m_daily = store.money_sum(meta_campaign_effective_daily(c) for c in m["campaigns"])
    g_mtd = store.money_sum((c.get("metrics") or {}).get("spend_mtd") for c in g["campaigns"])
    m_mtd = store.money_sum((c.get("metrics") or {}).get("spend_mtd") for c in m["campaigns"])
    doc["totals"] = {
        "google": {"daily_budget": g_daily, "spend_mtd": g_mtd},
        "meta": {"daily_budget": m_daily, "spend_mtd": m_mtd},
        "all": {"daily_budget": store.money_sum([g_daily, m_daily]), "spend_mtd": store.money_sum([g_mtd, m_mtd])},
    }
    ad_groups = sum(len(c.get("ad_groups") or []) + len(c.get("asset_groups") or []) for c in g["campaigns"])
    ad_sets = sum(len(c.get("ad_sets") or []) for c in m["campaigns"])
    ads = sum(len(ag.get("ads") or []) + 0 for c in g["campaigns"] for ag in c.get("ad_groups") or [])
    ads += sum(len(ag.get("assets") or []) for c in g["campaigns"] for ag in c.get("asset_groups") or [])
    ads += sum(len(s.get("ads") or []) for c in m["campaigns"] for s in c.get("ad_sets") or [])
    doc["counts"] = {
        "campaigns": len(g["campaigns"]) + len(m["campaigns"]),
        "ad_groups": ad_groups, "ad_sets": ad_sets, "ads": ads,
        "keywords": sum(len(ag.get("keywords") or []) for c in g["campaigns"] for ag in c.get("ad_groups") or []),
        "negatives": sum(len(c.get("negatives") or []) for c in g["campaigns"]),
    }
    return doc


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def build(mode=None):
    # type: (Optional[str]) -> Dict[str, Any]
    """The current state document, not saved. Sample mode reads store + overlay."""
    mode = mode or adapters.mode()
    if mode != "sample":
        raise RuntimeError("live account pull is not implemented: the live adapters only write. "
                           "Set mode: sample in config/platforms.yaml.")
    ov = sample.load_overlay()
    state = store.get_state()
    now = _now()
    doc = {"id": "SNAP-%s" % now.strftime("%Y%m%d-%H%M%S"),
           "taken_at": now.isoformat().replace("+00:00", "Z"), "reason": "", "mode": mode,
           "as_of": store.today(), "sample_derived": True,
           "google": _google(state, ov), "meta": _meta(state, ov)}
    return recompute(doc)


def _path(sid):
    # type: (str) -> str
    return os.path.join(_dir(), "%s.json" % sid)


def pull(reason="analyze"):
    # type: (str) -> Dict[str, Any]
    """Pull both accounts into a new saved snapshot and return it."""
    doc = build()
    doc["reason"] = str(reason or "")
    base, n = doc["id"], 1
    while os.path.exists(_path(doc["id"])):
        n += 1
        doc["id"] = "%s-%d" % (base, n)
    store.write_json_atomic(_path(doc["id"]), doc)
    return doc


def get(snapshot_id):
    # type: (str) -> Dict[str, Any]
    sid = str(snapshot_id or "")
    if not ID_RE.match(sid) or not os.path.exists(_path(sid)):
        raise store.NotFound("unknown snapshot: %s" % sid)
    with open(_path(sid), "r", encoding="utf-8") as fh:
        return json.load(fh)


def _ids():
    # type: () -> List[str]
    d = _dir()
    ids = [f[:-5] for f in os.listdir(d) if f.endswith(".json") and ID_RE.match(f[:-5])]

    def key(i):
        parts = i.split("-")
        return (parts[1], parts[2], int(parts[3]) if len(parts) > 3 else 1)
    return sorted(ids, key=key, reverse=True)


def latest():
    # type: () -> Optional[Dict[str, Any]]
    ids = _ids()
    return get(ids[0]) if ids else None


def list_snapshots(limit=20):
    # type: (int) -> List[Dict[str, Any]]
    out = []
    for sid in _ids()[:max(0, int(limit))]:
        try:
            d = get(sid)
        except (store.NotFound, ValueError):
            continue
        out.append({"id": d["id"], "taken_at": d.get("taken_at"), "reason": d.get("reason"),
                    "counts": d.get("counts"), "totals": d.get("totals"), "mode": d.get("mode")})
    return out


class _Dumper(yaml.SafeDumper):
    pass


def _str_rep(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_Dumper.add_representer(str, _str_rep)


def to_yaml(doc):
    # type: (Dict[str, Any]) -> str
    """The human state document. Stable key order, so two snapshots diff cleanly."""
    header = ("# Ad account state document %s (%s, as of %s)\n"
              "# Money in dollars; amount_micros and Meta cents only where the API uses them.\n"
              % (doc.get("id"), doc.get("mode"), doc.get("as_of")))
    return header + yaml.dump(doc, Dumper=_Dumper, sort_keys=False, allow_unicode=True,
                              default_flow_style=False, width=110)


def _strip(obj):
    if isinstance(obj, dict):
        return dict((k, _strip(v)) for k, v in obj.items()
                    if v is not None and v != [] and k not in ("sample_derived", "description"))
    if isinstance(obj, list):
        return [_strip(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 2)
    return obj


def compact(doc):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    """Trimmed for prompts: no nulls/empties/sample flags, metrics kept as 7d/MTD totals only."""
    d = copy.deepcopy(doc)
    for c in (d.get("google") or {}).get("campaigns", []) + (d.get("meta") or {}).get("campaigns", []):
        mt = c.get("metrics") or {}
        c["metrics"] = dict((k, mt.get(k)) for k in ("spend_7d", "trials_7d", "cpt_7d", "spend_mtd", "trials_mtd", "cpt_mtd"))
    d.pop("taken_at", None)
    return _strip(d)
