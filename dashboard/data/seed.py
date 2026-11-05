"""Deterministic sample-data generator for the Atlas Ops dashboard.

Run from the dashboard directory:

    python3 -m data.seed

Writes data/state.json. The random generator is seeded, so every run produces
byte-identical output. All numbers are sample data, not account data.

Story the data tells:
* Legacy campaigns run from 2026-08-10. The new build (five Meta campaigns and
  Search_Brand_UK) starts 2026-11-01; the three legacy Meta campaigns keep
  running in parallel at reduced budget.
* 2026-09-15 to 09-19: a shared budget lets Search_NonBrand_US starve
  Search_Brand_US.
* From 2026-09-22 Meta's reported conversions fall to roughly a third of
  PostHog trials (the event break); trials (truth) are unaffected.
* The UK signup tag never fired until 2026-11-02, so both UK campaigns report
  zero trials before that date.
"""

import json
import math
import os
import random
import tempfile
from datetime import date, timedelta

SEED = 4500
TODAY = date(2026, 11, 5)
HISTORY_START = date(2026, 8, 10)
NEW_BUILD = date(2026, 11, 1)
EVENT_BREAK = date(2026, 9, 22)
STARVE_START, STARVE_END = date(2026, 9, 15), date(2026, 9, 19)
UK_TAG_FIX = date(2026, 11, 2)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
DAYS_IN_NOV = 30

# id, platform, name, country, type, segment, monthly_now, monthly_before_nov,
# start, cpc, ctr%, click_to_trial%, bid_strategy, objective
CAMPAIGNS = [
    ("g_search_brand_us", "google", "Search_Brand_US", "US", "Brand", "brand", 6000, 6000,
     HISTORY_START, 4.40, 18.2, 3.0, "Target impression share 95%", "Trial signup"),
    ("g_search_nonbrand_us", "google", "Search_NonBrand_US", "US", "Search", "mixed", 29000, 29000,
     HISTORY_START, 8.90, 5.0, 3.35, "Target CPA $280", "Trial signup"),
    ("g_pmax_us", "google", "PMax_US", "US", "PMax", "mixed", 12000, 14000,
     HISTORY_START, 2.90, 1.6, 0.97, "Target CPA $300", "Trial signup"),
    ("g_search_nonbrand_uk", "google", "Search_NonBrand_UK", "UK", "Search", "mixed", 6000, 6000,
     HISTORY_START, 6.80, 4.6, 2.0, "Maximize conversions", "Trial signup"),
    ("g_search_brand_uk", "google", "Search_Brand_UK", "UK", "Brand", "brand", 2000, None,
     NEW_BUILD, 2.60, 16.5, 1.6, "Target impression share 90%", "Trial signup"),
    ("m_prospecting_core", "meta", "Prospecting_Core", "US", "Prospecting", "mixed", 22000, None,
     NEW_BUILD, 2.35, 1.12, 0.84, "Lowest cost", "Trial signup"),
    ("m_prospecting_test", "meta", "Prospecting_Test", "US", "Prospecting", "mixed", 8000, None,
     NEW_BUILD, 2.45, 1.05, 0.74, "Lowest cost", "Trial signup"),
    ("m_retargeting_agency_14d", "meta", "Retargeting_Agency_14d", "US", "Retargeting", "agency", 6000, None,
     NEW_BUILD, 3.30, 1.20, 2.0, "Cost cap $220", "Trial signup"),
    ("m_retargeting_individual_14d", "meta", "Retargeting_Individual_14d", "US", "Retargeting", "individual", 5000, None,
     NEW_BUILD, 3.10, 1.18, 1.55, "Cost cap $240", "Trial signup"),
    ("m_retargeting_lapsed_15to30d", "meta", "Retargeting_Lapsed_15to30d", "US", "Retargeting", "mixed", 3000, None,
     NEW_BUILD, 2.90, 1.02, 1.05, "Lowest cost", "Trial signup"),
    ("m_prospecting_advantageplus", "meta", "Prospecting_AdvantagePlus", "US", "Prospecting", "mixed", 9000, 30000,
     HISTORY_START, 2.20, 1.10, 0.82, "Lowest cost", "Trial signup"),
    ("m_prospecting_broad", "meta", "Prospecting_Broad", "US", "Prospecting", "individual", 7000, 22000,
     HISTORY_START, 2.10, 1.00, 0.57, "Lowest cost", "Trial signup"),
    ("m_retargeting_30d", "meta", "Retargeting_30d", "US", "Retargeting", "mixed", 5000, 13000,
     HISTORY_START, 3.00, 1.15, 1.6, "Lowest cost", "Trial signup"),
]

