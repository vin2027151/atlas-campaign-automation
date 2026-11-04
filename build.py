#!/usr/bin/env python3
"""plan.yaml -> Google Ads Editor CSV + Meta bulk-import CSV + build sheet.

    python3 build.py                 # validate plan.yaml and write to out/
    python3 build.py --plan x.yaml --out dir
    python3 build.py --check         # validate only, write nothing

Stdlib + PyYAML. No credentials, no network.
"""
import argparse
import csv
import os
import sys

import yaml

import validate as guard

# --- Google Ads Editor: one flat sheet, one row per entity. Editor keys rows off
# which columns are populated (Campaign only = campaign row; + Ad Group = ad group
# row; + Keyword = keyword/negative row; + Headline 1 = ad row).
GOOGLE_COLUMNS = [
    "Campaign", "Campaign Type", "Campaign Status", "Campaign Daily Budget",
    "Budget Type", "Bid Strategy Type", "Target CPA", "Maximum CPC",
    "Networks", "Languages", "Location", "Ad Group", "Ad Group Status",
    "Max CPC", "Keyword", "Criterion Type", "Ad Type",
    "Headline 1", "Headline 2", "Headline 3",
    "Description Line 1", "Description Line 2",
    "Long Headline", "Business Name", "Path 1", "Path 2", "Final URL", "Labels",
]

# --- Meta bulk import: one row per ad, campaign and ad set fields repeated.
# These are the column names Ads Manager itself exports, which is what makes the
# file round-trip through Import Ads in Bulk.
META_COLUMNS = [
    "Campaign Name", "Campaign Status", "Campaign Objective", "Buying Type",
    "Campaign Bid Strategy", "Ad Set Name", "Ad Set Status",
    "Ad Set Daily Budget", "Ad Set Bid Strategy", "Bid Amount",
    "Optimization Goal", "Billing Event", "Destination Type",
    "Countries", "Age Min", "Age Max", "Gender", "Audience Notes",
    "Custom Audiences", "Excluded Custom Audiences",
    "Optimized Conversion Tracking Pixels", "Conversion Event",
    "Ad Name", "Ad Status", "Creative Type", "Title", "Body",
    "Link Description", "Call to Action", "Website URL", "Display Link",
    "Link Object ID", "Video ID", "Image Hash", "Labels",
]


def money(x):
    return f"{float(x):.2f}"


def daily(monthly, days):
    return float(monthly) / float(days)


def build_google_rows(plan):
    acct = plan["account"]
    days = acct["days_in_month"]
    url = acct["landing_url"]
    rows = []
    for c in plan["google_campaigns"]:
        base = {k: "" for k in GOOGLE_COLUMNS}
        base["Campaign"] = c["name"]
        rows.append(dict(base, **{
            "Campaign Type": c["type"],
            "Campaign Status": "Paused",          # launched by hand after review
            "Campaign Daily Budget": money(daily(c["budget"], days)),
            "Budget Type": "Daily",               # never Shared (F3)
            "Bid Strategy Type": c["bid_strategy"],
            "Target CPA": money(c["target_cpa"]) if c.get("target_cpa") else "",
            "Maximum CPC": money(c["max_cpc"]) if c.get("max_cpc") else "",
            "Networks": c["networks"],
            "Languages": ";".join(c["languages"]),
            "Location": ";".join(c["locations"]),
            "Labels": f"{acct['month']} rebuild",
        }))
        for g in c.get("ad_groups", []):
            rows.append(dict(base, **{
                "Ad Group": g["name"],
                "Ad Group Status": "Paused",
                "Max CPC": money(c["max_cpc"]) if c.get("max_cpc") else "",
            }))
            for kw in g["keywords"]:
                rows.append(dict(base, **{
                    "Ad Group": g["name"],
                    "Keyword": kw["text"],
                    "Criterion Type": kw["match"],   # Exact / Phrase; no Broad
                }))
            for ad in g["ads"]:
                h = ad["headlines"] + ["", "", ""]
                d = ad["descriptions"] + ["", ""]
                rows.append(dict(base, **{
                    "Ad Group": g["name"],
                    "Ad Type": "Responsive search ad",
                    "Headline 1": h[0], "Headline 2": h[1], "Headline 3": h[2],
                    "Description Line 1": d[0], "Description Line 2": d[1],
                    "Path 1": ad.get("path1", ""), "Path 2": ad.get("path2", ""),
                    "Final URL": url,
                }))
        for g in c.get("asset_groups", []):
            rows.append(dict(base, **{
                "Ad Group": g["name"],              # Editor shows asset groups here
                "Ad Group Status": "Paused",
                "Ad Type": "Performance Max asset group",
                "Headline 1": g["headlines"][0],
                "Headline 2": g["headlines"][1],
                "Headline 3": g["headlines"][2],
                "Description Line 1": g["descriptions"][0],
                "Description Line 2": g["descriptions"][1],
                "Long Headline": g["long_headline"],
                "Business Name": g["business_name"],
                "Final URL": url,
            }))
        for neg in c.get("negatives", []):
            rows.append(dict(base, **{
                "Keyword": neg["text"],
                "Criterion Type": neg["match"],     # campaign-level negative
            }))
    return rows


