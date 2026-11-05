// Campaigns page: the centralized control surface.
import { api, fmt, toast, confirmButton, platformChip, badge, cptTone, esc, $, $$ } from "/static/js/common.js";

const S = {
  campaigns: [],
  summary: null,
  activity: [],
  cpa: [250, 280],
  platform: "all",
  filters: new Set(),
  q: "",
  open: new Set(),           // expanded campaign ids
  details: {},               // campaign id -> detail payload
  panelTab: {},              // campaign id -> "adsets" | "terms"
  openAdsets: new Set(),     // expanded adset ids
  match: {},                 // search term key -> selected match type
  lastSeenTs: null,
};

const COLS = 10;
const fmtBudget = (v) => fmt.money(v);

// ------------------------------------------------------------------ data
async function loadAll() {
  const d = await api("/api/campaigns/");
  S.campaigns = d.campaigns;
  S.cpa = d.cpa_target || S.cpa;
  S.summary = d.summary;
  setActivity(d.activity);
  await Promise.all([...S.open].map(loadDetail));
  render();
}

async function loadDetail(id) {
  try {
    S.details[id] = await api(`/api/campaigns/${encodeURIComponent(id)}`);
  } catch (e) {
    toast(e.message, "error");
    S.open.delete(id);
  }
}

function setActivity(list) {
  const prev = S.lastSeenTs;
  S.activity = list || [];
  S.freshCount = 0;
  if (prev) S.freshCount = S.activity.filter((a) => a.ts > prev).length;
  if (S.activity.length) S.lastSeenTs = S.activity[0].ts;
  else S.lastSeenTs = S.lastSeenTs || "0";
}

// After any mutation: refresh list, open details, summary and activity.
async function afterMutation(msg) {
  toast(msg, "success");
  await loadAll();
}

// ---------------------------------------------------------------- render
function render() {
  renderSummary();
  renderCounts();
  renderTable();
  renderActivity();
}

function renderSummary() {
  const s = S.summary;
  if (!s) return;
  const pendingNeg = S.campaigns.reduce((sum, c) => sum + (c.recommended_negatives || 0), 0);
  const negCampaigns = S.campaigns.filter((c) => c.recommended_negatives).length;
  const plat = (pl, label) => {
    const p = s.platforms[pl];
    const pct = p.pct_of_target || 0;
    const tone = pct > 105 ? "tone-watch" : pct < 90 ? "tone-watch" : "";
    return `<div class="kpi">
      <div class="kpi-label">${platformChip(pl)} ${label} daily budget, active</div>
      <div class="kpi-value num ${tone}">${fmt.money(p.active_daily_budget)}</div>
      <div class="kpi-sub" title="Platform monthly budget / 30">vs ${fmt.money(p.daily_target)}/day target (${fmt.money(p.monthly_budget)}/30) &middot; ${fmt.pct(p.pct_of_target, 0)}</div>
      <div class="kpi-bar"><span class="${pct > 100 ? "over" : ""}" style="width:${Math.min(100, pct)}%"></span></div>
    </div>`;
  };
  $("#cmp-summary").innerHTML = `
    <div class="kpi"><div class="kpi-label">Active campaigns</div><div class="kpi-value num tone-good">${fmt.int(s.active)}</div>
      <div class="kpi-sub">${s.platforms.google.active} Google &middot; ${s.platforms.meta.active} Meta</div></div>
    <div class="kpi"><div class="kpi-label">Paused campaigns</div><div class="kpi-value num ${s.paused ? "" : "tone-idle"}">${fmt.int(s.paused)}</div>
      <div class="kpi-sub">${s.legacy} legacy in the account</div></div>
    ${plat("google", "Google")}
    ${plat("meta", "Meta")}
    <div class="kpi"><div class="kpi-label">Negative keywords to review</div><div class="kpi-value num ${pendingNeg ? "tone-watch" : "tone-good"}">${fmt.int(pendingNeg)}</div>
      <div class="kpi-sub">recommended search terms not yet negated${negCampaigns ? ` &middot; ${negCampaigns} campaign${negCampaigns === 1 ? "" : "s"}` : ""}</div></div>`;
}

