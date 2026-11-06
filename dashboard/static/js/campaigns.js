// Campaigns page: one campaign table with its controls on each row.
// GET /api/campaigns/?window=... drives the pacing summary, the table (with ad
// sets and ads for the expandable rows) and the negative-keyword review.
// Direct controls (pause/enable, daily budget, bid) POST /api/campaigns/actions:
// the server turns each into the exact Google Ads / Meta API request, applies it
// to the account (sample state in data/state.json, so every browser sees it) and
// returns that request, shown in the undo toast. Negatives use their own route.
import { api, fmt, toast, platformChip, badge, cptTone, esc, $, $$ } from "/static/js/common.js";

const WINDOW_KEY = "campaigns.window";
const WINDOWS = ["3d", "7d", "14d", "30d", "mtd"];
const COLS = 10;

const S = {
  window: "7d",
  data: null,
  platform: "all",
  sort: { key: null, dir: 1 },
  open: new Set(),        // expanded campaign ids
  openAdsets: new Set(),  // ad sets showing their ads
  match: {},              // search term key -> chosen match type
  more: { terms: false, negs: false }, // <details> open state survives re-render
  target: null,           // deep-linked campaign id to highlight once
  edit: null,             // open inline editor {kind, id, field}
  pending: new Set(),     // "kind:id" with a request in flight
};

try {
  const saved = localStorage.getItem(WINDOW_KEY) || localStorage.getItem("spend.window");
  if (saved && WINDOWS.includes(saved)) S.window = saved;
} catch (e) { /* storage blocked: default window */ }

const plural = (n, one, many) => `${n} ${n === 1 ? one : (many || one + "s")}`;

// ------------------------------------------------------------------ data
async function load(win = S.window) {
  S.window = win;
  try { localStorage.setItem(WINDOW_KEY, win); } catch (e) { /* ignore */ }
  $$("#win-select [data-window]").forEach((b) => {
    const on = b.dataset.window === win;
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", on ? "true" : "false");
  });
  S.data = await api(`/api/campaigns/?window=${encodeURIComponent(win)}`);
  const w = S.data.window;
  $("#win-label").textContent = `${w.label}: ${fmt.date(w.start)} – ${fmt.date(w.end, { year: true })}`;
  render();
}

async function afterMutation(msg) {
  toast(msg, "success");
  try { await load(); } catch (e) { toast(`Saved, but the page did not refresh: ${e.message}`, "warn"); }
}

function render() {
  renderPace();
  renderCounts();
  renderTable();
  renderNegatives();
}

// ------------------------------------------------------------ pacing summary
function stat(label, value, cls = "") {
  return `<div class="pace-stat"><div class="kpi-label">${esc(label)}</div><div class="stat-value ${cls}">${value}</div></div>`;
}

function paceTone(p) {
  if (p === null || p === undefined) return "tone-idle";
  if (p >= 95 && p <= 102) return "tone-good";
  if (p >= 85 && p <= 105) return "tone-watch";
  return "tone-bad";
}

function renderPace() {
  const d = S.data, s = d.summary, tgt = d.cpa_target;
  const card = (key) => {
    const p = key === "account" ? s.account : s.platforms[key];
    const title = key === "account" ? "Account total" : `${platformChip(key)} ${esc(p.label)}`;
    const sub = key === "account"
      ? `${plural(p.campaigns, "campaign")} · ${p.active} active`
      : `${fmt.pct(p.share_pct)} of spend · ${plural(p.campaigns, "campaign")}`;
    const pct = p.pct_of_target || 0;
    const g = s.platforms.google.share_pct || 0, m = s.platforms.meta.share_pct || 0;
    const split = key === "account"
      ? `<div class="split-bar" role="img" aria-label="Google ${fmt.pct(g)}, Meta ${fmt.pct(m)} of spend"><span class="seg-google" style="width:${g}%"></span><span class="seg-meta" style="width:${m}%"></span></div>`
      : "";
    return `<div class="card pace-card">
      <div class="card-head"><h2 class="card-title">${title}</h2><span class="card-sub">${sub}</span></div>
      <div class="card-body">
        <div class="pace-stats">
          ${stat(`Spend, ${d.window.key}`, fmt.money(p.spend))}
          ${stat("Trials", fmt.int(p.trials))}
          ${stat("Cost / trial", fmt.cpt(p.cost_per_trial), cptTone(p.cost_per_trial, tgt))}
        </div>
        <div class="pace-line" title="Sum of daily budgets on active campaigns vs monthly budget / days in month">
          <span>Active budget <span class="v">${fmt.money(p.active_daily_budget)}</span>/day vs ${fmt.money(p.daily_target)} target</span>
          <span class="v ${pct > 105 || pct < 90 ? "tone-watch" : ""}">${fmt.pct(p.pct_of_target, 0)}</span>
        </div>
        <div class="kpi-bar"><span class="${pct > 100 ? "over" : ""}" style="width:${Math.min(100, pct)}%"></span></div>
        ${split}
      </div>
      <div class="card-foot">
        <span>MTD ${fmt.money(p.month_to_date_spend)} of ${fmt.moneyShort(p.monthly_budget)}</span>
        <span title="MTD ${fmt.money(p.month_to_date_spend)} + ${p.days_remaining} days × ${fmt.money(p.pacing_daily_budget)}/day enabled now">Projected month-end at current daily budgets <span class="${paceTone(p.month_pace_pct)} strong">${fmt.pct(p.month_pace_pct)}</span> (${fmt.moneyShort(p.projected_month_end)})</span>
      </div>
    </div>`;
  };
  $("#cmp-pace").innerHTML = card("google") + card("meta") + card("account");
}

function renderCounts() {
  const n = { all: S.data.campaigns.length, google: 0, meta: 0 };
  S.data.campaigns.forEach((c) => { n[c.platform] += 1; });
  $$("[data-count]").forEach((el) => { el.textContent = n[el.dataset.count]; });
}