def build_meta_rows(plan):
    acct = plan["account"]
    days = acct["days_in_month"]
    p = plan["platforms"]["meta"]
    ads = plan["meta_ads"]
    rows = []
    for c in plan["meta_campaigns"]:
        s = c["ad_set"]
        pct = float(c.get("launch_at_pct", 100)) / 100.0
        for name in c["ads"]:
            a = ads[name]
            rows.append({
                "Campaign Name": c["name"],
                "Campaign Status": "PAUSED",
                "Campaign Objective": c["objective"],
                "Buying Type": "AUCTION",
                # Budget sits on the ad set and each campaign has exactly one,
                # so no two campaigns can draw from one pool (F3).
                "Campaign Bid Strategy": "",
                "Ad Set Name": s["name"],
                "Ad Set Status": "PAUSED",
                "Ad Set Daily Budget": money(daily(c["budget"], days) * pct),
                "Ad Set Bid Strategy": s["bid_strategy"],
                "Bid Amount": money(c["cap"]) if s["bid_strategy"] == "COST_CAP" else "",
                "Optimization Goal": s["optimization_goal"],
                "Billing Event": "IMPRESSIONS",
                "Destination Type": "WEBSITE",
                "Countries": ",".join(s["countries"]),
                "Age Min": s["age_min"],
                "Age Max": s["age_max"],
                "Gender": s["gender"],
                "Audience Notes": s["audience"],
                "Custom Audiences": ",".join(s.get("custom_audiences", [])),
                "Excluded Custom Audiences": ",".join(s.get("excluded_audiences", [])),
                "Optimized Conversion Tracking Pixels": p["pixel_id"],
                "Conversion Event": p["conversion_event"],
                "Ad Name": name,
                "Ad Status": "PAUSED",
                "Creative Type": a["creative_type"],
                "Title": a["title"],
                "Body": a["body"],
                "Link Description": a["link_description"],
                "Call to Action": a["cta"],
                "Website URL": acct["landing_url"],
                "Display Link": acct["display_url"],
                "Link Object ID": p["page_id"],
                "Video ID": a["asset_ref"] if a["creative_type"] == "VIDEO" else "",
                "Image Hash": a["asset_ref"] if a["creative_type"] == "IMAGE" else "",
                "Labels": "proven" if a.get("proven") else "unproven",
            })
    return rows