PAID_RATE = {"agency": 0.31, "individual": 0.17, "brand": 0.28, "mixed": 0.22}

ADSETS = {
    "g_search_brand_us": [("Brand_Core", "Exact + phrase: search atlas, searchatlas"),
                          ("Brand_Product", "search atlas otto, search atlas pricing, search atlas review")],
    "g_search_nonbrand_us": [("Category_SEO_Software", "seo software, seo platform, all in one seo tool"),
                             ("Rank_Tracking", "rank tracker, keyword rank checker, serp tracker"),
                             ("Agency_SEO", "seo software for agencies, white label seo, client seo reporting"),
                             ("Competitor_Alternatives", "semrush alternative, ahrefs alternative, moz alternative")],
    "g_pmax_us": [("PMax_Agencies", "Audience signal: agency site visitors + customer list"),
                  ("PMax_InHouse", "Audience signal: in-house marketer interests")],
    "g_search_nonbrand_uk": [("UK_Category_SEO_Software", "seo software uk, seo tools uk"),
                             ("UK_Agency_SEO", "seo agency software uk, white label seo uk")],
    "g_search_brand_uk": [("UK_Brand_Core", "Exact + phrase: search atlas (UK geo)")],
    "m_prospecting_core": [("US_AdvantagePlus_Agency", "Advantage+ audience, agency-owner signal, US 25-60"),
                           ("US_Interest_Marketing_Mgr", "Interests: SEO, content marketing, HubSpot; US 25-55")],
    "m_prospecting_test": [("Test_Hook_Agency_WhiteLabel", "Advantage+ audience, US; hook A"),
                           ("Test_Hook_Individual_DIY", "Advantage+ audience, US; hook B")],
    "m_retargeting_agency_14d": [("RT_Agency_Pages_14d", "Visited /agency or /white-label in last 14 days")],
    "m_retargeting_individual_14d": [("RT_Individual_Pages_14d", "Visited /pricing or /features, not agency pages, last 14 days")],
    "m_retargeting_lapsed_15to30d": [("RT_Lapsed_15to30d", "Site visitors 15-30 days ago, excl. trials")],
    "m_prospecting_advantageplus": [("Legacy_AdvantagePlus_US", "Advantage+ audience, US 18-65+")],
    "m_prospecting_broad": [("Legacy_Broad_US", "Broad US 25-55, no interests")],
    "m_retargeting_30d": [("Legacy_RT_All_30d", "All site visitors 30 days, excl. trials")],
}

META_HOOKS = [
    ("UGC_Agency_Owner", "video", "How a 9-person agency runs 140 client audits a month", "Start free trial"),
    ("UGC_Founder_v2", "video", "I stopped paying for four SEO tools", "Start free trial"),
    ("Static_Benefits_Grid", "image", "Rank tracking, audits, content and backlinks in one login", "Sign up"),
    ("Demo_Screen_Walkthrough", "video", "90 seconds inside the dashboard", "Start free trial"),
    ("Static_WhiteLabel_Report", "image", "Send clients reports with your logo, not ours", "Start free trial"),
    ("UGC_Founder_v3", "video", "The fifth tool I cancelled this year", "Start free trial"),
    ("RT_Testimonial_Agency", "video", "We replaced three tools in our first week", "Finish signup"),
    ("RT_Pricing_Clarity", "image", "What it costs after the trial, all of it", "Finish signup"),
    ("RT_Objection_Migration", "video", "Moving your projects over takes an afternoon", "Finish signup"),
]

