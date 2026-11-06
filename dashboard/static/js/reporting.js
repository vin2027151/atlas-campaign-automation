// Reporting page: one GET /api/reporting/ call renders every section.
import { api, fmt, toast, esc, $, token, platformChip, cptTone, tick, chartDefaults, badge, seriesColors } from "/static/js/common.js";

const charts = [];
let DATA = null;

// --------------------------------------------------------------- helpers
const range = (w) => `${fmt.date(w.start)}–${fmt.date(w.end)}`;

/** Delta chip. goodWhen: "up" | "down" | "neutral". points=true renders "+4.0 pts". */
function deltaHtml(d, { goodWhen = "up", points = false, vs = "" } = {}) {
  if (d === null || d === undefined) return `<span class="kpi-delta na">no comparison</span>`;
  let cls = "flat";
  if (goodWhen !== "neutral" && Math.abs(d) >= 0.5) {
    const good = goodWhen === "up" ? d > 0 : d < 0;
    cls = good ? "up" : "down";
  }
  const arrow = d > 0 ? "▲" : d < 0 ? "▼" : "";
  const txt = points ? `${d > 0 ? "+" : ""}${Number(d).toFixed(1)} pts` : fmt.delta(d);
  return `<span class="kpi-delta ${cls}">${arrow} ${esc(txt)}</span>${vs ? ` <span class="muted">${esc(vs)}</span>` : ""}`;
}

function paceTone(p) {
  if (p === null || p === undefined) return "tone-idle";
  if (p >= 95 && p <= 102) return "tone-good";
  if (p >= 85 && p <= 105) return "tone-watch";
  return "tone-bad";
}

function tile({ label, value, tone = "", sub = "", bar = null, title = "" }) {
  return `<div class="kpi"${title ? ` title="${esc(title)}"` : ""}>
    <div class="kpi-label">${esc(label)}</div>
    <div class="kpi-value num ${tone}">${value}</div>
    ${bar !== null ? `<div class="kpi-bar"><span style="width:${Math.min(100, Math.max(0, bar))}%"></span></div>` : ""}
    <div class="kpi-sub">${sub}</div>
  </div>`;
}

// ------------------------------------------------------------------ KPIs
function renderKpis(d) {
  const k = d.kpis, tgt = d.cpa_target;
  const vsMonth = `vs ${range(k.prior_window)}`;
  const thin = k.cpt_7d.trials < 3 ? ` · <span class="caveat">thin read</span>` : "";
  // Four headline measures. Matured-cohort paid economics live in the account
  // table beside their cohort label (renderAccounts); MTD cost per trial is the
  // account table's Total row.
  const html = [
    tile({ label: "Cost / PostHog trial (7d)", value: fmt.cpt(k.cpt_7d.value), tone: cptTone(k.cpt_7d.value, tgt),
      title: `${fmt.money(k.cpt_7d.spend)} / ${k.cpt_7d.trials} trials, ${range(d.kpis.w7_window)}`,
      sub: `${deltaHtml(k.cpt_7d.delta, { goodWhen: "down", vs: `vs prior 7d (${fmt.cpt(k.cpt_7d.prev)})` })}<br><span class="muted">n=${fmt.int(k.cpt_7d.trials)} trials${thin}</span>` }),
    tile({ label: "PostHog trials (MTD)", value: fmt.int(k.trials_mtd.value),
      sub: deltaHtml(k.trials_mtd.delta, { goodWhen: "up", vs: vsMonth }) }),
    tile({ label: "Spend, month to date", value: fmt.money(k.mtd_spend.value),
      sub: deltaHtml(k.mtd_spend.delta, { goodWhen: "neutral", vs: vsMonth }) }),
    tile({ label: "Projected spend / budget", value: fmt.money(k.projected.value),
      tone: paceTone(k.projected.pace_pct), bar: k.projected.pace_pct,
      sub: `<span class="${paceTone(k.projected.pace_pct)} strong">${fmt.pct(k.projected.pace_pct)}</span> of ${fmt.moneyShort(k.projected.budget)} budget` }),
  ];
  $("#rp-kpis").innerHTML = html.join("");
}