def build_sheet(plan, g_rows, m_rows):
    acct = plan["account"]
    s = guard.summary(plan)
    days = acct["days_in_month"]
    L = []
    w = L.append
    w(f"BUILD SHEET - {acct['name']} - {acct['month']}")
    w("=" * 72)
    w("")
    w(f"Deployed       ${s['deployed']:>10,.0f}")
    w(f"Reserve held   ${s['reserve']:>10,.0f}   (released week 3 to whatever is proven)")
    w(f"Total          ${s['deployed'] + s['reserve']:>10,.0f}   of ${acct['total_budget']:,.0f} approved")
    w(f"Projected trials {s['projected_trials']:>8.0f}")
    w(f"Budget-weighted target CPA  ${s['weighted_cpa']:,.0f}   "
      f"(band ${acct['cpa_band'][0]}-${acct['cpa_band'][1]})")
    w("")
    for key, label, campaigns in (
        ("meta", "META", plan["meta_campaigns"]),
        ("google", "GOOGLE", plan["google_campaigns"]),
    ):
        tot = sum(float(c["budget"]) for c in campaigns)
        w(f"{label}  ${tot:,.0f}/mo  (ceiling ${plan['platforms'][key]['ceiling']:,.0f})")
        w("-" * 72)
        for c in campaigns:
            b = float(c["budget"])
            w(f"  {c['name']:<22} ${b:>7,.0f}/mo  ${daily(b, days):>7,.0f}/day  "
              f"own budget  target CPA ${float(c['expected_cpa']):,.0f}")
            if key == "meta":
                st = c["ad_set"]
                w(f"    ad set: {st['name']}  |  {','.join(st['countries'])} "
                  f"{st['age_min']}-{st['age_max']} {st['gender']}  |  {st['bid_strategy']}")
                w(f"    audience: {st['audience']}")
                w(f"    exclude:  {', '.join(st.get('excluded_audiences', [])) or '-'}")
                if c.get("launch_at_pct", 100) != 100:
                    w(f"    LAUNCHES AT {c['launch_at_pct']}% "
                      f"(${daily(b, days) * c['launch_at_pct'] / 100:,.0f}/day) until the "
                      f"Meta conversion event is verified")
                for a in c["ads"]:
                    flag = "proven" if plan["meta_ads"][a].get("proven") else "UNPROVEN"
                    cpa = plan["meta_ads"][a].get("true_cpa")
                    w(f"    - {a:<34} {flag}" + (f"  true CPA ${cpa}" if cpa else ""))
                for q in c.get("queue", []):
                    w(f"    - {q:<34} queued (not built)")
            else:
                bid = c["bid_strategy"]
                extra = (f" @ ${float(c['target_cpa']):,.0f}" if c.get("target_cpa")
                         else (f", max CPC ${float(c['max_cpc']):.2f}" if c.get("max_cpc") else ""))
                w(f"    bidding: {bid}{extra}  |  {', '.join(c['locations'])}  |  {c['networks']}")
                for g in c.get("ad_groups", []):
                    w(f"    - ad group {g['name']}: {len(g['keywords'])} keywords, "
                      f"{len(g['ads'])} RSA")
                for g in c.get("asset_groups", []):
                    w(f"    - asset group {g['name']}")
                if c.get("negatives"):
                    w(f"    - {len(c['negatives'])} campaign negatives")
            w("")
    w("CUT - blocked from rebuild by validator rule 6")
    w("-" * 72)
    for x in plan.get("cut", []):
        w(f"  x {x}")
    w("")
    w("FILES")
    w("-" * 72)
    w(f"  google_ads_editor.csv   {len(g_rows)} rows")
    w(f"  meta_bulk_import.csv    {len(m_rows)} rows (one per ad)")
    w("")
    w("Everything imports PAUSED. Review in Editor / Ads Manager, then enable.")
    return "\n".join(L) + "\n"


def write_csv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=columns)
        wr.writeheader()
        for r in rows:
            wr.writerow(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "plan.yaml"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"))
    ap.add_argument("--check", action="store_true", help="validate only, write nothing")
    args = ap.parse_args()

    with open(args.plan, encoding="utf-8") as f:
        plan = yaml.safe_load(f)

    rel = lambda q: os.path.relpath(q, os.getcwd()) if q.startswith(os.getcwd()) else q
    print(f"Reading {rel(args.plan)}")
    errors = guard.validate(plan)
    if errors:
        print(f"\nBUILD REFUSED - {len(errors)} rule violation(s):\n")
        for e in errors:
            print(f"  [X] {e}")
        print("\nNo files written.")
        return 1

    s = guard.summary(plan)
    print("Validation passed: 7 rules, 0 violations.")
    print(f"  deployed ${s['deployed']:,.0f} + reserve ${s['reserve']:,.0f} "
          f"= ${s['deployed'] + s['reserve']:,.0f} / ${plan['account']['total_budget']:,.0f}")
    print(f"  budget-weighted target CPA ${s['weighted_cpa']:,.2f} "
          f"(band ${plan['account']['cpa_band'][0]}-${plan['account']['cpa_band'][1]})")
    if args.check:
        print("\n--check: nothing written.")
        return 0

    os.makedirs(args.out, exist_ok=True)
    g_rows = build_google_rows(plan)
    m_rows = build_meta_rows(plan)
    write_csv(os.path.join(args.out, "google_ads_editor.csv"), GOOGLE_COLUMNS, g_rows)
    write_csv(os.path.join(args.out, "meta_bulk_import.csv"), META_COLUMNS, m_rows)
    sheet = build_sheet(plan, g_rows, m_rows)
    with open(os.path.join(args.out, "build_sheet.txt"), "w", encoding="utf-8") as f:
        f.write(sheet)
    print(f"\nWrote to {rel(args.out)}/")
    print(f"  google_ads_editor.csv  {len(g_rows)} rows")
    print(f"  meta_bulk_import.csv   {len(m_rows)} rows")
    print("  build_sheet.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
