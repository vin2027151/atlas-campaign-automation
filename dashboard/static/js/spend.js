// Spend page: platform split, account funnel, stacked daily spend, rolling 3-day
// CPT against the target band, and the campaign table with expandable ad sets.
// One call to /api/spend/?window=... drives everything.
import { api, fmt, toast, platformChip, badge, cptTone, esc, $, $$, token, seriesColors, chartDefaults, tick } from "/static/js/common.js";

const WINDOW_KEY = "spend.window";
const state = {
  window: "7d",
  data: null,
  sort: { key: null, dir: 1 },
  open: new Set(),
  charts: { daily: null, cpt: null },
  hidden: new Set(), // campaign ids hidden via chart legends (shared by both charts)
};

try {
  const saved = localStorage.getItem(WINDOW_KEY);
  if (saved && ["3d", "7d", "14d", "30d", "mtd"].includes(saved)) state.window = saved;
} catch (e) { /* storage blocked: default window */ }

// ------------------------------------------------------------------ colors
function hexToRgb(h) {
  const s = h.replace("#", "").trim();
  const v = s.length === 3 ? s.split("").map((c) => c + c).join("") : s;
  const n = parseInt(v, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function mix(a, b, t) {
  try {
    const x = hexToRgb(a), y = hexToRgb(b);
    const c = x.map((v, i) => Math.round(v * (1 - t) + y[i] * t));
    return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
  } catch (e) { return a; }
}
/** One stable color per campaign, from the series tokens plus tinted variants. */
function campaignColors(ids) {
  const base = seriesColors();
  const surface = token("--surface") || "#ffffff";
  const ink = token("--ink") || "#000000";
  const palette = [...base, ...base.map((c) => mix(c, surface, 0.45)), ...base.map((c) => mix(c, ink, 0.3))];
  const out = {};
  ids.forEach((id, i) => { out[id] = palette[i % palette.length]; });
  return out;
}

// --------------------------------------------------------------- loading
async function load(win) {
  state.window = win;
  try { localStorage.setItem(WINDOW_KEY, win); } catch (e) { /* ignore */ }
  $$("#win-select [data-window]").forEach((b) => {
    const on = b.dataset.window === win;
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", on ? "true" : "false");
  });
  let data;
  try {
    data = await api(`/api/spend/?window=${encodeURIComponent(win)}`);
  } catch (e) {
    toast(`Could not load spend data: ${e.message}`, "error");
    return;
  }
  state.data = data;
  const w = data.window;
  $("#win-label").textContent = `${w.label}: ${fmt.date(w.start)} – ${fmt.date(w.end, { year: true })}`;
  renderPlatforms(data);
  renderFunnel(data);
  renderDaily(data);
  renderCpt(data);
  renderTable();
}

// ----------------------------------------------------------- platform split
function stat(label, value, cls = "") {
  return `<div class="plat-stat"><div class="kpi-label">${esc(label)}</div><div class="stat-value ${cls}">${value}</div></div>`;
}

function renderPlatforms(d) {
  const target = d.cpa_target;
  const card = (p) => `
    <div class="card plat-card">
      <div class="card-head">
        <h2 class="card-title">${platformChip(p.platform)} ${esc(p.label)}</h2>
        <span class="card-sub">${fmt.pct(p.share_pct)} of spend · ${p.campaigns} campaigns</span>
      </div>
      <div class="card-body">
        <div class="plat-stats">
          ${stat("Spend", fmt.money(p.spend))}
          ${stat("Trials", fmt.int(p.trials))}
          ${stat("Cost / trial", fmt.cpt(p.cost_per_trial), cptTone(p.cost_per_trial, target))}
          ${stat("Paid", fmt.int(p.paid))}
          ${stat("Cost / paid", fmt.cpt(p.cost_per_paid))}
        </div>
      </div>
      <div class="card-foot">
        <span>Trial&rarr;paid ${fmt.pct(p.trial_to_paid)}</span>
        <span>Platform reports ${fmt.int(p.platform_conversions)} conv. (${fmt.pct(p.platform_vs_posthog_pct, 0)} of PostHog)</span>
      </div>
    </div>`;
  const g = d.platforms.find((p) => p.platform === "google");
  const m = d.platforms.find((p) => p.platform === "meta");
  const a = d.account;
  const gs = g.share_pct || 0, ms = m.share_pct || 0;
  const total = `
    <div class="card plat-card">
      <div class="card-head">
        <h2 class="card-title">Account total</h2>
        <span class="card-sub">${esc(d.window.label)}</span>
      </div>
      <div class="card-body">
        <div class="plat-stats">
          ${stat("Spend", fmt.money(a.spend))}
          ${stat("Trials", fmt.int(a.trials))}
          ${stat("Cost / trial", fmt.cpt(a.cost_per_trial), cptTone(a.cost_per_trial, target))}
          ${stat("Paid", fmt.int(a.paid))}
          ${stat("Cost / paid", fmt.cpt(a.cost_per_paid))}
        </div>
        <div class="mt-4">
          <div class="split-bar" role="img" aria-label="Google ${fmt.pct(gs)}, Meta ${fmt.pct(ms)} of spend">
            <span class="seg-google" style="width:${gs}%"></span><span class="seg-meta" style="width:${ms}%"></span>
          </div>
          <div class="split-legend">
            <span>${platformChip("google")} Google ${fmt.pct(gs)} · ${fmt.money(g.spend)}</span>
            <span>${platformChip("meta")} Meta ${fmt.pct(ms)} · ${fmt.money(m.spend)}</span>
          </div>
        </div>
      </div>
      <div class="card-foot"><span>Target CPT ${fmt.money(target[0])}–${fmt.money(target[1])}</span><span>Trial&rarr;paid ${fmt.pct(a.trial_to_paid)}</span></div>
    </div>`;
  $("#platform-split").innerHTML = card(g) + card(m) + total;
}

// ------------------------------------------------------------------ funnel
function renderFunnel(d) {
  const f = d.funnel;
  const stage = (label, value, sub) => `
    <div class="funnel-stage"><div class="kpi-label">${esc(label)}</div>
      <div class="stat-value">${value}</div><div class="kpi-sub">${sub}</div></div>`;
  const step = (rate, label) => `
    <div class="funnel-step"><span class="arrow" aria-hidden="true">&rarr;</span><span class="rate">${rate}</span><span>${esc(label)}</span></div>`;
  $("#funnel").innerHTML =
    stage("Spend", fmt.money(f.spend), `${fmt.int(f.impressions)} impressions`) +
    step(fmt.money(f.cpc, { cents: true }), "per click") +
    stage("Clicks", fmt.int(f.clicks), `CTR ${fmt.pct(f.ctr, 2)}`) +
    step(fmt.pct(f.click_to_trial, 2), "click→trial") +
    stage("Trials", fmt.int(f.trials), `<span class="${cptTone(f.cost_per_trial, d.cpa_target)}">${fmt.cpt(f.cost_per_trial)}</span> per trial`) +
    step(fmt.pct(f.trial_to_paid), "trial→paid") +
    stage("Paid", fmt.int(f.paid), `${fmt.cpt(f.cost_per_paid)} per paid`);
  $("#funnel-sub").textContent = `· ${d.window.label.toLowerCase()}`;
  $("#funnel-note").textContent = d.notes.paid_lag;
}

// ------------------------------------------------------------------ charts
function legendToggle(chartKey) {
  // Toggle a campaign in both charts so the two stay in sync.
  return (e, item, legend) => {
    const ds = legend.chart.data.datasets[item.datasetIndex];
    const id = ds.campaignId;
    if (!id) {
      const vis = legend.chart.isDatasetVisible(item.datasetIndex);
      legend.chart.setDatasetVisibility(item.datasetIndex, !vis);
      legend.chart.update();
      return;
    }
    if (state.hidden.has(id)) state.hidden.delete(id); else state.hidden.add(id);
    Object.values(state.charts).forEach((ch) => {
      if (!ch) return;
      ch.data.datasets.forEach((dset, i) => {
        if (dset.campaignId === id) ch.setDatasetVisibility(i, !state.hidden.has(id));
      });
      ch.update();
    });
  };
}

function labelsFor(dates) {
  return dates.map((d) => fmt.date(d, { dow: dates.length <= 14 }));
}

function renderDaily(d) {
  const Chart = window.Chart;
  if (!Chart) return;
  chartDefaults();
  const ids = d.daily.series.map((s) => s.campaign_id);
  const colors = campaignColors(ids);
  const datasets = d.daily.series.map((s) => ({
    label: s.name + (s.legacy ? " (legacy)" : ""),
    campaignId: s.campaign_id,
    data: s.spend,
    backgroundColor: colors[s.campaign_id],
    borderWidth: 0,
    stack: "spend",
    hidden: state.hidden.has(s.campaign_id),
  }));
  const cfg = {
    type: "bar",
    data: { labels: labelsFor(d.daily.dates), datasets },
    options: {
      scales: {
        x: { stacked: true, grid: { display: false } },
        y: { stacked: true, beginAtZero: true, ticks: { callback: tick.money } },
      },
      plugins: {
        legend: { onClick: legendToggle("daily") },
        tooltip: {
          filter: (item) => item.raw > 0,
          itemSort: (a, b) => b.raw - a.raw,
          callbacks: {
            label: (c) => ` ${c.dataset.label}: ${fmt.money(c.raw)}`,
            footer: (items) => {
              if (!items.length) return "";
              const i = items[0].dataIndex;
              return `Total ${fmt.money(d.daily.totals[i])}`;
            },
          },
        },
      },
    },
  };
  if (state.charts.daily) state.charts.daily.destroy();
  state.charts.daily = new Chart($("#daily-chart"), cfg);
}

// Shaded target band between cpa_target[0] and cpa_target[1].
const targetBand = {
  id: "targetBand",
  beforeDatasetsDraw(chart, args, opts) {
    const { ctx, chartArea, scales } = chart;
    if (!chartArea || !scales.y || !opts || !opts.range) return;
    const [lo, hi] = opts.range;
    const yTop = scales.y.getPixelForValue(hi);
    const yBot = scales.y.getPixelForValue(lo);
    const top = Math.max(chartArea.top, Math.min(yTop, yBot));
    const bot = Math.min(chartArea.bottom, Math.max(yTop, yBot));
    if (bot <= top) return;
    ctx.save();
    ctx.globalAlpha = 0.16;
    ctx.fillStyle = opts.fill;
    ctx.fillRect(chartArea.left, top, chartArea.right - chartArea.left, bot - top);
    ctx.globalAlpha = 0.7;
    ctx.strokeStyle = opts.line;
    ctx.setLineDash([4, 3]);
    ctx.lineWidth = 1;
    [top, bot].forEach((y) => { ctx.beginPath(); ctx.moveTo(chartArea.left, y); ctx.lineTo(chartArea.right, y); ctx.stroke(); });
    ctx.restore();
  },
};

function renderCpt(d) {
  const Chart = window.Chart;
  if (!Chart) return;
  const r = d.rolling_cpt;
  const ids = r.series.map((s) => s.campaign_id);
  const colors = campaignColors(ids);
  const datasets = r.series.map((s) => ({
    label: s.name + (s.legacy ? " (legacy)" : ""),
    campaignId: s.campaign_id,
    data: s.cost_per_trial,
    borderColor: colors[s.campaign_id],
    backgroundColor: colors[s.campaign_id],
    borderDash: s.legacy ? [5, 3] : [],
    spanGaps: false,
    tension: 0,
    pointRadius: r.dates.length <= 14 ? 2 : 0,
    hidden: state.hidden.has(s.campaign_id),
  }));
  datasets.push({
    label: "Account",
    data: r.account,
    borderColor: token("--ink"),
    backgroundColor: token("--ink"),
    borderWidth: 3,
    spanGaps: false,
    tension: 0,
    pointRadius: r.dates.length <= 14 ? 2 : 0,
  });
  const allVals = datasets.flatMap((x) => x.data).filter((v) => v !== null && v !== undefined);
  // Keep the axis readable: clip extreme 3-day spikes (a $1 trial-less spend day can make $2K+).
  const yMax = Math.min(Math.max(d.cpa_target[1] * 1.6, ...allVals.map((v) => Math.ceil(v / 50) * 50)), 900);
  const cfg = {
    type: "line",
    data: { labels: labelsFor(r.dates), datasets },
    options: {
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: true, suggestedMax: yMax, max: yMax, ticks: { callback: tick.money } },
      },
      plugins: {
        targetBand: { range: d.cpa_target, fill: token("--good"), line: token("--good") },
        legend: { onClick: legendToggle("cpt") },
        tooltip: {
          filter: (item) => item.raw !== null && item.raw !== undefined,
          itemSort: (a, b) => b.raw - a.raw,
          callbacks: { label: (c) => ` ${c.dataset.label}: ${fmt.cpt(c.raw)}` },
        },
      },
    },
    plugins: [targetBand],
  };
  if (state.charts.cpt) state.charts.cpt.destroy();
  state.charts.cpt = new Chart($("#cpt-chart"), cfg);
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

function ratioCell(c, band) {
  const pct = c.platform_vs_posthog_pct;
  if (pct === null || pct === undefined) {
    if (c.ratio_flag === "over") return `<span class="ratio-flag" title="Platform reports conversions, PostHog has no trials">no trials</span>`;
    return fmt.none;
  }
  const flag = c.ratio_flag
    ? `<span class="ratio-flag ${c.ratio_flag}" title="Platform reports ${c.ratio_flag === "under" ? "under" : "over"} ${c.ratio_flag === "under" ? band[0] : band[1]}% of PostHog trials">${c.ratio_flag === "under" ? "&darr; low" : "&uarr; high"}</span>`
    : "";
  return `${fmt.pct(pct, 0)}${flag}`;
}

function sumRows(rows) {
  const t = { spend: 0, spend_per_day: 0, trials: 0, paid: 0, platform_conversions: 0, daily_budget: 0, spend_3d: 0, trials_3d: 0 };
  rows.forEach((r) => {
    t.spend += r.spend; t.spend_per_day += r.spend_per_day || 0; t.trials += r.trials; t.paid += r.paid; t.platform_conversions += r.platform_conversions;
    t.spend_3d += r.spend_3d; t.trials_3d += r.trials_3d;
    if (r.status === "ACTIVE") t.daily_budget += r.daily_budget;
  });
  t.cpt_3d = t.trials_3d ? t.spend_3d / t.trials_3d : null;
  t.cost_per_paid = t.paid ? t.spend / t.paid : null;
  t.trial_to_paid = t.trials ? (t.paid / t.trials) * 100 : null;
  t.ratio = t.trials ? (t.platform_conversions / t.trials) * 100 : null;
  return t;
}

function renderTable() {
  const d = state.data;
  if (!d) return;
  const target = d.cpa_target, band = d.ratio_band;
  const { key, dir } = state.sort;
  $$("#camp-table thead th.sortable").forEach((th) => {
    if (th.dataset.key === key) th.setAttribute("aria-sort", dir > 0 ? "ascending" : "descending");
    else th.removeAttribute("aria-sort");
  });
  let html = "";
  GROUPS.forEach((g) => {
    let rows = d.campaigns.filter(g.test);
    if (!rows.length) return;
    if (key) rows = rows.slice().sort(compare(key, dir));
    const t = sumRows(rows);
    html += `<tr class="group-row${g.legacy ? " legacy" : ""}">
      <td colspan="3">${g.legacy ? "&#9888; " : ""}${esc(g.label)} · ${rows.length} campaign${rows.length === 1 ? "" : "s"}</td>
      <td class="num">${fmt.money(t.daily_budget)}</td>
      <td class="num">${fmt.money(t.spend)}</td>
      <td class="num">${fmt.int(t.trials)}</td>
      <td class="num ${cptTone(t.cpt_3d, target)}">${fmt.cpt(t.cpt_3d)}</td>
      <td class="num"></td>
      <td class="num">${fmt.int(t.paid)}</td>
      <td class="num">${fmt.cpt(t.cost_per_paid)}</td>
      <td class="num">${fmt.int(t.platform_conversions)} · ${fmt.pct(t.ratio, 0)}</td>
    </tr>`;
    rows.forEach((c) => {
      const open = state.open.has(c.id);
      const paused = c.status !== "ACTIVE";
      const caveat = c.trials_3d < 3 ? `<div class="caveat">${c.trials_3d === 0 ? "0 trials in 3d" : `n=${c.trials_3d}: thin read`}</div>` : "";
      html += `<tr class="camp-row${c.legacy ? " legacy" : ""}${open ? " is-open" : ""}${paused ? " is-paused" : ""}" data-id="${esc(c.id)}" tabindex="0" aria-expanded="${open}">
        <td><span class="caret" aria-hidden="true">&#9656;</span> ${platformChip(c.platform)}</td>
        <td><span class="strong">${esc(c.name)}</span>${c.legacy ? '<span class="tag legacy-tag">legacy</span>' : ""}<div class="small muted">${esc(c.country)} · ${esc(c.type)} · ${esc(c.bid_strategy || "")}${c.start_date && c.start_date > d.window.start ? ` · live ${fmt.date(c.start_date)}` : ""}</div></td>
        <td>${badge(c.status)}</td>
        <td class="num">${fmt.money(c.daily_budget)}</td>
        <td class="num" title="${fmt.money(c.spend_per_day)} per live day across ${c.active_days} live day${c.active_days === 1 ? "" : "s"} in this window">${fmt.money(c.spend)}</td>
        <td class="num">${fmt.int(c.trials)}</td>
        <td class="num monitor ${cptTone(c.cpt_3d, target)}" title="${fmt.money(c.spend_3d)} / ${c.trials_3d} trials, last 3 days">${fmt.cpt(c.cpt_3d)}${caveat}</td>
        <td class="num ${cptTone(c.cpt_7d, target)}">${fmt.cpt(c.cpt_7d)}</td>
        <td class="num" title="Trial to paid: ${fmt.pct(c.trial_to_paid)}. Recent cohorts are still maturing.">${fmt.int(c.paid)}</td>
        <td class="num">${fmt.cpt(c.cost_per_paid)}</td>
        <td class="num" title="${fmt.int(c.platform_conversions)} platform-reported conversions vs ${c.trials} PostHog trials"><span class="muted">${fmt.int(c.platform_conversions)} ·</span> ${ratioCell(c, band)}</td>
      </tr>`;
      if (open) html += adsetRows(c, target);
    });
  });
  $("#camp-body").innerHTML = html || `<tr><td colspan="11" class="table-empty">No campaigns.</td></tr>`;
  $("#table-sub").textContent = `· ${d.window.label.toLowerCase()}`;
  $("#table-note").textContent = `${d.notes.monitor} Platform conversions are flagged outside ${band[0]}–${band[1]}% of PostHog trials. ${d.notes.adset_allocation}`;
}

function adsetRows(c, target) {
  if (!c.adsets.length) return `<tr class="adset-row"><td></td><td colspan="10" class="muted">No ad sets.</td></tr>`;
  const kind = c.adsets[0].kind || "ad set";
  let html = `<tr class="adset-row"><td></td><td colspan="10" class="small muted">${c.adsets.length} ${esc(kind)}${c.adsets.length === 1 ? "" : "s"} · window totals, estimated split by ${c.adsets[0].allocation === "budget_share" ? "ad set budget" : "even share (no ad group budgets)"}</td></tr>`;
  c.adsets.forEach((a) => {
    html += `<tr class="adset-row${a.status !== "ACTIVE" ? " is-paused" : ""}">
      <td></td>
      <td class="adset-name"><span>${esc(a.name)}</span><div class="small muted truncate" title="${esc(a.targeting || "")}">${esc(a.targeting || "")}</div></td>
      <td>${badge(a.status)}</td>
      <td class="num">${a.daily_budget ? fmt.money(a.daily_budget) : fmt.none}</td>
      <td class="num" title="${fmt.pct(a.share_pct, 0)} apportioned share">${fmt.money(a.spend)}</td>
      <td class="num">${fmt.int(a.trials)}</td>
      <td class="num"></td>
      <td class="num"></td>
      <td class="num">${fmt.int(a.paid)}</td>
      <td class="num">${fmt.cpt(a.cost_per_paid)}</td>
      <td class="num ${cptTone(a.cost_per_trial, target)}" title="Window cost per trial">${fmt.cpt(a.cost_per_trial)} / trial</td>
    </tr>`;
  });
  return html;
}

function toggleRow(id) {
  if (state.open.has(id)) state.open.delete(id); else state.open.add(id);
  renderTable();
}

// ------------------------------------------------------------------ wiring
function wire() {
  $("#win-select").addEventListener("click", (e) => {
    const b = e.target.closest("[data-window]");
    if (b && b.dataset.window !== state.window) load(b.dataset.window);
  });
  $$("#camp-table thead th.sortable").forEach((th) => {
    th.addEventListener("click", () => {
      const k = th.dataset.key;
      if (state.sort.key === k) {
        if (state.sort.dir === -1) state.sort = { key: null, dir: 1 }; // third click: back to default order
        else state.sort.dir = -1;
      } else {
        // text columns start ascending, numbers descending (biggest first)
        state.sort = { key: k, dir: ["name", "country", "status"].includes(k) ? 1 : -1 };
      }
      renderTable();
    });
  });
  const body = $("#camp-body");
  body.addEventListener("click", (e) => {
    const tr = e.target.closest("tr.camp-row");
    if (tr) toggleRow(tr.dataset.id);
  });
  body.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const tr = e.target.closest("tr.camp-row");
    if (!tr) return;
    e.preventDefault();
    const id = tr.dataset.id;
    toggleRow(id);
    const again = body.querySelector(`tr.camp-row[data-id="${CSS.escape(id)}"]`);
    if (again) again.focus();
  });
}

wire();
load(state.window);
