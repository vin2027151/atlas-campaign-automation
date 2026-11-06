"""Core planning tests: snapshot, plan compare, changeset parse/validate/dry-run, executor.

Run from dashboard/:  .venv/bin/python -m tests.test_planning_core   (or pytest)

Every test works on a temp copy of data/state.json with store.STATE_PATH and
planning.DATA_DIR repointed, and a fake `media` module, so the real data is never touched.
"""

import contextlib
import re
import copy
import os
import shutil
import subprocess
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import yaml  # noqa: E402

import planning  # noqa: E402
import store  # noqa: E402
from planning import adapters, changeset, executor, plan_compare, snapshot  # noqa: E402
from planning.adapters import sample  # noqa: E402

FAKE_ASSETS = {
    "IMG-0002": {"id": "IMG-0002", "kind": "image", "status": "approved", "title": "Benefits grid 1:1",
                 "file_url": None, "format": "image/png", "platform_refs": {}},
    "IMG-0003": {"id": "IMG-0003", "kind": "image", "status": "in_review", "title": "Draft", "file_url": None},
    "VID-0001": {"id": "VID-0001", "kind": "video", "status": "approved", "title": "Founder cut", "file_url": None},
}


def _fake_media():
    mod = types.ModuleType("media")
    mod.published = []

    def get_asset(asset_id):
        if asset_id not in FAKE_ASSETS:
            raise store.NotFound("unknown media: %s" % asset_id)
        return copy.deepcopy(FAKE_ASSETS[asset_id])

    def list_assets(status=None, kind=None):
        return [copy.deepcopy(a) for a in FAKE_ASSETS.values()
                if (status is None or a["status"] == status) and (kind is None or a["kind"] == kind)]

    def mark_published(asset_id, platform, ref):
        mod.published.append((asset_id, platform, dict(ref)))
        return get_asset(asset_id)

    mod.get_asset, mod.list_assets, mod.mark_published = get_asset, list_assets, mark_published
    return mod


@contextlib.contextmanager
def sandbox():
    tmp = tempfile.mkdtemp(prefix="planning-core-")
    old = (store.STATE_PATH, planning.DATA_DIR, sys.modules.get("media"), adapters.CONFIG_PATH)
    shutil.copy(os.path.join(ROOT, "data", "state.json"), os.path.join(tmp, "state.json"))
    store.STATE_PATH = os.path.join(tmp, "state.json")
    store.reload_state()
    planning.DATA_DIR = os.path.join(tmp, "planning")
    adapters.CONFIG_PATH = os.path.join(ROOT, "config", "platforms.yaml")
    fake = _fake_media()
    sys.modules["media"] = fake
    try:
        yield fake
    finally:
        store.STATE_PATH, planning.DATA_DIR, media_mod, adapters.CONFIG_PATH = old
        if media_mod is None:
            sys.modules.pop("media", None)
        else:
            sys.modules["media"] = media_mod
        store.reload_state()
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------- helpers

def _gc(snap, cid):
    return [c for c in snap["google"]["campaigns"] if c["id"] == cid][0]


def _mc(snap, cid):
    return [c for c in snap["meta"]["campaigns"] if c["id"] == cid][0]


def _yaml(head, ops):
    return yaml.safe_dump({"changeset": head, "operations": ops}, sort_keys=False)