// ------------------------------------------------------------------- table
const GROUPS = [
  { key: "google", label: "Google Ads", test: (c) => c.platform === "google" },
  { key: "meta", label: "Meta, new build", test: (c) => c.platform === "meta" && !c.legacy },
  { key: "legacy", label: "Meta legacy, running in parallel at reduced budget", test: (c) => c.platform === "meta" && c.legacy, legacy: true },
];

function compare(key, dir) {
  return (a, b) => {
    const x = a[key], y = b[key];
    const xn = x === null || x === undefined, yn = y === null || y === undefined;
    if (xn && yn) return 0;
    if (xn) return 1; // nulls last regardless of direction
    if (yn) return -1;
    if (typeof x === "string") return x.localeCompare(y) * dir;
    return (x - y) * dir;
  };
}

function sumRows(rows) {
  const t = { spend: 0, trials: 0, daily_budget: 0, spend_3d: 0, trials_3d: 0, spend_7d: 0, trials_7d: 0 };
  rows.forEach((r) => {
    t.spend += r.spend; t.trials += r.trials;
    t.spend_3d += r.spend_3d; t.trials_3d += r.trials_3d;
    t.spend_7d += r.spend_7d; t.trials_7d += r.trials_7d;
    if (r.status === "ACTIVE") t.daily_budget += r.daily_budget;
  });
  t.cpt_3d = t.trials_3d ? t.spend_3d / t.trials_3d : null;
  t.cpt_7d = t.trials_7d ? t.spend_7d / t.trials_7d : null;
  return t;
}

function statusBtn(kind, id, status, name) {
  const paused = status === "PAUSED";
  const label = paused ? "Enable" : "Pause";
  const busy = S.pending.has(`${kind}:${id}`);
  return `<button class="btn btn-sm${paused ? " btn-primary" : ""}" type="button" data-status-btn data-kind="${kind}" data-id="${esc(id)}"
    data-next="${paused ? "ACTIVE" : "PAUSED"}" data-name="${esc(name)}" ${busy ? "disabled" : ""}
    aria-label="${label} ${esc(name)}">${label}</button>`;
}

// ------------------------------------------------------- budget / bid cells
const BID_SHORT = { "Target CPA": "tCPA", "Target CPA (max. conversions)": "tCPA", "Max CPC": "Max CPC", "Cost cap": "Cost cap", "Bid cap": "Bid cap" };

function stepFor(v) {
  const n = Math.abs(Number(v) || 0);
  if (n >= 20) return Math.max(1, Math.round(n * 0.05));
  return 0.5;
}

function editorHtml(kind, id, field, ctl, name) {
  const v = ctl.value === null || ctl.value === undefined ? "" : ctl.value;
  const what = field === "budget" ? "daily budget" : (ctl.label || "bid");
  return `<span class="ctl-editor" data-editor data-kind="${kind}" data-id="${esc(id)}" data-field="${field}" data-name="${esc(name)}" data-current="${esc(v)}">
    <button class="btn btn-sm ctl-step" type="button" data-step="-1" aria-label="Lower ${esc(what)}">&minus;</button>
    <input class="input ctl-input" type="number" inputmode="decimal" min="0.01" step="0.01" value="${esc(v)}" aria-label="${esc(what)} for ${esc(name)}">
    <button class="btn btn-sm ctl-step" type="button" data-step="1" aria-label="Raise ${esc(what)}">+</button>
    <button class="btn btn-sm btn-primary" type="button" data-save>Save</button>
    <button class="btn btn-sm btn-ghost" type="button" data-cancel aria-label="Cancel">&times;</button>
  </span>`;
}

function isEditing(kind, id, field) {
  return !!S.edit && S.edit.kind === kind && S.edit.id === id && S.edit.field === field;
}

function budgetCell(kind, item, name) {
  const ctl = (item.controls || {}).budget;
  if (!ctl) {
    if (kind === "campaign") return fmt.money(item.daily_budget);
    return item.daily_budget ? fmt.money(item.daily_budget) : '<span class="muted" title="Uses the campaign budget">campaign</span>';
  }
  if (isEditing(kind, item.id, "budget")) return editorHtml(kind, item.id, "budget", ctl, name);
  const note = ctl.level === "ad_sets" ? " (sets the ad set budgets)" : "";
  return `<button class="ctl-btn" type="button" data-edit="budget" data-kind="${kind}" data-id="${esc(item.id)}" ${ctl.editable ? "" : "disabled"}
    title="${esc(ctl.note || "Click to raise or lower the daily budget")}" aria-label="Edit daily budget for ${esc(name)}${note}, now ${fmt.money(ctl.value)}">${fmt.money(ctl.value)}</button>`;
}

function bidCell(kind, item, name) {
  const ctl = (item.controls || {}).bid;
  if (!ctl) return `<span class="muted">${fmt.none}</span>`;
  if (!ctl.editable) return `<span class="muted small ctl-fixed" title="${esc(ctl.note || "")}">${esc(ctl.label || fmt.none)}</span>`;
  if (isEditing(kind, item.id, "bid")) return editorHtml(kind, item.id, "bid", ctl, name);
  const short = BID_SHORT[ctl.label] || ctl.label;
  const val = ctl.value === null || ctl.value === undefined ? (ctl.level === "ad_sets" ? "mixed" : "not set") : fmt.money(ctl.value);
  return `<button class="ctl-btn" type="button" data-edit="bid" data-kind="${kind}" data-id="${esc(item.id)}"
    title="${esc(ctl.label)}${ctl.note ? ": " + esc(ctl.note) : ""}. Click to raise or lower it." aria-label="Edit ${esc(ctl.label)} for ${esc(name)}, now ${esc(val)}"><span class="ctl-label">${esc(short)}</span> ${esc(val)}</button>`;
}

function caveat(trials, days) {
  if (trials >= 3) return "";
  return `<div class="caveat">${trials === 0 ? `0 trials in ${days}d` : `n=${trials}: thin read`}</div>`;
}