RSA_HOOKS = [
    ("RSA_Core", "All-in-one SEO platform | Start a 7-day trial", "Start trial"),
    ("RSA_Agency", "SEO software built for agencies | White-label reports", "Start trial"),
    ("RSA_Price", "Replace 4 SEO tools with one | See pricing", "See pricing"),
    ("RSA_Competitor", "A faster semrush alternative | Try it free", "Start trial"),
]


def poisson(rng, lam):
    """Poisson draw (Knuth for small lambda, normal approximation above 30)."""
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def binomial(rng, n, p):
    return sum(1 for _ in range(n) if rng.random() < p)


def drange(a, b):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def build_campaigns():
    out = []
    for (cid, plat, name, country, typ, seg, m_now, _m_hist, start, _cpc, _ctr, _c2t, bid, obj) in CAMPAIGNS:
        out.append({
            "id": cid, "platform": plat, "name": name, "country": country, "type": typ,
            "status": "ACTIVE", "daily_budget": round(m_now / float(DAYS_IN_NOV), 2),
            "monthly_budget": m_now, "objective": obj, "bid_strategy": bid, "segment": seg,
            "start_date": start.isoformat(),
            "legacy": cid in ("m_prospecting_advantageplus", "m_prospecting_broad", "m_retargeting_30d"),
        })
    return out


def build_adsets_and_ads(rng):
    adsets, ads = [], []
    meta_i = 0
    for (cid, plat, name, _c, typ, _s, m_now, _h, start, _a, _b, _d, _e, _f) in CAMPAIGNS:
        groups = ADSETS[cid]
        kind = "ad set" if plat == "meta" else ("asset group" if typ == "PMax" else "ad group")
        for gi, (gname, targeting) in enumerate(groups):
            asid = "%s__as%d" % (cid, gi + 1)
            adsets.append({
                "id": asid, "campaign_id": cid, "name": gname, "status": "ACTIVE",
                "daily_budget": round(m_now / float(DAYS_IN_NOV) / len(groups), 2) if plat == "meta" else None,
                "targeting": targeting, "kind": kind,
            })
            n_ads = 2 if plat == "google" else 3
            for ai in range(n_ads):
                adid = "%s_ad%d" % (asid, ai + 1)
                launched = (start + timedelta(days=rng.randint(0, 20) if start == HISTORY_START else 0)).isoformat()
                if plat == "google":
                    rname, hook, cta = RSA_HOOKS[(gi + ai) % len(RSA_HOOKS)]
                    fmt = "rsa" if typ != "PMax" else ("video" if ai == 0 else "image")
                else:
                    if typ == "Retargeting":
                        rname, fmt, hook, cta = META_HOOKS[6 + (ai % 3)]
                    else:
                        rname, fmt, hook, cta = META_HOOKS[meta_i % 6]
                        meta_i += 1
                ads.append({
                    "id": adid, "adset_id": asid, "name": "%s_%s" % (rname, gname.split("_")[-1]),
                    "status": "ACTIVE", "format": fmt, "hook": hook, "cta": cta, "launched": launched,
                })
    # A few paused ads so pause/resume has something on both sides.
    for i in (4, 11, 23, 31):
        if i < len(ads):
            ads[i]["status"] = "PAUSED"
    return adsets, ads