// ---------------------------------------------------------------- pacing
function renderPacing(d) {
  $("#rp-pace-sub").textContent = `day ${d.days_elapsed} of ${d.days_in_month}`;
  const rows = d.pacing.map((p) => {
    const scale = Math.max(p.monthly_budget, p.projected_month_end) * 1.04 || 1;
    const w = (v) => (Math.max(0, v) / scale * 100).toFixed(2) + "%";
    const todayPos = p.budget_to_date / scale * 100;
    const cls = p.status === "over" ? "over" : p.status === "under" ? "under" : "";
    const name = p.key === "total"
      ? `<span class="strong">Total account</span>`
      : `<span class="strong">${platformChip(p.key)} ${esc(p.label)}</span>`;
    const stat = (label, v, extra = "") => `<div class="rp-stat"><div class="label">${label}</div><div class="v ${extra}">${v}</div></div>`;
    const vsPlan = p.month_to_date_spend - p.budget_to_date;
    return `<div class="rp-pace-row">
      <div class="rp-pace-name">${name}
        <div><span class="rp-pace-pct ${paceTone(p.pace_pct)}">${fmt.pct(p.pace_pct)}</span> <span class="muted small">projected pace</span></div>
      </div>
      <div>
        <div class="rp-bar ${cls}" role="img" aria-label="${esc(p.label)}: ${fmt.money(p.month_to_date_spend)} spent, should be ${fmt.money(p.budget_to_date)} today, projected ${fmt.money(p.projected_month_end)} of ${fmt.money(p.monthly_budget)}">
          <div class="proj" style="width:${w(p.projected_month_end)}"></div>
          <div class="fill" style="width:${w(p.month_to_date_spend)}"></div>
          <div class="budget" style="left:${w(p.monthly_budget)}" title="Monthly budget ${fmt.money(p.monthly_budget)}"></div>
          <div class="today${todayPos > 70 ? " flip" : ""}" style="left:${todayPos.toFixed(2)}%" title="Straight-line budget to date ${fmt.money(p.budget_to_date)}"><span>today ${fmt.moneyShort(p.budget_to_date)}</span></div>
        </div>
        <div class="rp-pace-stats">
          ${stat("Monthly budget", fmt.money(p.monthly_budget))}
          ${stat("Spent MTD", fmt.money(p.month_to_date_spend))}
          ${stat("Budget to date", `${fmt.money(p.budget_to_date)} <span class="muted small">(${vsPlan >= 0 ? "+" : "-"}${fmt.money(Math.abs(vsPlan))})</span>`)}
          ${stat("Daily rate, 7d avg", fmt.money(p.daily_rate_7d))}
          ${stat("Daily target", fmt.money(p.daily_target))}
          ${stat("Projected month end", fmt.money(p.projected_month_end), paceTone(p.pace_pct))}
        </div>
      </div>
    </div>`;
  });
  $("#rp-pacing").innerHTML = rows.join("");
}

// ---------------------------------------------------------------- charts
const bandPlugin = {
  id: "targetBand",
  beforeDatasetsDraw(chart, _args, opts) {
    const y = chart.scales.y, area = chart.chartArea;
    if (!y || !opts || !opts.range) return;
    const top = y.getPixelForValue(opts.range[1]), bot = y.getPixelForValue(opts.range[0]);
    const ctx = chart.ctx;
    ctx.save();
    ctx.fillStyle = opts.color;
    ctx.fillRect(area.left, Math.max(area.top, top), area.right - area.left, Math.min(area.bottom, bot) - Math.max(area.top, top));
    ctx.fillStyle = opts.labelColor;
    ctx.font = `600 10px ${token("--font")}`;
    ctx.textAlign = "right";
    ctx.fillText(`target $${opts.range[0]}–$${opts.range[1]}`, area.right - 4, Math.max(area.top, top) - 4);
    ctx.restore();
  },
};

