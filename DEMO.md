# Five-minute walkthrough

Terminal in `atlas/build`, `plan.yaml` open in an editor beside it. Delete `out/`
before starting so the files appear live.

**The one thing to emphasise, start and finish:** the validator rules are not
hygiene checks. Each one is a specific thing this account did that cost money,
turned into code that refuses to let it happen again. Rule 6 is $15,090.

---

**0:00 — what it is (30s)**

"One file is the plan — `plan.yaml`. One command turns it into a Google Ads
Editor CSV, a Meta bulk-import CSV and a build sheet for the founder. Python
standard library plus PyYAML. No API keys, no network — it runs on your laptop."

**0:30 — the plan as data (60s)**

Scroll `plan.yaml`. Show `meta_campaigns`: `Prospecting_Core` at $45,000, its one
ad set, the four proven ads with their true CPAs in the comments. Then
`google_campaigns`: three campaigns, each with **its own** daily budget.

"Every number here has a comment pointing at the finding it came from. This is
the only file anyone edits."

**1:30 — run it (45s)**

```
python3 build.py
```

Point at the two lines that matter:

```
deployed $112,000 + reserve $8,000 = $120,000 / $120,000
budget-weighted target CPA $278.77 (band $250-$280)
```

"$278.77 is total budget divided by projected trials, not an average of campaign
CPAs — brand at $155 and PMax at $330 are both right, and an average of those
two is a number that means nothing."

Open `out/build_sheet.txt` — this is the artefact the founder reads. Then the two
CSVs, briefly: one row per entity for Editor, one row per ad for Meta.

**2:15 — the differentiator (105s)**

"Now the part I'd actually keep." Open `validate.py`, scroll the rule comments.

Then break the plan live. In `plan.yaml`, re-add the UK campaign — or simply add
one line to `Search_Brand_US`:

```yaml
    shared_budget: "Google_Main_Shared"
```

```
python3 build.py
```

```
BUILD REFUSED - 1 rule violation(s):
  [X] RULE 2 shared budget: campaign 'Search_Brand_US' references a shared
      budget ('shared_budget: Google_Main_Shared'). F3 cost this account 30.9% of US spend.
No files written.
```

"That shared budget is why a zero-converting UK campaign took 30.9% of US spend
in September. And rule 6 means the UK campaign itself can't come back —
`Search_NonBrand_UK` is $15,090 for 4,944 clicks and zero trials. **The
automation will not let me repeat the mistake that cost this account $15,090.**"

Then the whole suite:

```
python3 test_validator.py
```

"Twelve ways of breaking it, each asserting the right refusal, plus the real plan
passing. 14 of 14."

**4:00 — reuse (45s)**

Live, in `plan.yaml`, do it twice — the contrast is the demo.

First **move** $3,000 from `PMax_US` to `Search_NonBrand_US` and re-run. It
builds, and the weighted CPA moves to $278.36. "A reallocation inside the
platform is fine, and it re-prices the plan for me."

Then **add** $3,000 to `Search_NonBrand_US` without taking it from anywhere:

```
BUILD REFUSED - 2 rule violation(s):
  [X] RULE 1 budget sum: google campaigns total $55,000 but declared_total is $52,000 (difference $3,000).
  [X] RULE 1 account ceiling: campaigns + reserve = $123,000, over the $120,000 monthly budget.
No files written.
```

"That's the tool doing its job. Either I raise `declared_total` and show myself
I'm over $120K, or I take the money from somewhere."

Fix it, re-run, show the build sheet updating. "Next launch is: change the month,
move the budgets, flip the test ad to `proven: true` and promote it into Core,
add anything you killed to the `cut` list. Run it, import, enable."

**4:45 — the honest close (15s)**

"It writes import files, it doesn't call the APIs — a developer token takes weeks
and wouldn't demo today. Creative IDs and the pixel ID are placeholders you paste
in from Ads Manager. The limitations are all listed in the README. What it does
guarantee is that the plan's arithmetic is right and the four things this account
got wrong can't be rebuilt by accident."

---

## If asked

- *"Why not the API?"* — developer-token approval takes weeks, and a live API
  build is nondeterministic in a demo. Choosing the thing that runs over the thing
  that demos better was the call.
- *"Why YAML and not a spreadsheet?"* — comments. Every budget carries its reason
  next to it, and that survives into next quarter.
- *"Why is the test campaign capped at 25%?"* — so an unproven ad's result is a
  number I chose to spend, not a number that blended into four proven ads. That
  is exactly what went wrong when the account's cheapest ad got paused.
- *"What if a rule is wrong?"* — then it gets changed in `validate.py` with a
  comment and a test, in daylight. The retargeting exception is already written
  that way: it lives in `plan.yaml` as `allow_unproven_without_slot`, so using it
  means writing it down.