function renderCounts() {
  const n = { all: S.campaigns.length, google: 0, meta: 0 };
  S.campaigns.forEach((c) => { n[c.platform] += 1; });
  $$("[data-count]").forEach((el) => { el.textContent = n[el.dataset.count]; });
}

function visible() {
  const statuses = ["ACTIVE", "PAUSED"].filter((s) => S.filters.has(s));
  const q = S.q.trim().toLowerCase();
  return S.campaigns.filter((c) => {
    if (S.platform !== "all" && c.platform !== S.platform) return false;
    if (statuses.length && !statuses.includes(c.status)) return false;
    if (S.filters.has("legacy") && !c.legacy) return false;
    if (q && !c.name.toLowerCase().includes(q)) return false;
    return true;
  });
}

function statusBtn(kind, id, status, name) {
  const paused = status === "PAUSED";
  const label = paused ? "Enable" : "Pause";
  const cls = paused ? "btn btn-sm" : "btn btn-sm btn-danger";
  return `<button class="${cls}" data-status-btn data-kind="${kind}" data-id="${esc(id)}" data-next="${paused ? "ACTIVE" : "PAUSED"}"
    data-name="${esc(name)}" data-confirm-label="Confirm ${label.toLowerCase()}?">${label}</button>`;
}

function renderTable() {
  const rows = visible();
  const body = $("#cmp-body");
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="${COLS}" class="table-empty">No campaigns match these filters.</td></tr>`;
    return;
  }
  body.innerHTML = rows.map((c) => {
    const open = S.open.has(c.id);
    const thin = c.trials_7d < 3 ? `<div class="caveat">${c.trials_7d === 0 ? "0 trials: CPT undefined" : `n=${c.trials_7d}: thin read`}</div>` : "";
    const negatives = c.platform !== "google"
      ? `<span class="muted" title="Meta has no search terms">n/a</span>`
      : c.recommended_negatives
        ? `<button class="btn btn-sm" type="button" data-review-neg="${esc(c.id)}" aria-label="Review ${c.recommended_negatives} recommended negatives for ${esc(c.name)}">${c.recommended_negatives} recommendation${c.recommended_negatives === 1 ? "" : "s"}</button>`
        : `<span class="tone-good">None pending</span>`;
    const main = `<tr class="${c.status === "PAUSED" ? "is-paused" : ""}${open ? " is-open" : ""}" data-cid="${esc(c.id)}">
      <td>${platformChip(c.platform)}</td>
      <td class="name">${esc(c.name)}${c.legacy ? ' <span class="tag">legacy</span>' : ""}
        <div class="small muted cmp-meta">${esc(c.country)} &middot; ${esc(c.type)} &middot; ${esc(c.bid_strategy)} &middot; started ${fmt.date(c.start_date)}</div></td>
      <td>${badge(c.status)}</td>
      <td class="num" data-budget-cell="${esc(c.id)}"><button class="budget-btn" data-budget="${esc(c.id)}" title="Click to edit daily budget">${fmtBudget(c.daily_budget)}</button></td>
      <td class="num">${fmt.money(c.spend_7d)}</td>
      <td class="num">${fmt.int(c.trials_7d)}</td>
      <td class="num ${cptTone(c.cpt_7d, S.cpa)}" title="${fmt.money(c.spend_7d)} divided by ${fmt.int(c.trials_7d)} trials">${fmt.cpt(c.cpt_7d)}${thin}</td>
      <td class="num ${cptTone(c.cpt_3d, S.cpa)}">${fmt.cpt(c.cpt_3d)}</td>
      <td>${negatives}</td>
      <td class="actions"><span class="row-actions">
        ${statusBtn("campaign", c.id, c.status, c.name)}
        <button class="btn btn-sm expand-btn" data-expand="${esc(c.id)}" aria-expanded="${open}" aria-label="${open ? "Close" : "Expand"} ${esc(c.name)}">${open ? "Close" : "Expand"}</button>
      </span></td></tr>`;
    return main + (open ? `<tr class="panel-row"><td colspan="${COLS}">${panelHtml(c)}</td></tr>` : "");
  }).join("");
  $$("[data-status-btn]", body).forEach((b) => confirmButton(b, onStatus));
}

// ------------------------------------------------------------ panel html
function panelHtml(c) {
  const d = S.details[c.id];
  if (!d) return `<div class="panel muted">Loading&hellip;</div>`;
  const tab = S.panelTab[c.id] || "adsets";
  const google = d.supports_negatives;
  const unit = c.platform === "meta" ? "Ad sets" : "Ad groups";
  const recs = d.search_terms.filter((t) => t.recommend_negative && !t.negated).length;
  return `<div class="panel" data-panel-for="${esc(c.id)}">
    <div class="tabs">
      <button class="tab${tab === "adsets" ? " active" : ""}" data-ptab="adsets" data-cid="${esc(c.id)}">${unit} &amp; ads <span class="count">${d.adsets.length}</span></button>
      ${google ? `<button class="tab${tab === "terms" ? " active" : ""}" data-ptab="terms" data-cid="${esc(c.id)}">Search terms &amp; negatives <span class="count">${recs ? recs + " rec." : d.search_terms.length}</span></button>` : ""}
    </div>
    ${tab === "terms" && google ? termsHtml(d) : adsetsHtml(d)}
  </div>`;
}

function adsetsHtml(d) {
  if (!d.adsets.length) return `<div class="empty">No ad sets under this campaign.</div>`;
  const basis = d.adsets[0].apportion_basis;
  const tip = `Apportioned: campaign 7-day totals split by ${basis}. Sample data has no ad-set-level daily rows.`;
  const rows = d.adsets.map((a) => {
    const open = S.openAdsets.has(a.id);
    const ads = open ? a.ads.map((ad) => `<tr class="ad-row indent-1${ad.status === "PAUSED" ? " is-paused" : ""}">
        <td>${esc(ad.name)}</td>
        <td>${badge(ad.status)}</td>
        <td><span class="tag">${esc(ad.format)}</span></td>
        <td class="hook" colspan="3">${esc(ad.hook)}</td>
        <td><span class="muted">CTA</span> ${esc(ad.cta)}</td>
        <td class="muted" title="Launched">${fmt.date(ad.launched)}</td>
        <td class="actions">${statusBtn("ad", ad.id, ad.status, ad.name)}</td>
      </tr>`).join("") || `<tr class="ad-row indent-1"><td colspan="9" class="muted">No ads.</td></tr>` : "";
    return `<tr class="${a.status === "PAUSED" ? "is-paused" : ""}">
      <td><span class="strong">${esc(a.name)}</span> <span class="muted small">${esc(a.kind)}</span></td>
      <td>${badge(a.status)}</td>
      <td class="num">${a.daily_budget ? fmt.money(a.daily_budget) : '<span class="muted" title="Uses the campaign budget">campaign</span>'}</td>
      <td class="wrap">${esc(a.targeting)}</td>
      <td class="num"><span class="apportioned" title="${esc(tip)}">${fmt.money(a.spend_7d)}</span></td>
      <td class="num"><span class="apportioned" title="${esc(tip)}">${a.trials_7d == null ? fmt.none : Number(a.trials_7d).toFixed(1)}</span></td>
      <td class="num ${cptTone(a.cpt_7d, S.cpa)}"><span class="apportioned" title="${esc(tip)}">${fmt.cpt(a.cpt_7d)}</span></td>
      <td class="muted small">${a.ads.length} ads</td>
      <td class="actions"><span class="row-actions">
        ${statusBtn("adset", a.id, a.status, a.name)}
        <button class="btn btn-sm expand-btn" data-adset-expand="${esc(a.id)}" aria-expanded="${open}">${open ? "Hide ads" : "Ads"}</button>
      </span></td></tr>${ads}`;
  }).join("");
  return `<div class="table-wrap"><table class="table compact sub-table">
    <thead><tr><th>Name</th><th>Status</th><th class="num">Daily budget</th><th>Targeting</th>
      <th class="num"><span class="apportioned" title="${esc(tip)}">7d spend*</span></th>
      <th class="num"><span class="apportioned" title="${esc(tip)}">7d trials*</span></th>
      <th class="num"><span class="apportioned" title="${esc(tip)}">7d CPT*</span></th><th></th><th class="actions"></th></tr></thead>
    <tbody>${rows}</tbody></table></div>
    <p class="panel-note">* Apportioned from campaign totals by ${esc(basis)}; the sample data has no ad-set-level rows. Expanded ad rows show format, hook, CTA, launch date and status.</p>`;
}

function matchSelect(key, current, extraAttr) {
  return `<select class="select sm" ${extraAttr} aria-label="Match type">${["phrase", "exact", "broad"].map((m) =>
    `<option value="${m}"${m === current ? " selected" : ""}>${m}</option>`).join("")}</select>`;
}

function termsHtml(d) {
  const cid = d.campaign.id;
  const terms = d.search_terms.map((t) => {
    const key = cid + "|" + t.term;
    const cls = t.negated ? "negated" : t.recommend_negative ? "recommend" : "";
    let action = "";
    if (t.negated) action = badge("paused", "Negated");
    else if (t.recommend_negative) action = `<span class="row-actions">${matchSelect(key, S.match[key] || "phrase", `data-match-for="${esc(key)}"`)}
      <button class="btn btn-sm btn-primary" data-add-neg="${esc(t.term)}" data-cid="${esc(cid)}" data-key="${esc(key)}">Add as negative</button></span>`;
    return `<tr class="${cls}">
      <td class="strong">${esc(t.term)}</td>
      <td class="num">${fmt.int(t.clicks)}</td>
      <td class="num">${fmt.money(t.cost)}</td>
      <td class="num">${fmt.int(t.trials)}</td>
      <td class="num ${cptTone(t.cpt, S.cpa)}">${t.cpt == null && t.cost > 0 ? '<span class="tone-bad">no trials</span>' : fmt.cpt(t.cpt)}</td>
      <td class="keep">${t.recommend_negative ? `<div class="st-reason">${esc(t.reason)}</div>` : ""}</td>
      <td class="actions keep">${action}</td></tr>`;
  }).join("") || `<tr><td colspan="7" class="table-empty">No search terms for this campaign.</td></tr>`;
  const negs = d.negatives.map((n) => `<tr><td class="strong">${esc(n.text)}</td><td><span class="tag">${esc(n.match)}</span></td>
      <td class="muted">${fmt.date(n.added)}</td><td>${n.source === "recommended" ? badge("info", "Recommended") : badge("idle", "Manual")}</td></tr>`).join("")
    || `<tr><td colspan="4" class="table-empty">No negatives yet.</td></tr>`;
  return `<div class="table-wrap"><table class="table compact st-table">
      <thead><tr><th>Search term</th><th class="num">Clicks</th><th class="num">Cost</th><th class="num">Trials</th><th class="num">CPT</th><th>Recommendation</th><th class="actions"></th></tr></thead>
      <tbody>${terms}</tbody></table></div>
    <form class="neg-form" data-neg-form="${esc(cid)}">
      <span class="label">Add negative</span>
      <input class="input" name="text" placeholder="e.g. free seo tool" aria-label="Negative keyword text" required>
      ${matchSelect("", "phrase", 'name="match"')}
      <button class="btn btn-sm btn-primary" type="submit">Add</button>
    </form>
    <h3 class="card-title mt-2">Negatives <span class="muted">(${d.negatives.length})</span></h3>
    <div class="table-wrap mt-2"><table class="table compact">
      <thead><tr><th>Text</th><th>Match</th><th>Added</th><th>Source</th></tr></thead>
      <tbody>${negs}</tbody></table></div>`;
}

function renderActivity() {
  const ul = $("#act-list");
  if (!S.activity.length) { ul.innerHTML = `<li class="muted">No changes yet.</li>`; return; }
  ul.innerHTML = S.activity.map((a, i) => `<li class="${i < (S.freshCount || 0) ? "fresh" : ""}">
      <div class="act-top"><span class="act-action">${esc(a.action)}</span><span class="act-ts">${esc(fmt.datetime(a.ts))}</span></div>
      <div class="act-detail">${esc(a.detail || a.target)}</div></li>`).join("");
}

// --------------------------------------------------------------- actions
const STATUS_PATH = {
  campaign: (id) => `/api/campaigns/${encodeURIComponent(id)}/status`,
  adset: (id) => `/api/campaigns/adsets/${encodeURIComponent(id)}/status`,
  ad: (id) => `/api/campaigns/ads/${encodeURIComponent(id)}/status`,
};

async function onStatus(btn) {
  const { kind, id, next, name } = btn.dataset;
  await api(STATUS_PATH[kind](id), { body: { status: next } });
  await afterMutation(`${name} ${next === "PAUSED" ? "paused" : "enabled"}`);
}

function startBudgetEdit(btn) {
  const id = btn.dataset.budget;
  const c = S.campaigns.find((x) => x.id === id);
  if (!c) return;
  const cell = btn.parentElement;
  cell.innerHTML = `<input class="input budget-input" type="number" min="0.01" step="1" value="${c.daily_budget}" aria-label="Daily budget for ${esc(c.name)}">`;
  const input = cell.querySelector("input");
  input.focus();
  input.select();
  let done = false;
  const cancel = () => { if (done) return; done = true; renderTable(); };
  input.addEventListener("keydown", async (e) => {
    if (e.key === "Escape") { e.preventDefault(); cancel(); }
    if (e.key !== "Enter") return;
    e.preventDefault();
    const v = Number(input.value);
    if (!input.value.trim() || !isFinite(v) || v <= 0) {
      toast("Daily budget must be a number greater than 0", "error");
      input.focus();
      return;
    }
    if (v === Number(c.daily_budget)) { cancel(); return; }
    done = true;
    input.disabled = true;
    try {
      await api(`/api/campaigns/${encodeURIComponent(id)}/budget`, { body: { daily_budget: v } });
      await afterMutation(`${c.name}: daily budget ${fmt.money(c.daily_budget)} -> ${fmt.money(v)}`);
    } catch (err) {
      toast(err.message, "error");
      renderTable();
    }
  });
  input.addEventListener("blur", () => setTimeout(cancel, 120));
}

async function addNegative(cid, text, match, source, btn) {
  if (btn) btn.disabled = true;
  try {
    await api(`/api/campaigns/${encodeURIComponent(cid)}/negatives`, { body: { text, match, source } });
    await afterMutation(`Negative added: "${text}" [${match}]`);
    return true;
  } catch (e) {
    toast(e.message, "error");
    return false;
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ---------------------------------------------------------------- events
function wire() {
  $$("#cmp-platform-tabs .tab").forEach((t) => t.addEventListener("click", () => {
    S.platform = t.dataset.platform;
    $$("#cmp-platform-tabs .tab").forEach((x) => { x.classList.toggle("active", x === t); x.setAttribute("aria-selected", x === t); });
    renderTable();
  }));
  $$(".fchip").forEach((b) => b.addEventListener("click", () => {
    const f = b.dataset.filter;
    if (S.filters.has(f)) S.filters.delete(f); else S.filters.add(f);
    b.setAttribute("aria-pressed", S.filters.has(f));
    renderTable();
  }));
  $("#cmp-search").addEventListener("input", (e) => { S.q = e.target.value; renderTable(); });

  const body = $("#cmp-body");
  body.addEventListener("click", async (e) => {
    const t = e.target;
    const budget = t.closest("[data-budget]");
    if (budget) return startBudgetEdit(budget);
    const reviewNeg = t.closest("[data-review-neg]");
    if (reviewNeg) {
      const id = reviewNeg.dataset.reviewNeg;
      S.open.add(id);
      S.panelTab[id] = "terms";
      renderTable();
      await loadDetail(id);
      renderTable();
      return;
    }
    const exp = t.closest("[data-expand]");
    if (exp) {
      const id = exp.dataset.expand;
      if (S.open.has(id)) { S.open.delete(id); renderTable(); return; }
      S.open.add(id);
      renderTable();
      await loadDetail(id);
      renderTable();
      return;
    }
    const ptab = t.closest("[data-ptab]");
    if (ptab) { S.panelTab[ptab.dataset.cid] = ptab.dataset.ptab; renderTable(); return; }
    const aexp = t.closest("[data-adset-expand]");
    if (aexp) {
      const id = aexp.dataset.adsetExpand;
      if (S.openAdsets.has(id)) S.openAdsets.delete(id); else S.openAdsets.add(id);
      renderTable();
      return;
    }
    const neg = t.closest("[data-add-neg]");
    if (neg) {
      const key = neg.dataset.key;
      await addNegative(neg.dataset.cid, neg.dataset.addNeg, S.match[key] || "phrase", "recommended", neg);
    }
  });
  body.addEventListener("change", (e) => {
    const sel = e.target.closest("[data-match-for]");
    if (sel) S.match[sel.dataset.matchFor] = sel.value;
  });
  body.addEventListener("submit", async (e) => {
    const form = e.target.closest("[data-neg-form]");
    if (!form) return;
    e.preventDefault();
    const text = form.elements.text.value.trim();
    if (!text) { toast("Type a negative keyword first", "error"); return; }
    await addNegative(form.dataset.negForm, text, form.elements.match.value, "manual", form.querySelector("button"));
  });
}

// Deep link: /campaigns#<campaign_id> clears filters, opens and scrolls to it.
async function openFromHash({ smooth = true } = {}) {
  let id = window.location.hash.replace(/^#/, "");
  try { id = decodeURIComponent(id); } catch (_) { /* keep raw */ }
  if (!id) return;
  if (!S.campaigns.find((c) => c.id === id)) {
    toast(`Campaign "${id}" is not in the current account state.`, "warn");
    return;
  }
  S.platform = "all";
  S.filters.clear();
  S.q = "";
  $("#cmp-search").value = "";
  $$("#cmp-platform-tabs .tab").forEach((tab) => {
    const on = tab.dataset.platform === "all";
    tab.classList.toggle("active", on);
    tab.setAttribute("aria-selected", on);
  });
  $$(".fchip").forEach((chip) => chip.setAttribute("aria-pressed", "false"));
  S.open.add(id);
  render();
  if (!S.details[id]) await loadDetail(id);
  render();
  const row = $(`#cmp-body tr[data-cid="${CSS.escape(id)}"]`);
  if (row) {
    // First load: "auto" (follows the page scroll-behavior); in-page hashchange: smooth.
    row.scrollIntoView({ block: "center", behavior: smooth ? "smooth" : "auto" });
    const expand = row.querySelector("[data-expand]");
    if (expand) expand.focus({ preventScroll: true });
  }
}

wire();
window.addEventListener("hashchange", () => { openFromHash().catch((e) => toast(e.message, "error")); });
loadAll().then(() => openFromHash({ smooth: false }).catch((e) => toast(e.message, "error")), (e) => {
  toast(e.message, "error");
  $("#cmp-body").innerHTML = `<tr><td colspan="${COLS}" class="table-empty">Could not load campaigns: ${esc(e.message)}</td></tr>`;
});