function renderCharts(d) {
  charts.splice(0).forEach((c) => c.destroy());
  const Chart = window.Chart;
  if (!Chart) { toast("Chart.js did not load; charts are unavailable", "warn"); return; }
  chartDefaults();
  const t = d.trends;
  const labels = t.dates.map((x) => fmt.date(x));
  const s1 = token("--series-1"), s3 = token("--series-3");

  charts.push(new Chart($("#rp-chart-volume"), {
    data: {
      labels,
      datasets: [
        { type: "bar", label: "Spend", data: t.spend, yAxisID: "y", backgroundColor: token("--accent-soft"),
          borderColor: token("--accent-line"), borderWidth: 1, order: 2 },
        { type: "line", label: "Trials (PostHog)", data: t.trials, yAxisID: "y1", borderColor: s3,
          backgroundColor: s3, pointRadius: 2, order: 1 },
      ],
    },
    options: {
      scales: {
        x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkipPadding: 12 } },
        y: { position: "left", beginAtZero: true, ticks: { callback: tick.money }, title: { display: true, text: "Spend / day" } },
        y1: { position: "right", beginAtZero: true, grid: { drawOnChartArea: false }, ticks: { callback: tick.int, precision: 0 },
              title: { display: true, text: "Trials / day" } },
      },
      plugins: {
        tooltip: { callbacks: { label: (c) => c.dataset.yAxisID === "y" ? ` Spend ${fmt.money(c.raw)}` : ` Trials ${fmt.int(c.raw)}` } },
      },
    },
  }));

  const pc = { google: token("--google"), meta: token("--meta") };
  charts.push(new Chart($("#rp-chart-cpt"), {
    type: "line",
    plugins: [bandPlugin],
    data: {
      labels,
      datasets: [
        { label: "Account", data: t.cpt_7d.total, borderColor: token("--ink"), backgroundColor: token("--ink"), borderWidth: 2.5, spanGaps: true },
        { label: "Google", data: t.cpt_7d.google, borderColor: pc.google, backgroundColor: pc.google, borderWidth: 1.5, spanGaps: true },
        { label: "Meta", data: t.cpt_7d.meta, borderColor: pc.meta, backgroundColor: pc.meta, borderWidth: 1.5, spanGaps: true },
      ],
    },
    options: {
      scales: {
        x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkipPadding: 12 } },
        y: { suggestedMin: 150, suggestedMax: 400, ticks: { callback: (v) => "$" + v } },
      },
      plugins: {
        targetBand: { range: t.cpa_target, color: token("--good-soft"), labelColor: token("--good") },
        tooltip: { callbacks: { label: (c) => ` ${c.dataset.label} ${fmt.cpt(c.raw)}` } },
      },
    },
  }));
}

// ------------------------------------------------------ campaign charts
// Daily spend by campaign and rolling 3-day cost per trial (moved here from the
// old Spend page). Hiding a campaign in one legend hides it in both charts.
const hiddenCampaigns = new Set();
const campaignCharts = { daily: null, cpt: null };

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
/** One stable color per campaign: the series tokens plus tinted and shaded variants. */
function campaignColors(ids) {
  const base = seriesColors();
  const surface = token("--surface") || "#ffffff";
  const ink = token("--ink") || "#000000";
  const palette = [...base, ...base.map((c) => mix(c, surface, 0.45)), ...base.map((c) => mix(c, ink, 0.3))];
  const out = {};
  ids.forEach((id, i) => { out[id] = palette[i % palette.length]; });
  return out;
}

function legendToggle(e, item, legend) {
  const id = legend.chart.data.datasets[item.datasetIndex].campaignId;
  if (!id) {
    legend.chart.setDatasetVisibility(item.datasetIndex, !legend.chart.isDatasetVisible(item.datasetIndex));
    legend.chart.update();
    return;
  }
  if (hiddenCampaigns.has(id)) hiddenCampaigns.delete(id); else hiddenCampaigns.add(id);
  Object.values(campaignCharts).forEach((ch) => {
    if (!ch) return;
    ch.data.datasets.forEach((ds, i) => { if (ds.campaignId === id) ch.setDatasetVisibility(i, !hiddenCampaigns.has(id)); });
    ch.update();
  });
}