def build_daily(rng):
    rows = []
    for (cid, plat, _n, country, typ, seg, m_now, m_hist, start, cpc, ctr, c2t, _b, _o) in CAMPAIGNS:
        for d in drange(start, TODAY):
            monthly = m_now if d >= NEW_BUILD or m_hist is None else m_hist
            base = monthly / 30.4
            weekend = d.weekday() >= 5
            if plat == "google":
                f = rng.uniform(0.90, 1.07) * (0.80 if weekend else 1.03)
            else:
                f = rng.uniform(0.94, 1.06) * (0.96 if weekend else 1.01)
                if d >= NEW_BUILD and m_hist is None:
                    f *= 1.04  # learning-phase overdelivery on the new build
            if cid == "g_search_brand_us" and STARVE_START <= d <= STARVE_END:
                f *= 0.30
            if cid == "g_search_nonbrand_us" and STARVE_START <= d <= STARVE_END:
                f *= 1.07
            spend = round(base * f, 2)
            day_cpc = cpc * rng.uniform(0.9, 1.1)
            clicks = max(1, int(round(spend / day_cpc)))
            impressions = int(round(clicks / (ctr * rng.uniform(0.92, 1.08) / 100.0)))
            rate = c2t * rng.uniform(0.85, 1.15)
            if plat == "meta" and d >= NEW_BUILD and m_hist is not None:
                rate *= 0.93  # legacy audiences overlap with the new build
            trials = poisson(rng, clicks * rate / 100.0)
            if country == "UK" and d < UK_TAG_FIX:
                trials = 0
            if plat == "google":
                pconv = round(trials * rng.uniform(1.05, 1.25), 1)
            elif d < EVENT_BREAK:
                pconv = round(trials * rng.uniform(1.2, 1.45), 1)
            else:
                pconv = round(trials * rng.uniform(0.28, 0.42), 1)
            age = (TODAY - d).days
            fill = 1.0 if age >= 14 else (0.0 if age <= 3 else (age - 3) / 11.0)
            paid = binomial(rng, trials, PAID_RATE[seg] * fill)
            rows.append({
                "date": d.isoformat(), "campaign_id": cid, "spend": spend,
                "impressions": impressions, "clicks": clicks,
                "platform_conversions": pconv, "trials": trials, "paid": paid,
            })
    rows.sort(key=lambda r: (r["date"], r["campaign_id"]))
    return rows


SEARCH_TERMS = [
    # campaign, term, clicks, cpc, trials, negative?, reason
    ("g_search_nonbrand_us", "seo software", 412, 9.4, 15, False, ""),
    ("g_search_nonbrand_us", "best seo software for agencies", 188, 10.1, 9, False, ""),
    ("g_search_nonbrand_us", "rank tracker", 240, 7.2, 6, False, ""),
    ("g_search_nonbrand_us", "semrush alternative", 205, 11.6, 8, False, ""),
    ("g_search_nonbrand_us", "white label seo reports", 96, 9.8, 5, False, ""),
    ("g_search_nonbrand_us", "all in one seo tool", 131, 8.7, 4, False, ""),
    ("g_search_nonbrand_us", "free seo tools", 174, 5.1, 0, True, "Free-intent: 174 clicks, $887, 0 trials"),
    ("g_search_nonbrand_us", "seo jobs remote", 63, 4.4, 0, True, "Job seekers, not buyers"),
    ("g_search_nonbrand_us", "what is seo", 118, 3.9, 0, True, "Informational; 0 trials in 12 weeks"),
    ("g_search_nonbrand_us", "semrush login", 57, 6.2, 0, True, "Navigational to a competitor's login page"),
    ("g_search_nonbrand_us", "seo course certification", 49, 5.6, 0, True, "Education intent"),
    ("g_search_nonbrand_us", "keyword rank checker", 87, 6.9, 2, False, ""),
    ("g_search_nonbrand_us", "ahrefs pricing", 74, 10.4, 2, False, ""),
    ("g_pmax_us", "atlas map", 92, 1.8, 0, True, "Wrong 'atlas': maps and geography"),
    ("g_pmax_us", "search atlas", 160, 2.2, 7, False, "Brand traffic leaking into PMax; consider brand exclusion"),
    ("g_pmax_us", "seo audit tool", 66, 3.4, 1, False, ""),
    ("g_search_brand_us", "search atlas", 980, 4.2, 31, False, ""),
    ("g_search_brand_us", "search atlas pricing", 214, 4.6, 9, False, ""),
    ("g_search_brand_us", "search atlas review", 133, 4.8, 3, False, ""),
    ("g_search_brand_us", "search atlas careers", 41, 3.9, 0, True, "Job seekers on the brand campaign"),
    ("g_search_nonbrand_uk", "seo software uk", 140, 6.9, 2, False, ""),
    ("g_search_nonbrand_uk", "seo tools uk", 118, 6.4, 1, False, ""),
    ("g_search_nonbrand_uk", "seo agency london", 77, 7.8, 0, True, "Looking to hire an agency, not buy software"),
    ("g_search_nonbrand_uk", "white label seo uk", 39, 7.1, 0, False, ""),
    ("g_search_brand_uk", "search atlas", 64, 2.5, 0, False, ""),
    ("g_search_brand_uk", "search atlas uk", 22, 2.7, 0, False, ""),
]