def _sample_changeset(snap):
    brand = _gc(snap, "g_search_brand_us")
    uk = _gc(snap, "g_search_nonbrand_uk")
    nb = _gc(snap, "g_search_nonbrand_us")
    core = _mc(snap, "m_prospecting_core")
    aset = core["ad_sets"][0]
    acct = snap["meta"]["ad_account_id"]
    ops = [
        {"ref": "op1", "platform": "google", "service": "CampaignBudgetService", "method": "mutateCampaignBudgets",
         "operation": "update", "resource_name": brand["budget"]["resource_name"],
         "fields": {"amount_micros": int(round(brand["budget"]["daily"] * 0.75, 2) * 100) * 10000},
         "update_mask": ["amount_micros"], "reason": "plan: brand $3K"},
        {"ref": "op2", "platform": "google", "service": "CampaignService", "method": "mutateCampaigns",
         "operation": "update", "resource_name": uk["resource_name"], "fields": {"status": "PAUSED"},
         "update_mask": ["status"], "reason": "UK tag unverified"},
        {"ref": "op3", "platform": "google", "service": "CampaignCriterionService", "method": "mutateCampaignCriteria",
         "operation": "create", "fields": {"campaign": nb["resource_name"], "negative": True,
                                            "keyword": {"text": "seo course", "match_type": "PHRASE"}},
         "reason": "search terms"},
        {"ref": "op4", "platform": "meta", "method": "POST", "path": "/%s/adimages" % acct,
         "params": {"media_id": "IMG-0002"}},
        {"ref": "op5", "platform": "meta", "method": "POST", "path": "/%s/adcreatives" % acct,
         "params": {"name": "Benefits grid v2", "object_story_spec": {
             "page_id": snap["meta"]["page_id"],
             "link_data": {"image_hash": "$ref:op4.hash", "link": "https://www.agentstack.example/trial",
                           "message": "One login for every SEO job.", "name": "One stack for every SEO job",
                           "call_to_action": {"type": "SIGN_UP"}}}}},
        {"ref": "op6", "platform": "meta", "method": "POST", "path": "/%s/ads" % acct,
         "params": {"name": "Static_Benefits_v2", "adset_id": aset["meta_id"],
                    "creative": {"creative_id": "$ref:op5.id"}, "status": "PAUSED"}},
    ]
    head = {"title": "Brand down, UK paused, negative, new Meta ad", "based_on_snapshot": snap["id"],
            "rationale": ["test"]}
    return _yaml(head, ops), aset


def _errors(issues):
    return [i for i in issues if i["level"] == "error"]


def _has(issues, level, text):
    return any(i["level"] == level and text in i["message"] for i in issues)


# ------------------------------------------------------------------ tests

def test_snapshot_pull_shape():
    with sandbox():
        doc = snapshot.pull(reason="analyze")
        for k in ("id", "taken_at", "reason", "mode", "as_of", "google", "meta", "totals", "counts"):
            assert k in doc, k
        assert doc["mode"] == "sample" and doc["as_of"] == "2026-11-05"
        assert doc["google"]["customer_id"] == "4445556666"
        assert doc["meta"]["ad_account_id"] == "act_7778889999"
        c = _gc(doc, "g_search_brand_us")
        assert c["resource_name"].startswith("customers/4445556666/campaigns/")
        assert c["status"] in ("ENABLED", "PAUSED") and c["channel"] == "SEARCH"
        assert c["budget"]["amount_micros"] == int(c["budget"]["daily"] * 1e6)
        assert "/campaignBudgets/" in c["budget"]["resource_name"]
        for k in ("spend_7d", "trials_7d", "cpt_7d", "spend_mtd", "trials_mtd", "cpt_mtd"):
            assert k in c["metrics"], k
        ag = c["ad_groups"][0]
        assert ag["keywords"] and "/adGroupCriteria/" in ag["keywords"][0]["resource_name"]
        assert ag["ads"][0]["type"] == "RESPONSIVE_SEARCH_AD" and ag["ads"][0]["headlines"]
        assert "~" in ag["ads"][0]["resource_name"]
        assert _gc(doc, "g_pmax_us")["asset_groups"]
        nb = _gc(doc, "g_search_nonbrand_us")
        assert nb["bidding"] == {"strategy": "TARGET_CPA", "target_cpa": 280.0}
        assert all("/campaignCriteria/" in n["resource_name"] for n in nb["negatives"])
        mc = _mc(doc, "m_prospecting_core")
        assert mc["meta_id"].isdigit() and mc["status"] in ("ACTIVE", "PAUSED")
        s = mc["ad_sets"][0]
        assert s["meta_id"].isdigit() and s["daily_budget"] > 0 and s["optimization_goal"] == "OFFSITE_CONVERSIONS"
        assert set(("geo_locations", "age_min", "age_max")) <= set(s["targeting"])
        assert {"title", "body", "cta", "media_id"} <= set(s["ads"][0])
        st = store.get_state()
        assert doc["counts"]["campaigns"] == len(st["campaigns"]) and doc["counts"]["ads"] == len(st["ads"])
        assert doc["counts"]["negatives"] == len(st["negatives"])
        assert doc["counts"]["ad_groups"] + doc["counts"]["ad_sets"] == len(st["adsets"])
        assert abs(doc["totals"]["google"]["daily_budget"] + doc["totals"]["meta"]["daily_budget"]
                   - doc["totals"]["all"]["daily_budget"]) < 0.01
        # persisted under the sandbox, readable back
        assert os.path.exists(os.path.join(planning.DATA_DIR, "snapshots", doc["id"] + ".json"))
        assert snapshot.get(doc["id"])["id"] == doc["id"]
        assert snapshot.latest()["id"] == doc["id"]
        lst = snapshot.list_snapshots()
        assert lst[0]["id"] == doc["id"] and set(("id", "taken_at", "reason", "counts")) <= set(lst[0])
        try:
            snapshot.get("SNAP-19990101-000000")
            raise AssertionError("expected NotFound")
        except store.NotFound:
            pass
        text = snapshot.to_yaml(doc)
        assert yaml.safe_load(text)["counts"] == doc["counts"]
        comp = snapshot.compact(doc)
        assert "taken_at" not in comp and len(str(comp)) < len(str(doc))
        assert os.path.exists(sample.overlay_path())


