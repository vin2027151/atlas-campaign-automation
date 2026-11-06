"""Stub LLM outputs for ATLAS_LLM_MODE=stub (tests and local dev).

The analysis fixture is static text (analysis.json) plus a line per deterministic fact; the
changeset fixture is generated from the live snapshot at call time so every resource name and
Meta id matches the current state (and validates against it).
"""

import json
import os
from typing import Any, Dict, List, Optional

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    # type: (str) -> Any
    with open(os.path.join(HERE, name), "r", encoding="utf-8") as fh:
        return json.load(fh)


def analysis_text(facts):
    # type: (List[Dict[str, Any]]) -> str
    base = _load("analysis.json")
    out = dict(base)
    extra = []
    for f in (facts or [])[:3]:
        note = f.get("note") or f.get("kind")
        if note:
            extra.append(str(note)[:140])
    out["plan_status"] = list(base["plan_status"]) + extra
    return json.dumps(out)


# ---------------------------------------------------------------- changeset

def _num(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _brand_budget(snapshot):
    # type: (Dict[str, Any]) -> Optional[Dict[str, Any]]
    camps = (snapshot.get("google") or {}).get("campaigns") or []
    ranked = sorted(camps, key=lambda c: (0 if "brand" in c.get("name", "").lower() and "nonbrand" not in c.get("name", "").lower() else 1,
                                          0 if c.get("status") == "ENABLED" else 1))
    for c in ranked:
        b = c.get("budget") or {}
        if b.get("resource_name") and (_num(b.get("daily"), 0) or 0) >= 20 and not b.get("shared"):
            return c
    return None


def _nonbrand_search(snapshot):
    # type: (Dict[str, Any]) -> Optional[Dict[str, Any]]
    camps = (snapshot.get("google") or {}).get("campaigns") or []
    for c in camps:
        if c.get("channel") == "SEARCH" and "nonbrand" in c.get("name", "").lower() and c.get("resource_name"):
            return c
    for c in camps:
        if c.get("channel") == "SEARCH" and c.get("resource_name"):
            return c
    return None


def _worst_meta(snapshot):
    # type: (Dict[str, Any]) -> Optional[Dict[str, Any]]
    """Active ad in the active Meta campaign with the highest 7-day cost per trial."""
    camps = [c for c in (snapshot.get("meta") or {}).get("campaigns") or [] if c.get("status") == "ACTIVE"]
    camps.sort(key=lambda c: -(_num((c.get("metrics") or {}).get("cpt_7d"), 0) or 0))
    for c in camps:
        for s in c.get("ad_sets") or []:
            if s.get("status") != "ACTIVE":
                continue
            active = [a for a in s.get("ads") or [] if a.get("status") == "ACTIVE" and a.get("meta_id")]
            if len(active) >= 2:  # never pause the last running ad in an ad set
                return {"campaign": c, "ad_set": s, "ad": active[0]}
    return None


def _target_adset(snapshot):
    # type: (Dict[str, Any]) -> Optional[Dict[str, Any]]
    for c in (snapshot.get("meta") or {}).get("campaigns") or []:
        if c.get("status") != "ACTIVE" or "prospecting" not in c.get("name", "").lower():
            continue
        for s in c.get("ad_sets") or []:
            if s.get("meta_id"):
                return {"campaign": c, "ad_set": s}
    for c in (snapshot.get("meta") or {}).get("campaigns") or []:
        for s in c.get("ad_sets") or []:
            if s.get("meta_id"):
                return {"campaign": c, "ad_set": s}
    return None


def changeset(snapshot, media_assets, tagged_media=None, revision=0, revision_note=None, page_id="123456789012345",
              landing_url="https://www.agentstack.example/trial"):
    # type: (Dict[str, Any], List[Dict[str, Any]], Optional[List[str]], int, Optional[str], str, str) -> str
    """Return the stub model reply (JSON text with a yaml field) built from the snapshot."""
    cut = min(0.10 + 0.05 * revision, 0.20)
    ops = []  # type: List[Dict[str, Any]]
    summary = []  # type: List[str]
    rationale = []  # type: List[str]

    brand = _brand_budget(snapshot)
    if brand:
        b = brand["budget"]
        new_daily = round(float(b["daily"]) * (1 - cut), 2)
        ops.append({"ref": "op%d" % (len(ops) + 1), "platform": "google", "service": "CampaignBudgetService",
                    "method": "mutateCampaignBudgets", "operation": "update", "resource_name": b["resource_name"],
                    "fields": {"amount_micros": int(round(new_daily * 1000000))}, "update_mask": ["amount_micros"],
                    "reason": "Brand demand is capped; trim %d%% and keep budget for nonbrand" % int(cut * 100)})
        summary.append("Lower %s daily budget %d%%: $%s to $%s." % (brand["name"], int(cut * 100), b["daily"], new_daily))
        rationale.append("Brand budget trimmed %d%%." % int(cut * 100))

    worst = _worst_meta(snapshot)
    if worst:
        ad = worst["ad"]
        ops.append({"ref": "op%d" % (len(ops) + 1), "platform": "meta", "method": "POST", "path": "/%s" % ad["meta_id"],
                    "params": {"status": "PAUSED"},
                    "reason": "Highest 7-day cost per trial among active Meta campaigns (%s)" % worst["campaign"]["name"]})
        summary.append("Pause ad %s in %s (worst 7-day CPT)." % (ad.get("name"), worst["campaign"]["name"]))
        rationale.append("Pause the weakest Meta ad.")

    nb = _nonbrand_search(snapshot)
    if nb:
        existing = set(n.get("text", "").lower() for n in nb.get("negatives") or [])
        text = "free"
        for cand in ("free", "open source", "tutorial", "jobs", "course"):
            if cand not in existing:
                text = cand
                break
        ops.append({"ref": "op%d" % (len(ops) + 1), "platform": "google", "service": "CampaignCriterionService",
                    "method": "mutateCampaignCriteria", "operation": "create",
                    "fields": {"campaign": nb["resource_name"], "negative": True,
                               "keyword": {"text": text, "match_type": "PHRASE"}},
                    "reason": "Non-buyer intent"})
        summary.append('Add phrase negative "%s" to %s.' % (text, nb["name"]))
        rationale.append("Block non-buyer search intent.")

    images = [a for a in media_assets or [] if a.get("kind") == "image"]
    tagged = [a for a in images if a.get("id") in (tagged_media or [])]
    asset = (tagged or images or [None])[0]
    target = _target_adset(snapshot)
    acct = (snapshot.get("meta") or {}).get("ad_account_id") or "act_7778889999"
    if asset and target:
        r_img = "op%d" % (len(ops) + 1)
        ops.append({"ref": r_img, "platform": "meta", "method": "POST", "path": "/%s/adimages" % acct,
                    "params": {"media_id": asset["id"]}, "reason": "Upload approved creative %s" % asset["id"]})
        r_cr = "op%d" % (len(ops) + 1)
        name = "Stub_%s_%s" % (asset["id"], target["ad_set"].get("name", "adset"))
        ops.append({"ref": r_cr, "platform": "meta", "method": "POST", "path": "/%s/adcreatives" % acct,
                    "params": {"name": name, "object_story_spec": {"page_id": str(page_id), "link_data": {
                        "image_hash": "$ref:%s.hash" % r_img, "link": landing_url,
                        "message": "Build and ship AI agents without the glue code. 14-day trial, no card.",
                        "name": "Start your free trial", "call_to_action": {"type": "SIGN_UP"}}}},
                    "reason": "Creative from %s" % asset["id"]})
        ops.append({"ref": "op%d" % (len(ops) + 1), "platform": "meta", "method": "POST", "path": "/%s/ads" % acct,
                    "params": {"name": name, "adset_id": str(target["ad_set"]["meta_id"]),
                               "creative": {"creative_id": "$ref:%s.id" % r_cr}, "status": "PAUSED"},
                    "reason": "New ad starts paused for review"})
        summary.append("Create a PAUSED Meta ad from %s in %s." % (asset["id"], target["ad_set"].get("name")))
        rationale.append("Test new approved creative, paused until reviewed.")

    doc = {"changeset": {"title": "Stub: trim Brand, pause weakest Meta ad, add negative" + (" (rev %d)" % revision if revision else ""),
                         "based_on_snapshot": snapshot.get("id"), "rationale": rationale},
           "operations": ops}
    assumptions = ["Stub output (ATLAS_LLM_MODE=stub); generated from the current snapshot."]
    if revision_note:
        assumptions.append("Revision %d applied: brand cut now %d%%." % (revision, int(cut * 100)))
    questions = [] if asset else ["No approved image in the Media library; skipped the new ad."]
    reply = {"yaml": yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120),
             "summary": summary, "assumptions": assumptions, "questions": questions}
    return json.dumps(reply)