NEGATIVES = [
    ("g_search_nonbrand_us", "jobs", "broad", "2026-08-12"),
    ("g_search_nonbrand_us", "salary", "broad", "2026-08-12"),
    ("g_search_nonbrand_us", "wordpress plugin free", "phrase", "2026-09-03"),
    ("g_search_brand_us", "atlas copco", "phrase", "2026-08-20"),
    ("g_pmax_us", "world atlas", "phrase", "2026-09-10"),
    ("g_search_nonbrand_uk", "jobs", "broad", "2026-08-12"),
]


def build_search_terms(rng):
    out = []
    for (cid, term, clicks, cpc, trials, neg, reason) in SEARCH_TERMS:
        cost = round(clicks * cpc * rng.uniform(0.95, 1.05), 2)
        out.append({"campaign_id": cid, "term": term, "clicks": clicks, "cost": cost, "trials": trials,
                    "recommend_negative": neg, "reason": reason, "negated": False})
    return out


def build_negatives():
    return [{"campaign_id": c, "text": t, "match": m, "added": a, "source": "manual"}
            for (c, t, m, a) in NEGATIVES]


CONTENT = [
    ("UGC_Agency_Owner (cut 2)", "meta", "video", "agency", "running", "Vin", "2026-11-01", "m_prospecting_core", None, "Proven; Core rotation."),
    ("Demo_Screen_Walkthrough", "meta", "video", "mixed", "running", "Vin", "2026-11-01", "m_prospecting_core", None, "Proven; Core rotation."),
    ("Hook A: white-label agency", "meta", "video", "agency", "running", "Creative", "2026-11-01", "m_prospecting_test", "t01", "Test arm A."),
    ("Hook B: individual DIY", "meta", "video", "individual", "running", "Creative", "2026-11-01", "m_prospecting_test", "t01", "Test arm B."),
    ("RSA headline set v3", "google", "rsa", "mixed", "running", "Vin", "2026-11-03", "g_search_nonbrand_us", "t02", "Pinned H1 variant."),
    ("RT_Pricing_Clarity static", "meta", "image", "individual", "scheduled", "Creative", "2026-11-07", "m_retargeting_individual_14d", None, "Goes live Friday."),
    ("UK GBP pricing landing page", "google", "landing page", "mixed", "scheduled", "Web", "2026-11-10", "g_search_nonbrand_uk", "t06", "Needed before t06 starts."),
    ("UGC_Founder_v3", "meta", "video", "mixed", "pending_feedback", "Client", "2026-11-06", None, None, "Sent 11-03; waiting on founder notes."),
    ("Agency case study carousel", "meta", "image", "agency", "pending_feedback", "Client", "2026-11-08", "m_retargeting_agency_14d", None, "Needs the customer's sign-off on the numbers."),
    ("RT_Objection_Migration v2", "meta", "video", "mixed", "pending_feedback", "Creative", "2026-11-09", "m_retargeting_lapsed_15to30d", None, "Voiceover re-record requested."),
    ("PMax asset refresh (Q4)", "google", "image", "mixed", "final_pending_approval", "Client", "2026-11-06", "g_pmax_us", None, "Final files uploaded; awaiting approval."),
    ("Static_WhiteLabel_Report v2", "meta", "image", "agency", "final_pending_approval", "Client", "2026-11-07", "m_prospecting_core", None, "Logo lockup fixed."),
    ("Brand UK RSA set", "google", "rsa", "brand", "approved", "Vin", "2026-10-30", "g_search_brand_uk", None, "Approved 10-30; live 11-01."),
    ("Retargeting 14d split: agency video", "meta", "video", "agency", "approved", "Vin", "2026-10-28", "m_retargeting_agency_14d", "t03", "Winner from t03, rebuilt for the 14d split."),
]


