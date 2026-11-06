"""Changesets: parse, validate and dry-run API-shaped operations against a snapshot.

A changeset is JSON: ``{"changeset": {title, based_on_snapshot, rationale}, "operations": [op]}``.
Each op names one Google Ads REST mutate or one Meta Graph API call; planning.api_requests
renders it as the exact HTTP request, which is what the reviewer sees and publish runs.

    SCHEMA_DOC: str                                     # the format, for the prompt
    parse(text_or_doc) -> (doc | None, [error str])     # JSON (legacy YAML still read)
    to_json(doc) -> str                                 # canonical pretty JSON
    validate(doc, snapshot) -> [{"op": ref | None, "level": "error" | "warn", "message"}]
    dry_run(doc, snapshot) -> {"after", "rows", "text_diff", "summary"}
    find_entity(doc, entity_id) -> (entity_type, entity, parents) | None
    read_field(entity, field) -> value

Deterministic. Never imports planning.llm, planning.llm_worker, planning.prompts or anthropic.
"""

import copy
import difflib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

import yaml

from planning.adapters.base import REF_RE, flatten_paths, media_asset, resolve_refs
from planning.adapters.live_google import normalize_fields
from planning.adapters.live_meta import EDGE_RE, NODE_RE, normalize_path
from planning import snapshot as snapshot_mod

_SCHEMA_EXAMPLE = {
    "changeset": {"title": "Shift $1,000/day from Brand to NonBrand agency",
                  "based_on_snapshot": "SNAP-20261105-142233",
                  "rationale": ["short bullet", "short bullet"]},
    "operations": [
        {"ref": "op1", "platform": "google", "service": "CampaignBudgetService", "method": "mutateCampaignBudgets",
         "operation": "update", "resource_name": "customers/4445556666/campaignBudgets/201",
         "fields": {"amount_micros": 150000000}, "update_mask": ["amount_micros"], "reason": "plan: brand at $3K/month"},
        {"ref": "op2", "platform": "google", "service": "CampaignService", "method": "mutateCampaigns",
         "operation": "update", "resource_name": "customers/4445556666/campaigns/104",
         "fields": {"status": "PAUSED"}, "update_mask": ["status"], "reason": "..."},
        {"ref": "op3", "platform": "google", "service": "CampaignService", "method": "mutateCampaigns",
         "operation": "update", "resource_name": "customers/4445556666/campaigns/103",
         "fields": {"target_cpa": {"target_cpa_micros": 330000000}}, "update_mask": ["target_cpa.target_cpa_micros"],
         "reason": "..."},
        {"ref": "op4", "platform": "google", "service": "AdGroupService", "method": "mutateAdGroups",
         "operation": "update", "resource_name": "customers/4445556666/adGroups/3003",
         "fields": {"status": "PAUSED", "cpc_bid_micros": 4500000}, "update_mask": ["status", "cpc_bid_micros"],
         "reason": "..."},
        {"ref": "op5", "platform": "google", "service": "AdGroupAdService", "method": "mutateAdGroupAds",
         "operation": "update", "resource_name": "customers/4445556666/adGroupAds/3003~50005",
         "fields": {"status": "PAUSED"}, "update_mask": ["status"], "reason": "..."},
        {"ref": "op6", "platform": "google", "service": "AdGroupAdService", "method": "mutateAdGroupAds",
         "operation": "create", "fields": {
             "ad_group": "customers/4445556666/adGroups/3003", "status": "PAUSED",
             "ad": {"final_urls": ["https://www.agentstack.example/trial"],
                    "responsive_search_ad": {"headlines": ["Headline one", "Headline two", "Headline three"],
                                             "descriptions": ["Description one.", "Description two."]}}},
         "reason": "..."},
        {"ref": "op7", "platform": "google", "service": "AdGroupCriterionService", "method": "mutateAdGroupCriteria",
         "operation": "create", "fields": {"ad_group": "customers/4445556666/adGroups/3003", "status": "ENABLED",
                                           "keyword": {"text": "white label seo", "match_type": "PHRASE"}},
         "reason": "..."},
        {"ref": "op8", "platform": "google", "service": "AdGroupCriterionService", "method": "mutateAdGroupCriteria",
         "operation": "remove", "resource_name": "customers/4445556666/adGroupCriteria/3003~70012", "reason": "..."},
        {"ref": "op9", "platform": "google", "service": "CampaignCriterionService", "method": "mutateCampaignCriteria",
         "operation": "create", "fields": {"campaign": "customers/4445556666/campaigns/102", "negative": True,
                                           "keyword": {"text": "free", "match_type": "PHRASE"}}, "reason": "..."},
        {"ref": "op10", "platform": "google", "service": "AssetService", "method": "mutateAssets",
         "operation": "create", "fields": {"name": "Benefits grid 1:1", "image_asset": {"media_id": "IMG-0001"}},
         "reason": "..."},
        {"ref": "op11", "platform": "google", "service": "AssetGroupAssetService", "method": "mutateAssetGroupAssets",
         "operation": "update", "resource_name": "customers/4445556666/assetGroupAssets/6001~50021~MARKETING_IMAGE",
         "fields": {"status": "PAUSED"}, "update_mask": ["status"], "reason": "..."},
        {"ref": "op12", "platform": "meta", "method": "POST", "path": "/120210000000000101",
         "params": {"daily_budget": 45000}, "reason": "..."},
        {"ref": "op13", "platform": "meta", "method": "POST", "path": "/120210000000000001",
         "params": {"status": "PAUSED"}, "reason": "..."},
        {"ref": "op14", "platform": "meta", "method": "POST", "path": "/act_7778889999/adimages",
         "params": {"media_id": "IMG-0002"}, "reason": "..."},
        {"ref": "op15", "platform": "meta", "method": "POST", "path": "/act_7778889999/adcreatives",
         "params": {"name": "Benefits grid v2", "object_story_spec": {
             "page_id": "123456789012345",
             "link_data": {"image_hash": "$ref:op14.hash", "link": "https://www.agentstack.example/trial",
                           "message": "Primary text", "name": "Headline", "call_to_action": {"type": "SIGN_UP"}}}},
         "reason": "..."},
        {"ref": "op16", "platform": "meta", "method": "POST", "path": "/act_7778889999/ads",
         "params": {"name": "Static_Benefits_v2", "adset_id": "120210000000000101",
                    "creative": {"creative_id": "$ref:op15.id"}, "status": "PAUSED"}, "reason": "..."},
    ],
}

