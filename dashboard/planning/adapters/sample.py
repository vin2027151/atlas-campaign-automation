"""Sample ad accounts: store state (data/state.json) + data/planning/account_overlay.json.

The store stays the source of truth for statuses, budgets, negatives and ads, so the
rest of the dashboard reflects a publish. The overlay holds what the store does not
model: platform-native IDs and resource names, keywords, RSA copy, Meta ad copy,
optimization goals, bid strategies with targets, targeting, uploaded images/videos and
creatives. It is generated deterministically on first use (everything synthesized carries
``sample_derived: true``) and then mutated by publishes.

SampleAdapter executes changeset operations against store + overlay and answers with
API-shaped responses: Google ``{"results": [{"resourceName": ...}]}``, Meta ``{"id": ...}``
/ ``{"images": {name: {"hash": ...}}}``. Its request preview is the real REST request.
"""

import copy
import hashlib
import json
import os
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

import yaml

import planning
import store
from planning.adapters.base import (Adapter, AdapterError, mark_media_published, media_asset,
                                    nest_paths, resolve_refs)

OVERLAY_NAME = "account_overlay.json"
PLAN_PATH = os.path.join(planning.BASE_DIR, "data", "plan", "plan.yaml")
_lock = threading.RLock()

GOOGLE_START = {"campaign": 101, "budget": 201, "ad_group": 3001, "asset_group": 6001,
                "ad": 50001, "criterion": 70001, "asset": 90001}
META_START = {"campaign": 1, "ad_set": 101, "ad": 1, "creative": 1, "video": 1}
META_PREFIX = {"campaign": "12021000000000", "ad_set": "12021000000000", "ad": "12022000000000",
               "creative": "12023000000000", "video": "12024000000000"}
CTA_MAP = {"start free trial": "SIGN_UP", "start trial": "SIGN_UP", "sign up": "SIGN_UP",
           "finish signup": "SIGN_UP", "see pricing": "LEARN_MORE", "learn more": "LEARN_MORE"}
COUNTRY = {"UK": "GB"}


def overlay_path():
    # type: () -> str
    return planning.data_path(OVERLAY_NAME)


# ------------------------------------------------------------------ plan hints

def _plan():
    # type: () -> Dict[str, Any]
    try:
        with open(PLAN_PATH, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _trim(s, n):
    # type: (str, int) -> str
    s = " ".join(str(s or "").split())
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0]
    return cut.rstrip(" ,.-|") or s[:n]


def _uniq(items):
    out = []  # type: List[str]
    for x in items:
        if x and x.lower() not in [o.lower() for o in out]:
            out.append(x)
    return out


# ------------------------------------------------------------- derivations

def _google_bidding(c):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    s = str(c.get("bid_strategy") or "")
    low = s.lower()
    num = re.search(r"\$\s*([\d,.]+)", s)
    pct = re.search(r"([\d.]+)\s*%", s)
    if "target cpa" in low:
        return {"strategy": "TARGET_CPA", "target_cpa": float(num.group(1).replace(",", "")) if num else None}
    if "impression share" in low:
        return {"strategy": "TARGET_IMPRESSION_SHARE", "target_cpa": None,
                "target_impression_share": float(pct.group(1)) if pct else None,
                "location": "ABSOLUTE_TOP_OF_PAGE"}
    if "maximize conversion value" in low:
        return {"strategy": "MAXIMIZE_CONVERSION_VALUE", "target_cpa": None}
    if "maximize conversions" in low:
        return {"strategy": "MAXIMIZE_CONVERSIONS", "target_cpa": float(num.group(1).replace(",", "")) if num else None}
    if "manual" in low:
        return {"strategy": "MANUAL_CPC", "target_cpa": None}
    return {"strategy": "MAXIMIZE_CONVERSIONS", "target_cpa": None}


def _keywords_for(adset, plan_groups, nxt):
    # type: (Dict[str, Any], Dict[str, Any], Dict[str, int]) -> List[Dict[str, Any]]
    kws = []  # type: List[Tuple[str, str, bool]]
    if adset["name"] in plan_groups:
        for k in plan_groups[adset["name"]].get("keywords") or []:
            kws.append((str(k["text"]).lower(), str(k.get("match", "Phrase")).upper(), False))
    else:
        t = str(adset.get("targeting") or "")
        head, _, tail = t.partition(":")
        text = tail if tail else head
        matches = ["PHRASE"]
        if tail and "exact" in head.lower():
            matches = ["EXACT", "PHRASE"] if "phrase" in head.lower() else ["EXACT"]
        terms = [" ".join(x.lower().split()) for x in text.split(",")]
        terms = [re.sub(r"\(.*?\)", "", x).strip() for x in terms]
        terms = [x for x in terms if x and len(x.split()) <= 10]
        if not terms:
            terms = [adset["name"].replace("_", " ").lower()]
        for m in matches:
            for x in terms:
                kws.append((x, m, True))
    out = []
    for text, match, derived in kws:
        n = nxt["criterion"]
        nxt["criterion"] += 1
        out.append({"num": n, "text": text, "match": match, "status": "ENABLED", "sample_derived": True,
                    "from_plan": not derived})
    return out


