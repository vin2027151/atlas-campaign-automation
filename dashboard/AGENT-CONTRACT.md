# Scaffold contract for page agents (read with SPEC.md)

app.py renders `<page>.html` with context: request, page, title, nav, today, meta, store (module; templates may call store.pacing() etc).
Routers: `api.<page>.router` with prefix "/api/<page>"; GET "/" is at `/api/<page>/`.
Exceptions: raise `store.NotFound` -> 404, `store.BadInput` -> 400 (JSON {"ok": false, "error"}).
base.html blocks: title, head, header (h1 + `subtitle`, `actions` blocks), content, scripts.
Page JS loads as `<script type="module" src="/static/js/<page>.js">` inside `{% block scripts %}`.
Rates are percentage points (4.9 == 4.9%). Zero denominators give None. Mutation helpers log activity already.

## store.py
Exceptions NotFound, BadInput. Constants CAMPAIGN_STATUSES, CONTENT_STATUSES, TEST_STATUSES, NEGATIVE_MATCH_TYPES.
get_state(); reload_state(); save_state(); mutate(fn); log_activity(action, target, detail="", actor="vin"); recent_activity(limit=50)
today(); parse_date(s); iso(d); shift(day, n); date_range(start, end)
campaign(id); campaigns(platform=None); adset(id); ad(id); adsets_for(campaign_id); ads_for(adset_id); content_item(id); test(id)
safe_div(num, den, scale=1.0, digits=2); derive(totals); aggregate(rows)
daily_for(campaign_id=None, platform=None, start=None, end=None)
daily_series(campaign_id=None, platform=None, start=None, end=None)  # one derived row per date, gaps zero-filled
window_totals(campaign_id=None, days=7, platform=None, end=None)     # trailing inclusive window ending today
rolling_cost_per_trial(campaign_id=None, days=3, platform=None, start=None, end=None) -> [{date, spend, trials, cost_per_trial}]
platform_budget(platform=None); pacing(platform=None) -> {month_to_date_spend, days_elapsed, days_in_month, days_remaining, daily_rate_7d, projected_month_end, monthly_budget, pace_pct, budget_to_date, mtd_vs_plan_pct, daily_target}
month_to_date(campaign_id=None, platform=None)
set_campaign_status(id, status); set_campaign_budget(id, daily_budget=None, monthly_budget=None); set_adset_status(id, status); set_ad_status(id, status)
add_negative(campaign_id, text, match="phrase", source="manual"); move_content(content_id, status); toggle_checklist(item_id, done=None); add_lesson(text, tags=None, source="manual", date_=None)
derive() adds: cost_per_trial, cost_per_paid, cpc, cpm, ctr, click_to_trial, trial_to_paid, platform_cost_per_conversion

## common.js (ES module; also window.atlas)
api(path, {method, body, headers})  # body without method => POST; throws Error with .status .data
fmt.money, moneyShort, int, pct, delta, cpt, date({year,dow}), datetime, none
toast(msg, kind in success|error|warn|info); confirmButton(el, onConfirm, {label, timeout}); chartDefaults(); platformChip(p)
badge, cptTone, withBusy, modal, tabs, esc, $, $$, token, seriesColors, platformColors, tick, parseDate, isoDate

## Seed facts
13 campaigns (5 Google incl. Search_Brand_UK new 11-01; 5 new Meta from 11-01; 3 legacy Meta ACTIVE reduced, `legacy: true`). Campaigns carry start_date, legacy.
21 adsets, 52 ads (4 paused). 646 daily rows 08-10..11-05. 26 search terms (8 recommended negatives, field `negated`). 6 negatives. 14 content items across all statuses. 6 tests (2 running, won, lost, inconclusive, queued). 10 lessons (with id). 30 checklist days from 11-01. meta has history_start, new_build_start, sample_data, adapter.
Headline: MTD spend $19,884, 73 trials MTD, 7d CPT $268, pace 97.9%.
Run: `cd dashboard && . .venv/bin/activate && uvicorn app:app --port 4500` (venv exists).