function paceSub(c) {
  if (c.pace_pct === null || c.pace_pct === undefined) return "";
  const off = c.status === "ACTIVE" && (c.pace_pct < 80 || c.pace_pct > 115);
  return `<div class="sub ${off ? "tone-watch" : ""}" title="${fmt.money(c.spend_per_day)} per live day across ${plural(c.active_days, "live day")} vs ${fmt.money(c.daily_budget)} budget">${fmt.money(c.spend_per_day)}/day · ${fmt.pct(c.pace_pct, 0)}</div>`;
}

function campaignRow(c, tgt, newStart) {
  const open = S.open.has(c.id);
  const paused = c.status !== "ACTIVE";
  const live = c.start_date && c.start_date > newStart ? ` · live ${fmt.date(c.start_date)}` : "";
  return `<tr class="camp-row${c.legacy ? " legacy" : ""}${open ? " is-open" : ""}${paused ? " is-paused" : ""}${S.target === c.id ? " is-target" : ""}" id="row-${esc(c.id)}" data-cid="${esc(c.id)}">
    <td><button class="caret-btn" type="button" data-expand="${esc(c.id)}" aria-expanded="${open}" aria-label="${open ? "Collapse" : "Expand"} ${esc(c.name)}"><span class="caret" aria-hidden="true">&#9656;</span></button>${platformChip(c.platform)}</td>
    <td class="name"><span class="strong">${esc(c.name)}</span>${c.legacy ? '<span class="tag legacy-tag">legacy</span>' : ""}
      <div class="small muted cmp-meta">${esc(c.country)} · ${esc(c.type)} · ${esc(c.bid_strategy || "")}${live}</div></td>
    <td>${badge(c.status)}</td>
    <td class="num">${budgetCell("campaign", c, c.name)}</td>
    <td class="num">${bidCell("campaign", c, c.name)}</td>
    <td class="num">${fmt.money(c.spend)}${paceSub(c)}</td>
    <td class="num">${fmt.int(c.trials)}</td>
    <td class="num monitor ${cptTone(c.cpt_3d, tgt)}" title="${fmt.money(c.spend_3d)} / ${c.trials_3d} trials, last 3 days">${fmt.cpt(c.cpt_3d)}${caveat(c.trials_3d, 3)}</td>
    <td class="num ${cptTone(c.cpt_7d, tgt)}" title="${fmt.money(c.spend_7d)} / ${c.trials_7d} trials, last 7 days">${fmt.cpt(c.cpt_7d)}${caveat(c.trials_7d, 7)}</td>
    <td class="actions">${statusBtn("campaign", c.id, c.status, c.name)}</td>
  </tr>${open ? `<tr class="panel-row"><td colspan="${COLS}">${panelHtml(c)}</td></tr>` : ""}`;
}

function renderTable() {
  const d = S.data, tgt = d.cpa_target;
  const { key, dir } = S.sort;
  $$("#cmp-table thead th.sortable").forEach((th) => {
    if (th.dataset.key === key) th.setAttribute("aria-sort", dir > 0 ? "ascending" : "descending");
    else th.removeAttribute("aria-sort");
  });
  const wk = d.window.key === "mtd" ? "MTD" : d.window.key;
  $("#th-spend").textContent = `Spend ${wk}`;
  $("#th-trials").textContent = `Trials ${wk}`;
  const newStart = d.window.start;
  let html = "";
  GROUPS.forEach((g) => {
    let rows = d.campaigns.filter(g.test);
    if (S.platform !== "all") rows = rows.filter((c) => c.platform === S.platform);
    if (!rows.length) return;
    if (key) rows = rows.slice().sort(compare(key, dir));
    const t = sumRows(rows);
    html += `<tr class="group-row${g.legacy ? " legacy" : ""}">
      <td colspan="3">${g.legacy ? "&#9888; " : ""}${esc(g.label)} · ${plural(rows.length, "campaign")}</td>
      <td class="num" title="Active campaigns only">${fmt.money(t.daily_budget)}</td>
      <td></td>
      <td class="num">${fmt.money(t.spend)}</td>
      <td class="num">${fmt.int(t.trials)}</td>
      <td class="num ${cptTone(t.cpt_3d, tgt)}">${fmt.cpt(t.cpt_3d)}</td>
      <td class="num ${cptTone(t.cpt_7d, tgt)}">${fmt.cpt(t.cpt_7d)}</td>
      <td></td></tr>`;
    html += rows.map((c) => campaignRow(c, tgt, newStart)).join("");
  });
  const body = $("#cmp-body");
  // keep a half-typed value in an open editor across re-renders (background reloads)
  const liveInput = body.querySelector("[data-editor] .ctl-input");
  const keep = liveInput ? { value: liveInput.value, focused: document.activeElement === liveInput } : null;
  body.innerHTML = html || `<tr><td colspan="${COLS}" class="table-empty">No campaigns.</td></tr>`;
  const nextInput = body.querySelector("[data-editor] .ctl-input");
  if (keep && nextInput) {
    nextInput.value = keep.value;
    nextInput.dataset.focused = "1";
    if (keep.focused) nextInput.focus();
  }
  focusEditor();
  $("#cmp-foot").textContent = `${d.notes.monitor} Spend sub-line: average spend per live day and its share of today's daily budget (amber below 80% or above 115%). Cost per trial = spend ÷ PostHog trials, target ${fmt.money(tgt[0])}–${fmt.money(tgt[1])}. Daily spend and rolling cost-per-trial charts are on Reporting.`;
}

// ------------------------------------------------------------ expanded row
function ratioHtml(c) {
  const band = S.data.ratio_band;
  const pct = c.platform_vs_posthog_pct;
  if (pct === null || pct === undefined) return c.ratio_flag === "over" ? `<span class="ratio-flag">no trials</span>` : fmt.none;
  const flag = c.ratio_flag
    ? `<span class="ratio-flag ${c.ratio_flag}" title="Outside ${band[0]}–${band[1]}% of PostHog trials">${c.ratio_flag === "under" ? "&darr; low" : "&uarr; high"}</span>` : "";
  return `${fmt.pct(pct, 0)}${flag}`;
}