def _rsa_copy(ad, campaign, landing):
    # type: (Dict[str, Any], Dict[str, Any], str) -> Dict[str, Any]
    parts = [p.strip() for p in str(ad.get("hook") or "").split("|") if p.strip()]
    heads = [_trim(p, 30) for p in parts]
    if campaign.get("type") == "Brand":
        heads.append("Search Atlas Official Site")
    heads += ["All-In-One SEO Platform", "Start A 7-Day Trial", _trim(str(ad.get("cta") or ""), 30)]
    desc = [_trim(". ".join(parts) + ".", 90) if parts else "",
            "Rank tracking, audits, content and backlinks in one login.",
            "Start a 7-day trial today. Cancel anytime."]
    return {"type": "RESPONSIVE_SEARCH_AD", "headlines": _uniq(heads)[:15],
            "descriptions": _uniq(desc)[:4], "final_url": landing, "sample_derived": True}


def _meta_targeting(adset, campaign, plan_campaign):
    # type: (Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]) -> Dict[str, Any]
    t = str(adset.get("targeting") or "")
    pa = (plan_campaign or {}).get("ad_set") or {}
    m = re.search(r"(\d{2})\s*-\s*(\d{2})(\+)?", t)
    if m and "days" not in t[m.end():m.end() + 6]:
        age_min, age_max = int(m.group(1)), int(m.group(2))
        if m.group(3):
            age_max = 65
    else:
        age_min, age_max = int(pa.get("age_min", 18)), int(pa.get("age_max", 65))
    m65 = re.search(r"(\d{2})\s*-\s*65\+", t)
    if m65:
        age_min, age_max = int(m65.group(1)), 65
    custom = list(pa.get("custom_audiences") or [])
    if not custom and campaign.get("type") == "Retargeting":
        custom = [re.sub(r"^(Legacy_)?RT_", "", adset["name"]) + "_Visitors"]
    return {"geo_locations": {"countries": [COUNTRY.get(campaign.get("country"), campaign.get("country") or "US")]},
            "age_min": age_min, "age_max": age_max, "custom_audiences": custom,
            "excluded_custom_audiences": list(pa.get("excluded_audiences") or []),
            "advantage_plus": "advantage+" in t.lower(), "description": t, "sample_derived": True}


def _meta_ad_copy(ad, plan_ads):
    # type: (Dict[str, Any], Dict[str, Any]) -> Dict[str, Any]
    best = None
    for key in plan_ads:
        if ad["name"].startswith(key) and (best is None or len(key) > len(best)):
            best = key
    cta = CTA_MAP.get(str(ad.get("cta") or "").lower(), "SIGN_UP")
    if best:
        p = plan_ads[best]
        return {"title": p.get("title"), "body": p.get("body"), "cta": p.get("cta") or cta,
                "plan_ad": best, "media_id": None, "creative_id": None, "sample_derived": True}
    return {"title": _trim(ad.get("hook"), 40), "body": "%s. 7-day trial." % str(ad.get("hook") or "").rstrip("."),
            "cta": cta, "plan_ad": None, "media_id": None, "creative_id": None, "sample_derived": True}


def meta_id(kind, n):
    # type: (str, int) -> str
    return "%s%04d" % (META_PREFIX[kind], n)


# --------------------------------------------------------------- overlay io

def _skeleton():
    # type: () -> Dict[str, Any]
    from planning.adapters import load_config
    cfg = load_config()
    return {
        "version": 1,
        "sample_derived": True,
        "note": "Generated from store state + data/plan/plan.yaml. Store owns statuses, budgets, negatives, ads.",
        "google": {"customer_id": str(cfg["google_ads"].get("customer_id")), "next": dict(GOOGLE_START),
                   "campaigns": {}, "ad_groups": {}, "ads": {}, "negatives": [], "assets": []},
        "meta": {"ad_account_id": str(cfg["meta"].get("ad_account_id")), "page_id": str(cfg["meta"].get("page_id")),
                 "next": dict(META_START), "campaigns": {}, "ad_sets": {}, "ads": {},
                 "images": [], "videos": [], "creatives": []},
    }


