# Atlas Ops Dashboard — build contract

Purpose: a permanent, API-driven paid-media operations dashboard for Search Atlas
(B2B SaaS, trial signups, ~$120K/month across Google Ads and Meta). For this
interview build there is NO access to the ad accounts, so every number is
deterministic sample data generated locally, and the "platform API" is a local
adapter layer with the same shape a real one would have. Every button must work
against that sample state and persist.

Served on port 4500. Public hostname later: atlas.richportmedia.ai.

## Stack (fixed — do not change)
- Python 3.9-compatible (the deploy host runs 3.9.6): no `match`, no `X | Y`
  type unions, no `list[str]` in runtime-evaluated annotations (use `typing`).
- FastAPI + uvicorn + Jinja2. Pinned in `requirements.txt`.
- Frontend: server-rendered Jinja templates + vanilla JS modules. Chart.js 4.4.1
  from cdnjs. No build step, no npm.
- State: `data/state.json`, loaded by `store.py`, mutated through `store`
  functions, written back atomically on every mutation. `data/seed.py`
  regenerates it deterministically (`python3 -m data.seed`).
- All money in USD floats, dates ISO `YYYY-MM-DD`. "Today" for sample data is
  `2026-11-05`; history runs 2026-08-10 → 2026-11-05 (the real assessment
  dataset covers 08-10 → 10-11; sample continues the same campaigns forward and
  adds the new build from 2026-11-01).

## Layout
```
dashboard/
  app.py              FastAPI app, mounts static, registers page routes + API routers
  store.py            load/save/mutate + derived-metric helpers (single source of truth)
  data/seed.py        deterministic sample generator -> data/state.json
  data/state.json     generated; committed so the demo runs with no setup
  api/__init__.py
  api/spend.py        APIRouter prefix /api/spend
  api/calendar.py     APIRouter prefix /api/calendar
  api/reporting.py    APIRouter prefix /api/reporting
  api/management.py   APIRouter prefix /api/management
  api/campaigns.py    APIRouter prefix /api/campaigns
  templates/base.html top nav (6 links), page slot, footer with "sample data" badge
  templates/home.html landing: one-line description per page + 4 headline KPIs
  templates/spend.html, calendar.html, reporting.html, management.html, campaigns.html
  static/css/app.css  design tokens, layout primitives, components (card, table, badge, button, tabs, modal, toast)
  static/js/common.js api() fetch helper, fmt (money, pct, int, date), toast(), chart defaults
  static/js/<page>.js one per page
  requirements.txt, run.sh, README.md
```

Routes (pages): `/` home, `/spend`, `/calendar`, `/reporting`, `/management`,
`/campaigns`. Each page route renders its template with `page` set to the
route name so the nav can highlight it.

## Ownership (parallel agents — never edit another agent's files)
- **scaffold**: app.py, store.py, data/seed.py, data/state.json, templates/base.html,
  templates/home.html, static/css/app.css, static/js/common.js, requirements.txt,
  run.sh, README.md, api/__init__.py, and an empty-but-mounted stub for each
  api/<page>.py and templates/<page>.html (page agents overwrite the stubs).
- **spend / calendar / reporting / management / campaigns**: only
  `api/<page>.py`, `templates/<page>.html`, `static/js/<page>.js`. If a page
  needs a store helper that does not exist, implement it inside its own
  `api/<page>.py` using `store.get_state()` — do not edit store.py.