def build_content():
    out = []
    for i, (name, plat, fmt, seg, status, owner, due, cid, tid, notes) in enumerate(CONTENT):
        out.append({"id": "c%02d" % (i + 1), "name": name, "platform": plat, "format": fmt,
                    "segment": seg, "status": status, "owner": owner, "due": due,
                    "campaign_id": cid, "test_id": tid, "notes": notes})
    return out


def _current(daily, cid, start, end, metric):
    rows = [r for r in daily if r["campaign_id"] == cid and start <= r["date"] <= end]
    spend = round(sum(r["spend"] for r in rows), 2)
    trials = sum(r["trials"] for r in rows)
    clicks = sum(r["clicks"] for r in rows)
    imps = sum(r["impressions"] for r in rows)
    if metric == "cost_per_trial":
        value = round(spend / trials, 2) if trials else None
    elif metric == "ctr":
        value = round(clicks / float(imps) * 100, 2) if imps else None
    else:
        value = round(trials / float(clicks) * 100, 2) if clicks else None
    return {"spend": spend, "trials": trials, "value": value}


def build_tests(daily):
    t = TODAY.isoformat()
    tests = [
        {"id": "t01", "name": "Hook A (agency white-label) vs Hook B (individual DIY)",
         "hypothesis": "An agency-outcome hook lowers prospecting cost per trial below $260 because agency trials convert to paid at ~1.8x.",
         "platform": "meta", "campaign_id": "m_prospecting_test", "started": "2026-11-01", "ends": "2026-11-21",
         "status": "running", "metric": "cost_per_trial",
         "benchmark": {"win_below": 260, "min_spend": 4000, "min_trials": 15},
         "current": _current(daily, "m_prospecting_test", "2026-11-01", t, "cost_per_trial"),
         "notes": "Read after both arms clear $2,000 each."},
        {"id": "t02", "name": "RSA headline v3 (pinned price claim)",
         "hypothesis": "Pinning 'Replace 4 SEO tools with one' as H1 lifts non-brand CTR above 5.5%.",
         "platform": "google", "campaign_id": "g_search_nonbrand_us", "started": "2026-11-03", "ends": "2026-11-17",
         "status": "running", "metric": "ctr",
         "benchmark": {"win_above": 5.5, "min_spend": 3000, "min_trials": 10},
         "current": _current(daily, "g_search_nonbrand_us", "2026-11-03", t, "ctr"),
         "notes": "Baseline CTR 5.0% (Aug-Oct)."},
        {"id": "t03", "name": "Retargeting split by segment, 14-day window",
         "hypothesis": "Splitting 30-day retargeting into agency and individual 14-day audiences lowers cost per trial below $220.",
         "platform": "meta", "campaign_id": "m_retargeting_30d", "started": "2026-10-06", "ends": "2026-10-26",
         "status": "won", "metric": "cost_per_trial",
         "benchmark": {"win_below": 220, "min_spend": 4000, "min_trials": 18},
         "current": {"spend": 4620.0, "trials": 24, "value": 192.5},
         "notes": "Won: $192.50 vs $220. Shipped as Retargeting_Agency_14d + Retargeting_Individual_14d on 11-01."},
        {"id": "t04", "name": "Interest stack vs Advantage+ broad",
         "hypothesis": "A hand-built interest stack beats Advantage+ broad on cost per trial (below $260).",
         "platform": "meta", "campaign_id": "m_prospecting_broad", "started": "2026-09-01", "ends": "2026-09-21",
         "status": "lost", "metric": "cost_per_trial",
         "benchmark": {"win_below": 260, "min_spend": 5000, "min_trials": 15},
         "current": {"spend": 6105.0, "trials": 17, "value": 359.12},
         "notes": "Lost: $359 per trial. Interest stack retired; budget moved to Advantage+."},
        {"id": "t05", "name": "PMax with brand exclusion",
         "hypothesis": "Excluding brand terms from PMax keeps click-to-trial above 1.2% without brand cannibalisation.",
         "platform": "google", "campaign_id": "g_pmax_us", "started": "2026-10-01", "ends": "2026-10-21",
         "status": "inconclusive", "metric": "click_to_trial",
         "benchmark": {"win_above": 1.2, "min_spend": 4000, "min_trials": 20},
         "current": {"spend": 4380.0, "trials": 13, "value": 0.86},
         "notes": "Under min_trials (13 of 20). Rerun with a longer window."},
        {"id": "t06", "name": "UK non-brand: GBP pricing landing page",
         "hypothesis": "Showing GBP prices lifts UK click-to-trial above 2.0% now that the tag fires.",
         "platform": "google", "campaign_id": "g_search_nonbrand_uk", "started": "2026-11-10", "ends": "2026-11-30",
         "status": "queued", "metric": "click_to_trial",
         "benchmark": {"win_above": 2.0, "min_spend": 2500, "min_trials": 10},
         "current": {"spend": 0.0, "trials": 0, "value": None},
         "notes": "Blocked on content c07 (landing page)."},
    ]
    return tests