def test_plan_compare_facts():
    with sandbox():
        doc = snapshot.build()
        facts = plan_compare.compare(plan_compare.load_plan(), doc)
        kinds = {"budget_gap", "missing_campaign", "unplanned_campaign", "status_mismatch", "cpa_out_of_band",
                 "precondition_open", "checklist_overdue", "pacing"}
        assert facts
        for f in facts:
            assert f["kind"] in kinds, f
            for k in ("kind", "platform", "campaign", "planned", "actual", "note"):
                assert k in f, (k, f)
        plan = plan_compare.load_plan()
        dim = plan["account"]["days_in_month"]
        expected = set()
        for pc in plan["google_campaigns"] + plan["meta_campaigns"]:
            c = [x for x in store.get_state()["campaigns"] if x["name"] == pc["name"]]
            if c:
                actual = c[0]["daily_budget"] if c[0]["platform"] == "google" else sum(
                    a["daily_budget"] for a in store.adsets_for(c[0]["id"]) if a["status"] == "ACTIVE")
                if abs(actual / (pc["budget"] / float(dim)) - 1) > 0.05:
                    expected.add(pc["name"])
        got = set(f["campaign"] for f in facts if f["kind"] == "budget_gap")
        assert got == expected, (got, expected)
        brand = [f for f in facts if f["kind"] == "budget_gap" and f["campaign"] == "Search_Brand_US"]
        if brand:
            assert brand[0]["planned"] == 100.0
            assert brand[0]["actual"] == store.campaign("g_search_brand_us")["daily_budget"]
        assert any(f["kind"] == "unplanned_campaign" and f["campaign"] == "Prospecting_Broad" for f in facts)
        assert any(f["kind"] == "checklist_overdue" for f in facts)
        assert any(f["kind"] == "precondition_open" for f in facts)
        # deterministic
        assert facts == plan_compare.compare(plan_compare.load_plan(), doc)


