# Plan & Adapt + Media — build contract (Task 2)

> **Update 2026-11-06:** changesets are now JSON (`{"changeset":…, "operations":[…]}`); legacy YAML versions are still read.
> `planning/api_requests.py` renders every operation as the exact HTTP request (Google Ads REST v26 `…:mutate`,
> Meta Graph v27.0), with redacted headers and a curl copy. The Plan & Adapt UI shows those requests in place of YAML,
> and publish refuses unless re-rendering against fresh state gives byte-identical requests. Direct Campaigns-page
> controls (pause/enable, budget, bid) use the same renderer and guardrails via `planning/direct.py` and
> `POST /api/campaigns/actions`. Where this spec still says "YAML" for changesets, read JSON.

Read SPEC.md and AGENT-CONTRACT.md first: same stack, same Python 3.9 rules, same UI
conventions, same visual style (read static/css/app.css and templates/campaigns.html +
static/js/campaigns.js before writing UI). This file adds two pages and the backend under them.

## The one rule that cannot bend
The LLM never touches an ad account. It reads a state document and writes a proposal.
Publishing is a separate, deterministic code path (`planning/executor.py`) that a human
triggers by hand after reading the diff. `planning/executor.py`, `planning/adapters/*` and
`planning/changeset.py` must NEVER import `planning.llm`, `planning.llm_worker`,
`planning.prompts` or `anthropic` (a test asserts this via sys.modules).

## Flow on the Plan & Adapt page (/planning)
1. **Analyze** button: pull the full current account state (Google + Meta: every campaign,
   setting, bid strategy/target, optimization goal, budget, ad group/ad set, targeting,
   keyword, negative keyword, ad title/headline, status, recent metrics) into a saved
   **state document** (snapshot). Then compare it to the 30-day plan (`data/plan/plan.yaml`
   + the 30-day checklist in state.json) deterministically, then send plan + state + facts to
   Claude Opus 5.5 (effort medium). Output, short bullets only, no play-by-play:
   where the plan stands, what the state shows, recommendations to adapt the plan.
   A loading bar runs for the estimated time and shows it ("Estimated 20 s").
2. **Command Brief** box: Vin writes what he wants done in plain English (and can tag media
   IDs). Submit -> Opus 5.5 medium returns a **changeset** in YAML whose operations are
   shaped exactly like the Google Ads API / Meta Marketing API requests. Server validates it
   and computes a **diff against the current state**. Vin sees the diff first, YAML second.
3. **Revise**: opens a text box; his notes + prior YAML go back through the same process ->
   new version of the same changeset. Repeatable.
4. **Publish (manual)**: deterministic execution of the exact reviewed version. No LLM.
   Re-pulls state first and refuses if any targeted value drifted from the diff's "before".

## Files and owners (never edit another owner's files)
- **orchestrator (done)**: app.py (nav + page routes for `planning`, `media`; routers load
  automatically from api/planning.py and api/media.py), nav icons in app.css,
  data/plan/plan.yaml (the 30-day plan), this file.
- **platform** agent: `planning/__init__.py`, `planning/adapters/{__init__,base,sample,live_google,live_meta}.py`,
  `planning/snapshot.py`, `planning/plan_compare.py`, `planning/changeset.py`,
  `planning/executor.py`, `config/platforms.yaml`, `tests/test_planning_core.py`,
  `data/planning/account_overlay.json` (generated).
- **llm** agent: `planning/llm.py`, `planning/llm_worker.py`, `planning/prompts.py`,
  `planning/jobs.py`, `planning/records.py`, `planning/fixtures/*` (stub outputs),
  `api/planning.py`, `tests/test_planning_api.py`, adds `anthropic` + `PyYAML` to requirements.txt.