LESSONS = [
    ("2026-08-18", "Brand search CPT ($150) is the cheapest line in the account but the least incremental; cap it, don't grow it.", ["google", "brand", "budget"], "analysis"),
    ("2026-08-29", "Meta CTR sits at 1.0-1.2% across prospecting; creative, not audience, moves it.", ["meta", "creative"], "analysis"),
    ("2026-09-15", "Shared budget starvation: Search_NonBrand_US drained the shared Google budget and Search_Brand_US delivered ~30% of plan 09-15 to 09-19. Every campaign now carries its own budget; no shared budgets.", ["google", "budget", "incident"], "incident"),
    ("2026-09-21", "Interest stacks lost to Advantage+ broad ($359 vs $270 per trial). Stop hand-building interest audiences for prospecting.", ["meta", "test", "audience"], "test t04"),
    ("2026-09-22", "Meta event break: from 09-22 Meta reports ~1/3 of the trials PostHog records. Judge Meta on PostHog trials only; never optimise to platform-reported conversions until the event is repaired.", ["meta", "tracking", "incident"], "incident"),
    ("2026-10-02", "Free-intent and informational queries ('free seo tools', 'what is seo') burned ~$1,300 with zero trials. Review search terms weekly.", ["google", "search terms", "negatives"], "search terms"),
    ("2026-10-21", "PMax brand-exclusion test never reached minimum trials. Set min_trials so a 3-week test can actually clear it.", ["google", "pmax", "test"], "test t05"),
    ("2026-10-26", "Segmented 14-day retargeting beat the 30-day pool ($192 vs $220 target). Agency visitors convert to paid at ~1.8x individuals.", ["meta", "retargeting", "test"], "test t03"),
    ("2026-11-02", "UK tag fix: the UK signup tag had never fired, so Search_NonBrand_UK showed zero trials for 12 weeks. Fixed 11-02; UK trials start appearing the same day. Treat any campaign with spend and zero trials for 7 days as a tracking problem first.", ["google", "uk", "tracking", "incident"], "incident"),
    ("2026-11-04", "New build plus legacy Meta campaigns overlap audiences; legacy click-to-trial dropped ~7% since 11-01. Watch frequency and wind legacy down once Core clears learning.", ["meta", "budget", "audience"], "pacing review"),
]


def build_lessons():
    return [{"id": "l%02d" % (i + 1), "date": d, "text": t, "tags": tags, "source": s}
            for i, (d, t, tags, s) in enumerate(LESSONS)]