function panelHtml(c) {
  const d = S.data, tgt = d.cpa_target;
  const unit = c.platform === "meta" ? "ad set" : (c.adsets[0] && c.adsets[0].kind) || "ad group";
  const neg = c.recommended_negatives
    ? `<button class="btn btn-sm" type="button" data-goto-neg="${esc(c.id)}">${plural(c.recommended_negatives, "negative")} to review &darr;</button>` : "";
  const stats = `<div class="panel-stats">
    <span>Clicks <span class="v">${fmt.int(c.clicks)}</span> · CTR <span class="v">${fmt.pct(c.ctr, 2)}</span></span>
    <span title="Trial to paid ${fmt.pct(c.trial_to_paid)}. Recent cohorts are still maturing.">Paid <span class="v">${fmt.int(c.paid)}</span> · cost / paid <span class="v">${fmt.cpt(c.cost_per_paid)}</span></span>
    <span title="Platform-reported conversions vs PostHog trials, this window">Platform conv. <span class="v">${fmt.int(c.platform_conversions)}</span> · ${ratioHtml(c)} of PostHog</span>
    <span>Monthly budget <span class="v">${fmt.money(c.monthly_budget)}</span></span>
    ${neg}
  </div>`;
  if (!c.adsets.length) return `<div class="panel">${stats}<div class="empty">No ${esc(unit)}s under this campaign.</div></div>`;
  const basis = c.adsets[0].allocation === "budget_share" ? "ad set budget" : "even share (no budgets of their own)";
  const tip = `Apportioned: campaign ${d.window.label.toLowerCase()} totals split by ${basis}. Sample data has no ad-set-level daily rows.`;
  const rows = c.adsets.map((a) => {
    const open = S.openAdsets.has(a.id);
    const ads = !open ? "" : (a.ads.map((ad) => {
      const m = ad.metrics || {};
      const atip = `${ad.metrics_basis || "sample split"}: ${fmt.int(m.impressions)} impressions, CTR ${fmt.pct(m.ctr, 2)}, ${fmt.int(m.platform_conversions)} platform conv.`;
      return `<tr class="ad-row indent-1${ad.status === "PAUSED" ? " is-paused" : ""}">
        <td class="hook"><span class="strong">${esc(ad.name)}</span> <span class="tag">${esc(ad.format)}</span>
          <div class="small muted">${esc(ad.hook)} · CTA ${esc(ad.cta)} · launched ${fmt.date(ad.launched)}</div></td>
        <td>${badge(ad.status)}</td>
        <td class="num"><span class="muted">${fmt.none}</span></td>
        <td class="num"><span class="muted">${fmt.none}</span></td>
        <td class="num"><span class="apportioned" title="${esc(atip)}">${fmt.money(m.spend)}</span></td>
        <td class="num"><span class="apportioned" title="${esc(atip)}">${fmt.int(m.clicks)}</span></td>
        <td class="num"><span class="apportioned" title="${esc(atip)}">${m.trials == null ? fmt.none : Number(m.trials).toFixed(1)}</span></td>
        <td class="num ${cptTone(m.cost_per_trial, tgt)}"><span class="apportioned" title="${esc(atip)}">${fmt.cpt(m.cost_per_trial)}</span></td>
        <td class="actions">${statusBtn("ad", ad.id, ad.status, ad.name)}</td>
      </tr>`;
    }).join("") || `<tr class="ad-row indent-1"><td colspan="9" class="muted">No ads.</td></tr>`);
    return `<tr class="${a.status === "PAUSED" ? "is-paused" : ""}">
      <td><span class="strong">${esc(a.name)}</span>
        <div class="small muted truncate" title="${esc(a.targeting || "")}">${esc(a.targeting || "")}</div></td>
      <td>${badge(a.status)}</td>
      <td class="num">${budgetCell("adset", a, a.name)}</td>
      <td class="num">${bidCell("adset", a, a.name)}</td>
      <td class="num"><span class="apportioned" title="${esc(tip)}">${fmt.money(a.spend)}</span></td>
      <td class="num"><span class="apportioned" title="${esc(tip)}">${fmt.int(a.clicks)}</span></td>
      <td class="num"><span class="apportioned" title="${esc(tip)}">${a.trials == null ? fmt.none : Number(a.trials).toFixed(1)}</span></td>
      <td class="num ${cptTone(a.cost_per_trial, tgt)}"><span class="apportioned" title="${esc(tip)}">${fmt.cpt(a.cost_per_trial)}</span></td>
      <td class="actions"><span class="row-actions">
        <button class="btn btn-sm expand-btn" type="button" data-adset-expand="${esc(a.id)}" aria-expanded="${open}">${open ? "Hide ads" : `Ads (${a.ads.length})`}</button>
        ${statusBtn("adset", a.id, a.status, a.name)}
      </span></td></tr>${ads}`;
  }).join("");
  const wk = d.window.key === "mtd" ? "MTD" : d.window.key;
  return `<div class="panel">${stats}
    <div class="table-wrap"><table class="table compact sub-table">
      <thead><tr><th>${esc(unit.charAt(0).toUpperCase() + unit.slice(1))}s &amp; ads</th><th>Status</th><th class="num">Budget / day</th><th class="num">Bid</th>
        <th class="num"><span class="apportioned" title="${esc(tip)}">Spend ${wk}*</span></th>
        <th class="num"><span class="apportioned" title="${esc(tip)}">Clicks*</span></th>
        <th class="num"><span class="apportioned" title="${esc(tip)}">Trials*</span></th>
        <th class="num"><span class="apportioned" title="${esc(tip)}">Cost / trial*</span></th><th class="actions"></th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <p class="panel-note">* Sample data has daily rows per campaign only: ${esc(unit)} numbers are the campaign total split by ${esc(basis)}, and each ad's numbers are its seeded share of its ${esc(unit)} (saved in the account state), so ads add up to their ${esc(unit)}.</p>
  </div>`;
}