SCHEMA_DOC = """\
A changeset is ONE JSON object with two keys, "changeset" and "operations". Every operation is
one real API call; code renders each as the exact HTTP request (Google Ads REST
POST https://googleads.googleapis.com/<version>/customers/<id>/<resource>:mutate, or Meta Graph API
POST https://graph.facebook.com/<version>/<path>) and that is what a human reviews and publishes.
Operations run in order; each has a unique "ref", a "platform" and a short "reason".

Example with one of every allowed operation:
""" + json.dumps(_SCHEMA_EXAMPLE, indent=1) + """

What each operation may do:
- op1 CampaignBudgetService update amount_micros: Google money is micros (dollars x 1,000,000, a multiple of 10,000).
  Every Google update lists update_mask, matching the fields exactly (dotted for nested fields).
- op2 CampaignService update status: ENABLED | PAUSED.
- op3 CampaignService update bidding target: target_cpa.target_cpa_micros (TARGET_CPA campaigns) or
  maximize_conversions.target_cpa_micros (MAXIMIZE_CONVERSIONS campaigns).
- op4 AdGroupService update status and/or cpc_bid_micros (max CPC).
- op5 AdGroupAdService update status. op6 AdGroupAdService create a responsive search ad:
  3-15 headlines <= 30 chars, 2-4 descriptions <= 90 chars, final_urls.
- op7/op8 AdGroupCriterionService keyword create (EXACT | PHRASE | BROAD), update status, or remove (resource_name only).
- op9 CampaignCriterionService campaign negative keyword create (negative: true) or remove.
- op10 AssetService create image_asset from an approved Media library media_id (PMax / Display).
- op11 AssetGroupAssetService update status (a PMax asset); AssetGroupService mutateAssetGroups update status (an asset group).
- Meta (Graph API, POST only). Budgets and bid_amount are CENTS (integers).
  op12 ad set: status, daily_budget, bid_amount (cost cap / bid cap campaigns),
  targeting {age_min, age_max, geo_locations}, frequency_control_specs.
  op13 campaign: status, daily_budget (CBO campaigns only); ad: status.
  op14 upload an approved image (/advideos for a video) from the Media library.
  op15 creative: link_data for images, video_data {video_id, image_hash, title, message,
  call_to_action {type, value: {link}}} for videos. op16 ad: new ads MUST start PAUSED.

Rules:
- Only the operations above exist. Use only resource names and Meta ids present in the state document.
- "$ref:<ref>.<field>" points to an EARLIER op: adimages -> .hash, advideos/adcreatives/ads -> .id,
  Google creates -> .resource_name.
- media_id must be an APPROVED (or active) Media library id (images for adimages/AssetService, videos for advideos).
- Guardrails: one entity's budget may move at most +/-50% in one changeset (warning above +/-20%);
  no daily budget below $10; total daily budget across both platforms rising more than 10% is flagged;
  a bid or target moving more than +/-20% is flagged.
"""

GOOGLE_SERVICES = {
    "CampaignService": {"method": "mutateCampaigns", "collection": "campaigns", "etype": "campaign",
                        "ops": {"update": {"status", "target_cpa.target_cpa_micros",
                                           "maximize_conversions.target_cpa_micros"}}},
    "CampaignBudgetService": {"method": "mutateCampaignBudgets", "collection": "campaignBudgets", "etype": "budget",
                              "ops": {"update": {"amount_micros"}}},
    "AdGroupService": {"method": "mutateAdGroups", "collection": "adGroups", "etype": "ad_group",
                       "ops": {"update": {"status", "cpc_bid_micros"}}},
    "AdGroupAdService": {"method": "mutateAdGroupAds", "collection": "adGroupAds", "etype": "ad",
                         "ops": {"update": {"status"}, "create": None}},
    "AdGroupCriterionService": {"method": "mutateAdGroupCriteria", "collection": "adGroupCriteria", "etype": "keyword",
                                "ops": {"update": {"status"}, "create": None, "remove": None}},
    "CampaignCriterionService": {"method": "mutateCampaignCriteria", "collection": "campaignCriteria",
                                 "etype": "negative_keyword", "ops": {"create": None, "remove": None}},
    "AssetService": {"method": "mutateAssets", "collection": "assets", "etype": "asset", "ops": {"create": None}},
    "AssetGroupService": {"method": "mutateAssetGroups", "collection": "assetGroups", "etype": "asset_group",
                          "ops": {"update": {"status"}}},
    "AssetGroupAssetService": {"method": "mutateAssetGroupAssets", "collection": "assetGroupAssets",
                               "etype": "asset_group_asset", "ops": {"update": {"status"}}},
}
META_NODE_PARAMS = {
    "campaign": {"status", "daily_budget"},
    "ad_set": {"status", "daily_budget", "bid_amount", "targeting", "frequency_control_specs"},
    "ad": {"status"},
}
GOOGLE_OP_KEYS = {"ref", "platform", "service", "method", "operation", "resource_name", "fields", "update_mask", "reason"}
META_OP_KEYS = {"ref", "platform", "method", "path", "params", "reason"}
MATCH_TYPES = ("EXACT", "PHRASE", "BROAD")
META_CTAS = ("SIGN_UP", "LEARN_MORE", "SUBSCRIBE", "GET_OFFER", "GET_STARTED", "DOWNLOAD", "APPLY_NOW",
             "CONTACT_US", "BOOK_NOW", "TRY_IT", "ORDER_NOW", "SHOP_NOW", "WATCH_MORE")
MONEY_FIELDS = ("daily", "daily_budget", "bid_amount", "bidding.target_cpa", "cpc_bid")
BUDGET_MIN = 10.0
BUDGET_MAX_STEP = 0.50
BUDGET_WARN_STEP = 0.20
BID_WARN_STEP = 0.20
TOTAL_WARN_RISE = 0.10
MAX_OPS = 100


class _OpError(Exception):
    pass


# ----------------------------------------------------------------------- parse

def _strip_fences(text):
    # type: (str) -> str
    t = str(text or "").strip()
    m = re.search(r"```(?:json|ya?ml)?\s*\n(.*?)```", t, re.S)
    return m.group(1) if m else t


def _load_text(text):
    # type: (str) -> Tuple[Any, Optional[str]]
    """JSON first (the format); fall back to YAML so versions stored before the switch still load."""
    t = _strip_fences(text)
    try:
        return json.loads(t), None
    except ValueError as exc:
        json_err = "JSON does not parse: %s" % exc
    if t.lstrip().startswith(("{", "[")):
        return None, json_err
    try:
        return yaml.safe_load(t), None
    except yaml.YAMLError:
        return None, json_err


def to_json(doc):
    # type: (Dict[str, Any]) -> str
    """Canonical pretty JSON for a changeset (what is stored and shown)."""
    return json.dumps({"changeset": (doc or {}).get("changeset"), "operations": (doc or {}).get("operations")},
                      indent=2, ensure_ascii=False)