def test_parse_and_validate_catch_bad_ops():
    with sandbox():
        snap = snapshot.build()
        brand = _gc(snap, "g_search_brand_us")
        acct = snap["meta"]["ad_account_id"]
        head = {"title": "t", "based_on_snapshot": snap["id"]}

        doc, errs = changeset.parse("changeset: [unclosed")
        assert doc is None and errs
        doc, errs = changeset.parse("changeset: {title: x, based_on_snapshot: S}\noperations: []\n")
        assert errs and "non-empty" in errs[0]
        doc, errs = changeset.parse("```yaml\n" + _yaml(head, [{"ref": "a", "platform": "google"},
                                                               {"ref": "a", "platform": "tiktok"}]) + "```")
        assert doc is not None and any("duplicate ref" in e for e in errs) and any("platform" in e for e in errs)

        def issues(ops):
            d, e = changeset.parse(_yaml(head, ops))
            assert not e, e
            return changeset.validate(d, snap)

        base_daily = brand["budget"]["daily"]
        mic = lambda factor: int(round(base_daily * factor, 2) * 100) * 10000
        budget = lambda micros: {"ref": "b", "platform": "google", "service": "CampaignBudgetService",
                                 "method": "mutateCampaignBudgets", "operation": "update",
                                 "resource_name": brand["budget"]["resource_name"],
                                 "fields": {"amount_micros": micros}, "update_mask": ["amount_micros"]}
        # not in allowlist
        assert _has(issues([{"ref": "x", "platform": "google", "service": "CustomerService", "method": "mutateCustomers",
                             "operation": "update", "resource_name": "customers/4445556666", "fields": {"a": 1},
                             "update_mask": ["a"]}]), "error", "allowlist")
        assert _has(issues([{"ref": "x", "platform": "google", "service": "CampaignService", "method": "mutateCampaigns",
                             "operation": "update", "resource_name": brand["resource_name"],
                             "fields": {"name": "Renamed"}, "update_mask": ["name"]}]), "error", "may not change name")
        assert _has(issues([{"ref": "x", "platform": "google", "service": "CampaignService", "method": "mutateCampaigns",
                             "operation": "remove", "resource_name": brand["resource_name"]}]), "error", "does not allow")
        assert _has(issues([{"ref": "x", "platform": "meta", "method": "DELETE", "path": "/123"}]), "error", "POST")
        # unknown resources
        assert _has(issues([dict(budget(mic(0.9)), resource_name="customers/4445556666/campaignBudgets/999")]),
                    "error", "not in snapshot")
        assert _has(issues([{"ref": "x", "platform": "meta", "method": "POST", "path": "/120219999999999999",
                             "params": {"status": "PAUSED"}}]), "error", "not in snapshot")
        assert _has(issues([{"ref": "x", "platform": "meta", "method": "POST", "path": "/act_1/adimages",
                             "params": {"media_id": "IMG-0002"}}]), "error", "not in snapshot")
        # mask mismatch, micros
        assert _has(issues([dict(budget(mic(0.9)), update_mask=["status"])]), "error", "update_mask")
        assert _has(issues([budget(mic(0.9) + 1)]), "error", "10,000")
        # guardrails
        assert _has(issues([budget(mic(2.0))]), "error", "limit is +/-50%")
        assert _has(issues([budget(mic(0.25))]), "error", "limit is +/-50%")
        w = issues([budget(mic(1.3))])
        assert not _errors(w) and _has(w, "warn", "+30%")
        assert not issues([budget(mic(1.1))])                                 # +10%: clean
        small = _gc(snap, "g_search_brand_uk")                                # $66.67/day
        low = issues([dict(budget(9000000), resource_name=small["budget"]["resource_name"])])
        assert _has(low, "error", "below the $10 minimum")
        sets = [s for c in snap["meta"]["campaigns"] for s in c["ad_sets"]]
        rises = [{"ref": "m%d" % i, "platform": "meta", "method": "POST", "path": "/%s" % s["meta_id"],
                  "params": {"daily_budget": int(round(s["daily_budget"] * 145))}} for i, s in enumerate(sets)]
        r = issues(rises)
        assert _has(r, "warn", "total daily budget rises") and not _errors(r)
        # meta: ABO campaign budget, new ad not paused, media status, refs
        core = _mc(snap, "m_prospecting_core")
        assert _has(issues([{"ref": "x", "platform": "meta", "method": "POST", "path": "/%s" % core["meta_id"],
                             "params": {"daily_budget": 100000}}]), "error", "ad set budgets")
        assert _has(issues([{"ref": "x", "platform": "meta", "method": "POST", "path": "/%s/adimages" % acct,
                             "params": {"media_id": "IMG-0003"}}]), "error", "not approved")
        assert _has(issues([{"ref": "x", "platform": "meta", "method": "POST", "path": "/%s/adimages" % acct,
                             "params": {"media_id": "IMG-9999"}}]), "error", "not in the Media library")
        assert _has(issues([{"ref": "x", "platform": "meta", "method": "POST", "path": "/%s/advideos" % acct,
                             "params": {"media_id": "IMG-0002"}}]), "error", "needs a video")
        text, aset = _sample_changeset(snap)
        d, _e = changeset.parse(text)
        d["operations"][5]["params"]["status"] = "ACTIVE"
        assert _has(changeset.validate(d, snap), "error", "must start PAUSED")
        d, _e = changeset.parse(text)
        d["operations"][4]["params"]["object_story_spec"]["link_data"]["image_hash"] = "$ref:op6.hash"
        v = changeset.validate(d, snap)
        assert _has(v, "error", "earlier op")
        # without a media library every media id is unknown
        sys.modules["media"] = None
        try:
            d, _e = changeset.parse(text)
            assert _has(changeset.validate(d, snap), "error", "not in the Media library")
        finally:
            sys.modules.pop("media", None)