// --------------------------------------------------------------- negatives
function matchSelect(current, attr) {
  return `<select class="select sm" ${attr} aria-label="Match type">${S.data.match_types.map((m) =>
    `<option value="${esc(m)}"${m === current ? " selected" : ""}>${esc(m)}</option>`).join("")}</select>`;
}

function termRow(t, withAction) {
  const key = t.campaign_id + "|" + t.term;
  const cls = t.negated ? "negated" : t.pending ? "pending" : "";
  let action = "";
  if (t.negated) action = badge("paused", "Negated");
  else if (withAction) action = `<span class="row-actions">${matchSelect(S.match[key] || "phrase", `data-match-for="${esc(key)}"`)}
    <button class="btn btn-sm btn-primary" type="button" data-add-neg="${esc(t.term)}" data-cid="${esc(t.campaign_id)}" data-key="${esc(key)}">Add negative</button></span>`;
  return `<tr class="${cls}">
    <td class="strong"><span class="term">${esc(t.term)}</span></td>
    <td><a href="#${esc(t.campaign_id)}">${esc(t.campaign_name)}</a></td>
    <td class="num">${fmt.int(t.clicks)}</td>
    <td class="num">${fmt.money(t.cost)}</td>
    <td class="num">${fmt.int(t.trials)}</td>
    <td class="num ${cptTone(t.cpt, S.data.cpa_target)}">${t.cpt == null && t.cost > 0 ? '<span class="tone-bad">no trials</span>' : fmt.cpt(t.cpt)}</td>
    <td>${t.recommend_negative ? `<div class="st-reason">${esc(t.reason)}</div>` : ""}</td>
    <td class="actions">${action}</td></tr>`;
}

const TERM_HEAD = `<thead><tr><th>Search term</th><th>Campaign</th><th class="num">Clicks</th><th class="num">Cost</th><th class="num">Trials</th><th class="num">Cost / trial</th><th>Why</th><th class="actions"></th></tr></thead>`;

function renderNegatives() {
  const d = S.data;
  const section = $("#negatives");
  section.hidden = S.platform === "meta";
  const pending = d.search_terms.filter((t) => t.pending);
  const googleCamps = d.campaigns.filter((c) => c.supports_negatives);
  $("#neg-sub").textContent = `· ${pending.length ? plural(pending.length, "recommendation") + " pending" : "none pending"}`;
  const pendingTable = pending.length
    ? `<div class="table-wrap"><table class="table st-table">${TERM_HEAD}<tbody>${pending.map((t) => termRow(t, true)).join("")}</tbody></table></div>`
    : `<div class="card-body"><div class="empty">No recommended negatives left to review.</div></div>`;
  const form = `<form class="neg-form" id="neg-form">
      <span class="small strong">Add negative keyword</span>
      <select class="select" name="campaign" aria-label="Campaign">${googleCamps.map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join("")}</select>
      <input class="input" name="text" placeholder="e.g. free seo tool" aria-label="Negative keyword text" required>
      ${matchSelect("phrase", 'name="match"')}
      <button class="btn btn-sm btn-primary" type="submit">Add</button>
    </form>`;
  const all = `<details class="neg-more" data-more="terms"${S.more.terms ? " open" : ""}>
      <summary>All search terms (${d.search_terms.length})</summary>
      <div class="table-wrap"><table class="table compact st-table">${TERM_HEAD}<tbody>${d.search_terms.map((t) => termRow(t, false)).join("")}</tbody></table></div>
    </details>`;
  const negs = `<details class="neg-more" data-more="negs"${S.more.negs ? " open" : ""}>
      <summary>Current negatives (${d.negatives.length})</summary>
      <div class="table-wrap"><table class="table compact">
        <thead><tr><th>Text</th><th>Campaign</th><th>Match</th><th>Added</th><th>Source</th></tr></thead>
        <tbody>${d.negatives.map((n) => `<tr><td class="strong">${esc(n.text)}</td><td>${esc(n.campaign_name)}</td><td><span class="tag">${esc(n.match)}</span></td>
          <td class="muted">${fmt.date(n.added)}</td><td>${n.source === "recommended" ? badge("info", "Recommended") : badge("idle", "Manual")}</td></tr>`).join("")
          || `<tr><td colspan="5" class="table-empty">No negatives yet.</td></tr>`}</tbody></table></div>
    </details>`;
  // Keep a half-typed manual negative across re-renders.
  const old = $("#neg-form");
  const keep = old ? { campaign: old.elements.campaign.value, text: old.elements.text.value, match: old.elements.match.value } : null;
  $("#neg-body").innerHTML = pendingTable + form + all + negs;
  if (keep) {
    const f = $("#neg-form");
    if (keep.campaign) f.elements.campaign.value = keep.campaign;
    f.elements.text.value = keep.text;
    f.elements.match.value = keep.match;
  }
}

// ----------------------------------------------------------------- actions
// Every direct control posts here. The server answers with the exact API
// request(s) it ran (or, for a large change, the warnings and the requests it
// would run, waiting for a confirm).
function postAction(actions, confirm = false) {
  return api("/api/campaigns/actions", { body: { actions, confirm } });
}

function findItem(kind, id) {
  for (const c of (S.data ? S.data.campaigns : [])) {
    if (kind === "campaign" && c.id === id) return c;
    for (const a of c.adsets || []) {
      if (kind === "adset" && a.id === id) return a;
      for (const ad of a.ads || []) if (kind === "ad" && ad.id === id) return ad;
    }
  }
  return null;
}

function itemName(kind, id) {
  const it = findItem(kind, id);
  return (it && it.name) || id;
}

