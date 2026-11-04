#!/usr/bin/env python3
"""Proves each validator rule fires. Run: python3 test_validator.py

Each case takes the real plan.yaml, breaks exactly one thing the way this account
actually broke it, and asserts the build is refused with the right rule.
"""
import copy
import os
import subprocess
import sys

import yaml

import validate as guard

HERE = os.path.dirname(os.path.abspath(__file__))
PLAN = yaml.safe_load(open(os.path.join(HERE, "plan.yaml"), encoding="utf-8"))


def case(label, mutate, expect):
    p = copy.deepcopy(PLAN)
    mutate(p)
    errs = guard.validate(p)
    hit = [e for e in errs if e.startswith(expect)]
    ok = bool(hit)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    for e in (hit or errs):
        print(f"          -> {e}")
    return ok


def rebuild_uk(p):
    """The $15,090 mistake, rebuilt by habit next quarter."""
    p["google_campaigns"].append({
        "name": "Search_NonBrand_UK", "type": "Search", "budget": 9000,
        "expected_cpa": 280, "bid_strategy": "Target CPA", "target_cpa": 280,
        "networks": "Google search", "locations": ["United Kingdom"],
        "languages": ["English"],
        "ad_groups": [{"name": "UK_Category", "keywords": [
            {"text": "ai agent platform", "match": "Phrase"}], "ads": [{
                "headlines": ["A", "B", "C"], "descriptions": ["D", "E"],
                "path1": "", "path2": ""}]}],
    })
    p["platforms"]["google"]["declared_total"] = 61000


def main():
    print("Validator should REFUSE each of these:\n")
    results = [
        case("budgets no longer sum to the declared platform total",
             lambda p: p["google_campaigns"][1].__setitem__("budget", 32000),
             "RULE 1 budget sum"),
        case("Meta pushed over its $65K platform ceiling",
             lambda p: (p["meta_campaigns"][0].__setitem__("budget", 52000),
                        p["platforms"]["meta"].__setitem__("declared_total", 67000)),
             "RULE 1 platform ceiling"),
        case("a shared budget reintroduced (F3)",
             lambda p: p["google_campaigns"][0].__setitem__("shared_budget", "Google_Main_Shared"),
             "RULE 2 shared budget"),
        case("two campaigns pointed at one budget by name (F3)",
             lambda p: [c.__setitem__("budget_name", "Pool_A") for c in p["google_campaigns"][:2]],
             "RULE 2 shared budget"),
        case("a campaign with no budget of its own",
             lambda p: p["meta_campaigns"][2].__setitem__("budget", 0),
             "RULE 3 own budget"),
        case("budget-weighted target CPA pushed outside $250-$280",
             lambda p: p["google_campaigns"][1].__setitem__("expected_cpa", 349),
             "RULE 4 weighted CPA"),
        case("one campaign targeting above the $350 ceiling",
             lambda p: p["google_campaigns"][2].__setitem__("target_cpa", 500),
             "RULE 5 campaign ceiling"),
        case("the cut UK campaign rebuilt (F2: $15,090, zero trials)",
             rebuild_uk, "RULE 6 cut entity"),
        case("two unproven ads in the one test slot at once",
             lambda p: p["meta_campaigns"][1]["ads"].append("Retargeting_Objection_Handler"),
             "RULE 7 one at a time"),
        case("an ad referenced but never defined",
             lambda p: p["meta_campaigns"][1]["ads"].append("Ad_That_Does_Not_Exist"),
             "SCHEMA"),
        case("an unproven ad dropped in beside the four proven ones (F6)",
             lambda p: p["meta_campaigns"][0]["ads"].append("UGC_Founder_v3"),
             "RULE 7 unproven creative"),
        case("the test campaign grown past 25% of Meta budget",
             lambda p: (p["meta_campaigns"][1].__setitem__("budget", 20000),
                        p["meta_campaigns"][0].__setitem__("budget", 34000)),
             "RULE 7 test size"),
    ]
    print("\nThe real plan should BUILD:")
    clean = guard.validate(copy.deepcopy(PLAN))
    print(f"  {'PASS' if not clean else 'FAIL'}  plan.yaml passes all rules")
    for e in clean:
        print(f"          -> {e}")
    results.append(not clean)

    print("\nEnd to end: build.py refuses a broken plan and writes nothing.")
    bad = copy.deepcopy(PLAN)
    rebuild_uk(bad)
    tmp = os.path.join(HERE, "_bad_plan.yaml")
    out = os.path.join(HERE, "_bad_out")
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(bad, f)
    r = subprocess.run([sys.executable, os.path.join(HERE, "build.py"),
                        "--plan", tmp, "--out", out],
                       capture_output=True, text=True)
    print("  --- build.py output ---")
    for line in r.stdout.strip().splitlines():
        print(f"  {line}")
    ok = r.returncode == 1 and not os.path.exists(out)
    print(f"  {'PASS' if ok else 'FAIL'}  exit code {r.returncode}, no output directory created")
    os.remove(tmp)
    results.append(ok)

    passed = sum(1 for x in results if x)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
