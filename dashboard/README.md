# Atlas Ops dashboard

A paid-media operations dashboard for Search Atlas (B2B SaaS, trial signups,
about $120K/month across Google Ads and Meta). It shows spend and pacing,
the 30-day launch calendar, cost per trial against PostHog truth, tests and
lessons, and campaign controls (pause, resume, budgets, negatives).

**Everything here is sample data.** No ad account is connected. The numbers
are generated deterministically by `data/seed.py`, and every button works
against that local state and persists to `data/state.json`.

The build contract for contributors is `SPEC.md`.

## Run

Python 3.9+.

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && python3 -m data.seed && ./run.sh
```

Then open http://localhost:4500. `GET /api/health` returns
`{"ok": true, "today": "2026-11-05", ...}`; interactive API docs are at
`/api/docs`.

## Pages

| Route | Page | What it is for |
|---|---|---|
| `/` | Overview | Four headline KPIs (MTD spend, trials MTD, 7-day cost per trial, pace) and links |
| `/spend` | Spend & pacing | MTD spend against budget by platform and campaign, daily pacing |
| `/calendar` | 30-day calendar | November checklist, content pipeline and test schedule by day |
| `/reporting` | Reporting | Cost per trial and paid conversion by campaign, PostHog vs platform-reported |
| `/management` | Tests & lessons | Tests against their benchmarks, results, lessons log |
| `/campaigns` | Campaigns | Campaigns, ad sets and ads; pause/resume, budgets, search terms, negatives |

Each page is three files: `api/<page>.py` (FastAPI router under
`/api/<page>`), `templates/<page>.html` and `static/js/<page>.js`.

## Reseed

```bash
python3 -m data.seed
```

This overwrites `data/state.json` with the deterministic sample (same output
every run) and clears the activity log and any changes made in the UI. A
running server picks up the new file on its next request; no restart needed.

## Where a real platform adapter plugs in

Today the "platform API" is local sample state: `store.py` reads and writes
`data/state.json`, and `data/seed.py` stands in for the reporting pull. The
seam for a live adapter is the set of store mutation functions:
`set_campaign_status`, `set_campaign_budget`, `set_adset_status`,
`set_ad_status`, `add_negative` (and, for the pipeline, `move_content`). A
real adapter would call the Google Ads API (campaign/ad group/ad status,
campaign budgets, campaign negative criteria) or the Meta Marketing API
(campaign/ad set/ad `status`, `daily_budget`) inside those functions, then
record the platform's response in state and log it as today; the API routes
and pages would not change. Daily rows would come from a scheduled pull of
Google Ads and Meta insights joined to PostHog trial and paid events,
replacing `data/seed.py` while keeping the same `daily` row shape.