// Apply the server's answer locally (status, budget, bid) so the table shows it
// before the background reload lands, and refresh the pacing cards.
function applyLocal(res) {
  const r = res.result || res;
  (r.changes || []).forEach((ch) => {
    const it = findItem(ch.kind, ch.id);
    if (!it) return;
    const v = ch.now !== undefined ? ch.now : ch.after;
    if (ch.field === "status") it.status = v;
    else if (it.controls && it.controls[ch.field]) it.controls[ch.field].value = v;
    if (ch.field === "budget" && "daily_budget" in it) it.daily_budget = v;
  });
  // pacing reacts at once; the window-based spend numbers wait for the reload
  const sm = res.summary;
  if (sm) {
    const keys = ["month_pace_pct", "projected_month_end", "pacing_daily_budget", "active_daily_budget",
      "pct_of_target", "active", "paused", "days_remaining"];
    ["account", "google", "meta"].forEach((k) => {
      const src = k === "account" ? sm.account : sm.platforms[k];
      const dst = k === "account" ? S.data.summary.account : S.data.summary.platforms[k];
      if (src && dst) keys.forEach((x) => { if (x in src) dst[x] = src[x]; });
    });
  }
}

function setLocalStatus(kind, id, status) {
  const it = findItem(kind, id);
  if (it) it.status = status;
}

async function onStatus(btn) {
  const { kind, id, next, name } = btn.dataset;
  const prev = next === "PAUSED" ? "ACTIVE" : "PAUSED";
  const key = `${kind}:${id}`;
  if (S.pending.has(key)) return;
  S.pending.add(key);
  setLocalStatus(kind, id, next);     // show it now; the server confirms below
  render();
  try {
    const res = await postAction([{ kind, id, action: "status", value: next, expected: prev }]);
    S.pending.delete(key);
    applyLocal(res);
    render();
    actionToast(`${name} ${next === "PAUSED" ? "paused" : "enabled"}`, res.result);
    refresh();
  } catch (e) {
    S.pending.delete(key);
    setLocalStatus(kind, id, prev);
    render();
    toast(e.status === 409 ? `${name} changed in another window. Reloaded the latest state.` : `Could not ${next === "PAUSED" ? "pause" : "enable"} ${name}: ${e.message}`, "error");
    if (e.status === 409) refresh();
  }
}

async function refresh() {
  try { await load(); } catch (e) { toast(`Saved, but the page did not refresh: ${e.message}`, "warn"); }
}

// ------------------------------------------------------------ inline editor
function openEditor(kind, id, field) {
  S.edit = { kind, id, field };
  render();
}

function closeEditor() {
  if (!S.edit) return;
  S.edit = null;
  render();
}

function focusEditor() {
  const input = document.querySelector("[data-editor] .ctl-input");
  if (input && document.activeElement !== input && !input.dataset.focused) {
    input.dataset.focused = "1";
    input.focus();
    input.select();
  }
}

function roundStep(v, step) {
  const n = Math.round(v / step) * step;
  return Math.round(n * 100) / 100;
}

function stepEditor(ed, dir) {
  const input = ed.querySelector(".ctl-input");
  const base = Number(ed.dataset.current) || Number(input.value) || 0;
  const step = stepFor(base);
  const cur = Number(input.value) || 0;
  input.value = String(Math.max(step, roundStep(cur + dir * step, step)));
  input.focus();
}

async function saveEditor(ed, confirm = false) {
  const { kind, id, field, name, current } = ed.dataset;
  const input = ed.querySelector(".ctl-input");
  const v = Number(input.value);
  if (!input.value.trim() || !isFinite(v) || v <= 0) {
    toast(`${field === "budget" ? "Daily budget" : "Bid"} must be a number greater than 0`, "error");
    input.focus();
    return;
  }
  const before = current === "" ? null : Number(current);
  if (before !== null && Math.abs(v - before) < 0.005) { closeEditor(); return; }
  ed.querySelectorAll("button, input").forEach((x) => { x.disabled = true; });
  try {
    const res = await postAction([{ kind, id, action: field, value: v, expected: before }], confirm);
    const r = res.result || {};
    if (r.needs_confirm) {
      ed.querySelectorAll("button, input").forEach((x) => { x.disabled = false; });
      confirmLarge(ed, r);
      return;
    }
    S.edit = null;
    applyLocal(res);
    render();
    const label = field === "budget" ? "daily budget" : (((findItem(kind, id) || {}).controls || {}).bid || {}).label || "bid";
    actionToast(`${name}: ${label} ${before === null ? "" : fmt.money(before) + " → "}${fmt.money(v)}`, r);
    refresh();
  } catch (e) {
    ed.querySelectorAll("button, input").forEach((x) => { x.disabled = false; });
    toast(e.status === 409 ? `${name} changed in another window; reloaded. Try again.` : e.message, "error");
    if (e.status === 409) { S.edit = null; refresh(); }
  }
}

// A large change (guardrail warning) needs a second, explicit click.
function confirmLarge(ed, r) {
  S.lastConfirm = r;
  let box = ed.querySelector(".ctl-confirm");
  if (!box) {
    box = document.createElement("div");
    box.className = "ctl-confirm";
    ed.appendChild(box);
  }
  box.innerHTML = `<div class="tone-watch small">${(r.warnings || []).map(esc).join("<br>")}</div>
    <details class="ctl-req"><summary>${r.requests.length === 1 ? "API request" : `${r.requests.length} API requests`} it will send</summary>${requestsHtml(r.requests)}</details>
    <div class="row-actions"><button class="btn btn-sm btn-danger" type="button" data-confirm-save>Confirm change</button>
    <button class="btn btn-sm btn-ghost" type="button" data-cancel>Cancel</button></div>`;
  box.querySelector("[data-confirm-save]").focus();
}

// ------------------------------------------------------- request rendering
function requestsHtml(reqs) {
  return (reqs || []).map((q, i) => `<div class="req-block">
      <div class="req-head"><span class="req-n">${q.step || i + 1}</span><span class="mono">${esc(q.method)} ${esc(q.url)}</span>
        <button class="btn btn-sm" type="button" data-copy-curl="${i}">Copy curl</button></div>
      <pre class="req-code"><code>${esc(requestText(q))}</code></pre>
    </div>`).join("");
}

