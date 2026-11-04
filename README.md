# Campaign build generator — Task 2

Turns the campaign plan (`plan.yaml`) into ready-to-import files:

- `out/google_ads_editor.csv` — paste/import into Google Ads Editor
- `out/meta_bulk_import.csv` — Meta Ads Manager → Import Ads in Bulk
- `out/build_sheet.txt` — the founder-facing summary of what was built

Everything imports **paused**. The tool builds; a human enables.

The part that matters is the **validator**: seven rules plus a schema check that
refuse to produce any file. Each rule is a lesson from the audit of this account,
written as code with a one-line comment pointing at the finding. The one that
pays for the whole thing is rule 6 — `Search_NonBrand_UK` spent **$15,090 across
4,944 clicks for zero trials**, and the generator will not let it be rebuilt.

## Run it

Python 3.9+ and PyYAML. Nothing else — no API keys, no network.

```
pip install pyyaml
cd atlas/build
python3 build.py
```

Real output, this machine, 2026-11-03:

```
$ python3 build.py
Reading plan.yaml
Validation passed: 7 rules, 0 violations.
  deployed $112,000 + reserve $8,000 = $120,000 / $120,000
  budget-weighted target CPA $278.77 (band $250-$280)

Wrote to out/
  google_ads_editor.csv  32 rows
  meta_bulk_import.csv   8 rows
  build_sheet.txt
```

`python3 build.py --check` validates and writes nothing. `--plan` and `--out`
override the paths.

## The validator refusing a bad plan

Two things broken at once — $3K of budget drift, and a shared budget put back:

```
$ python3 build.py --plan /tmp/bad.yaml
Reading /tmp/bad.yaml

BUILD REFUSED - 3 rule violation(s):

  [X] RULE 1 budget sum: google campaigns total $55,000 but declared_total is $52,000 (difference $3,000).
  [X] RULE 1 account ceiling: campaigns + reserve = $123,000, over the $120,000 monthly budget.
  [X] RULE 2 shared budget: campaign 'Search_Brand_US' references a shared budget ('shared_budget: Google_Main_Shared'). F3 cost this account 30.9% of US spend.

No files written.
exit=1
```

The full suite breaks one thing at a time and asserts the right rule fires:

```
$ python3 test_validator.py
Validator should REFUSE each of these:

  PASS  budgets no longer sum to the declared platform total
          -> RULE 1 budget sum: google campaigns total $55,000 but declared_total is $52,000 (difference $3,000).
  PASS  Meta pushed over its $65K platform ceiling
          -> RULE 1 platform ceiling: meta total $67,000 exceeds ceiling $65,000.
  PASS  a shared budget reintroduced (F3)
          -> RULE 2 shared budget: campaign 'Search_Brand_US' references a shared budget ('shared_budget: Google_Main_Shared'). F3 cost this account 30.9% of US spend.
  PASS  two campaigns pointed at one budget by name (F3)
          -> RULE 2 shared budget: budget_name 'Pool_A' is used by more than one campaign.
  PASS  a campaign with no budget of its own
          -> RULE 3 own budget: campaign 'Retargeting_30d' has no positive budget of its own.
  PASS  budget-weighted target CPA pushed outside $250-$280
          -> RULE 4 weighted CPA: budget-weighted target CPA is $286.22, outside the $250-$280 band.
  PASS  one campaign targeting above the $350 ceiling
          -> RULE 5 campaign ceiling: 'PMax_US' has target_cpa $500, above the $350 single-campaign ceiling.
  PASS  the cut UK campaign rebuilt (F2: $15,090, zero trials)
          -> RULE 6 cut entity: 'Search_NonBrand_UK' is on the cut list and may not be rebuilt (F2: $15,090 for zero trials / F3: the shared budget).
  PASS  two unproven ads in the one test slot at once
          -> RULE 7 one at a time: test campaign 'Prospecting_Test' has 2 unproven ads ['UGC_Founder_v3', 'Retargeting_Objection_Handler']; run one.
  PASS  an ad referenced but never defined
          -> SCHEMA: campaign 'Prospecting_Test' references undefined ad 'Ad_That_Does_Not_Exist'.
  PASS  an unproven ad dropped in beside the four proven ones (F6)
          -> RULE 7 unproven creative: 'Prospecting_Core' is not a test slot but contains unproven ads ['UGC_Founder_v3'].
  PASS  the test campaign grown past 25% of Meta budget
          -> RULE 7 test size: 'Prospecting_Test' is 33% of Meta budget, above the 25% cap on unproven spend.

The real plan should BUILD:
  PASS  plan.yaml passes all rules

End to end: build.py refuses a broken plan and writes nothing.
  --- build.py output ---
  Reading _bad_plan.yaml
  
  BUILD REFUSED - 3 rule violation(s):
  
    [X] RULE 1 platform ceiling: google total $61,000 exceeds ceiling $55,000.
    [X] RULE 1 account ceiling: campaigns + reserve = $129,000, over the $120,000 monthly budget.
    [X] RULE 6 cut entity: 'Search_NonBrand_UK' is on the cut list and may not be rebuilt (F2: $15,090 for zero trials / F3: the shared budget).
  
  No files written.
  PASS  exit code 1, no output directory created

14/14 checks passed
```