def sync_overlay(ov, state):
    # type: (Dict[str, Any], Dict[str, Any]) -> bool
    """Give every store entity an overlay entry (deterministic, in store order). Returns True if changed."""
    before = json.dumps(ov, sort_keys=True)
    plan = _plan()
    landing = str((plan.get("account") or {}).get("landing_url") or "https://www.example.com/trial")
    plan_groups = {}  # type: Dict[str, Any]
    plan_asset_copy = {}  # type: Dict[str, Any]
    for pc in plan.get("google_campaigns") or []:
        for ag in pc.get("ad_groups") or []:
            plan_groups[ag["name"]] = ag
        if pc.get("asset_groups"):
            plan_asset_copy[pc["name"]] = pc["asset_groups"][0]
    plan_meta = dict((pc["name"], pc) for pc in plan.get("meta_campaigns") or [])
    plan_ads = plan.get("meta_ads") or {}
    g, m = ov["google"], ov["meta"]
    gn, mn = g["next"], m["next"]
    camps = dict((c["id"], c) for c in state["campaigns"])

    for c in state["campaigns"]:
        if c["platform"] == "google" and c["id"] not in g["campaigns"]:
            n, b = gn["campaign"], gn["budget"]
            gn["campaign"] += 1
            gn["budget"] += 1
            g["campaigns"][c["id"]] = {
                "num": n, "budget_num": b, "budget_name": "%s_Budget" % c["name"], "shared": False,
                "channel": "PERFORMANCE_MAX" if c.get("type") == "PMax" else "SEARCH",
                "bidding": _google_bidding(c), "geo": [COUNTRY.get(c.get("country"), c.get("country") or "US")],
                "languages": ["en"], "sample_derived": True}
        if c["platform"] == "meta" and c["id"] not in m["campaigns"]:
            n = mn["campaign"]
            mn["campaign"] += 1
            bs = str(c.get("bid_strategy") or "").lower()
            m["campaigns"][c["id"]] = {
                "meta_id": meta_id("campaign", n), "objective": "OUTCOME_LEADS", "buying_type": "AUCTION",
                "bid_strategy": "COST_CAP" if "cost cap" in bs else "LOWEST_COST_WITHOUT_CAP",
                "cbo": False, "special_ad_categories": [], "sample_derived": True}

    for a in state["adsets"]:
        c = camps.get(a["campaign_id"])
        if c is None:
            continue
        if c["platform"] == "google" and a["id"] not in g["ad_groups"]:
            if a.get("kind") == "asset group":
                n = gn["asset_group"]
                gn["asset_group"] += 1
                pa = plan_asset_copy.get(c["name"])
                if pa:
                    cp = {"headlines": list(pa.get("headlines") or []), "long_headline": pa.get("long_headline"),
                          "descriptions": list(pa.get("descriptions") or []), "business_name": pa.get("business_name")}
                else:
                    cp = {"headlines": ["All-In-One SEO Platform", "Start A 7-Day Trial"], "long_headline": a["name"],
                          "descriptions": ["Rank tracking, audits, content and backlinks in one login."],
                          "business_name": "Search Atlas"}
                cp["audience_signal"] = a.get("targeting")
                g["ad_groups"][a["id"]] = {"num": n, "kind": "asset_group", "copy": cp, "final_url": landing,
                                           "sample_derived": True}
            else:
                n = gn["ad_group"]
                gn["ad_group"] += 1
                g["ad_groups"][a["id"]] = {"num": n, "kind": "ad_group", "cpc_bid": None,
                                           "keywords": _keywords_for(a, plan_groups, gn), "sample_derived": True}
        if c["platform"] == "meta" and a["id"] not in m["ad_sets"]:
            n = mn["ad_set"]
            mn["ad_set"] += 1
            bs = str(c.get("bid_strategy") or "")
            cap = re.search(r"cost cap \$\s*([\d,.]+)", bs, re.I)
            freq = None
            if c.get("type") == "Retargeting":
                freq = {"event": "IMPRESSIONS", "interval_days": 7, "max_frequency": 3, "sample_derived": True}
            m["ad_sets"][a["id"]] = {
                "meta_id": meta_id("ad_set", n), "optimization_goal": "OFFSITE_CONVERSIONS",
                "billing_event": "IMPRESSIONS", "promoted_object": {"custom_event_type": "START_TRIAL"},
                "bid_amount": float(cap.group(1).replace(",", "")) if cap else None,
                "targeting": _meta_targeting(a, c, plan_meta.get(c["name"])),
                "frequency_cap": freq, "sample_derived": True}

    adsets = dict((a["id"], a) for a in state["adsets"])
    for ad in state["ads"]:
        a = adsets.get(ad["adset_id"])
        c = camps.get(a["campaign_id"]) if a else None
        if c is None:
            continue
        if c["platform"] == "google" and ad["id"] not in g["ads"]:
            n = gn["ad"]
            gn["ad"] += 1
            if a.get("kind") == "asset group":
                g["ads"][ad["id"]] = {"num": n, "type": "ASSET", "asset_type":
                                      "YOUTUBE_VIDEO" if ad.get("format") == "video" else "IMAGE",
                                      "sample_derived": True}
            else:
                entry = _rsa_copy(ad, c, landing)
                entry["num"] = n
                g["ads"][ad["id"]] = entry
        if c["platform"] == "meta" and ad["id"] not in m["ads"]:
            n = mn["ad"]
            mn["ad"] += 1
            entry = _meta_ad_copy(ad, plan_ads)
            entry["meta_id"] = meta_id("ad", n)
            m["ads"][ad["id"]] = entry

    # negatives: every store negative maps to one campaign criterion
    keys = set()
    for neg in state.get("negatives", []):
        key = (neg["campaign_id"], neg["text"], neg["match"])
        keys.add(key)
        if not any((x["campaign_id"], x["text"], x["match"]) == key for x in g["negatives"]):
            g["negatives"].append({"num": gn["criterion"], "campaign_id": neg["campaign_id"],
                                   "text": neg["text"], "match": neg["match"]})
            gn["criterion"] += 1
    g["negatives"] = [x for x in g["negatives"] if (x["campaign_id"], x["text"], x["match"]) in keys]
    return json.dumps(ov, sort_keys=True) != before