function requestText(q) {
  const h = Object.entries(q.headers || {}).map(([k, v]) => `${k}: ${v}`).join("\n");
  let body;
  if (q.content_type === "application/x-www-form-urlencoded") {
    body = Object.entries(q.body || {}).map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join("\n");
  } else {
    body = JSON.stringify(q.body, null, 2);
  }
  return `${q.method} ${q.url}\n${h}\n\n${body}`;
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* fall back */ }
  const ta = document.createElement("textarea");
  ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  ta.remove();
  return ok;
}

function wireCopy(root, reqs) {
  root.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-copy-curl]");
    if (!b) return;
    e.stopPropagation();
    const q = reqs[Number(b.dataset.copyCurl)];
    if (q && await copyText(q.curl)) { b.textContent = "Copied"; setTimeout(() => { b.textContent = "Copy curl"; }, 1500); }
    else toast("Copy failed", "error");
  });
}

// ------------------------------------------------------------- undo toast
function toastStack() {
  let stack = document.getElementById("cmp-toasts");
  if (!stack) {
    stack = document.createElement("div");
    stack.id = "cmp-toasts";
    stack.className = "cmp-toasts";
    stack.setAttribute("aria-live", "polite");
    document.body.appendChild(stack);
  }
  return stack;
}

function actionToast(msg, r, { undoable = true } = {}) {
  r = r || {};
  const reqs = r.requests || [];
  const undo = (r.undo || {}).actions || [];
  const el = document.createElement("div");
  el.className = "cmp-toast";
  el.setAttribute("role", "status");
  const sample = r.mode && r.mode !== "live" ? ` <span class="muted small">(${esc(r.mode)} account)</span>` : "";
  el.innerHTML = `<div class="cmp-toast-head"><span class="cmp-toast-msg">${esc(msg)}${sample}</span>
      ${undoable && undo.length ? '<button class="btn btn-sm" type="button" data-undo>Undo</button>' : ""}
      <button class="cmp-toast-x" type="button" aria-label="Dismiss">&times;</button></div>
    ${reqs.length ? `<details class="ctl-req"><summary>${reqs.length === 1 ? "API request sent" : `${reqs.length} API requests sent`}</summary>${requestsHtml(reqs)}</details>` : ""}`;
  toastStack().appendChild(el);
  wireCopy(el, reqs);
  let timer = null;
  const close = () => { clearTimeout(timer); el.classList.add("leaving"); setTimeout(() => el.remove(), 220); };
  const arm = () => { clearTimeout(timer); timer = setTimeout(close, 12000); };
  el.addEventListener("mouseenter", () => clearTimeout(timer));
  el.addEventListener("mouseleave", () => { if (!el.querySelector("details[open]")) arm(); });
  el.addEventListener("toggle", () => { if (el.querySelector("details[open]")) clearTimeout(timer); else arm(); }, true);
  el.querySelector(".cmp-toast-x").addEventListener("click", close);
  const ub = el.querySelector("[data-undo]");
  if (ub) ub.addEventListener("click", async () => {
    ub.disabled = true;
    ub.textContent = "Undoing…";
    try {
      // the undo carries the exact before values; confirm is implied (the user made the change)
      const res = await postAction(undo, true);
      applyLocal(res);
      render();
      close();
      actionToast(`Undone: ${msg}`, res.result, { undoable: false });
      refresh();
    } catch (e) {
      ub.disabled = false;
      ub.textContent = "Undo";
      toast(`Undo failed: ${e.message}`, "error");
      if (e.status === 409) refresh();
    }
  });
  arm();
  return el;
}

async function addNegative(cid, text, match, source, btn) {
  if (btn) { btn.disabled = true; btn.classList.add("is-busy"); }
  try {
    await api(`/api/campaigns/${encodeURIComponent(cid)}/negatives`, { body: { text, match, source } });
    const name = (S.data.campaigns.find((c) => c.id === cid) || {}).name || cid;
    await afterMutation(`Negative added to ${name}: "${text}" [${match}]`);
    return true;
  } catch (e) {
    toast(e.message, "error");
    return false;
  } finally {
    if (btn && btn.isConnected) { btn.disabled = false; btn.classList.remove("is-busy"); }
  }
}

function toggleCampaign(id) {
  if (S.open.has(id)) S.open.delete(id); else S.open.add(id);
  S.target = null;
  renderTable();
  const btn = $(`#cmp-body [data-expand="${CSS.escape(id)}"]`);
  if (btn) btn.focus({ preventScroll: true });
}

// ------------------------------------------------------------------ wiring
function setPlatform(p) {
  S.platform = p;
  $$("#cmp-platform-tabs .tab").forEach((x) => {
    const on = x.dataset.platform === p;
    x.classList.toggle("active", on);
    x.setAttribute("aria-selected", on ? "true" : "false");
  });
}