def test_dry_run_rows():
    with sandbox():
        snap = snapshot.build()
        text, aset = _sample_changeset(snap)
        doc, errs = changeset.parse(text)
        assert not errs
        issues = changeset.validate(doc, snap)
        assert not _errors(issues), issues
        assert _has(issues, "warn", "-25%")
        out = changeset.dry_run(doc, snap)
        assert set(out) == {"after", "rows", "text_diff", "summary"}
        rows = dict((r["op"], r) for r in out["rows"])
        for r in out["rows"]:
            for k in ("op", "platform", "entity_type", "entity_id", "entity_name", "action", "field",
                      "before", "after", "display_before", "display_after"):
                assert k in r, k
        b = rows["op1"]
        bd = _gc(snap, "g_search_brand_us")["budget"]["daily"]
        new = round(bd * 0.75, 2)
        assert (b["entity_type"], b["action"], b["field"], b["before"], b["after"]) == ("budget", "update", "daily", bd, new)
        assert b["display_before"] == changeset.display("daily", bd) and b["display_after"].endswith("/day")
        assert changeset.display("daily", 200.0) == "$200/day" and changeset.display("daily", 127.5) == "$127.50/day"
        p = rows["op2"]
        assert (p["entity_type"], p["entity_id"], p["before"], p["after"]) == ("campaign", "g_search_nonbrand_uk", "ENABLED", "PAUSED")
        n = rows["op3"]
        assert n["entity_type"] == "negative_keyword" and n["action"] == "create"
        assert n["after"]["text"] == "seo course" and n["after"]["match"] == "PHRASE"
        assert rows["op4"]["entity_type"] == "image" and rows["op5"]["entity_type"] == "creative"
        ad = rows["op6"]
        assert ad["entity_type"] == "ad" and ad["action"] == "create" and ad["after"]["media_id"] == "IMG-0002"
        assert ad["after"]["status"] == "PAUSED" and ad["after"]["ad_set_id"] == aset["id"]
        s = out["summary"]
        assert s["creates"] == 4 and s["updates"] == 2 and s["removes"] == 0
        uk_daily = _gc(snap, "g_search_nonbrand_uk")["budget"]["daily"]
        assert abs(s["daily_budget_delta"]["google"] - ((new - bd) - uk_daily)) < 0.01
        assert s["daily_budget_delta"]["meta"] == 0
        assert ("-      daily: %s" % bd) in out["text_diff"] and ("+      daily: %s" % new) in out["text_diff"]
        assert "seo course" in out["text_diff"] and "Static_Benefits_v2" in out["text_diff"]
        after_ad = [a for a in _mc(out["after"], "m_prospecting_core")["ad_sets"][0]["ads"] if a["name"] == "Static_Benefits_v2"]
        assert after_ad and after_ad[0]["media_id"] == "IMG-0002"
        assert snap["counts"]["ads"] + 1 == out["after"]["counts"]["ads"]
        # input snapshot untouched
        assert _gc(snap, "g_search_brand_us")["budget"]["daily"] == bd


def test_executor_drift_refusal():
    with sandbox():
        base = snapshot.pull()
        text, _aset = _sample_changeset(base)
        doc, _e = changeset.parse(text)
        rows = changeset.dry_run(doc, base)["rows"]
        bd = store.campaign("g_search_brand_us")["daily_budget"]
        store.set_campaign_budget("g_search_brand_us", daily_budget=bd + 10)   # someone edits the account
        n_logs = len([a for a in store.get_state()["activity"] if a["action"] == "api publish"])
        n_ads = len(store.get_state()["ads"])
        res = executor.publish(doc, rows, base["id"])
        assert res["ok"] is False and res["drift"], res
        d = res["drift"][0]
        assert d["op"] == "op1" and d["field"] == "daily" and d["expected_before"] == bd and d["actual"] == bd + 10
        assert res["results"] == [] and res["verified"] is False and res["pre_snapshot_id"]
        assert store.campaign("g_search_nonbrand_uk")["status"] == "ACTIVE"
        assert len(store.get_state()["ads"]) == n_ads
        assert len([a for a in store.get_state()["activity"] if a["action"] == "api publish"]) == n_logs