MILESTONES = {
    1: ["Launch new Meta build (5 campaigns) and Search_Brand_UK", "Cut legacy Meta budgets to reduced levels",
        "Confirm PostHog trial events for every new campaign"],
    2: ["Verify UK signup tag fires (PostHog + Google)", "Add recommended negatives on Search_NonBrand_US"],
    3: ["Start t02 RSA headline test", "Send UGC_Founder_v3 for client feedback"],
    4: ["First read of new build vs legacy cost per trial"],
    5: ["Approve PMax asset refresh", "Chase founder notes on UGC_Founder_v3"],
    7: ["Weekly report to client", "Launch RT_Pricing_Clarity static"],
    8: ["Decide legacy Meta wind-down step 1"],
    10: ["Start t06 UK GBP pricing test"],
    14: ["Weekly report to client", "Mid-month budget reallocation"],
    15: ["Release reserve if Core cost per trial is under $280"],
    17: ["Read t02 result"],
    21: ["Weekly report to client", "Read t01 result and ship the winner to Core"],
    24: ["Thanksgiving week: lower bids on individual segment"],
    26: ["Black Friday creative live"],
    28: ["Weekly report to client", "Draft December plan"],
    30: ["Month close: final pacing, lessons, December budgets"],
}

ROTATION = [
    "Review search terms: Search_NonBrand_US",
    "Check Meta frequency on retargeting",
    "Compare platform vs PostHog trials (Meta)",
    "Review cost per trial by campaign (3d / 7d)",
    "Check content pipeline: anything overdue",
    "Review search terms: PMax_US and UK",
]


def build_checklist(rng):
    out = []
    for day in range(1, 31):
        d = NEW_BUILD + timedelta(days=day - 1)
        texts = ["Pacing check vs daily target"]
        texts.extend(MILESTONES.get(day, []))
        texts.append(ROTATION[(day - 1) % len(ROTATION)])
        if len(texts) < 3:
            texts.append(ROTATION[day % len(ROTATION)])
        texts = texts[:5]
        items = []
        for i, text in enumerate(texts):
            done = False
            if d < TODAY:
                done = rng.random() < 0.72
            items.append({"id": "d%02d-%d" % (day, i + 1), "text": text, "done": done})
        if d < TODAY and all(it["done"] for it in items):
            items[-1]["done"] = False  # every past day is only partially done
        out.append({"day": day, "date": d.isoformat(), "items": items})
    return out


def build_state():
    rng = random.Random(SEED)
    daily = build_daily(rng)
    adsets, ads = build_adsets_and_ads(rng)
    return {
        "meta": {
            "today": TODAY.isoformat(),
            "generated_at": "2026-11-05T06:00:00Z",
            "monthly_budget": 120000,
            "platform_budgets": {"google": 55000, "meta": 65000},
            "cpa_target": [250, 280],
            "history_start": HISTORY_START.isoformat(),
            "new_build_start": NEW_BUILD.isoformat(),
            "sample_data": True,
            "adapter": "local",
        },
        "campaigns": build_campaigns(),
        "adsets": adsets,
        "ads": ads,
        "daily": daily,
        "search_terms": build_search_terms(rng),
        "negatives": build_negatives(),
        "content": build_content(),
        "tests": build_tests(daily),
        "lessons": build_lessons(),
        "checklist": build_checklist(rng),
        "activity": [],
    }


def write_atomic(path, data):
    fd, tmp = tempfile.mkstemp(prefix=".state-", suffix=".json", dir=os.path.dirname(path))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def main():
    state = build_state()
    write_atomic(OUT, state)
    print("wrote %s: %d campaigns, %d adsets, %d ads, %d daily rows, %d search terms, "
          "%d content, %d tests, %d lessons, %d checklist days" % (
              OUT, len(state["campaigns"]), len(state["adsets"]), len(state["ads"]),
              len(state["daily"]), len(state["search_terms"]), len(state["content"]),
              len(state["tests"]), len(state["lessons"]), len(state["checklist"])))


if __name__ == "__main__":
    main()