def load_overlay(sync=True):
    # type: (bool) -> Dict[str, Any]
    """The overlay, generated on first use and synced with the store (saved if anything changed)."""
    with _lock:
        path = overlay_path()
        ov = None
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                ov = json.load(fh)
        created = ov is None
        if created:
            ov = _skeleton()
        changed = sync_overlay(ov, store.get_state()) if sync else False
        if created or changed:
            save_overlay(ov)
        return ov


def save_overlay(ov):
    # type: (Dict[str, Any]) -> None
    with _lock:
        planning.ensure_dir(os.path.dirname(overlay_path()))
        store.write_json_atomic(overlay_path(), ov)


def update_overlay(fn):
    """Run fn(overlay) under the lock and save. Returns fn's result."""
    with _lock:
        ov = load_overlay()
        res = fn(ov)
        save_overlay(ov)
        return res


# --------------------------------------------------------- resource helpers

def google_rn(ov, collection, *ids):
    # type: (Dict[str, Any], str, *Any) -> str
    return "customers/%s/%s/%s" % (ov["google"]["customer_id"], collection, "~".join(str(i) for i in ids))


def parse_rn(rn):
    # type: (Any) -> Tuple[Optional[str], List[str]]
    m = re.match(r"^customers/(\d+)/([A-Za-z]+)/([\w~\-]+)$", str(rn or "").strip())
    if not m:
        return None, []
    return m.group(2), m.group(3).split("~")


def _find_num(mapping, num, key="num"):
    for k, v in mapping.items():
        if str(v.get(key)) == str(num):
            return k
    return None


def _status_store(s):
    # type: (Any) -> str
    s = str(s or "").upper()
    if s == "ENABLED":
        return "ACTIVE"
    if s in ("ACTIVE", "PAUSED"):
        return s
    raise AdapterError("unsupported status %r" % s)


def _bid_label(bidding):
    # type: (Dict[str, Any]) -> str
    st = bidding.get("strategy")
    t = bidding.get("target_cpa")
    if st == "TARGET_CPA":
        return "Target CPA $%s" % store._n(t)
    if st == "MAXIMIZE_CONVERSIONS":
        return "Maximize conversions" + (" (target CPA $%s)" % store._n(t) if t else "")
    if st == "TARGET_IMPRESSION_SHARE":
        return "Target impression share %s%%" % store._n(bidding.get("target_impression_share"))
    return st or ""


def _next_ad_id(state, adset_id):
    # type: (Dict[str, Any], str) -> str
    nums = [int(m.group(1)) for a in state["ads"] if a["adset_id"] == adset_id
            for m in [re.search(r"_ad(\d+)$", a["id"])] if m]
    return "%s_ad%d" % (adset_id, (max(nums) if nums else 0) + 1)


def _add_store_ad(ad):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    def _apply(state):
        ad["id"] = _next_ad_id(state, ad["adset_id"])
        state["ads"].append(ad)
        return ad
    return store.mutate(_apply)


def image_hash(media_id):
    # type: (str) -> str
    return hashlib.md5(("atlas-sample:%s" % media_id).encode("utf-8")).hexdigest()


# ----------------------------------------------------------------- adapter