def test_executor_publish_verified():
    with sandbox() as media:
        base = snapshot.pull()
        text, aset = _sample_changeset(base)
        doc, _e = changeset.parse(text)
        rows = changeset.dry_run(doc, base)["rows"]
        bd = store.campaign("g_search_brand_us")["daily_budget"]
        n_logs = len([a for a in store.get_state()["activity"] if a["action"] == "api publish"])
        res = executor.publish(doc, rows, base["id"])
        assert res["ok"] is True and res["verified"] is True, res
        assert res["mode"] == "sample" and not res["drift"]
        assert res["pre_snapshot_id"] and res["post_snapshot_id"] and res["pre_snapshot_id"] != res["post_snapshot_id"]
        assert [r["status"] for r in res["results"]] == ["applied"] * 6
        r1 = res["results"][0]
        assert r1["request"]["method"] == "POST"
        assert r1["request"]["url"] == "https://googleads.googleapis.com/v22/customers/4445556666/campaignBudgets:mutate"
        assert r1["request"]["body"]["operations"][0]["update"]["amountMicros"] == int(round(bd * 0.75, 2) * 1e6)
        assert r1["request"]["body"]["operations"][0]["updateMask"] == "amountMicros"
        assert r1["response"]["results"][0]["resourceName"].endswith("/campaignBudgets/201")
        assert "hash" in list(res["results"][3]["response"]["images"].values())[0]
        assert res["results"][4]["request"]["url"] == "https://graph.facebook.com/v24.0/act_7778889999/adcreatives"
        img_hash = list(res["results"][3]["response"]["images"].values())[0]["hash"]
        assert res["results"][4]["request"]["body"]["object_story_spec"]["link_data"]["image_hash"] == img_hash
        assert res["results"][5]["request"]["body"]["creative"]["creative_id"] == res["results"][4]["response"]["id"]
        # the rest of the dashboard sees it
        assert store.campaign("g_search_brand_us")["daily_budget"] == round(bd * 0.75, 2)
        assert store.campaign("g_search_nonbrand_uk")["status"] == "PAUSED"
        assert any(n["text"] == "seo course" and n["match"] == "phrase" for n in store.get_state()["negatives"])
        new_ads = [a for a in store.ads_for(aset["id"]) if a["name"] == "Static_Benefits_v2"]
        assert len(new_ads) == 1 and new_ads[0]["status"] == "PAUSED" and new_ads[0]["format"] == "image"
        post = snapshot.get(res["post_snapshot_id"])
        pad = [a for a in _mc(post, "m_prospecting_core")["ad_sets"][0]["ads"] if a["name"] == "Static_Benefits_v2"][0]
        assert pad["media_id"] == "IMG-0002" and pad["meta_id"].isdigit()
        assert ("IMG-0002", "meta", {"image_hash": img_hash}) in media.published
        logs = [a for a in store.get_state()["activity"] if a["action"] == "api publish"][n_logs:]
        assert len(logs) == 6 and all(a["actor"] == "vin" for a in logs)
        # publishing the same reviewed version again is refused before anything is applied
        # (the negative now exists, and the budget/status "before" values moved)
        again = executor.publish(doc, rows, base["id"])
        assert again["ok"] is False and again["results"] == [] and again["error"], again
        doc2, _e = changeset.parse(text)
        doc2["operations"] = doc2["operations"][:2]
        again = executor.publish(doc2, [r for r in rows if r["op"] in ("op1", "op2")], base["id"])
        assert again["ok"] is False and {d["op"] for d in again["drift"]} == {"op1", "op2"}