## The rules, and the finding behind each

| # | Rule | Finding it comes from |
|---|---|---|
| 1 | Campaign budgets sum to the declared per-platform total; totals + reserve ≤ $120K; neither platform over its ceiling | The brief. A silent $3K drift turns a $120K plan into a $127K invoice |
| 2 | No shared budget, and no two campaigns naming one budget | **F3** — all four Google campaigns sat on `Google_Main_Shared`; a zero-converting UK campaign joined the pool and cut the three US campaigns by exactly 30.9% each |
| 3 | Every campaign carries its own positive budget | F3, from the other side: a campaign without its own budget is one whose spend another campaign decides |
| 4 | Budget-weighted target CPA inside $250–$280 (this plan: **$278.77**) | The brief's constraint is on the **account**, not per campaign. Brand at $155 and PMax at $330 are both correct; a per-campaign rule would force exceptions on half the plan, and a rule half the plan bypasses is a log, not a guardrail |
| 5 | No single campaign targets or caps above $350 | Rule 4 is an average and averages can be gamed — $6K of brand at $155 would hide one campaign buying trials at $600 |
| 6 | Nothing on the `cut` list may reappear as any entity | **F2** — `Search_NonBrand_UK`: $15,090, 4,944 clicks, **zero** conversions. This is the pitch: the tool will not let next quarter rebuild it out of habit |
| 7 | Unproven creative only in a flagged test campaign, one ad at a time, ≤25% of platform budget | **F6** — the account paused its cheapest ad (UGC_Founder_v2, $215 true CPA) for an unproven refresh. Unproven creative gets its own readable budget instead of blending into four proven ads |

Rule 4 is computed as **total budget ÷ projected trials** (a harmonic mean), not
a plain average of campaign CPAs. $10K at $150 and $10K at $350 is not $250 of
performance — it buys 96 trials at $208. The number the generator prints,
**$278.77**, is the same central case as the plan document's $278.

## Reusing it for the next launch

Edit `plan.yaml`. Nothing else. It holds every campaign, ad set / ad group,
targeting, bidding, budget, ad and the ads→campaign mapping, with a comment on
each number saying where it came from.

Next month, typically:

1. Change `account.month` and `days_in_month` (daily budgets are derived, so a
   31-day month re-derives itself).
2. Move budgets. If you move one, the validator makes you move the
   `declared_total` with it — which is the point.
3. Promote the test ad: set `proven: true` on it, add it to `Prospecting_Core`'s
   `ads`, and move the next concept from `queue` into `Prospecting_Test.ads`.
4. Add a cut entity to `cut` when you kill something, so it stays killed.
5. `python3 test_validator.py && python3 build.py`, then import.

## What it does not do

Honest list.

- **No API calls.** It writes import files; a human imports them and presses
  enable. Deliberate: the Google Ads API needs a developer token that takes weeks
  to approve, and the brief required something runnable and demoable today with
  no shareable credentials.
- **Creative assets are referenced, not uploaded.** `VIDEO_ID_*` / `IMAGE_HASH_*`
  are placeholders; the real video IDs and image hashes get pasted into
  `plan.yaml` from Ads Manager before import. Same for `pixel_id` and `page_id`.
- **It does not read the performance data.** The CPAs in `plan.yaml` were derived
  by the separate analysis and typed in by hand. The generator checks the plan's
  arithmetic, not the plan's judgement.
- **No Google Ads Editor / Meta schema validation.** Columns match what those
  tools export, but the only real proof is an import, and Editor will still object
  to things it objects to (asset requirements, policy, URL suffixes). Expect to
  fix a field or two on the first import of a new account.
- **PMax asset groups are headline/description text only** — no images, logos or
  video, which Editor will not take from a CSV anyway.
- **No audience creation.** `Customers_All`, `Site_Visitors_30d`,
  `Video_Viewers_50pct` must already exist in the ad account under those names.
- **One ad set per Meta campaign.** That is the plan's structure, and it is what
  makes "every campaign owns its budget" true by construction. Multiple ad sets
  per campaign would need a budget-location rule the validator does not have.
- **Rule 7's retargeting exception is declared in `plan.yaml`**
  (`allow_unproven_without_slot: true`), not hidden in the validator. Anyone can
  switch it on — but they have to write it down in the plan to do it.

## Files

```
plan.yaml           the plan as data — the only file you edit
build.py            reads, validates, writes the three outputs
validate.py         the seven rules + schema check, each traced to a finding
test_validator.py   breaks the plan 12 ways, asserts the right refusal
out/                generated; safe to delete
```

~500 lines total, no classes, no framework.