def parse(text):
    # type: (Any) -> Tuple[Optional[Dict[str, Any]], List[str]]
    """Parse a changeset (JSON text, an already-parsed dict, or legacy YAML text).
    Returns (doc, errors); doc is None when it is not a usable object."""
    if isinstance(text, dict):
        doc = copy.deepcopy(text)
    else:
        doc, err = _load_text(text)
        if err:
            return None, [err]
    if not isinstance(doc, dict):
        return None, ["changeset must be a JSON object with `changeset` and `operations`"]
    errors = []  # type: List[str]
    head = doc.get("changeset")
    if not isinstance(head, dict):
        errors.append("missing `changeset` object (title, based_on_snapshot, rationale)")
    else:
        if not str(head.get("title") or "").strip():
            errors.append("changeset.title is required")
        if not head.get("based_on_snapshot"):
            errors.append("changeset.based_on_snapshot is required")
        r = head.get("rationale")
        if r is not None and not isinstance(r, list):
            errors.append("changeset.rationale must be a list of short bullets")
    ops = doc.get("operations")
    if not isinstance(ops, list) or not ops:
        errors.append("`operations` must be a non-empty list")
        ops = []
    if len(ops) > MAX_OPS:
        errors.append("too many operations (%d > %d)" % (len(ops), MAX_OPS))
    seen = set()
    for i, op in enumerate(ops):
        label = "operations[%d]" % i
        if not isinstance(op, dict):
            errors.append("%s is not an object" % label)
            continue
        ref = op.get("ref")
        if not ref or not re.match(r"^[A-Za-z0-9_\-]+$", str(ref)):
            errors.append("%s needs a `ref` (letters, digits, _ or -)" % label)
        elif str(ref) in seen:
            errors.append("duplicate ref %s" % ref)
        else:
            seen.add(str(ref))
            op["ref"] = str(ref)
        if op.get("platform") not in ("google", "meta"):
            errors.append("%s (%s): platform must be google or meta" % (label, ref))
    return doc, errors


# ---------------------------------------------------------------------- index

def _index(doc):
    # type: (Dict[str, Any]) -> Dict[str, Tuple[str, Dict[str, Any], Dict[str, Any]]]
    idx = {}  # type: Dict[str, Tuple[str, Dict[str, Any], Dict[str, Any]]]

    def put(keys, etype, obj, parents):
        for k in keys:
            if k:
                idx[str(k)] = (etype, obj, parents)

    for c in (doc.get("google") or {}).get("campaigns", []):
        par = {"platform": "google", "campaign": c}
        put([c.get("id"), c.get("resource_name")], "campaign", c, {"platform": "google"})
        b = c.get("budget") or {}
        put([b.get("resource_name")], "budget", b, par)
        for n in c.get("negatives") or []:
            put([n.get("resource_name")], "negative_keyword", n, par)
        for ag in c.get("ad_groups") or []:
            p2 = {"platform": "google", "campaign": c, "ad_group": ag}
            put([ag.get("id"), ag.get("resource_name")], "ad_group", ag, par)
            for k in ag.get("keywords") or []:
                put([k.get("resource_name")], "keyword", k, p2)
            for a in ag.get("ads") or []:
                put([a.get("id"), a.get("resource_name")], "ad", a, p2)
        for ag in c.get("asset_groups") or []:
            put([ag.get("id"), ag.get("resource_name")], "asset_group", ag, par)
            p3 = {"platform": "google", "campaign": c, "asset_group": ag}
            for a in ag.get("assets") or []:
                put([a.get("id"), a.get("resource_name")], "asset_group_asset", a, p3)
    for a in (doc.get("google") or {}).get("assets", []):
        put([a.get("resource_name")], "asset", a, {"platform": "google"})
    meta = doc.get("meta") or {}
    for c in meta.get("campaigns", []):
        par = {"platform": "meta", "campaign": c}
        put([c.get("id"), c.get("meta_id")], "campaign", c, {"platform": "meta"})
        for s in c.get("ad_sets") or []:
            p2 = {"platform": "meta", "campaign": c, "ad_set": s}
            put([s.get("id"), s.get("meta_id")], "ad_set", s, par)
            for a in s.get("ads") or []:
                put([a.get("id"), a.get("meta_id")], "ad", a, p2)
    for i in meta.get("images") or []:
        put([i.get("hash")], "image", i, {"platform": "meta"})
    for v in meta.get("videos") or []:
        put([v.get("id")], "video", v, {"platform": "meta"})
    for cr in meta.get("creatives") or []:
        put([cr.get("id")], "creative", cr, {"platform": "meta"})
    return idx


def find_entity(doc, entity_id):
    # type: (Dict[str, Any], Any) -> Optional[Tuple[str, Dict[str, Any], Dict[str, Any]]]
    """(entity_type, entity, parents) for a dashboard id, resource name, Meta id, image hash or creative id."""
    return _index(doc).get(str(entity_id))