def test_live_adapters_refuse_and_build_requests():
    from planning.adapters.base import AdapterError  # noqa: F401
    from planning.adapters.live_google import LiveGoogleAdapter
    from planning.adapters.live_meta import LiveMetaAdapter
    with sandbox():
        snap = snapshot.build()
        text, _aset = _sample_changeset(snap)
        doc, _e = changeset.parse(text)
        cfg = adapters.load_config()
        assert cfg["mode"] == "sample"
        pub = adapters.config_public()
        assert pub["google_ads"]["developer_token"] == "EXAM…"
        assert pub["meta"]["access_token"] == "EXAM…" and pub["meta"]["app_secret"] == "EXAM…"
        assert pub["google_ads"]["customer_id"] == "4445556666" and pub["live_allowed"] is False
        live = copy.deepcopy(cfg)
        live["mode"] = "live"
        g, m = LiveGoogleAdapter(live), LiveMetaAdapter(live)
        assert isinstance(adapters.get_adapter("google", live), LiveGoogleAdapter)
        assert isinstance(adapters.get_adapter("meta", cfg), sample.SampleAdapter)
        ctx = {"mode": "live", "config": live, "snapshot": snap, "outputs": {}}
        req = g.build_request(doc["operations"][2], ctx)
        assert req["url"].endswith("/v22/customers/4445556666/campaignCriteria:mutate")
        create = req["body"]["operations"][0]["create"]
        assert create["negative"] is True and create["keyword"] == {"text": "seo course", "matchType": "PHRASE"}
        assert req["headers"]["developer-token"] == "EXAM…" and req["headers"]["login-customer-id"] == "1112223333"
        assert "EXAMPLE" not in str(req["headers"])
        mreq = m.build_request(doc["operations"][3], ctx)
        assert mreq["url"] == "https://graph.facebook.com/v24.0/act_7778889999/adimages"
        assert "bytes" in mreq["body"] and "media_id" not in mreq["body"]
        aset = _mc(snap, "m_prospecting_core")["ad_sets"][0]
        treq = m.build_request({"platform": "meta", "method": "POST", "path": "/" + aset["meta_id"],
                                "params": {"targeting": {"age_min": 27}}}, ctx)
        assert treq["body"]["targeting"]["age_min"] == 27 and treq["body"]["targeting"]["geo_locations"]
        old = os.environ.get("ATLAS_ALLOW_LIVE")
        try:
            for env in (None, "1"):
                if env is None:
                    os.environ.pop("ATLAS_ALLOW_LIVE", None)
                else:
                    os.environ["ATLAS_ALLOW_LIVE"] = env
                for adapter, op in ((g, doc["operations"][0]), (m, doc["operations"][3])):
                    try:
                        adapter.execute(op, ctx)
                        raise AssertionError("live send was not refused")
                    except adapters.LiveRefused as exc:
                        assert ("ATLAS_ALLOW_LIVE" in str(exc)) if env is None else ("EXAMPLE" in str(exc))
            os.environ.pop("ATLAS_ALLOW_LIVE", None)
            assert adapters.live_allowed(cfg)[0] is False
        finally:
            if old is None:
                os.environ.pop("ATLAS_ALLOW_LIVE", None)
            else:
                os.environ["ATLAS_ALLOW_LIVE"] = old


def test_no_llm_imports():
    code = ("import sys\n"
            "import planning.executor, planning.changeset, planning.snapshot, planning.plan_compare\n"
            "import planning.adapters, planning.adapters.base, planning.adapters.sample\n"
            "import planning.adapters.live_google, planning.adapters.live_meta\n"
            "bad = [m for m in ('planning.llm', 'planning.llm_worker', 'planning.prompts', 'anthropic') if m in sys.modules]\n"
            "assert not bad, bad\n"
            "print('clean')\n")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and "clean" in out.stdout, out.stderr
    for name in ("executor.py", "changeset.py", "adapters/__init__.py", "adapters/base.py", "adapters/sample.py",
                 "adapters/live_google.py", "adapters/live_meta.py"):
        with open(os.path.join(ROOT, "planning", name), "r", encoding="utf-8") as fh:
            src = fh.read()
        for line in src.splitlines():
            ln = line.strip()
            if ln.startswith(("import ", "from ")):
                assert not re.search(r"\b(llm|llm_worker|prompts|anthropic)\b", ln), (name, ln)


TESTS = [test_snapshot_pull_shape, test_plan_compare_facts, test_parse_and_validate_catch_bad_ops,
         test_dry_run_rows, test_executor_drift_refusal, test_executor_publish_verified,
         test_live_adapters_refuse_and_build_requests, test_no_llm_imports]


def main():
    failed = 0
    for t in TESTS:
        try:
            t()
            print("PASS %s" % t.__name__)
        except Exception:
            failed += 1
            import traceback
            print("FAIL %s" % t.__name__)
            traceback.print_exc()
    print("%d passed, %d failed" % (len(TESTS) - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