- **planning-ui** agent: `templates/planning.html`, `static/js/planning.js`, `static/css/planning.css`
  (link it from the template's `{% block head %}`; do not edit app.css).
- **media** agent: `media/__init__.py` (+ any `media/*.py`), `api/media.py`, `templates/media.html`,
  `static/js/media.js`, `static/css/media.css`, `data/media.json`, `static/media/library/H5-*`
  (HTML5 sample), `tests/test_media.py`. The orchestrator drops the downloaded Search Atlas
  creative into `static/media/library/` with `static/media/library/manifest.json`.

## Shared runtime rules for agents
- Never reseed or overwrite `data/state.json`. Tests that mutate must point
  `store.STATE_PATH` (and any planning/media paths) at a temp copy and call `store.reload_state()`.
- Local test servers: platform none, llm port 4502, planning-ui 4503, media 4504. Never 4500/4501.
  Run from `dashboard/`: `.venv/bin/uvicorn app:app --port 450X`. Kill your server when done.
- Local venv is Python 3.9.6 with PyYAML 6.0.3. `anthropic` may not install on 3.9; the worker
  imports it lazily. Deploy host runs Python 3.12.
- All new persistent files live under `data/planning/` (JSON, atomic writes via `store.write_json_atomic`).

## Platform config: config/platforms.yaml (EXAMPLE credentials only, committed)
```yaml
mode: sample          # sample | live. live also needs env ATLAS_ALLOW_LIVE=1 and real values.
google_ads:
  api_version: "v22"  # set to the current Google Ads API version before going live
  developer_token: "EXAMPLE-DEV-TOKEN-NOT-REAL"
  client_id: "000000000000-example.apps.googleusercontent.com"
  client_secret: "EXAMPLE-CLIENT-SECRET"
  refresh_token: "EXAMPLE-REFRESH-TOKEN"
  login_customer_id: "1112223333"   # MCC
  customer_id: "4445556666"         # Search Atlas ads account (sample)
meta:
  api_version: "v24.0"  # set to the current Graph API version before going live
  app_id: "000000000000000"
  app_secret: "EXAMPLE-APP-SECRET"
  access_token: "EXAMPLE-SYSTEM-USER-TOKEN"
  ad_account_id: "act_7778889999"
  page_id: "123456789012345"
  instagram_actor_id: "17840000000000000"
  required_permissions: [ads_management, ads_read, business_management, pages_read_engagement, pages_manage_ads, pages_show_list]
  media_access: "ad account /adimages and /advideos (upload), page for object_story_spec"
```
`planning.adapters.config_public()` returns this with every secret masked to 4 chars + "…".

## Sample account model
The sample "ad accounts" are store state (data/state.json) plus `data/planning/account_overlay.json`,
which the platform agent generates deterministically on first use and then mutates:
platform-native IDs (Google: `customers/4445556666/campaigns/<n>`, `.../campaignBudgets/<n>`,
`.../adGroups/<n>`, `.../adGroupAds/<adgroup>~<ad>`, `.../campaignCriteria/<campaign>~<n>`,
`.../adGroupCriteria/<adgroup>~<n>`; Meta: numeric strings for campaign/adset/ad), keywords
per Google ad group (derive from plan.yaml ad groups where names match, else from adset name),
RSA headlines/descriptions, Meta ad titles/bodies, optimization goals, bid strategies with
targets, geo/age targeting. Anything synthesized carries `sample_derived: true`.
Store remains the source of truth for statuses, budgets, negatives, ads (so the other pages
reflect a publish). New entities created by publish are written to store (ads, negatives) and
the overlay.

## State document (snapshot) — planning/snapshot.py
```
pull(reason="analyze") -> doc        # saves data/planning/snapshots/<id>.json, returns doc
get(snapshot_id) -> doc              # NotFound if missing (use store.NotFound)
latest() -> doc | None
list_snapshots(limit=20) -> [{id, taken_at, reason, counts}]
to_yaml(doc) -> str                  # the human state document (download)
compact(doc) -> dict                 # trimmed for prompts: no daily rows, metrics as 7d/MTD totals
```
doc shape:
```
{ "id": "SNAP-20261105-142233", "taken_at": ISO, "reason": str, "mode": "sample",
  "as_of": store.today(),
  "google": {"customer_id": "4445556666", "campaigns": [ {
       "id": "g_search_brand_us", "resource_name": "customers/.../campaigns/101", "name", "status": "ENABLED"|"PAUSED",
       "channel": "SEARCH"|"PERFORMANCE_MAX", "bidding": {"strategy": "TARGET_CPA"|"MAXIMIZE_CONVERSIONS"|..., "target_cpa": 280.0|null},
       "budget": {"resource_name": ".../campaignBudgets/201", "daily": 100.0, "amount_micros": 100000000, "shared": bool, "name"},
       "geo": ["US"], "start_date", "metrics": {"spend_7d","trials_7d","cpt_7d","spend_mtd","trials_mtd","cpt_mtd"},
       "negatives": [{"resource_name","text","match": "EXACT"|"PHRASE"|"BROAD"}],
       "ad_groups": [ {"id","resource_name","name","status","cpc_bid": float|null,
            "keywords": [{"resource_name","text","match","status"}],
            "ads": [{"id","resource_name","type": "RESPONSIVE_SEARCH_AD"|..., "status","headlines":[...],"descriptions":[...],"final_url"}] } ],
       "asset_groups": [...]  # PMax only
  } ] },
  "meta": {"ad_account_id": "act_7778889999", "campaigns": [ {
       "id","meta_id","name","status": "ACTIVE"|"PAUSED","objective": "OUTCOME_LEADS"|..., "buying_type": "AUCTION",
       "daily_budget": float|null (CBO), "bid_strategy": "LOWEST_COST_WITHOUT_CAP"|"COST_CAP", "metrics": {...},
       "ad_sets": [ {"id","meta_id","name","status","daily_budget": float|null,"optimization_goal": "OFFSITE_CONVERSIONS",
            "billing_event": "IMPRESSIONS","bid_amount": float|null,
            "targeting": {"geo_locations": {"countries": [...]}, "age_min": int, "age_max": int, "custom_audiences": [...], "advantage_plus": bool},
            "frequency_cap": {...}|null,
            "ads": [{"id","meta_id","name","status","format","title","body","cta","media_id": "IMG-0001"|null}] } ] } ] },
  "totals": {"google": {"daily_budget","spend_mtd"}, "meta": {...}},
  "counts": {"campaigns","ad_groups","ad_sets","ads","keywords","negatives"} }
```
Values use dashboard units (dollars); API units (micros, cents) appear only where the API uses them.

## Plan comparison — planning/plan_compare.py (deterministic)
`load_plan() -> dict` (data/plan/plan.yaml); `compare(plan, snapshot) -> [fact]` where
fact = `{"kind": "budget_gap"|"missing_campaign"|"unplanned_campaign"|"status_mismatch"|"cpa_out_of_band"|"precondition_open"|"checklist_overdue"|"pacing", "platform", "campaign", "planned", "actual", "note"}`.
Budget gaps compare plan monthly budget / days_in_month to the snapshot daily budget (±5% tolerance).

## Changeset YAML — planning/changeset.py
The LLM writes exactly this; `SCHEMA_DOC` (a str constant) documents it for the prompt with one
example per operation.
```yaml
changeset:
  title: "Shift $1,000/day from Brand to NonBrand agency"
  based_on_snapshot: SNAP-20261105-142233
  rationale: ["...", "..."]           # short bullets
operations:
  - ref: op1                           # unique within the changeset
    platform: google
    service: CampaignBudgetService
    method: mutateCampaignBudgets
    operation: update                  # update | create | remove
    resource_name: customers/4445556666/campaignBudgets/201
    fields: {amount_micros: 2000000000}
    update_mask: [amount_micros]
    reason: "plan rule: brand at $3K/month"
  - ref: op2
    platform: meta
    method: POST
    path: /120210000000000101          # Graph API node (ad set id)
    params: {daily_budget: 150000}     # Meta budgets are cents
    reason: "..."
  - ref: op3
    platform: meta
    method: POST
    path: /act_7778889999/adimages
    params: {media_id: IMG-0002}       # executor resolves the file from the Media library
  - ref: op4
    platform: meta
    method: POST
    path: /act_7778889999/adcreatives
    params: {name: ..., object_story_spec: {page_id: "123456789012345", link_data: {image_hash: "$ref:op3.hash", link: ..., message: ..., name: ..., call_to_action: {type: SIGN_UP}}}}
  - ref: op5
    platform: meta
    method: POST
    path: /act_7778889999/ads
    params: {name: ..., adset_id: "120210000000000101", creative: {creative_id: "$ref:op4.id"}, status: PAUSED}
```
Allowlist (validate rejects anything else):
- google CampaignService.mutateCampaigns update: status (ENABLED|PAUSED), bidding target (target_cpa.target_cpa_micros / maximize_conversions.target_cpa_micros)
- google CampaignBudgetService.mutateCampaignBudgets update: amount_micros
- google AdGroupService.mutateAdGroups update: status, cpc_bid_micros
- google AdGroupAdService.mutateAdGroupAds update: status; create: responsive_search_ad (headlines 3-15 ≤30 chars, descriptions 2-4 ≤90 chars, final_urls)
- google AdGroupCriterionService.mutateAdGroupCriteria create: keyword {text, match_type}; update: status; remove
- google CampaignCriterionService.mutateCampaignCriteria create: negative keyword {keyword:{text,match_type}, negative: true}; remove
- google AssetService.mutateAssets create: image_asset from `media_id` (for PMax/Display)
- meta POST /{campaign_id}: status, daily_budget (cents, CBO only)
- meta POST /{adset_id}: status, daily_budget (cents), bid_amount (cents), targeting (age_min, age_max, geo_locations), frequency_control_specs
- meta POST /{ad_id}: status
- meta POST /act_{id}/adimages {media_id}; /act_{id}/advideos {media_id}; /act_{id}/adcreatives; /act_{id}/ads (new ads must start PAUSED)
`media_id` must exist in the Media library with status `approved` or `active` (else error). `$ref:<ref>.<field>` must point to an earlier op.
Guardrails (errors): resource not in snapshot; budget change > +50% or < -50% on one entity in one changeset
(warn above ±20%); any daily budget below $10; total daily budget across both platforms rising more than 10% (warn).

API:
```
SCHEMA_DOC: str
parse(yaml_text) -> (doc|None, [error str])
validate(doc, snapshot) -> [{"op": ref|None, "level": "error"|"warn", "message"}]
dry_run(doc, snapshot) -> {"after": snapshot', "rows": [row], "text_diff": unified diff of to_yaml(before) vs to_yaml(after),
                           "summary": {"creates", "updates", "removes", "daily_budget_delta": {"google": float, "meta": float}}}
row = {"op": ref, "platform", "entity_type": "campaign"|"budget"|"ad_group"|"ad_set"|"ad"|"keyword"|"negative_keyword"|"creative"|"image"|"video"|"asset",
       "entity_id", "entity_name", "action": "update"|"create"|"remove", "field", "before", "after", "display_before", "display_after"}
```

## Executor — planning/executor.py (deterministic, no LLM)
```
publish(doc, expected_rows, base_snapshot_id) -> {
  "ok": bool, "mode": "sample"|"live", "pre_snapshot_id", "post_snapshot_id",
  "drift": [{"op","field","expected_before","actual"}],      # non-empty => nothing applied, ok False
  "results": [{"op","status": "applied"|"failed"|"skipped","request": {method,url,body},"response": {...},"message"}],
  "verified": bool }    # post snapshot matches dry-run "after" for every row
```
Order: re-validate -> fresh snapshot -> drift check -> apply ops in order through the adapter
(stop at first failure, mark the rest skipped) -> post snapshot -> verify. Every applied op
calls `store.log_activity("api publish", <entity>, <detail>, actor="vin")`.
Adapters (`planning/adapters`): `get_adapter(platform)`; base interface `build_request(op, ctx) -> {method,url,headers(masked),body}`,
`execute(op, ctx) -> response dict`. `sample` executes against store + overlay and returns API-shaped
responses (`{"results":[{"resourceName":...}]}` for Google, `{"id": ...}` / `{"images": {...: {"hash": ...}}}` for Meta).
`live_google` / `live_meta` build the real REST requests (googleads.googleapis.com/{v}/customers/{cid}/<resource>:mutate
with developer-token, login-customer-id, OAuth bearer from refresh token; graph.facebook.com/{v}/<path>) and refuse to send
unless mode == live AND env ATLAS_ALLOW_LIVE == "1". The request preview is shown in the UI either way.

## LLM layer — planning/llm.py + planning/llm_worker.py
Model `claude-opus-5-5`, `output_config={"effort": "medium"}`, no `thinking` param (adaptive is on by
default and cannot be disabled), no temperature. Official `anthropic` Python SDK, streaming:
```python
client = anthropic.Anthropic()   # key from env ANTHROPIC_API_KEY
with client.beta.messages.stream(model="claude-opus-5-5", max_tokens=32000,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        output_config={"effort": "medium"}, system=SYSTEM, messages=[...]) as stream:
    msg = stream.get_final_message()
# check msg.stop_reason == "refusal" (and "max_tokens") before reading text
```
If the installed SDK rejects `fallbacks=` as a kwarg, pass it via `extra_body={"fallbacks": "default"}`.
Ask for JSON (put the JSON shape in the prompt; parse the first JSON object; on parse failure retry once).
The worker is a separate process: reads `{"system","messages","max_tokens"}` JSON on stdin, writes
`{"ok","text","stop_reason","usage","model","seconds"}` on stdout. `llm.call()` spawns it:
- env `ATLAS_LLM_MODE=stub` -> return fixtures (deterministic, valid against the sample snapshot); used by tests and local dev.
- else env `ATLAS_LLM_CMD` set -> run that command line (shlex) with stdin JSON. On the Studio it is
  `/Users/owner/owner-vault/secret.sh use ANTHROPIC_API_KEY --export ANTHROPIC_API_KEY -- <venv python> -m planning.llm_worker`
  so the key never sits in the server's environment.
- else if ANTHROPIC_API_KEY in env -> `[sys.executable, "-m", "planning.llm_worker"]`.
- else -> raise a clear "LLM not configured" error (job ends in status error with that message).
Timeout 300 s. Never log prompts' secrets (there are none; config_public is masked).
Cost guards (public URL): one LLM job at a time (409 if busy), max 60 LLM calls per day (config in jobs.py),
directive/revision text max 4,000 chars.

## Jobs + ETA — planning/jobs.py, planning/records.py
Background thread per job. Job: `{"id": "JOB-...", "kind": "analyze"|"draft"|"revise", "status": "queued"|"running"|"done"|"error",
"stage": "Pulling account state"|"Comparing to plan"|"Asking Opus 5.5"|"Validating"|"Computing diff", "started_at", "finished_at",
"eta_seconds", "elapsed_seconds", "result": {"analysis_id"|"changeset_id", "version"}, "error"}`.
ETA = median of the last 5 measured durations of that kind (data/planning/durations.json); defaults
analyze 20 s, draft 30 s, revise 25 s until measured. Records persisted in data/planning/{analyses,changesets,jobs}.json.

## API — api/planning.py (prefix /api/planning)
```
GET  /                         -> {ok, mode, config (masked), latest_snapshot (summary|null), latest_analysis|null,
                                   changesets: [summary], eta: {analyze, draft, revise}, busy: job|null, limits: {max_chars, calls_left_today}}
POST /analyze                  -> {ok, job}                       (409 {ok:false,error} if a job is running)
GET  /jobs/{job_id}            -> {ok, job}
GET  /analyses/latest          -> {ok, analysis|null}
GET  /analyses/{id}            -> {ok, analysis}
     analysis = {id, snapshot_id, created_at, model, effort, duration_s,
                 plan_status: [str], state_summary: [str],
                 recommendations: [{text, priority: "high"|"medium"|"low", platform: "google"|"meta"|"both", campaign_id|null}],
                 facts: [fact]}
GET  /snapshots                -> {ok, snapshots: [summary]}
GET  /snapshots/{id}           -> {ok, snapshot}
GET  /snapshots/{id}/yaml      -> text/yaml attachment (the state document)
POST /changesets               body {directive: str, media_ids: [str]} -> {ok, job}
GET  /changesets               -> {ok, changesets: [summary]}
GET  /changesets/{id}          -> {ok, changeset}
POST /changesets/{id}/revise   body {text: str} -> {ok, job}
POST /changesets/{id}/publish  body {version: int, confirm: true} -> {ok, publish}   (synchronous, executor only)
POST /changesets/{id}/discard  -> {ok, changeset}
changeset = {id: "CS-0001", title, status: "drafting"|"ready"|"invalid"|"published"|"discarded", directive, media_ids,
             created_at, current_version, published: publish_result|null,
             versions: [{n, created_at, snapshot_id, yaml, summary: [str], assumptions: [str], questions: [str],
                         validation: [...], diff: dry_run minus "after", revision_note|null, model, duration_s}]}
summary = {id, title, status, current_version, created_at, ops, errors, warnings}
```
`ready` = current version has zero validation errors. Publish allowed only for `ready`, only the
version number sent, only with `confirm: true`. 400 otherwise.

## Media — media/ + api/media.py (prefix /api/media)
Asset: `{id, kind: "image"|"video"|"html5", status: "requested"|"in_review"|"approved"|"active", title, description,
brief, format (mime), file_url|null, thumb_url|null, width, height, duration_s|null, size_bytes|null,
aspect ("1:1"|"4:5"|"9:16"|"16:9"|"1.91:1"|"300x250"...), platforms: ["meta","google"], placements: [str],
source, source_url, requested_by, due|null, created_at, updated_at, history: [{ts, action, note}],
tags: [campaign_id], platform_refs: {"meta": {"image_hash"|"video_id"}, "google": {"asset_resource"}}}`.
IDs `IMG-0001`, `VID-0001`, `H5-0001` (per-kind counter). Library module API used by planning:
`list_assets(status=None, kind=None)` (status: one, comma-separated or a list), `get_asset(id)` (store.NotFound), `mark_published(id, platform, ref_dict)`.
Lifecycle: requested -> (upload) in_review -> (approve) approved -> (activate) active -> (deactivate) approved;
reject sends in_review back to requested. `approved` and `active` are the usable statuses (`USABLE_STATUSES`):
both can be tagged in Plan & Adapt briefs, referenced by `media_id` and published.
Endpoints: `GET /` (?status=&kind=, status may be `approved,active`) -> {ok, assets, counts}; `GET /{id}`; `POST /requests` {title, description, kind, brief,
due, platforms, placements} -> requested asset; `POST /{id}/upload` multipart `file` (image/png|jpeg|webp|gif, video/mp4|quicktime,
text/html or application/zip; max 50 MB) -> in_review; `POST /{id}/approve`; `POST /{id}/reject` {note} -> requested with note;
`POST /{id}/activate` {note?} approved -> active; `POST /{id}/deactivate` {note?} active -> approved;
`POST /{id}` {title, description, brief, tags} edit. Every mutation `store.log_activity`.
Page /media: a page-level thread switcher (Creative requests / Ready for review / Approved / Active / in use),
each thread showing only its assets; cards with media preview, ID chip (click copies),
title, description, format/size/aspect, tags; "New request" form; approve / send back with note; upload on request cards;
mark active / take out of use on approved and active cards.