function renderCampaignCharts(d) {
  const Chart = window.Chart;
  const cc = d.campaign_charts;
  if (!Chart || !cc) return;
  const winTxt = cc.window.label.toLowerCase();
  $("#rp-daily-sub").textContent = `${winTxt}, ${range(cc.window)} · platform-reported spend`;
  $("#rp-cpt3-sub").textContent = `${winTxt}, ${range(cc.window)} · spend ÷ PostHog trials`;
  const labels = cc.daily.dates.map((x) => fmt.date(x));
  const colors = campaignColors(cc.daily.series.map((s) => s.campaign_id));
  const name = (s) => s.name + (s.legacy ? " (legacy)" : "");

  const daily = new Chart($("#rp-chart-daily"), {
    type: "bar",
    data: {
      labels,
      datasets: cc.daily.series.map((s) => ({
        label: name(s), campaignId: s.campaign_id, data: s.spend, backgroundColor: colors[s.campaign_id],
        borderWidth: 0, stack: "spend", hidden: hiddenCampaigns.has(s.campaign_id),
      })),
    },
    options: {
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { maxRotation: 0, autoSkipPadding: 12 } },
        y: { stacked: true, beginAtZero: true, ticks: { callback: tick.money } },
      },
      plugins: {
        legend: { onClick: legendToggle },
        tooltip: {
          filter: (item) => item.raw > 0,
          itemSort: (a, b) => b.raw - a.raw,
          callbacks: {
            label: (c) => ` ${c.dataset.label}: ${fmt.money(c.raw)}`,
            footer: (items) => (items.length ? `Total ${fmt.money(cc.daily.totals[items[0].dataIndex])}` : ""),
          },
        },
      },
    },
  });

  const r = cc.rolling_cpt;
  const datasets = r.series.map((s) => ({
    label: name(s), campaignId: s.campaign_id, data: s.cost_per_trial,
    borderColor: colors[s.campaign_id], backgroundColor: colors[s.campaign_id],
    borderDash: s.legacy ? [5, 3] : [], spanGaps: false, tension: 0, pointRadius: 0,
    hidden: hiddenCampaigns.has(s.campaign_id),
  }));
  datasets.push({ label: "Account", data: r.account, borderColor: token("--ink"), backgroundColor: token("--ink"),
    borderWidth: 3, spanGaps: false, tension: 0, pointRadius: 0 });
  const vals = datasets.flatMap((x) => x.data).filter((v) => v !== null && v !== undefined);
  // Clip extreme 3-day spikes (a trial-less stretch can make $2K+) so the band stays readable.
  const yMax = Math.min(Math.max(cc.cpa_target[1] * 1.6, ...vals.map((v) => Math.ceil(v / 50) * 50)), 900);
  const cpt = new Chart($("#rp-chart-cpt3"), {
    type: "line",
    plugins: [bandPlugin],
    data: { labels, datasets },
    options: {
      scales: {
        x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkipPadding: 12 } },
        y: { beginAtZero: true, max: yMax, ticks: { callback: tick.money } },
      },
      plugins: {
        targetBand: { range: cc.cpa_target, color: token("--good-soft"), labelColor: token("--good") },
        legend: { onClick: legendToggle },
        tooltip: {
          filter: (item) => item.raw !== null && item.raw !== undefined,
          itemSort: (a, b) => b.raw - a.raw,
          callbacks: { label: (c) => ` ${c.dataset.label}: ${fmt.cpt(c.raw)}` },
        },
      },
    },
  });
  campaignCharts.daily = daily;
  campaignCharts.cpt = cpt;
  charts.push(daily, cpt);
}

// -------------------------------------------------------------- accounts
function renderAccounts(d) {
  const tgt = d.cpa_target;
  $("#rp-acct-sub").textContent = `month to date, ${range(d.kpis.mtd_window)}`;
  const k = d.kpis;
  const prior = `vs prior cohort, trials ${range(k.cohort_prior_window)}`;
  // Total row carries the matured-cohort comparison that used to sit in the KPI tiles.
  const cohDelta = (a, which) => {
    if (a.key !== "total") return "";
    const chip = which === "cpp"
      ? deltaHtml(k.cost_per_paid.delta, { goodWhen: "down" })
      : deltaHtml(k.trial_to_paid.delta, { goodWhen: "up", points: true });
    return `<span class="rp-cell-delta" title="${esc(prior)}">${chip}</span>`;
  };
  $("#rp-coh-head").textContent = `Matured trial cohort*, trials ${range(k.cohort_window)}`;
  $("#rp-acct").innerHTML = d.accounts.map((a) => `
    <tr class="${a.key === "total" ? "total" : ""}">
      <td>${a.key === "total" ? "Total" : `${platformChip(a.key)} ${esc(a.label)}`}</td>
      <td class="num">${fmt.money(a.spend)}</td>
      <td class="num">${fmt.int(a.trials)}</td>
      <td class="num ${cptTone(a.cost_per_trial, tgt)}">${fmt.cpt(a.cost_per_trial)}</td>
      <td class="num">${fmt.int(a.cohort_paid)}</td>
      <td class="num"${a.key === "total" ? ` title="${esc(`${k.cost_per_paid.paid} paid of ${k.cost_per_paid.trials} trials`)}"` : ""}>${fmt.cpt(a.cohort_cost_per_paid)}${cohDelta(a, "cpp")}</td>
      <td class="num">${fmt.pct(a.cohort_trial_to_paid)}${cohDelta(a, "t2p")}</td>
      <td class="num">${fmt.pct(a.share_spend)}</td>
      <td class="num">${fmt.pct(a.share_trials)}</td>
    </tr>`).join("");
  $("#rp-acct-foot").textContent = `* Paid columns use the matured trial cohort (trials ${range(k.cohort_window)}); Total-row changes are ${prior}. Trials need 7–14 days to convert, so month-to-date trials are still maturing (${k.paid_mtd.lag_days}-day lag): ${fmt.int(k.paid_mtd.value)} paid so far, ${fmt.int(k.paid_mtd.paid_30d)} paid from last-30-day trials.`;
}