## Data model (state.json) — scaffold owns this; page agents read it
```
{
  "meta": {"today": "2026-11-05", "generated_at": ..., "monthly_budget": 120000,
           "platform_budgets": {"google": 55000, "meta": 65000},
           "cpa_target": [250, 280]},
  "campaigns": [ {
      "id": "g_search_nonbrand_us", "platform": "google"|"meta",
      "name": "Search_NonBrand_US", "country": "US"|"UK", "type": "Search"|"PMax"|"Prospecting"|"Retargeting"|"Brand",
      "status": "ACTIVE"|"PAUSED", "daily_budget": 953.0, "monthly_budget": 29000,
      "objective": "Trial signup", "bid_strategy": "Target CPA $280",
      "segment": "agency"|"individual"|"brand"|"mixed"
  } ],
  "adsets": [ {"id","campaign_id","name","status","daily_budget","targeting":"...", "kind":"ad set"|"ad group"|"asset group"} ],
  "ads": [ {"id","adset_id","name","status","format":"video"|"image"|"rsa","hook":"...","cta":"...","launched":"date"} ],
  "daily": [ {"date","campaign_id","spend","impressions","clicks",
               "platform_conversions","trials","paid"} ],
       # trials = PostHog-attributed trial signups (truth). paid = trials that became
       # paid memberships (lagged ~7-14 days; recent days are partially filled).
       # platform_conversions = what Google/Meta claim; Meta's deflates after 09-22.
  "search_terms": [ {"campaign_id","term","clicks","cost","trials","recommend_negative":bool,"reason":"..."} ],
  "negatives": [ {"campaign_id","text","match","added":"date","source":"manual"|"recommended"} ],
  "content": [ {"id","name","platform","format","segment","status":
                "running"|"scheduled"|"pending_feedback"|"final_pending_approval"|"approved",
                "owner","due":"date","campaign_id"|null,"test_id"|null,"notes"} ],
  "tests": [ {"id","name","hypothesis","platform","campaign_id","started","ends",
              "status":"running"|"won"|"lost"|"inconclusive"|"queued",
              "metric":"cost_per_trial"|"ctr"|"click_to_trial",
              "benchmark":{"win_below"|"win_above":number,"min_spend":number,"min_trials":number},
              "current":{"spend","trials","value"},"notes"} ],
  "lessons": [ {"date","text","tags":[...],"source"} ],
  "checklist": [ {"day":1..30,"date","items":[{"id","text","done":bool}]} ],
  "activity": [ {"ts","actor":"vin","action","target","detail"} ]   # every mutation appends
}
```
Seed must include the real campaign names from the assessment plus the new
build: Google — Search_Brand_US, Search_NonBrand_US, PMax_US, Search_NonBrand_UK,
Search_Brand_UK (new, small); Meta — Prospecting_Core, Prospecting_Test,
Retargeting_Agency_14d, Retargeting_Individual_14d, Retargeting_Lapsed_15to30d,
plus the legacy Prospecting_AdvantagePlus, Prospecting_Broad, Retargeting_30d
running in parallel at reduced budget (PAUSED from 2026-11-08 in the seed? no —
ACTIVE, reduced). Realistic numbers: CTR ~1.0–1.2% Meta, ~5% nonbrand search,
~18% brand; cost per trial $150–$400 by campaign; UK nonbrand starts converting
on 2026-11-02 once its tag is "fixed" (seed a lesson for that).

## store.py helpers the scaffold must provide (page agents rely on these)
- `get_state()`, `save_state()`, `mutate(fn)`; `log_activity(action, target, detail)`
- `campaign(id)`, `adsets_for(campaign_id)`, `ads_for(adset_id)`
- `daily_for(campaign_id=None, platform=None, start=None, end=None)`
- `window_totals(campaign_id, days)` -> spend, clicks, impressions, trials, paid, cost_per_trial, cost_per_paid, click_to_trial, trial_to_paid
- `rolling_cost_per_trial(campaign_id, days=3)` and `days=7`
- `pacing(platform=None)` -> month_to_date_spend, days_elapsed, days_in_month, daily_rate_7d, projected_month_end, monthly_budget, pace_pct
- `set_campaign_status`, `set_campaign_budget`, `set_adset_status`, `set_ad_status`,
  `add_negative`, `move_content`, `toggle_checklist`, `add_lesson`

## API conventions
- JSON only. Mutations are POST with a JSON body; respond with the updated
  object and `{"ok": true}`. Errors: 404 for unknown id, 400 for bad input.
- Every mutation calls `store.log_activity`.

## UI conventions
- Tokens in `:root` (and dark mode via `prefers-color-scheme`). Palette:
  background near-white, ink near-black, one accent (blue), status colors
  (green win / amber watch / red loss / grey paused). Google rows carry a small
  "G" chip, Meta rows an "M" chip.
- Numbers right-aligned, tabular figures. Money `$1,234`, CPT `$287`, pct `4.9%`.
- Status badge component: `.badge.active/.paused/.won/.lost/.running/.queued`.
- Every destructive-looking action (pause) confirms inline (second click), not with
  `window.confirm`. Toast on every successful mutation.
- Pages must render usable at 1280 wide and not break at 390 wide.
- A visible "SAMPLE DATA" pill in the footer and in the nav on every page.
