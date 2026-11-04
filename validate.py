"""Guardrails. Each rule traces to a finding in plan-final.md.

The point of this file: the account lost $15,090 to a campaign that produced zero
trials, and 30.9% of US spend to a shared budget. Those were not analysis failures,
they were build failures. So they are blocked at build time, not reviewed later.

validate(plan) returns a list of error strings. build.py refuses to write any CSV
if that list is non-empty.
"""


def _meta_campaign_budget(c):
    return float(c["budget"])


def _weighted_cpa(campaigns, total):
    """Budget-weighted CPA = total spend / total projected trials (harmonic mean).

    A plain average of campaign CPAs is the wrong number: $10k at $150 and $10k at
    $350 does not average to $250 of actual performance, it buys 67+29=96 trials at
    $208. This matches the $278 central case in plan-final.md.
    """
    trials = sum(float(c["budget"]) / float(c["expected_cpa"]) for c in campaigns)
    return total / trials if trials else float("inf")


def validate(plan):
    errors = []
    acct = plan["account"]
    total_budget = float(acct["total_budget"])
    lo, hi = acct["cpa_band"]
    ceiling = float(acct["campaign_cpa_ceiling"])
    reserve = float(acct.get("reserve", 0))

    meta = plan["meta_campaigns"]
    google = plan["google_campaigns"]
    all_campaigns = meta + google

    # --- RULE 1 -------------------------------------------------------------
    # Budgets must sum to the declared per-platform total, and the declared
    # totals plus the reserve must fit the brief's $120K.
    # Finding: the plan is only defensible if the arithmetic is the plan's own.
    # A silent $3K drift is how a "$120K plan" becomes a $127K invoice.
    for key, campaigns in (("meta", meta), ("google", google)):
        p = plan["platforms"][key]
        declared = float(p["declared_total"])
        actual = sum(float(c["budget"]) for c in campaigns)
        if abs(actual - declared) > 0.01:
            errors.append(
                f"RULE 1 budget sum: {key} campaigns total ${actual:,.0f} but "
                f"declared_total is ${declared:,.0f} (difference ${actual - declared:,.0f})."
            )
        if actual > float(p["ceiling"]) + 0.01:
            errors.append(
                f"RULE 1 platform ceiling: {key} total ${actual:,.0f} exceeds "
                f"ceiling ${float(p['ceiling']):,.0f}."
            )
    grand = sum(float(c["budget"]) for c in all_campaigns) + reserve
    if grand > total_budget + 0.01:
        errors.append(
            f"RULE 1 account ceiling: campaigns + reserve = ${grand:,.0f}, "
            f"over the ${total_budget:,.0f} monthly budget."
        )

    # --- RULE 2 -------------------------------------------------------------
    # No shared budget, anywhere.
    # Finding F3: all four Google campaigns sat on `Google_Main_Shared` at
    # $1,800/day. A zero-converting UK campaign joined the pool on 09-15 and cut
    # Search_Brand_US, Search_NonBrand_US and PMax_US by exactly 30.9% each.
    for c in all_campaigns:
        for k in ("shared_budget", "shared_budget_name", "budget_pool"):
            if c.get(k):
                errors.append(
                    f"RULE 2 shared budget: campaign '{c['name']}' references a shared "
                    f"budget ('{k}: {c[k]}'). F3 cost this account 30.9% of US spend."
                )
    # Two campaigns naming the same budget is the same mistake under another name.
    named = [c.get("budget_name") for c in all_campaigns if c.get("budget_name")]
    dupes = {n for n in named if named.count(n) > 1}
    for n in sorted(dupes):
        errors.append(f"RULE 2 shared budget: budget_name '{n}' is used by more than one campaign.")

    # --- RULE 3 -------------------------------------------------------------
    # Every campaign owns a positive budget of its own.
    # Finding F3 again, from the other side: a campaign with no budget of its own
    # is a campaign whose spend some other campaign decides.
    for c in all_campaigns:
        b = c.get("budget")
        if b is None or float(b) <= 0:
            errors.append(f"RULE 3 own budget: campaign '{c['name']}' has no positive budget of its own.")

    # --- RULE 4 -------------------------------------------------------------
    # Budget-weighted target CPA must land inside the brief's $250-$280 band.
    # Finding: the brief's constraint is on the ACCOUNT, not on each campaign.
    # A per-campaign rule would force exceptions on half this plan (brand at $155,
    # PMax at $330) and a rule half the plan bypasses is a log, not a guardrail.
    deployed = sum(float(c["budget"]) for c in all_campaigns)
    wcpa = _weighted_cpa(all_campaigns, deployed)
    if not (lo - 0.5 <= wcpa <= hi + 0.5):
        errors.append(
            f"RULE 4 weighted CPA: budget-weighted target CPA is ${wcpa:,.2f}, "
            f"outside the ${lo}-${hi} band."
        )

    # --- RULE 5 -------------------------------------------------------------
    # No single campaign may target or cap above $350.
    # Finding: rule 4 is an average, and an average can be gamed. $6K of brand at
    # $155 will hide one campaign buying trials at $600. The ceiling stops that.
    for c in all_campaigns:
        for field in ("expected_cpa", "cap", "target_cpa"):
            v = c.get(field)
            if v is not None and float(v) > ceiling:
                errors.append(
                    f"RULE 5 campaign ceiling: '{c['name']}' has {field} ${float(v):,.0f}, "
                    f"above the ${ceiling:,.0f} single-campaign ceiling."
                )

    # --- RULE 6 -------------------------------------------------------------
    # Nothing on the cut list may reappear, under any entity type.
    # Finding F2: Search_NonBrand_UK spent $15,090 across 4,944 clicks for zero
    # conversions. This is the rule the pitch is about: the automation will not let
    # me rebuild it next quarter out of habit.
    cut = {str(x).strip().lower() for x in plan.get("cut", [])}
    names = []
    for c in meta:
        names.append(c["name"])
        names.append(c["ad_set"]["name"])
        names.extend(c.get("ads", []))
        names.extend(c.get("queue", []))
        names.append(c.get("budget_name"))
    for c in google:
        names.append(c["name"])
        names.append(c.get("budget_name"))
        for g in c.get("ad_groups", []):
            names.append(g["name"])
        for g in c.get("asset_groups", []):
            names.append(g["name"])
    for n in [x for x in names if x]:
        if str(n).strip().lower() in cut:
            errors.append(
                f"RULE 6 cut entity: '{n}' is on the cut list and may not be rebuilt "
                f"(F2: $15,090 for zero trials / F3: the shared budget)."
            )

    # --- RULE 7 -------------------------------------------------------------
    # Unproven creative runs one ad at a time, only in a campaign flagged as a
    # test slot, and the test slot stays under 25% of its platform's budget.
    # Finding F6: the account paused its cheapest ad (UGC_Founder_v2, $215 true CPA)
    # for an unproven refresh. Unproven creative gets its own readable budget and
    # never sits next to four proven ads where its result blends away.
    ads = plan["meta_ads"]
    meta_total = sum(float(c["budget"]) for c in meta) or 1.0
    for c in meta:
        unproven = [a for a in c.get("ads", []) if not ads.get(a, {}).get("proven")]
        if not c.get("unproven_slot"):
            # A retargeting control + challengers is the one declared exception:
            # it is flagged per-campaign below rather than silently allowed.
            if unproven and not c.get("allow_unproven_without_slot"):
                errors.append(
                    f"RULE 7 unproven creative: '{c['name']}' is not a test slot but "
                    f"contains unproven ads {unproven}."
                )
        else:
            if len(unproven) > 1:
                errors.append(
                    f"RULE 7 one at a time: test campaign '{c['name']}' has "
                    f"{len(unproven)} unproven ads {unproven}; run one."
                )
            share = float(c["budget"]) / meta_total
            if share > 0.25 + 1e-9:
                errors.append(
                    f"RULE 7 test size: '{c['name']}' is {share:.0%} of Meta budget, "
                    f"above the 25% cap on unproven spend."
                )

    # Also: an ad referenced but not defined is a build error, not a warning.
    for c in meta:
        for a in c.get("ads", []):
            if a not in ads:
                errors.append(f"SCHEMA: campaign '{c['name']}' references undefined ad '{a}'.")

    return errors


def summary(plan):
    """Numbers the validator checked, for the build sheet."""
    all_c = plan["meta_campaigns"] + plan["google_campaigns"]
    deployed = sum(float(c["budget"]) for c in all_c)
    trials = sum(float(c["budget"]) / float(c["expected_cpa"]) for c in all_c)
    return {
        "deployed": deployed,
        "reserve": float(plan["account"].get("reserve", 0)),
        "projected_trials": trials,
        "weighted_cpa": deployed / trials,
    }