function wire() {
  $("#win-select").addEventListener("click", (e) => {
    const b = e.target.closest("[data-window]");
    if (b && b.dataset.window !== S.window) load(b.dataset.window).catch((err) => toast(`Could not load campaigns: ${err.message}`, "error"));
  });
  $$("#cmp-platform-tabs .tab").forEach((t) => t.addEventListener("click", () => {
    setPlatform(t.dataset.platform);
    renderTable();
    renderNegatives();
  }));
  $$("#cmp-table thead th.sortable").forEach((th) => {
    th.addEventListener("click", () => {
      const k = th.dataset.key;
      if (S.sort.key === k) {
        if (S.sort.dir === -1) S.sort = { key: null, dir: 1 }; // third click: default order
        else S.sort.dir = -1;
      } else {
        S.sort = { key: k, dir: ["name", "status"].includes(k) ? 1 : -1 };
      }
      renderTable();
    });
  });

  const body = $("#cmp-body");
  body.addEventListener("click", (e) => {
    const t = e.target;
    const st = t.closest("[data-status-btn]");
    if (st) { e.stopPropagation(); onStatus(st); return; }
    const ed = t.closest("[data-editor]");
    if (ed) {
      e.stopPropagation();
      const stepB = t.closest("[data-step]");
      if (stepB) { stepEditor(ed, Number(stepB.dataset.step)); return; }
      if (t.closest("[data-confirm-save]")) { saveEditor(ed, true); return; }
      if (t.closest("[data-save]")) { saveEditor(ed); return; }
      if (t.closest("[data-cancel]")) { closeEditor(); return; }
      return;
    }
    const editB = t.closest("[data-edit]");
    if (editB) { e.stopPropagation(); openEditor(editB.dataset.kind, editB.dataset.id, editB.dataset.edit); return; }
    const exp = t.closest("[data-expand]");
    if (exp) { toggleCampaign(exp.dataset.expand); return; }
    const aexp = t.closest("[data-adset-expand]");
    if (aexp) {
      const id = aexp.dataset.adsetExpand;
      if (S.openAdsets.has(id)) S.openAdsets.delete(id); else S.openAdsets.add(id);
      renderTable();
      return;
    }
    const goNeg = t.closest("[data-goto-neg]");
    if (goNeg) { $("#negatives").scrollIntoView({ behavior: "smooth", block: "start" }); return; }
    if (t.closest("button, a, input, select, label")) return;
    const row = t.closest("tr.camp-row");
    if (row) toggleCampaign(row.dataset.cid);
  });

  body.addEventListener("keydown", (e) => {
    const ed = e.target.closest("[data-editor]");
    if (!ed) return;
    if (e.key === "Escape") { e.preventDefault(); closeEditor(); }
    else if (e.key === "Enter" && e.target.matches(".ctl-input")) { e.preventDefault(); saveEditor(ed); }
    else if (e.key === "ArrowUp" && e.target.matches(".ctl-input")) { e.preventDefault(); stepEditor(ed, 1); }
    else if (e.key === "ArrowDown" && e.target.matches(".ctl-input")) { e.preventDefault(); stepEditor(ed, -1); }
  });
  body.addEventListener("click", (e) => { wireCopyClick(e); });

  const neg = $("#neg-body");
  neg.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-add-neg]");
    if (b) await addNegative(b.dataset.cid, b.dataset.addNeg, S.match[b.dataset.key] || "phrase", "recommended", b);
  });
  neg.addEventListener("change", (e) => {
    const sel = e.target.closest("[data-match-for]");
    if (sel) S.match[sel.dataset.matchFor] = sel.value;
  });
  neg.addEventListener("toggle", (e) => {
    const d = e.target.closest && e.target.closest("details[data-more]");
    if (d) S.more[d.dataset.more] = d.open;
  }, true);
  neg.addEventListener("submit", async (e) => {
    const form = e.target.closest("#neg-form");
    if (!form) return;
    e.preventDefault();
    const text = form.elements.text.value.trim();
    if (!text) { toast("Type a negative keyword first", "error"); return; }
    const ok = await addNegative(form.elements.campaign.value, text, form.elements.match.value, "manual", form.querySelector("button"));
    if (ok) { const f = $("#neg-form"); if (f) f.elements.text.value = ""; }
  });
}

async function wireCopyClick(e) {
  const b = e.target.closest("[data-copy-curl]");
  if (!b) return;
  const ed = b.closest("[data-editor]");
  if (!ed) return;
  e.stopPropagation();
  const it = S.lastConfirm && S.lastConfirm.requests ? S.lastConfirm.requests[Number(b.dataset.copyCurl)] : null;
  if (it && await copyText(it.curl)) { b.textContent = "Copied"; setTimeout(() => { b.textContent = "Copy curl"; }, 1500); }
}

// The brand preloader locks page scroll while it plays; wait for it to finish.
function scrollToRow(id, smooth, tries = 0) {
  const locked = document.querySelector(".sa-preloader") || document.documentElement.style.overflow === "hidden";
  if (locked && tries < 40) { setTimeout(() => scrollToRow(id, smooth, tries + 1), 150); return; }
  const row = document.getElementById(`row-${id}`);
  if (!row) return;
  row.scrollIntoView({ block: "center", behavior: smooth ? "smooth" : "instant" });
  if (smooth) {
    // Smooth scrolling can stall (throttled or background tab): land it anyway.
    setTimeout(() => {
      const r = document.getElementById(`row-${id}`);
      if (!r) return;
      const box = r.getBoundingClientRect();
      if (box.bottom < 0 || box.top > window.innerHeight) r.scrollIntoView({ block: "center", behavior: "instant" });
    }, 900);
  }
  const btn = row.querySelector("[data-expand]");
  if (btn) btn.focus({ preventScroll: true });
  // Restart the highlight now that the row is on screen, then drop it so a
  // later re-render does not replay it.
  row.classList.remove("is-target");
  void row.offsetWidth;
  row.classList.add("is-target");
  setTimeout(() => {
    if (S.target !== id) return;
    S.target = null;
    const r = document.getElementById(`row-${id}`);
    if (r) r.classList.remove("is-target");
  }, 3500);
}

// Deep link: /campaigns#<campaign_id> shows all platforms, expands the row,
// scrolls to it and highlights it.
function openFromHash({ smooth = true } = {}) {
  let id = window.location.hash.replace(/^#/, "");
  try { id = decodeURIComponent(id); } catch (_) { /* keep raw */ }
  if (!id || !S.data) return;
  if (!S.data.campaigns.find((c) => c.id === id)) {
    if (!document.getElementById(id)) toast(`Campaign "${id}" is not in the current account state.`, "warn");
    return;
  }
  setPlatform("all");
  S.open.add(id);
  S.target = id;
  render();
  scrollToRow(id, smooth);
}

wire();
window.addEventListener("hashchange", () => openFromHash());
load().then(() => openFromHash({ smooth: false }), (e) => {
  toast(`Could not load campaigns: ${e.message}`, "error");
  $("#cmp-body").innerHTML = `<tr><td colspan="${COLS}" class="table-empty">Could not load campaigns: ${esc(e.message)}</td></tr>`;
});