class SampleAdapter(Adapter):
    """Executes against store + overlay. Request previews are the real REST requests."""

    mode = "sample"

    def __init__(self, platform, cfg):
        Adapter.__init__(self, cfg)
        self.platform = platform

    def build_request(self, op, ctx):
        if self.platform == "google":
            from planning.adapters.live_google import build_google_request
            return build_google_request(op, ctx, self.cfg)
        from planning.adapters.live_meta import build_meta_request
        return build_meta_request(op, ctx, self.cfg)

    def execute(self, op, ctx):
        op = resolve_refs(op, (ctx or {}).get("outputs") or {}, strict=True)
        if self.platform == "google":
            return self._google(op)
        return self._meta(op)

    def execute_request(self, req, ctx):
        """Apply a rendered HTTP request (planning.api_requests) to the sample account.

        The request is the source of truth: it is parsed back into the operation it
        carries, so what runs is exactly what the reviewer saw."""
        from planning import api_requests
        req = api_requests.resolve(req, (ctx or {}).get("outputs") or {})
        op = api_requests.to_op(req)
        if op.get("platform") != self.platform:
            raise AdapterError("request is for %s, adapter is %s" % (op.get("platform"), self.platform))
        if self.platform == "google":
            return self._google(op)
        return self._meta(op)

    # ---------------------------------------------------------------- google
    def _google(self, op):
        ov = load_overlay()
        g = ov["google"]
        service, kind = op.get("service"), op.get("operation")
        from planning.adapters.live_google import normalize_fields
        fields = normalize_fields(op)
        rn = op.get("resource_name")
        coll, ids = parse_rn(rn)

        if service == "CampaignService" and kind == "update":
            cid = _find_num(g["campaigns"], ids[0] if ids else None)
            if coll != "campaigns" or not cid:
                raise AdapterError("unknown campaign %s" % rn)
            if "status" in fields:
                store.set_campaign_status(cid, _status_store(fields["status"]))
            for key in ("target_cpa", "maximize_conversions"):
                micros = (fields.get(key) or {}).get("target_cpa_micros")
                if micros is not None:
                    def _bid(o, cid=cid, micros=micros):
                        o["google"]["campaigns"][cid]["bidding"]["target_cpa"] = round(int(micros) / 1e6, 2)
                        return o["google"]["campaigns"][cid]["bidding"]
                    bidding = update_overlay(_bid)
                    label = _bid_label(bidding)

                    def _label(state, cid=cid, label=label):
                        for c in state["campaigns"]:
                            if c["id"] == cid:
                                old = c["bid_strategy"]
                                c["bid_strategy"] = label
                                return c, old
                    c, old = store.mutate(_label)
                    store.log_activity("campaign.bidding", cid, "%s: %s -> %s" % (c["name"], old, label))
            return {"results": [{"resourceName": rn}]}

        if service == "CampaignBudgetService" and kind == "update":
            cid = _find_num(g["campaigns"], ids[0] if ids else None, "budget_num")
            if coll != "campaignBudgets" or not cid:
                raise AdapterError("unknown campaign budget %s" % rn)
            store.set_campaign_budget(cid, daily_budget=int(fields["amount_micros"]) / 1e6)
            return {"results": [{"resourceName": rn}]}

        if service == "AdGroupService" and kind == "update":
            aid = _find_num(g["ad_groups"], ids[0] if ids else None)
            if coll != "adGroups" or not aid:
                raise AdapterError("unknown ad group %s" % rn)
            if "status" in fields:
                store.set_adset_status(aid, _status_store(fields["status"]))
            if "cpc_bid_micros" in fields:
                bid = round(int(fields["cpc_bid_micros"]) / 1e6, 2)

                def _cpc(o):
                    o["google"]["ad_groups"][aid]["cpc_bid"] = bid
                update_overlay(_cpc)
                store.log_activity("adgroup.cpc_bid", aid, "%s: max CPC $%.2f" % (store.adset(aid)["name"], bid))
            return {"results": [{"resourceName": rn}]}

        if service == "AssetGroupService" and kind == "update":
            aid = _find_num(dict((k, v) for k, v in g["ad_groups"].items() if v.get("kind") == "asset_group"),
                            ids[0] if ids else None)
            if coll != "assetGroups" or not aid:
                raise AdapterError("unknown asset group %s" % rn)
            store.set_adset_status(aid, _status_store(fields.get("status")))
            return {"results": [{"resourceName": rn}]}

        if service == "AssetGroupAssetService" and kind == "update":
            if coll != "assetGroupAssets" or len(ids) < 2:
                raise AdapterError("unknown asset group asset %s" % rn)
            ad_id = _find_num(dict((k, v) for k, v in g["ads"].items() if v.get("type") == "ASSET"), ids[1])
            if not ad_id:
                raise AdapterError("unknown asset group asset %s" % rn)
            store.set_ad_status(ad_id, _status_store(fields.get("status")))
            return {"results": [{"resourceName": rn}]}

        if service == "AdGroupAdService" and kind == "update":
            if coll != "adGroupAds" or len(ids) != 2:
                raise AdapterError("unknown ad %s" % rn)
            ad_id = _find_num(g["ads"], ids[1])
            if not ad_id:
                raise AdapterError("unknown ad %s" % rn)
            store.set_ad_status(ad_id, _status_store(fields.get("status")))
            return {"results": [{"resourceName": rn}]}

        if service == "AdGroupAdService" and kind == "create":
            _c, agids = parse_rn(fields.get("ad_group"))
            aid = _find_num(g["ad_groups"], agids[0] if agids else None)
            if not aid:
                raise AdapterError("unknown ad group %s" % fields.get("ad_group"))
            ad = fields.get("ad") or {}
            rsa = ad.get("responsive_search_ad") or {}
            heads = [h["text"] for h in rsa.get("headlines") or []]
            descs = [d["text"] for d in rsa.get("descriptions") or []]
            status = _status_store(fields.get("status") or "PAUSED")
            new = _add_store_ad({"adset_id": aid, "name": "RSA_" + re.sub(r"\W+", "_", heads[0]).strip("_")[:40],
                                 "status": status, "format": "rsa", "hook": " | ".join(heads[:2]),
                                 "cta": "Start trial", "launched": store.today()})

            def _ad(o):
                n = o["google"]["next"]["ad"]
                o["google"]["next"]["ad"] += 1
                o["google"]["ads"][new["id"]] = {"num": n, "type": "RESPONSIVE_SEARCH_AD", "headlines": heads,
                                                 "descriptions": descs,
                                                 "final_url": (ad.get("final_urls") or [None])[0],
                                                 "path1": rsa.get("path1"), "path2": rsa.get("path2")}
                return n
            n = update_overlay(_ad)
            store.log_activity("ad.create", new["id"], "%s in %s (%s)" % (new["name"], store.adset(aid)["name"], status))
            return {"results": [{"resourceName": google_rn(ov, "adGroupAds", agids[0], n)}]}

        if service == "AdGroupCriterionService":
            if kind == "create":
                _c, agids = parse_rn(fields.get("ad_group"))
                aid = _find_num(g["ad_groups"], agids[0] if agids else None)
                if not aid:
                    raise AdapterError("unknown ad group %s" % fields.get("ad_group"))
                kw = fields.get("keyword") or {}
                text = " ".join(str(kw.get("text") or "").lower().split())
                match = str(kw.get("match_type") or "PHRASE").upper()
                status = str(fields.get("status") or "ENABLED").upper()

                def _kw(o):
                    n = o["google"]["next"]["criterion"]
                    o["google"]["next"]["criterion"] += 1
                    o["google"]["ad_groups"][aid]["keywords"].append(
                        {"num": n, "text": text, "match": match, "status": status})
                    return n
                n = update_overlay(_kw)
                store.log_activity("keyword.add", aid, "%s [%s] in %s" % (text, match, store.adset(aid)["name"]))
                return {"results": [{"resourceName": google_rn(ov, "adGroupCriteria", agids[0], n)}]}
            if coll != "adGroupCriteria" or len(ids) != 2:
                raise AdapterError("unknown keyword %s" % rn)
            aid = _find_num(g["ad_groups"], ids[0])
            kws = (g["ad_groups"].get(aid) or {}).get("keywords") or []
            hit = [k for k in kws if str(k["num"]) == ids[1]]
            if not aid or not hit:
                raise AdapterError("unknown keyword %s" % rn)
            if kind == "update":
                status = str(fields.get("status") or "").upper()

                def _ks(o):
                    for k in o["google"]["ad_groups"][aid]["keywords"]:
                        if str(k["num"]) == ids[1]:
                            k["status"] = status
                update_overlay(_ks)
                store.log_activity("keyword.status", aid, "%s [%s]: %s" % (hit[0]["text"], hit[0]["match"], status))
            elif kind == "remove":
                def _kr(o):
                    o["google"]["ad_groups"][aid]["keywords"] = [
                        k for k in o["google"]["ad_groups"][aid]["keywords"] if str(k["num"]) != ids[1]]
                update_overlay(_kr)
                store.log_activity("keyword.remove", aid, "%s [%s]" % (hit[0]["text"], hit[0]["match"]))
            return {"results": [{"resourceName": rn}]}

        if service == "CampaignCriterionService":
            if kind == "create":
                _c, cids = parse_rn(fields.get("campaign"))
                cid = _find_num(g["campaigns"], cids[0] if cids else None)
                if not cid:
                    raise AdapterError("unknown campaign %s" % fields.get("campaign"))
                kw = fields.get("keyword") or {}
                try:
                    neg = store.add_negative(cid, kw.get("text"), str(kw.get("match_type") or "PHRASE").lower())
                except store.BadInput as exc:
                    raise AdapterError(str(exc))
                ov2 = load_overlay()  # sync assigns the criterion id
                hit = [x for x in ov2["google"]["negatives"]
                       if (x["campaign_id"], x["text"], x["match"]) == (cid, neg["text"], neg["match"])]
                return {"results": [{"resourceName": google_rn(ov2, "campaignCriteria", cids[0], hit[0]["num"])}]}
            if kind == "remove":
                if coll != "campaignCriteria" or len(ids) != 2:
                    raise AdapterError("unknown campaign criterion %s" % rn)
                cid = _find_num(g["campaigns"], ids[0])
                hit = [x for x in g["negatives"] if str(x["num"]) == ids[1] and x["campaign_id"] == cid]
                if not hit:
                    raise AdapterError("unknown negative keyword %s" % rn)
                h = hit[0]

                def _nr(state):
                    before = len(state["negatives"])
                    state["negatives"] = [n for n in state["negatives"]
                                          if (n["campaign_id"], n["text"], n["match"]) != (cid, h["text"], h["match"])]
                    return before - len(state["negatives"])
                store.mutate(_nr)
                load_overlay()
                store.log_activity("negative.remove", cid, "%s [%s] on %s" % (h["text"], h["match"], store.campaign(cid)["name"]))
                return {"results": [{"resourceName": rn}]}

        if service == "AssetService" and kind == "create":
            media_id = (fields.get("image_asset") or {}).get("media_id")
            asset = media_asset(media_id)
            if not asset:
                raise AdapterError("unknown media id %s" % media_id)

            def _as(o):
                n = o["google"]["next"]["asset"]
                o["google"]["next"]["asset"] += 1
                o["google"]["assets"].append({"num": n, "name": fields.get("name") or asset.get("title") or media_id,
                                              "type": "IMAGE", "media_id": media_id})
                return n
            n = update_overlay(_as)
            out_rn = google_rn(ov, "assets", n)
            mark_media_published(media_id, "google", {"asset_resource": out_rn})
            store.log_activity("asset.create", media_id, "image asset %s" % out_rn)
            return {"results": [{"resourceName": out_rn}]}

        raise AdapterError("not supported in sample adapter: %s %s" % (service, kind))

    # ------------------------------------------------------------------ meta
    def _meta(self, op):
        from planning.adapters.live_meta import EDGE_RE, NODE_RE, normalize_path
        ov = load_overlay()
        m = ov["meta"]
        path = normalize_path(op.get("path"))
        params = op.get("params") or {}
        node = NODE_RE.match(path)
        if node:
            nid = node.group(1)
            cid = _find_num(m["campaigns"], nid, "meta_id")
            sid = _find_num(m["ad_sets"], nid, "meta_id")
            adid = _find_num(m["ads"], nid, "meta_id")
            if cid:
                if "status" in params:
                    store.set_campaign_status(cid, _status_store(params["status"]))
                if "daily_budget" in params:
                    store.set_campaign_budget(cid, daily_budget=int(params["daily_budget"]) / 100.0)
            elif sid:
                if "status" in params:
                    store.set_adset_status(sid, _status_store(params["status"]))
                if "daily_budget" in params:
                    self._adset_budget(sid, int(params["daily_budget"]) / 100.0)
                extra = dict((k, params[k]) for k in ("bid_amount", "targeting", "frequency_control_specs") if k in params)
                if extra:
                    def _as(o):
                        s = o["meta"]["ad_sets"][sid]
                        if "bid_amount" in extra:
                            s["bid_amount"] = round(int(extra["bid_amount"]) / 100.0, 2)
                        if "targeting" in extra:
                            s["targeting"].update(copy.deepcopy(extra["targeting"]))
                        if "frequency_control_specs" in extra:
                            specs = extra["frequency_control_specs"] or []
                            s["frequency_cap"] = dict(specs[0]) if specs else None
                    update_overlay(_as)
                    store.log_activity("adset.settings", sid, "%s: %s" % (store.adset(sid)["name"], ", ".join(sorted(extra))))
            elif adid:
                store.set_ad_status(adid, _status_store(params.get("status")))
            else:
                raise AdapterError("unknown Graph node %s" % nid)
            return {"success": True, "id": nid}

        edge = EDGE_RE.match(path)
        if not edge or edge.group(1) != m["ad_account_id"]:
            raise AdapterError("unsupported path %s" % path)
        what = edge.group(2)
        if what == "adimages":
            media_id = params.get("media_id")
            asset = media_asset(media_id)
            if not asset:
                raise AdapterError("unknown media id %s" % media_id)
            h = image_hash(media_id)

            def _img(o):
                if not any(i["hash"] == h for i in o["meta"]["images"]):
                    o["meta"]["images"].append({"hash": h, "media_id": media_id,
                                                "name": asset.get("title") or media_id})
            update_overlay(_img)
            mark_media_published(media_id, "meta", {"image_hash": h})
            store.log_activity("media.upload", media_id, "Meta ad image %s" % h)
            return {"images": {str(media_id): {"hash": h, "url": asset.get("file_url")}}}
        if what == "advideos":
            media_id = params.get("media_id")
            asset = media_asset(media_id)
            if not asset:
                raise AdapterError("unknown media id %s" % media_id)

            def _vid(o):
                n = o["meta"]["next"]["video"]
                o["meta"]["next"]["video"] += 1
                vid = meta_id("video", n)
                o["meta"]["videos"].append({"id": vid, "media_id": media_id, "title": asset.get("title") or media_id})
                return vid
            vid = update_overlay(_vid)
            mark_media_published(media_id, "meta", {"video_id": vid})
            store.log_activity("media.upload", media_id, "Meta ad video %s" % vid)
            return {"id": vid}
        if what == "adcreatives":
            spec = params.get("object_story_spec") or {}
            link, video = spec.get("link_data"), spec.get("video_data")
            media_id, fmt = None, "image"
            if link:
                media_id = next((i["media_id"] for i in m["images"] if i["hash"] == link.get("image_hash")), None)
                data = {"title": link.get("name"), "body": link.get("message"), "link": link.get("link"),
                        "cta": (link.get("call_to_action") or {}).get("type"), "image_hash": link.get("image_hash"),
                        "video_id": None}
            elif video:
                fmt = "video"
                media_id = next((v["media_id"] for v in m["videos"] if v["id"] == video.get("video_id")), None)
                cta = video.get("call_to_action") or {}
                data = {"title": video.get("title"), "body": video.get("message"),
                        "link": (cta.get("value") or {}).get("link"), "cta": cta.get("type"),
                        "image_hash": video.get("image_hash"), "video_id": video.get("video_id")}
            else:
                raise AdapterError("object_story_spec needs link_data or video_data")

            def _cr(o):
                n = o["meta"]["next"]["creative"]
                o["meta"]["next"]["creative"] += 1
                cid_ = meta_id("creative", n)
                rec = dict(data)
                rec.update({"id": cid_, "name": params.get("name"), "format": fmt, "media_id": media_id})
                o["meta"]["creatives"].append(rec)
                return cid_
            crid = update_overlay(_cr)
            store.log_activity("creative.create", crid, "%s (%s)" % (params.get("name"), media_id or fmt))
            return {"id": crid}
        if what == "ads":
            sid = _find_num(m["ad_sets"], params.get("adset_id"), "meta_id")
            if not sid:
                raise AdapterError("unknown ad set %s" % params.get("adset_id"))
            crid = str((params.get("creative") or {}).get("creative_id") or "")
            cr = next((x for x in m["creatives"] if x["id"] == crid), None)
            if cr is None:
                raise AdapterError("unknown creative %s" % crid)
            status = _status_store(params.get("status") or "PAUSED")
            cta_label = {"SIGN_UP": "Sign up", "LEARN_MORE": "Learn more"}.get(cr.get("cta"), cr.get("cta") or "")
            new = _add_store_ad({"adset_id": sid, "name": params.get("name"), "status": status,
                                 "format": cr.get("format") or "image", "hook": cr.get("title") or "",
                                 "cta": cta_label, "launched": store.today()})

            def _ad(o):
                n = o["meta"]["next"]["ad"]
                o["meta"]["next"]["ad"] += 1
                mid = meta_id("ad", n)
                o["meta"]["ads"][new["id"]] = {"meta_id": mid, "title": cr.get("title"), "body": cr.get("body"),
                                               "cta": cr.get("cta"), "media_id": cr.get("media_id"),
                                               "creative_id": crid}
                return mid
            mid = update_overlay(_ad)
            store.log_activity("ad.create", new["id"], "%s in %s (%s)" % (new["name"], store.adset(sid)["name"], status))
            return {"id": mid}
        raise AdapterError("unsupported path %s" % path)

    def _adset_budget(self, sid, daily):
        # type: (str, float) -> None
        if daily <= 0:
            raise AdapterError("budget must be greater than 0")
        a = store.adset(sid)
        cid = a["campaign_id"]

        def _apply(state):
            for x in state["adsets"]:
                if x["id"] == sid:
                    old = x["daily_budget"]
                    x["daily_budget"] = round(daily, 2)
                    return old
        old = store.mutate(_apply)
        store.log_activity("adset.budget", sid, "%s: $%s/day -> $%s/day" % (a["name"], store._n(old), store._n(daily)))
        # Move the campaign's daily and monthly totals by the same delta (not a re-sum), so a
        # change and its undo restore the campaign's figures exactly.
        delta = round(daily - float(old or 0), 2)
        import calendar
        t = store.parse_date(store.today())
        dim = calendar.monthrange(t.year, t.month)[1]

        def _camp(state):
            for c in state["campaigns"]:
                if c["id"] == cid:
                    before = c["daily_budget"]
                    c["daily_budget"] = round(float(c["daily_budget"]) + delta, 2)
                    c["monthly_budget"] = round(float(c["monthly_budget"]) + delta * dim, 2)
                    if float(c["monthly_budget"]).is_integer():
                        c["monthly_budget"] = int(c["monthly_budget"])
                    return c, before
        c, before = store.mutate(_camp)
        store.log_activity("campaign.budget", cid, "%s: $%s/day -> $%s/day ($%s/mo)" % (
            c["name"], store._n(before), store._n(c["daily_budget"]), store._n(c["monthly_budget"])))