// ----------------------------------------------------------------- trust
function renderTrust(d) {
  $("#rp-trust").innerHTML = d.trust.map((t) => `
    <div class="card rp-trust-card ${esc(t.tone)}">
      <div class="card-head"><h3 class="card-title">${platformChip(t.platform)} ${esc(t.label)} <span class="card-sub">${range(t)}</span></h3>
        ${badge(t.tone === "good" ? "good" : t.tone === "bad" ? "bad" : "watch", t.tone === "good" ? "Trustworthy" : t.tone === "bad" ? "Do not use" : "Over-reports")}</div>
      <div class="card-body rp-trust-item">
        <div class="rp-ratio tone-${t.tone === "good" ? "good" : t.tone === "bad" ? "bad" : "watch"}">${fmt.pct(t.ratio_pct, 0)}</div>
        <div><strong>${esc(t.note)}</strong></div>
        <dl class="dl">
          <dt>Platform reports</dt><dd>${fmt.int(t.platform_conversions)} conv.</dd>
          <dt>PostHog trials</dt><dd>${fmt.int(t.posthog_trials)}</dd>
          <dt>Platform CPA</dt><dd>${fmt.cpt(t.platform_cpa)}</dd>
          <dt>True cost / trial</dt><dd class="${cptTone(t.true_cpt, d.cpa_target)}">${fmt.cpt(t.true_cpt)}</dd>
        </dl>
      </div>
    </div>`).join("");
}

// --------------------------------------------------------------- changes
const KIND_LABEL = { cpt: "High CPT", pace: "Pacing", paused: "Paused", resumed: "Resumed", launched: "Launched", legacy: "Legacy" };
const TONE_BADGE = { bad: "bad", watch: "watch", good: "good", info: "info", idle: "idle" };

function renderChanges(d) {
  $("#rp-chg-sub").textContent = `${range(d.kpis.w7_window)} · alerts: 7-day CPT > $350 on ≥ $1,500 spend, pace outside 85–105%`;
  if (!d.changes.length) { $("#rp-changes").innerHTML = `<li class="muted">Nothing changed this week.</li>`; return; }
  $("#rp-changes").innerHTML = d.changes.map((c) => `
    <li>${badge(TONE_BADGE[c.tone] || "idle", KIND_LABEL[c.kind] || c.kind)}
      ${c.platform ? platformChip(c.platform) : ""}
      <span>${esc(c.text)}</span></li>`).join("");
}

// ------------------------------------------------------------------ boot
async function load() {
  try {
    DATA = await api("/api/reporting/");
  } catch (e) {
    toast("Could not load reporting: " + e.message, "error");
    $("#rp-kpis").innerHTML = `<div class="callout bad span-all">Reporting data failed to load: ${esc(e.message)}</div>`;
    return;
  }
  const d = DATA;
  renderKpis(d);
  renderPacing(d);
  renderAccounts(d);
  renderTrust(d);
  renderChanges(d);
  renderCharts(d);
  renderCampaignCharts(d);
}

$("#rp-print").addEventListener("click", () => window.print());
// Chart.js canvases need a resize to fit the print layout and again afterwards.
const resizeAll = () => charts.forEach((c) => c.resize());
window.addEventListener("beforeprint", resizeAll);
window.addEventListener("afterprint", resizeAll);
$("#rp-export").addEventListener("click", () => toast("CSV export downloading", "info"));

load();