def read_field(entity, field):
    # type: (Dict[str, Any], Optional[str]) -> Any
    cur = entity  # type: Any
    for p in str(field or "").split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _set_field(entity, field, value):
    parts = field.split(".")
    cur = entity
    for p in parts[:-1]:
        if not isinstance(cur.get(p), dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


# --------------------------------------------------------------------- display

def _fmt_money(v, per_day=False):
    if v is None:
        return "—"
    s = "${:,.2f}".format(float(v))
    if s.endswith(".00"):
        s = s[:-3]
    return s + ("/day" if per_day else "")


def display(field, value):
    # type: (Optional[str], Any) -> str
    if value is None:
        return "—"
    if field in ("daily", "daily_budget"):
        return _fmt_money(value, True)
    if field in MONEY_FIELDS:
        return _fmt_money(value)
    if field == "targeting.geo_locations" and isinstance(value, dict):
        return ", ".join(value.get("countries") or []) or str(value)
    if field == "frequency_cap" and isinstance(value, dict):
        return "%s per %s days" % (value.get("max_frequency"), value.get("interval_days"))
    if isinstance(value, dict):
        return value.get("summary") or ", ".join("%s: %s" % (k, v) for k, v in value.items() if v is not None)
    if isinstance(value, list):
        return ", ".join(str(x) for x in value)
    return str(value)


# ------------------------------------------------------------------ simulation

def _int_value(v, what):
    if isinstance(v, bool):
        raise _OpError("%s must be an integer" % what)
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if not isinstance(v, int):
        try:
            v = int(str(v).replace(",", "").replace("_", ""))
        except (TypeError, ValueError):
            raise _OpError("%s must be an integer" % what)
    return v


def _micros_to_dollars(v, what):
    v = _int_value(v, what)
    if v <= 0:
        raise _OpError("%s must be positive" % what)
    if v % 10000:
        raise _OpError("%s must be a multiple of 10,000 micros (whole cents)" % what)
    return round(v / 1e6, 2)


def _cents_to_dollars(v, what):
    v = _int_value(v, what)
    if v <= 0:
        raise _OpError("%s must be positive (cents)" % what)
    return round(v / 100.0, 2)


def _norm_text(s):
    return " ".join(str(s or "").lower().split())


class _Sim(object):
    def __init__(self, doc, snap, guardrails=True, total_rise=True):
        self.doc = doc or {}
        self.use_guardrails = guardrails
        self.use_total_rise = guardrails and total_rise
        self.before = snap
        self.after = copy.deepcopy(snap)
        self.idx = _index(self.after)
        self.rows = []  # type: List[Dict[str, Any]]
        self.issues = []  # type: List[Dict[str, Any]]
        self.outputs = {}  # type: Dict[str, Dict[str, Any]]
        self.failed = set()  # type: set
        self.budgets = {}  # type: Dict[str, Dict[str, Any]]
        self.counts = {"creates": 0, "updates": 0, "removes": 0}
        self.dim = 30
        try:
            import calendar
            d = (snap.get("as_of") or "2026-11-05")
            self.dim = calendar.monthrange(int(d[:4]), int(d[5:7]))[1]
        except Exception:
            pass

    # helpers
    def issue(self, ref, level, msg):
        item = {"op": ref, "level": level, "message": msg}
        if item not in self.issues:
            self.issues.append(item)

    def row(self, ref, platform, etype, eid, ename, action, field, before, after):
        self.rows.append({"op": ref, "platform": platform, "entity_type": etype, "entity_id": eid,
                          "entity_name": ename, "action": action, "field": field,
                          "before": copy.deepcopy(before), "after": copy.deepcopy(after),
                          "display_before": display(field, before) if action != "create" else "—",
                          "display_after": display(field, after) if action != "remove" else "removed"})

    def lookup(self, key, etypes, platform):
        hit = self.idx.get(str(key))
        if not hit or hit[0] not in etypes or (hit[2].get("platform") not in (None, platform)):
            raise _OpError("resource not in snapshot: %s" % key)
        return hit

    def media(self, media_id, kind):
        if not media_id:
            raise _OpError("media_id is required")
        asset = media_asset(media_id)
        if not asset:
            raise _OpError("media_id %s is not in the Media library" % media_id)
        if asset.get("status") not in ("approved", "active"):
            raise _OpError("media_id %s is %s, not approved or active" % (media_id, asset.get("status")))
        if kind and asset.get("kind") != kind:
            raise _OpError("media_id %s is a %s, this operation needs a %s" % (media_id, asset.get("kind"), kind))
        return asset

    def track_budget(self, ref, platform, eid, name, before, after):
        t = self.budgets.setdefault(eid, {"before": before, "platform": platform, "name": name, "ops": []})
        t["after"] = after
        t["ops"].append(ref)

    def check_bid(self, ref, name, before, after):
        if not self.use_guardrails:
            return
        try:
            b, a = float(before), float(after)
        except (TypeError, ValueError):
            return
        if b > 0 and abs(a / b - 1) > BID_WARN_STEP:
            self.issue(ref, "warn", "%s bid moves %+.0f%% (%s -> %s)" % (name, (a / b - 1) * 100, _fmt_money(b), _fmt_money(a)))

    def check_refs(self, ref, obj):
        if isinstance(obj, dict):
            for v in obj.values():
                self.check_refs(ref, v)
        elif isinstance(obj, list):
            for v in obj:
                self.check_refs(ref, v)
        elif isinstance(obj, str) and obj.strip().startswith("$ref:"):
            m = REF_RE.match(obj.strip())
            if not m:
                raise _OpError("malformed reference %r (use $ref:<ref>.<field>)" % obj)
            target, field = m.group(1), m.group(2)
            if target in self.failed:
                raise _OpError("%s points to %s, which has errors" % (obj, target))
            if target not in self.outputs:
                raise _OpError("%s must point to an earlier op" % obj)
            if field not in self.outputs[target]:
                raise _OpError("%s: %s produces %s" % (obj, target, ", ".join(sorted(self.outputs[target]))))

    # run
    def run(self):
        head = self.doc.get("changeset") or {}
        based = head.get("based_on_snapshot")
        if based and based != self.before.get("id"):
            self.issue(None, "warn", "changeset is based on %s; checked against %s" % (based, self.before.get("id")))
        for op in self.doc.get("operations") or []:
            if not isinstance(op, dict):
                continue
            ref = op.get("ref")
            n_rows = len(self.rows)
            saved = (copy.deepcopy(self.after), copy.deepcopy(self.budgets))
            try:
                self.check_refs(ref, op)
                if op.get("platform") == "google":
                    self.google(ref, op)
                elif op.get("platform") == "meta":
                    self.meta(ref, op)
                else:
                    raise _OpError("platform must be google or meta")
            except _OpError as exc:
                del self.rows[n_rows:]
                self.after, self.budgets = saved
                self.idx = _index(self.after)
                self.outputs.pop(ref, None)
                self.failed.add(ref)
                self.issue(ref, "error", str(exc))
        if self.use_guardrails:
            self.guardrails()
        snapshot_mod.recompute(self.after)
        # recount the before total with the same rule as the after total (a stored total
        # in an older snapshot may predate the current counting rule)
        b = snapshot_mod.recompute(copy.deepcopy(self.before))["totals"]["all"]["daily_budget"]
        a = self.after["totals"]["all"]["daily_budget"]
        if self.use_total_rise and b and a > b * (1 + TOTAL_WARN_RISE):
            self.issue(None, "warn", "total daily budget rises %s -> %s (+%.0f%%, above +%d%%)" % (
                _fmt_money(b), _fmt_money(a), (a / b - 1) * 100, TOTAL_WARN_RISE * 100))
        return self

    def guardrails(self):
        for eid, t in self.budgets.items():
            before, after = t["before"], t["after"]
            ref = t["ops"][-1]
            if after is not None and after < BUDGET_MIN:
                self.issue(ref, "error", "%s daily budget %s is below the %s minimum" % (
                    t["name"], _fmt_money(after), _fmt_money(BUDGET_MIN)))
            if before:
                pct = after / before - 1
                if abs(pct) > BUDGET_MAX_STEP:
                    self.issue(ref, "error", "%s budget moves %+.0f%% (%s -> %s); the limit is +/-%d%% per changeset" % (
                        t["name"], pct * 100, _fmt_money(before), _fmt_money(after), BUDGET_MAX_STEP * 100))
                elif abs(pct) > BUDGET_WARN_STEP:
                    self.issue(ref, "warn", "%s budget moves %+.0f%% (%s -> %s)" % (
                        t["name"], pct * 100, _fmt_money(before), _fmt_money(after)))

    # ------------------------------------------------------------- google
    def google(self, ref, op):
        for k in op:
            if k not in GOOGLE_OP_KEYS:
                self.issue(ref, "warn", "unknown key %r ignored" % k)
        service, kind = op.get("service"), op.get("operation")
        spec = GOOGLE_SERVICES.get(service)
        if spec is None:
            raise _OpError("service %r is not in the allowlist" % service)
        if op.get("method") != spec["method"]:
            raise _OpError("%s method must be %s" % (service, spec["method"]))
        if kind not in spec["ops"]:
            raise _OpError("%s does not allow operation %r (allowed: %s)" % (service, kind, ", ".join(spec["ops"])))
        resolved = resolve_refs(op, self.outputs)
        fields = normalize_fields(resolved)
        rn = resolved.get("resource_name")
        if kind in ("update", "remove"):
            if not rn:
                raise _OpError("resource_name is required for %s" % kind)
            if "/%s/" % spec["collection"] not in str(rn):
                raise _OpError("resource_name %s is not a %s resource" % (rn, spec["collection"]))
            etype, ent, par = self.lookup(rn, (spec["etype"],), "google")
        if kind == "update":
            flat = flatten_paths(fields)
            mask = resolved.get("update_mask")
            if isinstance(mask, str):
                mask = [x.strip() for x in mask.split(",") if x.strip()]
            if not mask:
                raise _OpError("update_mask is required for update")
            if set(mask) != set(flat):
                raise _OpError("update_mask %s does not match fields %s" % (sorted(mask), sorted(flat)))
            bad = set(flat) - spec["ops"]["update"]
            if bad:
                raise _OpError("%s update may not change %s" % (service, ", ".join(sorted(bad))))
            self.google_update(ref, service, ent, par, flat)
            self.counts["updates"] += 1
        elif kind == "create":
            self.google_create(ref, service, fields)
            self.counts["creates"] += 1
        else:
            if fields:
                raise _OpError("remove takes resource_name only")
            self.google_remove(ref, etype, ent, par)
            self.counts["removes"] += 1

    def _status(self, v, allowed):
        s = str(v or "").upper()
        if s not in allowed:
            raise _OpError("status must be one of %s" % ", ".join(allowed))
        return s

    def google_update(self, ref, service, ent, par, flat):
        if service == "CampaignService":
            for path, v in sorted(flat.items()):
                if path == "status":
                    new = self._status(v, ("ENABLED", "PAUSED"))
                    self.row(ref, "google", "campaign", ent["id"], ent["name"], "update", "status", ent["status"], new)
                    ent["status"] = new
                else:
                    want = "TARGET_CPA" if path.startswith("target_cpa") else "MAXIMIZE_CONVERSIONS"
                    bidding = ent.setdefault("bidding", {})
                    if bidding.get("strategy") != want:
                        raise _OpError("%s uses %s; %s needs %s" % (ent["name"], bidding.get("strategy"), path, want))
                    if want == "MAXIMIZE_CONVERSIONS" and not isinstance(v, bool) and str(v).strip() == "0":
                        new = None  # 0 clears the optional target CPA (Google Ads semantics)
                    else:
                        new = _micros_to_dollars(v, path)
                    self.check_bid(ref, ent["name"], bidding.get("target_cpa"), new)
                    self.row(ref, "google", "campaign", ent["id"], ent["name"], "update", "bidding.target_cpa",
                             bidding.get("target_cpa"), new)
                    bidding["target_cpa"] = new
        elif service == "CampaignBudgetService":
            new = _micros_to_dollars(flat["amount_micros"], "amount_micros")
            camp = par["campaign"]
            if ent.get("shared"):
                self.issue(ref, "warn", "%s is a shared budget" % ent.get("name"))
            self.row(ref, "google", "budget", ent["resource_name"], ent.get("name") or camp["name"], "update",
                     "daily", ent["daily"], new)
            self.track_budget(ref, "google", ent["resource_name"], camp["name"], ent["daily"], new)
            ent["daily"] = new
            ent["amount_micros"] = int(round(new * 1e6))
            camp["monthly_budget"] = round(new * self.dim, 2)
        elif service == "AdGroupService":
            for path, v in sorted(flat.items()):
                if path == "status":
                    new = self._status(v, ("ENABLED", "PAUSED"))
                    self.row(ref, "google", "ad_group", ent["id"], ent["name"], "update", "status", ent["status"], new)
                    ent["status"] = new
                else:
                    new = _micros_to_dollars(v, path)
                    self.check_bid(ref, ent["name"], ent.get("cpc_bid"), new)
                    self.row(ref, "google", "ad_group", ent["id"], ent["name"], "update", "cpc_bid", ent.get("cpc_bid"), new)
                    ent["cpc_bid"] = new
        elif service == "AdGroupAdService":
            new = self._status(flat["status"], ("ENABLED", "PAUSED"))
            self.row(ref, "google", "ad", ent["id"], ent["name"], "update", "status", ent["status"], new)
            ent["status"] = new
        elif service == "AssetGroupService":
            new = self._status(flat["status"], ("ENABLED", "PAUSED"))
            self.row(ref, "google", "asset_group", ent["id"], ent["name"], "update", "status", ent["status"], new)
            ent["status"] = new
        elif service == "AssetGroupAssetService":
            new = self._status(flat["status"], ("ENABLED", "PAUSED"))
            self.row(ref, "google", "ad", ent["id"], ent["name"], "update", "status", ent["status"], new)
            ent["status"] = new
        elif service == "AdGroupCriterionService":
            new = self._status(flat["status"], ("ENABLED", "PAUSED"))
            name = "%s [%s] (%s)" % (ent["text"], ent["match"], par["ad_group"]["name"])
            self.row(ref, "google", "keyword", ent["resource_name"], name, "update", "status", ent["status"], new)
            ent["status"] = new

    def _keyword(self, kw):
        if not isinstance(kw, dict):
            raise _OpError("keyword {text, match_type} is required")
        text = _norm_text(kw.get("text"))
        match = str(kw.get("match_type") or "").upper()
        if not text:
            raise _OpError("keyword.text is empty")
        if len(text) > 80 or len(text.split()) > 10:
            raise _OpError("keyword %r is longer than 80 characters / 10 words" % text)
        if match not in MATCH_TYPES:
            raise _OpError("keyword.match_type must be one of %s" % ", ".join(MATCH_TYPES))
        extra = set(kw) - {"text", "match_type"}
        if extra:
            raise _OpError("keyword may only have text and match_type (got %s)" % ", ".join(sorted(extra)))
        return text, match

    def google_create(self, ref, service, fields):
        pending = "pending:%s" % ref
        if service == "AdGroupAdService":
            extra = set(fields) - {"ad_group", "status", "ad"}
            if extra:
                raise _OpError("ad create may not set %s" % ", ".join(sorted(extra)))
            _t, ag, par = self.lookup(fields.get("ad_group"), ("ad_group",), "google")
            ad = fields.get("ad") or {}
            if set(ad) - {"responsive_search_ad", "final_urls"}:
                raise _OpError("only responsive_search_ad creates are allowed")
            rsa = ad.get("responsive_search_ad")
            if not isinstance(rsa, dict):
                raise _OpError("ad.responsive_search_ad is required")
            heads = [str(h.get("text") or "") for h in rsa.get("headlines") or []]
            descs = [str(d.get("text") or "") for d in rsa.get("descriptions") or []]
            if not 3 <= len(heads) <= 15:
                raise _OpError("responsive search ads need 3-15 headlines (got %d)" % len(heads))
            if not 2 <= len(descs) <= 4:
                raise _OpError("responsive search ads need 2-4 descriptions (got %d)" % len(descs))
            for h in heads:
                if not h.strip() or len(h) > 30:
                    raise _OpError("headline %r must be 1-30 characters (%d)" % (h, len(h)))
            for d in descs:
                if not d.strip() or len(d) > 90:
                    raise _OpError("description %r must be 1-90 characters (%d)" % (d, len(d)))
            for p in ("path1", "path2"):
                if rsa.get(p) and len(str(rsa[p])) > 15:
                    raise _OpError("%s must be 15 characters or fewer" % p)
            urls = ad.get("final_urls") or []
            if not urls or not all(re.match(r"^https?://", str(u)) for u in urls):
                raise _OpError("ad.final_urls needs at least one http(s) URL")
            status = self._status(fields.get("status") or "PAUSED", ("ENABLED", "PAUSED"))
            if status == "ENABLED":
                self.issue(ref, "warn", "new ad starts ENABLED")
            name = "RSA_" + re.sub(r"\W+", "_", heads[0]).strip("_")[:40]
            new = {"id": "new:%s" % ref, "resource_name": pending, "name": name, "type": "RESPONSIVE_SEARCH_AD",
                   "status": status, "headlines": heads, "descriptions": descs, "final_url": str(urls[0])}
            ag.setdefault("ads", []).append(new)
            self.row(ref, "google", "ad", new["id"], name, "create", None, None,
                     {"summary": "RSA in %s (%s): %s" % (ag["name"], status, " | ".join(heads[:3])),
                      "ad_group_id": ag["id"], "headlines": heads, "status": status})
            self.outputs[ref] = {"resource_name": pending, "id": new["id"]}
        elif service == "AdGroupCriterionService":
            extra = set(fields) - {"ad_group", "status", "keyword"}
            if extra:
                raise _OpError("keyword create may not set %s (ad group negatives are not allowed)" % ", ".join(sorted(extra)))
            _t, ag, par = self.lookup(fields.get("ad_group"), ("ad_group",), "google")
            text, match = self._keyword(fields.get("keyword"))
            for k in ag.get("keywords") or []:
                if _norm_text(k["text"]) == text and k["match"] == match:
                    raise _OpError("keyword %s [%s] already exists in %s" % (text, match, ag["name"]))
            status = self._status(fields.get("status") or "ENABLED", ("ENABLED", "PAUSED"))
            ag.setdefault("keywords", []).append({"resource_name": pending, "text": text, "match": match, "status": status})
            self.row(ref, "google", "keyword", "new:%s" % ref, "%s [%s]" % (text, match), "create", None, None,
                     {"summary": "%s [%s] in %s (%s)" % (text, match, ag["name"], status),
                      "ad_group_id": ag["id"], "text": text, "match": match})
            self.outputs[ref] = {"resource_name": pending, "id": "new:%s" % ref}
        elif service == "CampaignCriterionService":
            extra = set(fields) - {"campaign", "negative", "keyword"}
            if extra:
                raise _OpError("negative keyword create may not set %s" % ", ".join(sorted(extra)))
            if fields.get("negative") is not True:
                raise _OpError("campaign criteria creates must be negative keywords (negative: true)")
            _t, camp, _p = self.lookup(fields.get("campaign"), ("campaign",), "google")
            text, match = self._keyword(fields.get("keyword"))
            for n in camp.get("negatives") or []:
                if _norm_text(n["text"]) == text and n["match"] == match:
                    raise _OpError("negative %s [%s] already exists on %s" % (text, match, camp["name"]))
            camp.setdefault("negatives", []).append({"resource_name": pending, "text": text, "match": match})
            self.row(ref, "google", "negative_keyword", "new:%s" % ref, "%s [%s]" % (text, match), "create", None, None,
                     {"summary": "-%s [%s] on %s" % (text, match, camp["name"]),
                      "campaign_id": camp["id"], "text": text, "match": match})
            self.outputs[ref] = {"resource_name": pending, "id": "new:%s" % ref}
        elif service == "AssetService":
            extra = set(fields) - {"name", "type", "image_asset"}
            if extra:
                raise _OpError("asset create may not set %s" % ", ".join(sorted(extra)))
            if str(fields.get("type") or "IMAGE").upper() != "IMAGE":
                raise _OpError("only IMAGE assets may be created")
            media_id = (fields.get("image_asset") or {}).get("media_id")
            asset = self.media(media_id, "image")
            name = fields.get("name") or asset.get("title") or media_id
            self.after.setdefault("google", {}).setdefault("assets", []).append(
                {"resource_name": pending, "name": name, "type": "IMAGE", "media_id": media_id})
            self.row(ref, "google", "asset", "new:%s" % ref, name, "create", None, None,
                     {"summary": "image asset %s from %s" % (name, media_id), "media_id": media_id})
            self.outputs[ref] = {"resource_name": pending, "id": "new:%s" % ref}

    def google_remove(self, ref, etype, ent, par):
        if etype == "keyword":
            ag = par["ad_group"]
            ag["keywords"] = [k for k in ag["keywords"] if k is not ent]
            self.row(ref, "google", "keyword", ent["resource_name"], "%s [%s]" % (ent["text"], ent["match"]),
                     "remove", None, {"summary": "%s [%s] in %s" % (ent["text"], ent["match"], ag["name"])}, None)
        elif etype == "negative_keyword":
            camp = par["campaign"]
            camp["negatives"] = [n for n in camp["negatives"] if n is not ent]
            self.row(ref, "google", "negative_keyword", ent["resource_name"], "%s [%s]" % (ent["text"], ent["match"]),
                     "remove", None, {"summary": "-%s [%s] on %s" % (ent["text"], ent["match"], camp["name"])}, None)
        else:
            raise _OpError("remove is not allowed for %s" % etype)

    # --------------------------------------------------------------- meta
    def meta(self, ref, op):
        for k in op:
            if k not in META_OP_KEYS:
                self.issue(ref, "warn", "unknown key %r ignored" % k)
        if str(op.get("method") or "").upper() != "POST":
            raise _OpError("Meta operations must be POST")
        path = normalize_path(op.get("path"))
        params = resolve_refs(op.get("params") or {}, self.outputs)
        if not isinstance(params, dict) or not params:
            raise _OpError("params are required")
        node = NODE_RE.match(path)
        if node:
            etype, ent, par = self.lookup(node.group(1), ("campaign", "ad_set", "ad"), "meta")
            bad = set(params) - META_NODE_PARAMS[etype]
            if bad:
                raise _OpError("POST /{%s_id} may not set %s" % (etype, ", ".join(sorted(bad))))
            self.meta_update(ref, etype, ent, par, params)
            self.counts["updates"] += 1
            return
        edge = EDGE_RE.match(path)
        if not edge:
            raise _OpError("path %s is not in the allowlist" % path)
        acct = (self.after.get("meta") or {}).get("ad_account_id")
        if edge.group(1) != acct:
            raise _OpError("resource not in snapshot: ad account %s (snapshot has %s)" % (edge.group(1), acct))
        getattr(self, "meta_" + edge.group(2))(ref, params)
        self.counts["creates"] += 1

    def meta_update(self, ref, etype, ent, par, params):
        name = ent["name"]
        for key in sorted(params):
            v = params[key]
            if key == "status":
                new = self._status(v, ("ACTIVE", "PAUSED"))
                self.row(ref, "meta", etype, ent["id"], name, "update", "status", ent["status"], new)
                ent["status"] = new
            elif key == "daily_budget":
                new = _cents_to_dollars(v, "daily_budget")
                if etype == "campaign" and ent.get("daily_budget") is None:
                    raise _OpError("%s uses ad set budgets; change daily_budget on its ad sets" % name)
                if etype == "ad_set" and (par["campaign"].get("daily_budget") is not None or ent.get("daily_budget") is None):
                    raise _OpError("%s is under a campaign budget (CBO); change the campaign budget" % name)
                self.row(ref, "meta", etype, ent["id"], name, "update", "daily_budget", ent["daily_budget"], new)
                self.track_budget(ref, "meta", ent["id"], name, ent["daily_budget"], new)
                ent["daily_budget"] = new
            elif key == "bid_amount":
                new = _cents_to_dollars(v, "bid_amount")
                if par["campaign"].get("bid_strategy") not in ("COST_CAP", "LOWEST_COST_WITH_BID_CAP"):
                    raise _OpError("%s bids %s; bid_amount needs a cost cap or bid cap" % (
                        par["campaign"]["name"], par["campaign"].get("bid_strategy")))
                self.check_bid(ref, name, ent.get("bid_amount"), new)
                self.row(ref, "meta", etype, ent["id"], name, "update", "bid_amount", ent.get("bid_amount"), new)
                ent["bid_amount"] = new
            elif key == "targeting":
                if not isinstance(v, dict) or not v:
                    raise _OpError("targeting must be a mapping")
                bad = set(v) - {"age_min", "age_max", "geo_locations"}
                if bad:
                    raise _OpError("targeting may only change age_min, age_max, geo_locations (got %s)" % ", ".join(sorted(bad)))
                t = ent.setdefault("targeting", {})
                lo = _int_value(v.get("age_min", t.get("age_min", 18)), "age_min")
                hi = _int_value(v.get("age_max", t.get("age_max", 65)), "age_max")
                if not (18 <= lo <= hi <= 65):
                    raise _OpError("ages must satisfy 18 <= age_min <= age_max <= 65")
                if "geo_locations" in v:
                    geo = v["geo_locations"]
                    if not isinstance(geo, dict) or set(geo) - {"countries"} or not geo.get("countries") or \
                            not all(re.match(r"^[A-Z]{2}$", str(cc)) for cc in geo["countries"]):
                        raise _OpError("geo_locations must be {countries: [two-letter codes]}")
                for k2 in ("age_min", "age_max", "geo_locations"):
                    if k2 in v:
                        val = {"age_min": lo, "age_max": hi}.get(k2, v.get(k2))
                        self.row(ref, "meta", etype, ent["id"], name, "update", "targeting.%s" % k2, t.get(k2), val)
                        t[k2] = copy.deepcopy(val)
            elif key == "frequency_control_specs":
                if not isinstance(v, list) or len(v) != 1 or not isinstance(v[0], dict):
                    raise _OpError("frequency_control_specs must be a list with one {event, interval_days, max_frequency}")
                s = v[0]
                if str(s.get("event") or "").upper() != "IMPRESSIONS":
                    raise _OpError("frequency_control_specs.event must be IMPRESSIONS")
                days = _int_value(s.get("interval_days"), "interval_days")
                mx = _int_value(s.get("max_frequency"), "max_frequency")
                if not (1 <= days <= 90) or mx < 1:
                    raise _OpError("interval_days must be 1-90 and max_frequency >= 1")
                new = {"event": "IMPRESSIONS", "interval_days": days, "max_frequency": mx}
                self.row(ref, "meta", etype, ent["id"], name, "update", "frequency_cap", ent.get("frequency_cap"), new)
                ent["frequency_cap"] = new

    def _only(self, params, allowed, what):
        bad = set(params) - set(allowed)
        if bad:
            raise _OpError("%s may not set %s" % (what, ", ".join(sorted(bad))))

    def meta_adimages(self, ref, params):
        self._only(params, ("media_id", "name"), "adimages")
        media_id = params.get("media_id")
        asset = self.media(media_id, "image")
        h = "pending:%s.hash" % ref
        img = {"hash": h, "media_id": media_id, "name": params.get("name") or asset.get("title") or media_id}
        self.after["meta"].setdefault("images", []).append(img)
        self.idx[h] = ("image", img, {"platform": "meta"})
        self.row(ref, "meta", "image", "new:%s" % ref, img["name"], "create", None, None,
                 {"summary": "upload image %s" % media_id, "media_id": media_id})
        self.outputs[ref] = {"hash": h, "id": h}

    def meta_advideos(self, ref, params):
        self._only(params, ("media_id", "name", "title"), "advideos")
        media_id = params.get("media_id")
        asset = self.media(media_id, "video")
        vid = "new:%s" % ref
        rec = {"id": vid, "media_id": media_id, "title": params.get("title") or params.get("name") or asset.get("title") or media_id}
        self.after["meta"].setdefault("videos", []).append(rec)
        self.idx[vid] = ("video", rec, {"platform": "meta"})
        self.row(ref, "meta", "video", vid, rec["title"], "create", None, None,
                 {"summary": "upload video %s" % media_id, "media_id": media_id})
        self.outputs[ref] = {"id": vid}

    def meta_adcreatives(self, ref, params):
        self._only(params, ("name", "object_story_spec", "url_tags"), "adcreatives")
        name = str(params.get("name") or "").strip()
        if not name:
            raise _OpError("creative name is required")
        spec = params.get("object_story_spec")
        if not isinstance(spec, dict):
            raise _OpError("object_story_spec is required")
        page = (self.after.get("meta") or {}).get("page_id")
        if str(spec.get("page_id") or "") != str(page):
            raise _OpError("object_story_spec.page_id must be the account page %s" % page)
        link, video = spec.get("link_data"), spec.get("video_data")
        if bool(link) == bool(video):
            raise _OpError("object_story_spec needs exactly one of link_data or video_data")
        if set(spec) - {"page_id", "link_data", "video_data", "instagram_actor_id", "instagram_user_id"}:
            raise _OpError("object_story_spec has unsupported keys")
        data = link or video
        cta = data.get("call_to_action") or {}
        if cta.get("type") and cta["type"] not in META_CTAS:
            self.issue(ref, "warn", "call_to_action %s is unusual" % cta["type"])
        if link:
            h = link.get("image_hash")
            hit = self.idx.get(str(h))
            if not h or not hit or hit[0] != "image":
                raise _OpError("link_data.image_hash must be an uploaded image ($ref to an adimages op or an existing hash)")
            if not re.match(r"^https?://", str(link.get("link") or "")):
                raise _OpError("link_data.link must be an http(s) URL")
            media_id, fmt = hit[1].get("media_id"), "image"
            title, body, url = link.get("name"), link.get("message"), link.get("link")
        else:
            vid = video.get("video_id")
            hit = self.idx.get(str(vid))
            if not vid or not hit or hit[0] != "video":
                raise _OpError("video_data.video_id must be an uploaded video ($ref to an advideos op or an existing id)")
            if not video.get("image_hash") and not video.get("image_url"):
                self.issue(ref, "warn", "video_data has no thumbnail (image_hash or image_url); Meta requires one")
            url = (cta.get("value") or {}).get("link")
            if not re.match(r"^https?://", str(url or "")):
                raise _OpError("video_data.call_to_action.value.link must be an http(s) URL")
            media_id, fmt = hit[1].get("media_id"), "video"
            title, body = video.get("title"), video.get("message")
        cid = "new:%s" % ref
        rec = {"id": cid, "name": name, "format": fmt, "title": title, "body": body, "link": url,
               "cta": cta.get("type"), "image_hash": data.get("image_hash"), "video_id": data.get("video_id"),
               "media_id": media_id}
        self.after["meta"].setdefault("creatives", []).append(rec)
        self.idx[cid] = ("creative", rec, {"platform": "meta"})
        self.row(ref, "meta", "creative", cid, name, "create", None, None,
                 {"summary": "%s creative %s: %s" % (fmt, name, title or ""), "name": name, "media_id": media_id})
        self.outputs[ref] = {"id": cid}

    def meta_ads(self, ref, params):
        self._only(params, ("name", "adset_id", "creative", "status", "tracking_specs"), "ads")
        name = str(params.get("name") or "").strip()
        if not name:
            raise _OpError("ad name is required")
        _t, aset, par = self.lookup(params.get("adset_id"), ("ad_set",), "meta")
        crid = (params.get("creative") or {}).get("creative_id")
        hit = self.idx.get(str(crid))
        if not crid or not hit or hit[0] != "creative":
            raise _OpError("creative.creative_id must be a creative ($ref to an adcreatives op or an existing id)")
        if str(params.get("status") or "") != "PAUSED":
            raise _OpError("new ads must start PAUSED (status: PAUSED)")
        cr = hit[1]
        for a in aset.get("ads") or []:
            if a["name"] == name:
                self.issue(ref, "warn", "an ad named %s already exists in %s" % (name, aset["name"]))
        new = {"id": "new:%s" % ref, "meta_id": "new:%s" % ref, "name": name, "status": "PAUSED",
               "format": cr.get("format"), "title": cr.get("title"), "body": cr.get("body"), "cta": cr.get("cta"),
               "media_id": cr.get("media_id"), "creative_id": cr.get("id")}
        aset.setdefault("ads", []).append(new)
        self.row(ref, "meta", "ad", new["id"], name, "create", None, None,
                 {"summary": "new %s ad %s in %s (PAUSED)%s" % (new["format"], name, aset["name"],
                                                               ", media %s" % new["media_id"] if new["media_id"] else ""),
                  "ad_set_id": aset["id"], "name": name, "status": "PAUSED", "media_id": new["media_id"]})
        self.outputs[ref] = {"id": new["id"]}


# --------------------------------------------------------------------- public

def _doc_or_issue(doc):
    if not isinstance(doc, dict):
        return None
    return doc


def validate(doc, snapshot, guardrails=True, total_rise=True):
    # type: (Dict[str, Any], Dict[str, Any], bool, bool) -> List[Dict[str, Any]]
    """Every problem with a changeset against a snapshot: allowlist, unknown resources, refs, media, guardrails.

    ``guardrails=False`` skips every guardrail: the budget step / minimum / total-rise
    checks and the bid-move warning (an undo that restores values the account held
    moments ago, or direct controls with guardrails off); ``total_rise=False`` skips only the total
    daily budget rise check (direct status flips: see planning.direct)."""
    if _doc_or_issue(doc) is None:
        return [{"op": None, "level": "error", "message": "no changeset to validate"}]
    issues = []  # type: List[Dict[str, Any]]
    # structural problems parse() would report (doc may be hand-built)
    _d, errs = parse(doc)
    for e in errs:
        issues.append({"op": None, "level": "error", "message": e})
    sim = _Sim(doc, snapshot, guardrails=guardrails, total_rise=total_rise).run()
    for i in sim.issues:
        if i not in issues:
            issues.append(i)
    return issues


def dry_run(doc, snapshot):
    # type: (Dict[str, Any], Dict[str, Any]) -> Dict[str, Any]
    """Apply the changeset to a copy of the snapshot. Ops with errors are skipped."""
    sim = _Sim(doc or {}, snapshot).run()
    before_y = snapshot_mod.to_yaml(snapshot).splitlines()
    after_y = snapshot_mod.to_yaml(sim.after).splitlines()
    sid = snapshot.get("id") or "snapshot"
    diff = "\n".join(difflib.unified_diff(before_y, after_y, fromfile="%s.yaml" % sid,
                                          tofile="%s+changeset.yaml" % sid, lineterm="", n=3))
    bt = snapshot.get("totals") or snapshot_mod.recompute(copy.deepcopy(snapshot))["totals"]
    at = sim.after["totals"]
    summary = dict(sim.counts)
    summary["daily_budget_delta"] = {
        "google": round(at["google"]["daily_budget"] - bt["google"]["daily_budget"], 2),
        "meta": round(at["meta"]["daily_budget"] - bt["meta"]["daily_budget"], 2)}
    summary["errors"] = len([i for i in sim.issues if i["level"] == "error"])
    summary["warnings"] = len([i for i in sim.issues if i["level"] == "warn"])
    return {"after": sim.after, "rows": sim.rows, "text_diff": diff, "summary": summary}
