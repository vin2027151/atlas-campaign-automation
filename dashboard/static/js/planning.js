// Campaign planning page: analyze -> command brief -> review the diff -> publish by hand.
//
// Talks to /api/planning (api/planning.py) and, for the media picker, /api/media.
// `?mock=1` swaps the network for the inline fixtures at the bottom of this file so
// every state can be exercised without the backend. The real API is the default.
//   ?mock=1&llm=off     jobs end in "LLM not configured"
//   ?mock=1&busy=1      a draft job is already running on load (attach + 409 path)
//   ?mock=1&drift=1     publish is refused with a drift list
//   ?mock=1&slow=1      jobs overrun their estimate
//   ?mock=1&media=404   media library endpoint missing
//   ?mock=1&empty=1     no analysis, no changesets yet
import { api as realApi, fmt, toast, confirmButton, platformChip, tabs, esc, $, $$ } from "/static/js/common.js";

const BASE = "/api/planning";
const QS = new URLSearchParams(location.search);
const MOCK = QS.get("mock") === "1";
const call = MOCK ? mockApi : realApi;

const S = {
  cfg: null,
  mode: "sample",
  eta: { analyze: 20, draft: 30, revise: 25 },
  limits: { max_chars: 4000, calls_left_today: null },
  analysis: null,
  snapshots: {},            // id -> summary {id, taken_at, reason, counts}
  latestSnapshotId: null,
  changesets: [],           // summaries
  cs: null,                 // full selected changeset
  view: null,               // version number shown
  reviewTab: "yaml",
  reviewed: false,          // the "I reviewed the diff" checkbox
  lastPublish: {},          // changeset id -> publish result from this session (refusals included)
  media: [], mediaState: "loading", mediaErr: "", mediaSel: [], mediaQ: "",
  job: null, jobBase: null, ticker: null, polling: false, slotEl: null,
  yaml: {},                 // snapshot id -> YAML text
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const plural = (n, one, many) => `${fmt.int(n)} ${n === 1 ? one : (many || one + "s")}`;
const isFinal = (st) => st === "done" || st === "error";

function secs(v) {
  if (v === null || v === undefined || !isFinite(v)) return fmt.none;
  const s = Math.max(0, Math.round(Number(v)));
  if (s < 60) return `${s} s`;
  return `${Math.floor(s / 60)} min ${s % 60 ? (s % 60) + " s" : ""}`.trim();
}
function moneySigned(v) {
  if (v === null || v === undefined || !isFinite(v)) return fmt.none;
  const n = Number(v);
  if (Math.abs(n) < 0.005) return "$0";
  return (n > 0 ? "+" : "") + fmt.money(n, { cents: Math.round(n) !== n });
}
function show(el, on) { if (el) el.hidden = !on; }
function setErr(id, msg) { const el = $(id); if (!el) return; el.textContent = msg || ""; el.hidden = !msg; }

const ERR_FOR = { analyze: "#an-error", draft: "#brief-error", revise: "#rv-error" };
const KIND_LABEL = { analyze: "Analysis", draft: "Draft", revise: "Revision" };

// ------------------------------------------------------------------ data
async function loadHome() {
  const d = await call(`${BASE}/`);
  S.cfg = d.config || null;
  S.mode = d.mode || (d.config && d.config.mode) || "sample";
  S.eta = Object.assign({}, S.eta, d.eta || {});
  S.limits = Object.assign({}, S.limits, d.limits || {});
  if (d.latest_snapshot) {
    S.snapshots[d.latest_snapshot.id] = d.latest_snapshot;
    S.latestSnapshotId = d.latest_snapshot.id;
  }
  if (d.latest_analysis) S.analysis = d.latest_analysis;
  if (Array.isArray(d.changesets)) S.changesets = d.changesets;
  return d;
}

async function ensureSnapshot(id) {
  if (!id || S.snapshots[id]) return;
  try {
    const d = await call(`${BASE}/snapshots`);
    (d.snapshots || []).forEach((s) => { S.snapshots[s.id] = s; });
  } catch (e) { /* the analysis still renders without the counts */ }
  if (!S.snapshots[id]) S.snapshots[id] = { id, missing: true };
  renderAnalysis();
}

async function loadChangesets() {
  const d = await call(`${BASE}/changesets`);
  S.changesets = d.changesets || [];
}

async function selectCs(id, { version, quiet } = {}) {
  try {
    const d = await call(`${BASE}/changesets/${encodeURIComponent(id)}`);
    S.cs = d.changeset;
    S.view = version || S.cs.current_version || (S.cs.versions.length ? S.cs.versions[S.cs.versions.length - 1].n : null);
    S.reviewed = false;
    setErr("#rv-error", "");
    try { history.replaceState(null, "", location.pathname + location.search + "#" + encodeURIComponent(id)); } catch (e) { /* ignore */ }
  } catch (e) {
    if (!quiet) toast(e.message, "error");
    return;
  }
  renderHistory();
  renderReview();
  renderPublish();
}

async function loadMedia() {
  try {
    const d = await call("/api/media/?status=approved");
    S.media = (d.assets || []).filter((a) => !a.status || a.status === "approved");
    S.mediaState = "ok";
  } catch (e) {
    S.mediaState = e.status === 404 ? "missing" : "error";
    S.mediaErr = e.message;
  }
  renderMedia();
}

async function getText(path) {
  if (MOCK) return mockText(path);
  const res = await fetch(path, { headers: { Accept: "text/yaml, text/plain, */*" } });
  const text = await res.text();
  if (!res.ok) {
    let msg = res.statusText || "Request failed";
    try { const j = JSON.parse(text); msg = j.error || j.detail || msg; } catch (e) { /* not JSON */ }
    throw new Error(msg);
  }
  return text;
}

// ------------------------------------------------------------------ jobs
function slotFor(kind) { return $(`[data-job-slot="${kind}"]`); }

function elapsedOf(job) {
  if (job.elapsed_seconds !== undefined && job.elapsed_seconds !== null) return Number(job.elapsed_seconds);
  if (job.started_at) return Math.max(0, (Date.now() - new Date(job.started_at).getTime()) / 1000);
  return 0;
}

function attachJob(job) {
  if (!job || !job.id) return;
  if (S.job && S.job.id === job.id) return;
  $$("[data-job-slot]").forEach((el) => { el.hidden = true; el.innerHTML = ""; });
  S.job = job;
  S.jobBase = { elapsed: elapsedOf(job), at: performance.now() };
  const slot = slotFor(job.kind) || slotFor("analyze");
  slot.className = "pl-job";
  slot.hidden = false;
  slot.innerHTML = `
    <div class="pl-bar" role="progressbar" aria-label="${esc(KIND_LABEL[job.kind] || "Job")} progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><span></span></div>
    <div class="pl-job-line">
      <span class="pl-job-stage" role="status" aria-live="polite">${esc(job.stage || "Queued")}</span>
      <span class="pl-job-time"></span>
    </div>`;
  S.slotEl = slot;
  setErr(ERR_FOR[job.kind], "");
  syncButtons();
  clearInterval(S.ticker);
  S.ticker = setInterval(tick, 250);
  tick();
  if (!S.polling) poll();
  if (job.kind === "revise") show($("#rv-form"), false);
  slot.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function tick() {
  const job = S.job, slot = S.slotEl;
  if (!job || !slot) return;
  const eta = Number(job.eta_seconds || S.eta[job.kind] || 20);
  let elapsed = S.jobBase.elapsed;
  if (!isFinal(job.status)) elapsed += (performance.now() - S.jobBase.at) / 1000;
  let pct = Math.min(95, (elapsed / eta) * 100);
  if (job.status === "done") pct = 100;
  const bar = $(".pl-bar", slot), fill = $(".pl-bar > span", slot);
  fill.style.width = pct.toFixed(1) + "%";
  bar.setAttribute("aria-valuenow", String(Math.round(pct)));
  bar.setAttribute("aria-valuetext", `${Math.round(pct)}%, ${secs(elapsed)} of about ${secs(eta)}`);
  const over = !isFinal(job.status) && elapsed > eta * 1.1;
  $(".pl-job-time", slot).textContent = job.status === "done"
    ? `Done in ${secs(job.elapsed_seconds !== undefined && job.elapsed_seconds !== null ? job.elapsed_seconds : elapsed)}`
    : `${secs(elapsed)} of ~${secs(eta)}${over ? ", taking longer than usual" : ""}`;
  const stageText = job.status === "error" ? "Failed" : job.status === "done" ? "Done" : (job.stage || (job.status === "queued" ? "Queued" : "Working"));
  const stageEl = $(".pl-job-stage", slot);
  if (stageEl.textContent !== stageText) stageEl.textContent = stageText;
}

async function poll() {
  S.polling = true;
  let fails = 0;
  let job = S.job;
  while (job && !isFinal(job.status)) {
    await sleep(1000);
    try {
      const d = await call(`${BASE}/jobs/${encodeURIComponent(job.id)}`);
      fails = 0;
      job = d.job;
      S.job = job;
      S.jobBase = { elapsed: elapsedOf(job), at: performance.now() };
    } catch (e) {
      fails += 1;
      if (fails >= 5) {
        job = Object.assign({}, job, { status: "error", error: `Lost track of the job: ${e.message}` });
        S.job = job;
      }
    }
  }
  S.polling = false;
  await finishJob(job);
}

async function finishJob(job) {
  clearInterval(S.ticker);
  S.ticker = null;
  tick();
  const slot = S.slotEl;
  if (slot) slot.classList.add(job.status === "done" ? "is-done" : "is-error");
  S.job = null;
  syncButtons();

  if (job.status === "error") {
    const msg = job.error || "The job failed.";
    setErr(ERR_FOR[job.kind] || "#an-error", msg);
    toast(`${KIND_LABEL[job.kind] || "Job"} failed: ${msg}`, "error");
    if (slot) setTimeout(() => { if (!S.job) slot.hidden = true; }, 1500);
    if (job.kind === "revise") show($("#rv-form"), true);
    refreshSide();
    return;
  }

  const r = job.result || {};
  try {
    if (job.kind === "analyze") {
      const d = r.analysis_id ? await call(`${BASE}/analyses/${encodeURIComponent(r.analysis_id)}`)
                              : await call(`${BASE}/analyses/latest`);
      S.analysis = d.analysis;
      await loadHome().catch(() => {});
      renderAll();
      toast("Analysis ready");
    } else {
      await loadHome().catch(() => {});
      if (job.kind === "revise") { $("#rv-text").value = ""; updateCounter("#rv-text", "#rv-count"); }
      await selectCs(r.changeset_id || (S.cs && S.cs.id), { version: r.version });
      renderAll();
      toast(job.kind === "draft" ? `Changeset ${r.changeset_id || ""} v${r.version || 1} drafted` : `Revision v${r.version || ""} ready`);
      const sec = $("#sec-review");
      if (sec) sec.scrollIntoView({ block: "start", behavior: "smooth" });
    }
  } catch (e) {
    setErr(ERR_FOR[job.kind], e.message);
    toast(e.message, "error");
  }
  if (slot) setTimeout(() => { if (!S.job) slot.hidden = true; }, 1600);
}

async function startJob(kind, path, body) {
  if (S.job) { toast("A job is already running; wait for it to finish.", "warn"); return false; }
  setErr(ERR_FOR[kind], "");
  try {
    const d = await call(path, { method: "POST", body: body || {} });
    attachJob(d.job);
    return true;
  } catch (e) {
    if (e.status === 409) {
      toast("Another planning job is already running. Following it now.", "warn");
      if (e.data && e.data.busy && e.data.busy.id) { attachJob(e.data.busy); return false; }
      try {
        const h = await loadHome();
        if (h.busy) attachJob(h.busy);
      } catch (e2) { /* nothing to attach to */ }
      return false;
    }
    setErr(ERR_FOR[kind], e.message);
    toast(e.message, "error");
    return false;
  }
}

async function refreshSide() {
  try { await loadHome(); } catch (e) { return; }
  renderHistory();
  renderEtas();
}

// ---------------------------------------------------------------- render
function renderAll() {
  renderEtas();
  renderAnalysis();
  renderHistory();
  renderConnections();
  renderReview();
  renderPublish();
  syncButtons();
}

function renderEtas() {
  $("#an-eta").textContent = `Estimated ${secs(S.eta.analyze)}`;
  $("#brief-eta").textContent = `Estimated ${secs(S.eta.draft)}`;
  $("#rv-eta").textContent = `Estimated ${secs(S.eta.revise)}`;
  const left = S.limits.calls_left_today;
  $("#brief-calls").textContent = left === null || left === undefined ? "Plain English in, API-shaped changes out"
    : `${plural(left, "model call")} left today`;
  const pill = $("#pl-mode-pill");
  pill.textContent = `Mode: ${S.mode}`;
  updateCounter("#brief-text", "#brief-count");
  updateCounter("#rv-text", "#rv-count");
}

function updateCounter(inputSel, countSel) {
  const n = $(inputSel).value.length, max = S.limits.max_chars || 4000;
  const el = $(countSel);
  el.textContent = `${fmt.int(n)} / ${fmt.int(max)}`;
  el.classList.toggle("tone-bad", n > max);
  el.classList.toggle("tone-watch", n <= max && n > max * 0.9);
}

function syncButtons() {
  const busy = !!S.job, max = S.limits.max_chars || 4000;
  $("#an-run").disabled = busy;
  const bl = $("#brief-text").value.trim().length;
  $("#brief-submit").disabled = busy || !bl || $("#brief-text").value.length > max;
  const rl = $("#rv-text").value.trim().length;
  $("#rv-submit").disabled = busy || !rl || $("#rv-text").value.length > max || !S.cs;
  $$("[data-revise-open]").forEach((b) => { b.disabled = busy || !canRevise(); });
}

// --- 1. analysis
const COUNT_LABELS = [["campaigns", "campaign"], ["ad_groups", "ad group"], ["ad_sets", "ad set"], ["ads", "ad"], ["keywords", "keyword"], ["negatives", "negative"]];

function renderAnalysis() {
  const a = S.analysis, box = $("#an-result");
  if (!a) {
    box.innerHTML = `<p class="muted mt-0">No analysis yet. Analyze pulls every campaign, budget, bid strategy, ad group, ad set, keyword, negative and ad into a saved state document, checks it against the 30-day plan, then asks Opus 5.5 for recommendations, each traced from the plan to the test or data behind it.</p>`;
    return;
  }
  const bullets = (list) => (list && list.length)
    ? `<ul class="pl-bullets">${list.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>`
    : `<p class="muted small mt-0">Nothing to report.</p>`;
  const recs = (a.recommendations || []).length
    ? `<ul class="pl-recs">${a.recommendations.map(recHTML).join("")}</ul>`
    : `<p class="muted small mt-0">No recommendations.</p>`;
  const facts = a.facts || [];
  box.innerHTML = `
    <div class="stack">
      <div class="pl-meta-line">
        <span class="strong ink-2">${esc(a.id)}</span>
        <span>${esc(fmt.datetime(a.created_at))}</span>
        ${a.model ? `<span>${esc(a.model)}${a.effort ? ` · effort ${esc(a.effort)}` : ""}</span>` : ""}
        ${a.duration_s !== undefined && a.duration_s !== null ? `<span>${esc(secs(a.duration_s))}</span>` : ""}
      </div>
      ${(a.items && a.items.length) ? itemsHTML(a) : `<div class="pl-cols">
        <div class="pl-col"><h3>Where the plan stands</h3>${bullets(a.plan_status)}</div>
        <div class="pl-col"><h3>What the account shows</h3>${bullets(a.state_summary)}</div>
        <div class="pl-col"><h3>Recommendations</h3>${recs}</div>
      </div>`}
      ${facts.length ? `<details class="pl-details">
        <summary>Deterministic plan checks (${facts.length})</summary>
        <ul class="pl-bullets small">${facts.map((f) => `<li><span class="tag">${esc(String(f.kind || "").replace(/_/g, " "))}</span> ${platformChip(f.platform)} ${f.campaign ? `<span class="strong">${esc(f.campaign)}</span>` : ""}
          ${f.note ? esc(f.note) : ""}${f.planned !== undefined && f.planned !== null ? ` <span class="muted">(planned ${esc(fmtVal(f.planned))}, actual ${esc(fmtVal(f.actual))})</span>` : ""}</li>`).join("")}</ul>
      </details>` : ""}
      ${snapshotHTML(a.snapshot_id)}
    </div>`;
  wireSnapshot(box, a.snapshot_id);
  if (a.snapshot_id && !S.snapshots[a.snapshot_id]) ensureSnapshot(a.snapshot_id);
}

const ITEM_ROWS = [["plan", "Plan"], ["running", "Running"], ["testing", "Testing"], ["evidence", "Evidence"], ["recommendation", "Recommendation"]];

function itemsHTML(a) {
  const reads = {};
  (a.test_reads || []).forEach((r) => { reads[r.test_id] = r; });
  const rows = a.items.map((it, i) => {
    const pri = String(it.priority || "low").toLowerCase();
    const plat = it.platform === "both" ? platformChip("google") + platformChip("meta") : platformChip(it.platform);
    const camp = it.campaign_id ? `<a href="/campaigns#${encodeURIComponent(it.campaign_id)}" class="mono small">${esc(it.campaign_id)}</a>` : "";
    const r = it.test_id ? reads[it.test_id] : null;
    const test = it.test_id ? `<span class="tag" title="${esc(r ? r.verdict_text : "")}">Test ${esc(it.test_id)}${r ? " · " + esc(String(r.verdict || "").replace(/_/g, " ")) : ""}</span>` : "";
    const lines = ITEM_ROWS.filter(([k]) => it[k]).map(([k, label]) =>
      `<div class="pl-item-row${k === "recommendation" ? " is-rec" : ""}"><div class="pl-item-label">${label}</div><div class="pl-item-text">${esc(it[k])}</div></div>`).join("");
    const research = it.research ? `<details class="pl-item-more"><summary>Further research</summary><p>${esc(it.research)}</p></details>` : "";
    return `<li class="pl-item">
      <div class="pl-item-head"><span class="pl-item-n">${i + 1}</span><span class="pl-item-title">${esc(it.title || "Recommendation")}</span>
        <span class="pl-item-tags"><span class="badge pri-${esc(pri)}">${esc(pri)}</span>${plat}${test}${camp}</span></div>
      <div class="pl-item-body">${lines}</div>${research}
    </li>`;
  }).join("");
  const notes = (a.notes || []).length
    ? `<div class="pl-notes"><div class="label">Other notes</div><ul class="pl-bullets">${a.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>` : "";
  const stats = (a.test_reads || []).length ? `<details class="pl-details">
      <summary>Test statistics, computed by code (${a.test_reads.length})</summary>
      <div class="table-wrap"><table class="table small"><thead><tr><th>Test</th><th>Rule</th><th class="num">Observed</th><th class="num">95% interval</th><th>Sample</th><th>Minimums</th><th>Verdict</th></tr></thead><tbody>
      ${a.test_reads.map((t) => `<tr><td><span class="strong">${esc(t.test_id)}</span> ${esc(t.name || "")}</td><td>${esc(t.win_rule || "")}</td>
        <td class="num">${esc(fmtVal(t.observed))}</td><td class="num">${t.ci95 ? esc(fmtVal(t.ci95[0])) + " to " + esc(fmtVal(t.ci95[1])) : fmt.none}</td>
        <td>${esc(t.sample || "")}</td><td>${t.minimums_met ? "met" : "not met"}</td><td>${esc(String(t.verdict || "").replace(/_/g, " "))}</td></tr>`).join("")}
      </tbody></table></div></details>` : "";
  return `<ol class="pl-items">${rows}</ol>${notes}${stats}`;
}

function fmtVal(v) {
  if (v === null || v === undefined) return fmt.none;
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function recHTML(r) {
  const pri = String(r.priority || "low").toLowerCase();
  const plat = r.platform === "both" ? platformChip("google") + platformChip("meta") : platformChip(r.platform);
  const camp = r.campaign_id ? `<a href="/campaigns#${encodeURIComponent(r.campaign_id)}" class="mono">${esc(r.campaign_id)}</a>` : "";
  return `<li>
    <div class="pl-rec-meta"><span class="badge pri-${esc(pri)}">${esc(pri)}</span>${plat}${camp}</div>
    <div>${esc(r.text)}</div>
  </li>`;
}

function snapshotHTML(id) {
  if (!id) return "";
  const s = S.snapshots[id] || {};
  const counts = s.counts || {};
  const tags = COUNT_LABELS.filter(([k]) => counts[k] !== undefined)
    .map(([k, one]) => `<span class="tag">${esc(plural(counts[k], one))}</span>`).join("");
  const isLatest = S.latestSnapshotId === id;
  return `<div class="pl-snap">
    <div class="pl-snap-head">
      <div>
        <div class="label">State document used${isLatest ? "" : ` <span class="caveat">not the latest pull</span>`}</div>
        <span class="pl-snap-id">${esc(id)}</span>
        <span class="muted small">${s.taken_at ? "· taken " + esc(fmt.datetime(s.taken_at)) : ""}${s.reason ? " · " + esc(s.reason) : ""}</span>
      </div>
      <div class="row">
        <button class="btn btn-sm" type="button" data-snap-view aria-expanded="false" aria-controls="snap-yaml-${esc(id)}">View state document</button>
        <a class="btn btn-sm" data-snap-dl href="${BASE}/snapshots/${encodeURIComponent(id)}/yaml" download="${esc(id)}.yaml">Download state document</a>
      </div>
    </div>
    ${tags ? `<div class="pl-counts">${tags}</div>` : (s.missing ? `<div class="muted small mt-2">Snapshot summary not found.</div>` : "")}
    <div class="mt-2" id="snap-yaml-${esc(id)}" hidden>
      <pre class="pl-code" tabindex="0" aria-label="State document ${esc(id)} (YAML)"><code>Loading&hellip;</code></pre>
    </div>
  </div>`;
}

function wireSnapshot(root, id) {
  const btn = $("[data-snap-view]", root), dl = $("[data-snap-dl]", root);
  if (!btn) return;
  const panel = root.querySelector(`[id="snap-yaml-${CSS.escape(id)}"]`);
  btn.addEventListener("click", async () => {
    const open = btn.getAttribute("aria-expanded") !== "true";
    btn.setAttribute("aria-expanded", String(open));
    btn.textContent = open ? "Hide state document" : "View state document";
    panel.hidden = !open;
    if (!open) return;
    const code = $("code", panel);
    if (S.yaml[id] === undefined) {
      try { S.yaml[id] = await getText(`${BASE}/snapshots/${encodeURIComponent(id)}/yaml`); }
      catch (e) { code.textContent = `Could not load the state document: ${e.message}`; return; }
    }
    code.textContent = S.yaml[id];
  });
  if (MOCK && dl) {
    dl.addEventListener("click", (ev) => {
      ev.preventDefault();
      const blob = new Blob([mockText(`${BASE}/snapshots/${id}/yaml`)], { type: "text/yaml" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${id}.yaml`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    });
  }
}

// --- 2. media picker
function renderMedia() {
  const box = $("#media-picker"), filter = $("#media-filter");
  if (S.mediaState === "loading") return;
  if (S.mediaState !== "ok") {
    filter.hidden = true;
    box.innerHTML = `<p class="muted small mt-0">${S.mediaState === "missing"
      ? "The media library isn't available yet. You can still type media IDs (IMG-0001, VID-0001, H5-0001) into the brief."
      : `Could not load the media library: ${esc(S.mediaErr)}`}</p>`;
    renderMediaChips();
    return;
  }
  if (!S.media.length) {
    filter.hidden = true;
    box.innerHTML = `<p class="muted small mt-0">No approved media yet. Approve assets on the <a href="/media">Media</a> page to tag them here.</p>`;
    renderMediaChips();
    return;
  }
  filter.hidden = S.media.length < 7;
  const q = S.mediaQ.trim().toLowerCase();
  const list = S.media.filter((m) => !q || `${m.id} ${m.title || ""} ${m.kind || ""} ${m.aspect || ""}`.toLowerCase().includes(q));
  box.innerHTML = list.length ? list.map((m) => {
    const on = S.mediaSel.includes(m.id);
    const thumb = m.thumb_url || (m.kind === "image" ? m.file_url : null);
    return `<button type="button" class="pl-asset" data-media="${esc(m.id)}" aria-pressed="${on}" title="${esc(m.description || m.title || m.id)}">
      <span class="pl-thumb">${thumb ? `<img src="${esc(thumb)}" alt="" loading="lazy">` : esc(m.kind || "asset")}</span>
      <span class="id">${esc(m.id)}</span>
      <span class="t">${esc(m.title || "")}</span>
      <span class="muted small">${esc([m.kind, m.aspect].filter(Boolean).join(" · "))}</span>
    </button>`;
  }).join("") : `<p class="muted small mt-0">No approved media match "${esc(S.mediaQ)}".</p>`;
  renderMediaChips();
}

function renderMediaChips() {
  const box = $("#media-selected");
  box.innerHTML = S.mediaSel.length
    ? S.mediaSel.map((id) => `<span class="pl-chip">${esc(id)}<button type="button" data-unmedia="${esc(id)}" aria-label="Remove ${esc(id)}">&times;</button></span>`).join("")
    : `<span class="muted small">No media tagged.</span>`;
}

function toggleMedia(id) {
  const i = S.mediaSel.indexOf(id);
  if (i >= 0) S.mediaSel.splice(i, 1); else S.mediaSel.push(id);
  renderMedia();
}

// --- 3. review
function currentVersion() {
  if (!S.cs) return null;
  return (S.cs.versions || []).find((v) => v.n === S.view) || null;
}
function canRevise() { return !!S.cs && !["published", "discarded", "drafting"].includes(S.cs.status); }

const STATUS_LABEL = { ready: "Ready", invalid: "Invalid", published: "Published", drafting: "Drafting", discarded: "Discarded" };
function csBadge(status) { return `<span class="badge ${esc(status)}">${esc(STATUS_LABEL[status] || status)}</span>`; }

function renderReview() {
  const head = $("#rv-head"), box = $("#rv-content");
  const cs = S.cs, v = currentVersion();
  if (cs && !v) {
    head.innerHTML = csBadge(cs.status);
    box.innerHTML = `<div class="stack">
      <div><div class="pl-title">${esc(cs.title || cs.id)}</div>
        <div class="pl-meta-line mt-2"><span class="mono">${esc(cs.id)}</span><span>${esc(fmt.datetime(cs.created_at))}</span><span>no version</span></div></div>
      ${cs.directive ? `<div><h3 class="pl-sub-h">Brief</h3><div class="pl-directive">${esc(cs.directive)}</div></div>` : ""}
      <div class="callout ${cs.last_error ? "bad" : "watch"} small">${cs.last_error
        ? `The draft failed before producing a version: ${esc(cs.last_error)}`
        : "No version has been produced yet."} Submit the brief again to retry.</div>
    </div>`;
    show($("#rv-form"), false);
    return;
  }
  if (!cs || !v) {
    head.innerHTML = "";
    box.innerHTML = `<p class="muted mt-0">Submit a brief, or pick a changeset from the history, to review its diff here.</p>`;
    show($("#rv-form"), false);
    return;
  }
  const versions = cs.versions || [];
  head.innerHTML = `${csBadge(cs.status)}
    <div class="btn-group pl-versions" role="group" aria-label="Version">
      ${versions.map((x) => `<button type="button" class="btn btn-sm${x.n === S.view ? " active" : ""}" data-version="${x.n}" aria-pressed="${x.n === S.view}"
        title="Version ${x.n}${x.n === cs.current_version ? " (current)" : ""}">v${x.n}</button>`).join("")}
    </div>`;

  const validation = (v.validation || []).slice().sort((a, b) => (a.level === "error" ? 0 : 1) - (b.level === "error" ? 0 : 1));
  const nErr = validation.filter((x) => x.level === "error").length;
  const nWarn = validation.length - nErr;
  const list = (items, empty) => (items && items.length)
    ? `<ul class="pl-bullets">${items.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : `<p class="muted small mt-0">${empty}</p>`;
  const diff = v.diff || {};
  const oldView = S.view !== cs.current_version;

  box.innerHTML = `<div class="stack">
    <div>
      <div class="pl-title">${esc(cs.title || cs.id)}</div>
      <div class="pl-meta-line mt-2">
        <span class="mono">${esc(cs.id)}</span>
        <span>v${v.n}${oldView ? ` <span class="caveat">older version; current is v${cs.current_version}</span>` : ""}</span>
        <span>${esc(fmt.datetime(v.created_at || cs.created_at))}</span>
        ${v.model ? `<span>${esc(v.model)}${v.duration_s ? " · " + esc(secs(v.duration_s)) : ""}</span>` : ""}
        ${v.snapshot_id ? `<span>diffed against <span class="mono">${esc(v.snapshot_id)}</span></span>` : ""}
      </div>
    </div>
    ${cs.directive ? `<div><h3 class="pl-sub-h">Brief</h3><div class="pl-directive">${esc(cs.directive)}</div>
      ${(cs.media_ids || []).length ? `<div class="pl-chips mt-2">${cs.media_ids.map((m) => `<span class="pl-chip" style="padding-right:8px">${esc(m)}</span>`).join("")}</div>` : ""}</div>` : ""}
    ${v.revision_note ? `<div><h3 class="pl-sub-h">Revision note for v${v.n}</h3><div class="pl-directive">${esc(v.revision_note)}</div></div>` : ""}
    <div class="pl-grid-2">
      <div><h3 class="pl-sub-h">Summary</h3>${list(v.summary, "No summary.")}</div>
      <div><h3 class="pl-sub-h">Assumptions</h3>${list(v.assumptions, "None stated.")}</div>
    </div>
    ${(v.questions || []).length ? `<div class="callout watch"><h3 class="pl-sub-h">Open questions</h3>${list(v.questions)}</div>` : ""}
    <div>
      <h3 class="pl-sub-h">Validation${validation.length ? ` · ${plural(nErr, "error")}, ${plural(nWarn, "warning")}` : ""}</h3>
      ${validation.length ? `<ul class="pl-valid">${validation.map((x) => `<li class="${x.level === "error" ? "error" : "warn"}">
          <span class="op">${esc(x.op || (x.level === "error" ? "error" : "warn"))}</span>${esc(x.message)}</li>`).join("")}</ul>`
        : `<p class="tone-good small mt-0">Passed: no errors or warnings.</p>`}
    </div>
    <div>
      <div class="row-between"><h3 class="pl-sub-h mt-0">Diff against the current state</h3></div>
      ${totalsHTML(diff)}
      ${diffTableHTML(diff.rows || [])}
    </div>
    <div class="pl-review-tabs">
      <div class="tabs" role="tablist" aria-label="Changeset detail">
        <button class="tab${S.reviewTab === "yaml" ? " active" : ""}" type="button" data-tab="yaml" id="rv-tab-yaml" aria-controls="rv-panel-yaml">API changes (YAML)</button>
        <button class="tab${S.reviewTab === "text" ? " active" : ""}" type="button" data-tab="text" id="rv-tab-text" aria-controls="rv-panel-text">State diff</button>
      </div>
      <div class="mt-2" data-panel="yaml" id="rv-panel-yaml" role="tabpanel" aria-labelledby="rv-tab-yaml">
        <div class="pl-code-tools"><button class="btn btn-sm" type="button" data-copy-yaml>Copy YAML</button></div>
        <pre class="pl-code" tabindex="0" aria-label="Changeset YAML, version ${v.n}"><code>${esc(v.yaml || "")}</code></pre>
      </div>
      <div class="mt-2" data-panel="text" id="rv-panel-text" role="tabpanel" aria-labelledby="rv-tab-text">
        ${diff.text_diff ? `<pre class="pl-code" tabindex="0" aria-label="State document diff"><code class="pl-diff-lines">${textDiffHTML(diff.text_diff)}</code></pre>`
          : `<p class="muted small mt-0">No state differences.</p>`}
      </div>
    </div>
    <div class="row">
      <button class="btn" type="button" data-revise-open ${canRevise() && !S.job ? "" : "disabled"}>Revise</button>
      <span class="muted small">${canRevise() ? "Notes plus this YAML go back to Opus 5.5 and come back as a new version." : `This changeset is ${esc(cs.status)}; it can't be revised.`}</span>
    </div>
  </div>`;
  if (!canRevise()) show($("#rv-form"), false);
  tabs($(".pl-review-tabs", box), (name) => { S.reviewTab = name; });
}

function totalsHTML(diff) {
  const s = diff.summary || {};
  const d = s.daily_budget_delta || {};
  const rows = diff.rows || [];
  if (!rows.length) return `<p class="muted small">No changes against the current state.</p>`;
  const bits = [
    `<span><b>${fmt.int(s.creates || 0)}</b> create${s.creates === 1 ? "" : "s"}</span>`,
    `<span><b>${fmt.int(s.updates || 0)}</b> update${s.updates === 1 ? "" : "s"}</span>`,
    `<span><b>${fmt.int(s.removes || 0)}</b> remove${s.removes === 1 ? "" : "s"}</span>`,
  ];
  const plat = Object.keys(d);
  if (plat.length) {
    bits.push(`<span>Daily budget: ${plat.map((p) => {
      const n = Number(d[p]) || 0;
      return `${platformChip(p)} <b class="${n > 0 ? "tone-watch" : n < 0 ? "tone-good" : ""}">${esc(moneySigned(n))}/day</b>`;
    }).join(" &nbsp;")}</span>`);
  }
  return `<div class="pl-totals mt-2">${bits.join("")}</div>`;
}

const PLATFORM_NAME = { google: "Google Ads", meta: "Meta" };
function diffTableHTML(rows) {
  if (!rows.length) return "";
  const groups = {};
  rows.forEach((r) => { (groups[r.platform] = groups[r.platform] || []).push(r); });
  const order = ["google", "meta"].concat(Object.keys(groups).filter((k) => k !== "google" && k !== "meta"));
  const cell = (val, disp) => (disp !== undefined && disp !== null && disp !== "") ? String(disp) : fmtVal(val);
  const body = order.filter((p) => groups[p]).map((p) => {
    const g = groups[p];
    return `<tr class="group"><td colspan="5">${platformChip(p)} ${esc(PLATFORM_NAME[p] || p)} <span class="muted">· ${plural(g.length, "change")}</span></td></tr>` +
      g.map((r) => {
        const act = String(r.action || "update").toLowerCase();
        const before = cell(r.before, r.display_before), after = cell(r.after, r.display_after);
        const hasBefore = act !== "create" && r.before !== null && r.before !== undefined;
        return `<tr class="act-${esc(act)}">
          <td class="ent"><span class="tag">${esc(String(r.entity_type || "").replace(/_/g, " "))}</span>
            <div class="ent-name">${esc(r.entity_name || r.entity_id || "")}</div>
            ${r.entity_id && r.entity_id !== r.entity_name ? `<div class="ent-id">${esc(r.entity_id)}</div>` : ""}</td>
          <td class="fld">${esc(r.field || "")}</td>
          <td class="val">${hasBefore ? `<span class="before">${esc(before)}</span>` : `<span class="muted">${fmt.none}</span>`}</td>
          <td class="val">${act === "remove" ? `<span class="after">removed</span>` : `<span class="after">${esc(after)}</span>`}</td>
          <td class="act"><span class="badge plain act-${esc(act)}">${esc(act)}</span>${r.op ? `<span class="op muted mono small">${esc(r.op)}</span>` : ""}</td>
        </tr>`;
      }).join("");
  }).join("");
  return `<div class="table-wrap mt-2"><table class="table compact pl-diff">
    <caption class="sr-only">Changes by platform: entity, field, before, after and action</caption>
    <thead><tr><th scope="col">Entity</th><th scope="col">Field</th><th scope="col">Before</th><th scope="col">After</th><th scope="col">Action</th></tr></thead>
    <tbody>${body}</tbody></table></div>`;
}

function textDiffHTML(text) {
  return String(text).split("\n").map((line) => {
    let cls = "ln";
    if (line.startsWith("+++") || line.startsWith("---")) cls = "ln ln-file";
    else if (line.startsWith("@@")) cls = "ln ln-hunk";
    else if (line.startsWith("+")) cls = "ln ln-add";
    else if (line.startsWith("-")) cls = "ln ln-del";
    return `<span class="${cls}">${line ? esc(line) : " "}</span>`;
  }).join("");
}

// --- 4. publish
function renderPublish() {
  const box = $("#pb-body");
  const cs = S.cs, v = currentVersion();
  if (cs && !v) {
    const can = !["published", "discarded"].includes(cs.status);
    box.innerHTML = `<p class="pl-publish-line mt-0">Manual. Deterministic code, no AI in the loop.</p>
      <p class="muted">${esc(cs.id)} has no version to publish.</p>
      ${can ? `<div class="pl-pb-actions"><span class="spacer"></span><button class="btn btn-danger btn-sm" type="button" id="pb-discard" data-confirm-label="Confirm discard?">Discard changeset</button></div>` : ""}`;
    const dz = $("#pb-discard");
    if (dz) confirmButton(dz, () => doDiscard(cs.id));
    return;
  }
  if (!cs || !v) {
    box.innerHTML = `<p class="pl-publish-line mt-0">Manual. Deterministic code, no AI in the loop.</p>
      <p class="muted">Nothing to publish yet. Draft a changeset and review its diff first.</p>`;
    return;
  }
  const n = v.n;
  const isCurrent = n === cs.current_version;
  const ready = cs.status === "ready" && isCurrent;
  const live = S.mode === "live";
  let why = "";
  if (cs.status === "invalid") why = `v${cs.current_version} has validation errors. Revise it until there are none.`;
  else if (cs.status === "published") why = "This changeset is already published.";
  else if (cs.status === "discarded") why = "This changeset was discarded.";
  else if (cs.status === "drafting") why = "This changeset is still drafting.";
  else if (!isCurrent) why = `You are viewing v${n}. Only the current version, v${cs.current_version}, can be published.`;
  const result = S.lastPublish[cs.id] || cs.published || cs.last_publish;
  const terminal = cs.status === "published" || cs.status === "discarded";

  box.innerHTML = `
    <p class="pl-publish-line mt-0">Manual. Deterministic code, no AI in the loop. Sends exactly version v${n} shown above.</p>
    <p class="muted small">It re-pulls the account state first and refuses if any value it changes no longer matches the diff's "before". ${live
      ? `<span class="tone-watch strong">Mode is live: requests go to the platforms only if the server also has ATLAS_ALLOW_LIVE=1.</span>`
      : `Mode is ${esc(S.mode)}: live sending is off, so it applies to the local sample account.`}</p>
    ${why ? `<div class="callout ${cs.status === "invalid" ? "bad" : "watch"} small">${esc(why)}${!isCurrent && cs.versions.some((x) => x.n === cs.current_version)
      ? ` <button class="btn btn-sm" type="button" data-version="${cs.current_version}">Show v${cs.current_version}</button>` : ""}</div>` : ""}
    ${terminal ? "" : `<label class="check"><input type="checkbox" id="pb-check" ${S.reviewed && ready ? "checked" : ""} ${ready ? "" : "disabled"}> I reviewed the diff for v${n}</label>`}
    <div class="pl-pb-actions">
      ${terminal ? "" : `<button class="btn btn-primary" type="button" id="pb-publish" data-confirm-label="Confirm publish of v${n}?" ${ready && S.reviewed ? "" : "disabled"}>Publish v${n}</button>`}
      <span class="spacer"></span>
      ${terminal ? "" : `<button class="btn btn-danger btn-sm" type="button" id="pb-discard" data-confirm-label="Confirm discard?">Discard changeset</button>`}
    </div>
    ${result ? publishResultHTML(result) : ""}`;

  const check = $("#pb-check"), btn = $("#pb-publish"), discard = $("#pb-discard");
  if (check) check.addEventListener("change", () => {
    S.reviewed = check.checked;
    if (btn) btn.disabled = !(ready && S.reviewed);
  });
  if (btn) confirmButton(btn, () => doPublish(cs.id, n));
  if (discard) confirmButton(discard, () => doDiscard(cs.id));
}

function publishResultHTML(p) {
  const results = p.results || [];
  const drift = p.drift || [];
  const applied = results.filter((r) => r.status === "applied").length;
  const failed = results.filter((r) => r.status === "failed").length;
  const skipped = results.filter((r) => r.status === "skipped").length;
  let head;
  if (drift.length) head = `<div class="callout bad"><span class="strong">Refused.</span> The account drifted from the reviewed "before" values, so nothing was applied. Revise against a fresh analysis.</div>`;
  else if (p.ok) head = `<div class="callout good"><span class="strong">Published.</span> ${plural(applied, "operation")} applied in ${esc(p.mode || S.mode)} mode.</div>`;
  else head = `<div class="callout bad"><span class="strong">Publish failed.</span> ${plural(applied, "operation")} applied, ${failed} failed, ${skipped} skipped.${p.error ? " " + esc(p.error) : ""}</div>`;
  const verified = p.verified
    ? `<b class="tone-good">Yes</b>` : `<b class="tone-bad">No</b>${drift.length ? ' <span class="muted">(nothing applied)</span>' : ""}`;
  return `<div class="stack-sm" aria-live="polite">
    <h3 class="pl-sub-h mt-4">Publish result</h3>
    ${head}
    <dl class="pl-kv">
      <dt>Verified against a fresh state pull</dt><dd>${verified}</dd>
      <dt>Mode</dt><dd>${esc(p.mode || S.mode)}</dd>
      ${p.pre_snapshot_id ? `<dt>State before</dt><dd><code>${esc(p.pre_snapshot_id)}</code></dd>` : ""}
      ${p.post_snapshot_id ? `<dt>State after</dt><dd><code>${esc(p.post_snapshot_id)}</code></dd>` : ""}
      ${p.published_at || p.finished_at ? `<dt>When</dt><dd>${esc(fmt.datetime(p.published_at || p.finished_at))}</dd>` : ""}
    </dl>
    ${drift.length ? `<h3 class="pl-sub-h mt-2">Drift</h3>
      <div class="table-wrap"><table class="table compact"><thead><tr><th scope="col">Op</th><th scope="col">Field</th><th scope="col">Expected before</th><th scope="col">Actual now</th></tr></thead>
      <tbody>${drift.map((d) => `<tr><td class="mono">${esc(d.op)}</td><td class="mono">${esc(d.field)}</td><td>${esc(fmtVal(d.expected_before))}</td><td class="tone-bad strong">${esc(fmtVal(d.actual))}</td></tr>`).join("")}</tbody></table></div>` : ""}
    ${results.length ? `<h3 class="pl-sub-h mt-2">Operations</h3><ul class="pl-results">${results.map(resultRowHTML).join("")}</ul>` : ""}
  </div>`;
}

function resultRowHTML(r) {
  const req = r.request || {};
  const st = String(r.status || "skipped").toLowerCase();
  const json = (o) => esc(JSON.stringify(o, null, 2));
  return `<li>
    <div class="pl-res-head">
      <span class="badge ${esc(st)}">${esc(st)}</span>
      <span class="op">${esc(r.op || "")}</span>
      <span class="req">${esc(req.method || "")} ${esc(req.url || "")}</span>
    </div>
    ${r.message ? `<div class="small ${st === "failed" ? "tone-bad" : "muted"} mt-2">${esc(r.message)}</div>` : ""}
    <details class="pl-details">
      <summary>Request and response</summary>
      <div class="stack-sm">
        <div><div class="label">Request</div><pre class="pl-code sm"><code>${esc(req.method || "")} ${esc(req.url || "")}${req.headers ? "\n" + json(req.headers) : ""}${req.body !== undefined ? "\n\n" + json(req.body) : ""}</code></pre></div>
        <div><div class="label">Response</div><pre class="pl-code sm"><code>${r.response !== undefined && r.response !== null ? json(r.response) : "(none)"}</code></pre></div>
      </div>
    </details>
  </li>`;
}

async function doPublish(id, n) {
  let p = null;
  try {
    const d = await call(`${BASE}/changesets/${encodeURIComponent(id)}/publish`, { method: "POST", body: { version: n, confirm: true } });
    p = d.publish || d;
  } catch (e) {
    if (e.data && e.data.publish) p = e.data.publish;
    else throw e;
  }
  S.lastPublish[id] = p;
  if (p.ok) toast(`Published ${id} v${n}`);
  else if ((p.drift || []).length) toast(`Publish refused: ${plural(p.drift.length, "value")} drifted. Nothing was applied.`, "error");
  else toast("Publish failed. See the operation list.", "error");
  await loadHome().catch(() => {});
  await selectCs(id, { version: n, quiet: true });
  renderAll();
}

async function doDiscard(id) {
  const d = await call(`${BASE}/changesets/${encodeURIComponent(id)}/discard`, { method: "POST", body: {} });
  if (d.changeset) S.cs = d.changeset;
  toast(`Discarded ${id}`);
  await loadChangesets().catch(() => {});
  renderAll();
}

// --- side
function renderHistory() {
  const ul = $("#hist-list");
  const list = S.changesets.slice().sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")) || String(b.id).localeCompare(String(a.id)));
  $("#hist-sub").textContent = list.length ? plural(list.length, "changeset") : "";
  if (!list.length) { ul.innerHTML = `<li class="muted" style="padding: var(--s3) var(--s4)">No changesets yet.</li>`; return; }
  ul.innerHTML = list.map((c) => {
    const sel = S.cs && S.cs.id === c.id;
    const counts = [
      typeof c.ops === "number" ? plural(c.ops, "op") : "",
      c.errors ? `<span class="tone-bad">${plural(c.errors, "error")}</span>` : "",
      c.warnings ? `<span class="tone-watch">${plural(c.warnings, "warning")}</span>` : "",
    ].filter(Boolean).join(" · ");
    return `<li><button type="button" class="pl-hist-btn" data-cs="${esc(c.id)}" aria-current="${sel}">
      <span class="pl-hist-top"><span class="id">${esc(c.id)}</span>${csBadge(c.status)}${c.current_version ? `<span class="muted small">v${esc(c.current_version)}</span>` : `<span class="muted small">no version</span>`}</span>
      <span class="pl-hist-title">${esc(c.title || "(untitled)")}</span>
      <span class="pl-hist-meta">${esc(fmt.datetime(c.created_at))}${counts ? " · " + counts : ""}</span>
    </button></li>`;
  }).join("");
}

const CRED_LABELS = {
  api_version: "API version", developer_token: "Developer token", client_id: "Client ID", client_secret: "Client secret",
  refresh_token: "Refresh token", login_customer_id: "Login customer (MCC)", customer_id: "Customer ID",
  app_id: "App ID", app_secret: "App secret", access_token: "Access token", ad_account_id: "Ad account",
  page_id: "Page ID", instagram_actor_id: "Instagram actor ID",
};
function renderConnections() {
  const box = $("#conn-body"), c = S.cfg;
  if (!c) { box.innerHTML = `<p class="muted mt-0">No platform config returned.</p>`; return; }
  const mode = c.mode || S.mode;
  $("#conn-sub").textContent = `mode ${mode}`;
  const kv = (obj, skip) => `<dl class="pl-kv">${Object.keys(obj || {}).filter((k) => !skip.includes(k) && (typeof obj[k] !== "object" || obj[k] === null))
    .map((k) => `<dt>${esc(CRED_LABELS[k] || k.replace(/_/g, " "))}</dt><dd>${esc(obj[k] === null || obj[k] === "" ? fmt.none : obj[k])}</dd>`).join("")}</dl>`;
  const g = c.google_ads || c.google || {}, m = c.meta || {};
  const perms = m.required_permissions || [];
  box.innerHTML = `
    <div class="callout ${mode === "live" ? "watch" : ""} small">${mode === "live"
      ? "Mode is <b>live</b>. Requests leave this server only when ATLAS_ALLOW_LIVE=1 is also set."
      : `Live sending is off. Mode is <b>${esc(mode)}</b>: publish applies to the local sample account and shows the request it would send.`}</div>
    <div class="pl-conn"><h3>${platformChip("google")} Google Ads</h3>${kv(g, [])}</div>
    <div class="pl-conn"><h3>${platformChip("meta")} Meta</h3>${kv(m, ["required_permissions", "media_access"])}
      ${perms.length ? `<div class="label mt-2">Required permissions</div><div class="pl-tags mt-2">${perms.map((p) => `<span class="tag mono">${esc(p)}</span>`).join("")}</div>` : ""}
      ${m.media_access ? `<div class="label mt-2">Media access</div><div class="small ink-2">${esc(m.media_access)}</div>` : ""}
    </div>
    <p class="muted small">Example credentials only, masked by the server. Real values live outside the repo.</p>`;
}

// ----------------------------------------------------------------- wiring
function wire() {
  $("#an-run").addEventListener("click", () => startJob("analyze", `${BASE}/analyze`, {}));

  const bt = $("#brief-text");
  bt.addEventListener("input", () => { updateCounter("#brief-text", "#brief-count"); syncButtons(); });
  bt.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); $("#brief-form").requestSubmit(); } });
  $("#brief-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = bt.value.trim();
    if (!text || bt.value.length > (S.limits.max_chars || 4000) || S.job) return;
    await startJob("draft", `${BASE}/changesets`, { directive: text, media_ids: S.mediaSel.slice() });
  });

  $("#media-picker").addEventListener("click", (e) => {
    const b = e.target.closest("[data-media]");
    if (b) toggleMedia(b.dataset.media);
  });
  $("#media-selected").addEventListener("click", (e) => {
    const b = e.target.closest("[data-unmedia]");
    if (b) toggleMedia(b.dataset.unmedia);
  });
  $("#media-filter").addEventListener("input", (e) => { S.mediaQ = e.target.value; renderMedia(); });

  $("#sec-review").addEventListener("click", async (e) => {
    const vb = e.target.closest("[data-version]");
    if (vb) { setView(Number(vb.dataset.version)); return; }
    if (e.target.closest("[data-revise-open]")) {
      show($("#rv-form"), true);
      $("#rv-text").focus();
      return;
    }
    if (e.target.closest("[data-copy-yaml]")) {
      const v = currentVersion();
      try { await copyText(v ? v.yaml || "" : ""); toast("YAML copied"); } catch (err) { toast("Copy failed: " + err.message, "error"); }
    }
  });
  $("#sec-publish").addEventListener("click", (e) => {
    const vb = e.target.closest("[data-version]");
    if (vb) setView(Number(vb.dataset.version));
  });

  const rt = $("#rv-text");
  rt.addEventListener("input", () => { updateCounter("#rv-text", "#rv-count"); syncButtons(); });
  rt.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); $("#rv-form").requestSubmit(); }
    if (e.key === "Escape") { show($("#rv-form"), false); const b = $("[data-revise-open]"); if (b) b.focus(); }
  });
  $("#rv-cancel").addEventListener("click", () => { show($("#rv-form"), false); const b = $("[data-revise-open]"); if (b) b.focus(); });
  $("#rv-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!S.cs || S.job) return;
    const text = rt.value.trim();
    if (!text || rt.value.length > (S.limits.max_chars || 4000)) return;
    await startJob("revise", `${BASE}/changesets/${encodeURIComponent(S.cs.id)}/revise`, { text });
  });

  $("#hist-list").addEventListener("click", (e) => {
    const b = e.target.closest("[data-cs]");
    if (b) selectCs(b.dataset.cs);
  });
}

function setView(n) {
  if (!S.cs || !S.cs.versions.some((v) => v.n === n)) return;
  S.view = n;
  S.reviewed = false;
  renderReview();
  renderPublish();
  syncButtons();
  const b = $(`#rv-head [data-version="${n}"]`);
  if (b) b.focus();
}

async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  const ok = document.execCommand("copy");
  ta.remove();
  if (!ok) throw new Error("clipboard unavailable");
}

async function init() {
  if (MOCK) show($("#pl-mock-note"), true);
  wire();
  renderEtas();
  loadMedia();
  let home;
  try {
    home = await loadHome();
  } catch (e) {
    const el = $("#pl-load-error");
    el.textContent = e.status === 404
      ? "The planning API isn't available yet (GET /api/planning/ returned 404). Add ?mock=1 to the URL to preview this page with fixtures."
      : `Could not load planning data: ${e.message}`;
    el.hidden = false;
    $("#an-result").innerHTML = "";
    renderAll();
    $("#an-run").disabled = true;
    $("#brief-submit").disabled = true;
    return;
  }
  renderAll();
  const hash = decodeURIComponent((location.hash || "").slice(1));
  const want = (hash && S.changesets.some((c) => c.id === hash)) ? hash
    : (S.changesets.slice().sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")))[0] || {}).id;
  if (want) await selectCs(want, { quiet: true });
  if (home.busy && !isFinal(home.busy.status)) attachJob(home.busy);
}

// =================================================================== MOCK
// Fixtures shaped like PLANNING-SPEC.md. Only used with ?mock=1.
function mockApi(path, { method, body } = {}) {
  const M = mockState();
  method = method || (body !== undefined ? "POST" : "GET");
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const fail = (status, msg, data) => { const e = new Error(msg); e.status = status; e.data = Object.assign({ ok: false, error: msg }, data || {}); return e; };
  return new Promise((resolve, reject) => setTimeout(() => {
    try { resolve(clone(route())); } catch (e) { reject(e); }
  }, 120 + Math.random() * 120));

  function route() {
    const p = path.replace(/\?.*$/, "");
    const q = new URLSearchParams(path.split("?")[1] || "");
    let m;
    if (p === "/api/media/") {
      if (QS.get("media") === "404") throw fail(404, "Not Found");
      const st = q.get("status");
      return { ok: true, assets: M.media.filter((a) => !st || a.status === st), counts: {} };
    }
    if (p === `${BASE}/` && method === "GET") {
      return { ok: true, mode: "sample", config: M.config, latest_snapshot: M.snapshots[M.snapshots.length - 1] || null,
        latest_analysis: M.analyses[M.analyses.length - 1] || null, changesets: M.changesets.map(summ),
        eta: M.eta, busy: runningJob(), limits: { max_chars: 4000, calls_left_today: M.callsLeft } };
    }
    if (p === `${BASE}/analyze` && method === "POST") return { ok: true, job: newJob("analyze", {}) };
    if ((m = p.match(/\/jobs\/([^/]+)$/))) {
      const j = M.jobs[m[1]];
      if (!j) throw fail(404, "job not found");
      return { ok: true, job: jobView(j) };
    }
    if (p === `${BASE}/analyses/latest`) return { ok: true, analysis: M.analyses[M.analyses.length - 1] || null };
    if ((m = p.match(/\/analyses\/([^/]+)$/))) {
      const a = M.analyses.find((x) => x.id === m[1]);
      if (!a) throw fail(404, "analysis not found");
      return { ok: true, analysis: a };
    }
    if (p === `${BASE}/snapshots`) return { ok: true, snapshots: M.snapshots.slice().reverse() };
    if ((m = p.match(/\/snapshots\/([^/]+)$/))) {
      const s = M.snapshots.find((x) => x.id === m[1]);
      if (!s) throw fail(404, "snapshot not found");
      return { ok: true, snapshot: s };
    }
    if (p === `${BASE}/changesets` && method === "POST") {
      const dir = String((body || {}).directive || "").trim();
      if (!dir) throw fail(400, "directive is required");
      if (dir.length > 4000) throw fail(400, "directive is over 4,000 characters");
      return { ok: true, job: newJob("draft", { directive: dir, media_ids: (body || {}).media_ids || [] }) };
    }
    if (p === `${BASE}/changesets`) return { ok: true, changesets: M.changesets.map(summ) };
    if ((m = p.match(/\/changesets\/([^/]+)$/))) return { ok: true, changeset: getCs(m[1]) };
    if ((m = p.match(/\/changesets\/([^/]+)\/revise$/))) {
      const cs = getCs(m[1]);
      if (["published", "discarded"].includes(cs.status)) throw fail(400, `changeset is ${cs.status}`);
      if (!String((body || {}).text || "").trim()) throw fail(400, "text is required");
      return { ok: true, job: newJob("revise", { cs: cs.id, text: body.text }) };
    }
    if ((m = p.match(/\/changesets\/([^/]+)\/discard$/))) {
      const cs = getCs(m[1]);
      if (cs.status === "published") throw fail(400, "published changesets can't be discarded");
      cs.status = "discarded";
      return { ok: true, changeset: cs };
    }
    if ((m = p.match(/\/changesets\/([^/]+)\/publish$/))) {
      const cs = getCs(m[1]);
      if (!body || body.confirm !== true) throw fail(400, "confirm: true is required");
      if (cs.status !== "ready") throw fail(400, `changeset is ${cs.status}, not ready`);
      if (body.version !== cs.current_version) throw fail(400, `only the current version v${cs.current_version} can be published`);
      const v = cs.versions.find((x) => x.n === body.version);
      if (QS.get("drift") === "1") {
        const pub = { ok: false, mode: "sample", pre_snapshot_id: newSnap("publish").id, post_snapshot_id: null, verified: false, results: [],
          drift: [{ op: "op1", field: "amount_micros", expected_before: 450000000, actual: 500000000 },
                  { op: "op4", field: "status", expected_before: "ACTIVE", actual: "PAUSED" }] };
        throw fail(409, "state drifted since the diff was computed; nothing applied", { publish: pub });
      }
      const pre = newSnap("publish");
      const results = v.diff.rows.filter((r, i, a) => a.findIndex((x) => x.op === r.op) === i).map((r) => opResult(r));
      const post = newSnap("publish-verify");
      const pub = { ok: true, mode: "sample", pre_snapshot_id: pre.id, post_snapshot_id: post.id, drift: [], results, verified: true, published_at: new Date().toISOString() };
      cs.status = "published";
      cs.published = pub;
      return { ok: true, publish: pub };
    }
    throw fail(404, `mock: no route for ${method} ${path}`);
  }

  function getCs(id) {
    const cs = M.changesets.find((x) => x.id === id);
    if (!cs) throw fail(404, `changeset ${id} not found`);
    return cs;
  }
  function summ(cs) {
    const v = cs.versions.find((x) => x.n === cs.current_version) || {};
    const val = v.validation || [];
    return { id: cs.id, title: cs.title, status: cs.status, current_version: cs.current_version, created_at: cs.created_at,
      ops: new Set(((v.diff || {}).rows || []).map((r) => r.op)).size,
      errors: val.filter((x) => x.level === "error").length, warnings: val.filter((x) => x.level === "warn").length };
  }
  function runningJob() {
    const j = Object.values(M.jobs).find((x) => !isFinal(jobView(x).status));
    return j ? jobView(j) : null;
  }
  function newJob(kind, args) {
    if (runningJob()) throw fail(409, "a planning job is already running");
    M.callsLeft -= 1;
    const id = "JOB-" + String(++M.seq).padStart(4, "0");
    const eta = M.eta[kind];
    const dur = QS.get("llm") === "off" ? 2.5 : eta * (QS.get("slow") === "1" ? 1.7 : 0.85);
    M.jobs[id] = { id, kind, args, t0: Date.now(), eta, dur, applied: false };
    return jobView(M.jobs[id]);
  }
  function jobView(j) {
    const el = (Date.now() - j.t0) / 1000;
    const stages = j.kind === "analyze" ? ["Pulling account state", "Comparing to plan", "Asking Opus 5.5"]
      : ["Pulling account state", "Asking Opus 5.5", "Validating", "Computing diff"];
    const out = { id: j.id, kind: j.kind, status: "running", started_at: new Date(j.t0).toISOString(), finished_at: null,
      eta_seconds: j.eta, elapsed_seconds: Math.round(el * 10) / 10, result: null, error: null,
      stage: stages[Math.min(stages.length - 1, Math.floor((el / j.dur) * stages.length))] };
    if (el < 0.6) { out.status = "queued"; out.stage = "Queued"; }
    if (el >= j.dur) {
      out.elapsed_seconds = Math.round(j.dur * 10) / 10;
      out.finished_at = new Date(j.t0 + j.dur * 1000).toISOString();
      if (QS.get("llm") === "off") {
        out.status = "error";
        out.stage = "Asking Opus 5.5";
        out.error = "LLM not configured: set ATLAS_LLM_CMD or ANTHROPIC_API_KEY on the server (or ATLAS_LLM_MODE=stub for fixtures).";
      } else {
        out.status = "done";
        if (!j.applied) { j.result = applyJob(j); j.applied = true; }
        out.result = j.result;
      }
    }
    return out;
  }
  function applyJob(j) {
    if (j.kind === "analyze") {
      const snap = newSnap("analyze");
      const a = mockAnalysis("AN-" + String(M.analyses.length + 1).padStart(4, "0"), snap.id);
      M.analyses.push(a);
      return { analysis_id: a.id };
    }
    const snap = M.snapshots[M.snapshots.length - 1];
    if (j.kind === "draft") {
      const id = "CS-" + String(M.changesets.length + 1).padStart(4, "0");
      const cs = mockChangeset(id, { title: "Draft from brief: budget shift + new Meta ad", directive: j.args.directive, media_ids: j.args.media_ids,
        status: "ready", versions: [mockVersion(1, snap.id, { brand: 300, warn: true, media: j.args.media_ids[0] || "IMG-0002" })] });
      M.changesets.push(cs);
      return { changeset_id: id, version: 1 };
    }
    const cs = M.changesets.find((x) => x.id === j.args.cs);
    const n = cs.versions.length + 1;
    cs.versions.push(mockVersion(n, snap.id, { brand: 330 - n * 5, warn: false, note: j.args.text, media: (cs.media_ids || [])[0] || "IMG-0002" }));
    cs.current_version = n;
    cs.status = "ready";
    return { changeset_id: cs.id, version: n };
  }
  function newSnap(reason) {
    const d = new Date();
    const p = (x) => String(x).padStart(2, "0");
    let id = `SNAP-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
    while (M.snapshots.some((s) => s.id === id)) id += "b";
    const s = { id, taken_at: d.toISOString(), reason, counts: { campaigns: 13, ad_groups: 9, ad_sets: 12, ads: 52, keywords: 64, negatives: 6 } };
    M.snapshots.push(s);
    return s;
  }
  function opResult(r) {
    const g = r.platform === "google";
    const url = g ? `https://googleads.googleapis.com/v22/customers/4445556666/${r.entity_type === "budget" ? "campaignBudgets" : r.entity_type === "negative_keyword" ? "campaignCriteria" : "adGroupCriteria"}:mutate`
      : `https://graph.facebook.com/v24.0/${r.entity_type === "ad" ? "act_7778889999/ads" : r.entity_type === "image" ? "act_7778889999/adimages" : r.entity_type === "creative" ? "act_7778889999/adcreatives" : r.entity_id}`;
    return { op: r.op, status: "applied", message: "",
      request: { method: "POST", url, headers: g ? { "developer-token": "EXAM…", "login-customer-id": "1112223333", Authorization: "Bearer EXAM…" } : { Authorization: "Bearer EXAM…" },
        body: g ? { operations: [{ [r.action]: { resourceName: r.entity_id, [r.field]: r.after }, updateMask: r.field }] } : { [r.field]: r.after } },
      response: g ? { results: [{ resourceName: r.entity_id }] } : r.entity_type === "image" ? { images: { "ig.png": { hash: "a1b2c3d4e5" } } } : { id: "120210000000000999", success: true } };
  }
}

function mockText(path) {
  const id = (path.match(/snapshots\/([^/]+)\/yaml/) || [])[1] || "SNAP";
  return `# Search Atlas account state document
# ${id} · mode sample · as of 2026-11-05
id: ${id}
mode: sample
as_of: '2026-11-05'
google:
  customer_id: '4445556666'
  campaigns:
  - id: g_search_brand_us
    resource_name: customers/4445556666/campaigns/101
    name: Search_Brand_US
    status: ENABLED
    channel: SEARCH
    bidding: {strategy: TARGET_CPA, target_cpa: 150.0}
    budget: {resource_name: customers/4445556666/campaignBudgets/201, daily: 450.0, amount_micros: 450000000, shared: false}
    geo: [US]
    metrics: {spend_7d: 3120.4, trials_7d: 21, cpt_7d: 148.59, spend_mtd: 2240.0, trials_mtd: 15, cpt_mtd: 149.33}
    negatives:
    - {resource_name: customers/4445556666/campaignCriteria/101~9001, text: jobs, match: PHRASE}
    ad_groups:
    - id: ag_brand_core
      name: Brand_Core
      status: ENABLED
      keywords:
      - {text: search atlas, match: EXACT, status: ENABLED}
      - {text: searchatlas, match: EXACT, status: ENABLED}
  - id: g_search_nonbrand_us
    name: Search_NonBrand_US
    status: ENABLED
    budget: {daily: 953.0, amount_micros: 953000000}
meta:
  ad_account_id: act_7778889999
  campaigns:
  - id: m_prospecting_broad
    meta_id: '120210000000000301'
    name: Prospecting_Broad
    status: ACTIVE
    objective: OUTCOME_LEADS
    ad_sets:
    - {id: as_broad_us, meta_id: '120210000000000101', name: Broad_US, status: ACTIVE, daily_budget: 180.0, optimization_goal: OFFSITE_CONVERSIONS}
totals:
  google: {daily_budget: 1833.0, spend_mtd: 9120.0}
  meta: {daily_budget: 2140.0, spend_mtd: 10764.0}
counts: {campaigns: 13, ad_groups: 9, ad_sets: 12, ads: 52, keywords: 64, negatives: 6}
` + Array.from({ length: 40 }, (_, i) => `# ... ${i + 1} more lines of ads, keywords and targeting in the real document`).join("\n") + "\n";
}

let MOCK_STATE = null;
function mockState() {
  if (MOCK_STATE) return MOCK_STATE;
  const empty = QS.get("empty") === "1";
  const M = MOCK_STATE = {
    seq: 0, callsLeft: 57, jobs: {},
    eta: { analyze: 8, draft: 10, revise: 7 },
    config: {
      mode: "sample",
      google_ads: { api_version: "v22", developer_token: "EXAM…", client_id: "0000…", client_secret: "EXAM…", refresh_token: "EXAM…", login_customer_id: "1112223333", customer_id: "4445556666" },
      meta: { api_version: "v24.0", app_id: "0000…", app_secret: "EXAM…", access_token: "EXAM…", ad_account_id: "act_7778889999", page_id: "123456789012345", instagram_actor_id: "17840000000000000",
        required_permissions: ["ads_management", "ads_read", "business_management", "pages_read_engagement", "pages_manage_ads", "pages_show_list"],
        media_access: "ad account /adimages and /advideos (upload), page for object_story_spec" },
    },
    snapshots: [{ id: "SNAP-20261105-142233", taken_at: "2026-11-05T14:22:33", reason: "analyze", counts: { campaigns: 13, ad_groups: 9, ad_sets: 12, ads: 52, keywords: 64, negatives: 6 } }],
    analyses: [], changesets: [],
    media: [
      { id: "IMG-0001", kind: "image", status: "approved", title: "Agency dashboard hero, 1:1", aspect: "1:1", thumb_url: svgThumb("#653A9D", "1:1"), platforms: ["meta"] },
      { id: "IMG-0002", kind: "image", status: "approved", title: "Trial offer card with OTTO screenshot", aspect: "4:5", thumb_url: svgThumb("#087866", "4:5"), platforms: ["meta"] },
      { id: "VID-0001", kind: "video", status: "approved", title: "15 s founder hook, vertical", aspect: "9:16", thumb_url: null, platforms: ["meta"] },
      { id: "H5-0001", kind: "html5", status: "approved", title: "Display 300x250 animated", aspect: "300x250", thumb_url: null, platforms: ["google"] },
      { id: "IMG-0003", kind: "image", status: "in_review", title: "Not approved yet", aspect: "1:1", thumb_url: null },
    ],
  };
  if (QS.get("busy") === "1") {
    M.jobs["JOB-0099"] = { id: "JOB-0099", kind: "draft", args: { directive: "Already running when the page loaded", media_ids: [] }, t0: Date.now() - 4000, eta: 10, dur: 12, applied: false };
  }
  if (!empty) {
    M.analyses.push(mockAnalysis("AN-0001", "SNAP-20261105-142233"));
    M.changesets.push(mockChangeset("CS-0001", {
      title: "Pause Prospecting_Broad and add two negatives", status: "published", created_at: "2026-11-04T10:12:00",
      directive: "Pause the legacy Prospecting_Broad ad set and negate 'seo jobs' and 'free seo tool' on NonBrand US.",
      versions: [mockVersion(1, "SNAP-20261104-100500", { brand: null, small: true })],
    }));
    const cs1 = M.changesets[0];
    cs1.published = { ok: true, mode: "sample", pre_snapshot_id: "SNAP-20261104-101500", post_snapshot_id: "SNAP-20261104-101502", drift: [], verified: true, published_at: "2026-11-04T10:15:02",
      results: [
        { op: "op1", status: "applied", message: "", request: { method: "POST", url: "https://graph.facebook.com/v24.0/120210000000000101", body: { status: "PAUSED" } }, response: { success: true } },
        { op: "op2", status: "applied", message: "", request: { method: "POST", url: "https://googleads.googleapis.com/v22/customers/4445556666/campaignCriteria:mutate", body: { operations: [{ create: { campaign: "customers/4445556666/campaigns/102", negative: true, keyword: { text: "seo jobs", matchType: "PHRASE" } } }] } }, response: { results: [{ resourceName: "customers/4445556666/campaignCriteria/102~9101" }] } },
      ] };
    M.changesets.push(mockChangeset("CS-0002", {
      title: "Shift budget from Brand US to NonBrand US, launch IMG-0002 in Prospecting_Core", status: "ready", created_at: "2026-11-05T14:30:10",
      directive: "Move budget from Search_Brand_US to Search_NonBrand_US, pause Broad_US, negate 'free seo tool', and launch a paused Prospecting_Core ad with IMG-0002.",
      media_ids: ["IMG-0002"],
      versions: [mockVersion(1, "SNAP-20261105-142233", { brand: 150, err: true }), mockVersion(2, "SNAP-20261105-142233", { brand: 300, warn: true, note: "Don't cut Brand by more than a third. Keep the rest." })],
    }));
  }
  return M;

  function svgThumb(color, label) {
    const svg = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 160 100'><rect width='160' height='100' fill='${color}'/><circle cx='120' cy='30' r='18' fill='#00FFD4' opacity='.7'/><text x='12' y='88' font-family='sans-serif' font-size='16' fill='white'>${label}</text></svg>`;
    return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
  }
}

function mockAnalysis(id, snapId) {
  return {
    id, snapshot_id: snapId, created_at: new Date().toISOString(), model: "claude-opus-5-5", effort: "medium", duration_s: 17.8,
    plan_status: [
      "Day 5 of 30: 9 of 14 launch checklist items done; 2 overdue (UK conversion tag QA, Meta CAPI dedupe check).",
      "Google is pacing 4% under plan; Meta 6% over on the legacy campaigns.",
      "Search_Brand_UK launched on plan; Retargeting_Lapsed_15to30d still waiting on its audience.",
    ],
    state_summary: [
      "13 campaigns, 12 active. Legacy Meta campaigns still carry $640/day.",
      "Search_NonBrand_US converts at $241 per trial over 7 days, inside the $250 to $280 band and budget-limited.",
      "Search_Brand_US spends $450/day against a plan of $3,000/month ($100/day).",
    ],
    recommendations: [
      { text: "Cut Search_Brand_US to the planned $100/day and move the difference to NonBrand US, in two steps of at most 50%.", priority: "high", platform: "google", campaign_id: "g_search_brand_us" },
      { text: "Pause Prospecting_Broad: $1,140 spent in 7 days for 2 trials.", priority: "high", platform: "meta", campaign_id: "m_prospecting_broad" },
      { text: "Close the two overdue checklist items before scaling either platform.", priority: "medium", platform: "both", campaign_id: null },
      { text: "Add the 6 recommended search-term negatives on NonBrand UK.", priority: "low", platform: "google", campaign_id: "g_search_nonbrand_uk" },
    ],
    facts: [
      { kind: "budget_gap", platform: "google", campaign: "Search_Brand_US", planned: 100, actual: 450, note: "daily budget 350% of plan" },
      { kind: "checklist_overdue", platform: "both", campaign: null, planned: null, actual: null, note: "Day 3: UK conversion tag QA" },
      { kind: "cpa_out_of_band", platform: "meta", campaign: "Prospecting_Broad", planned: 280, actual: 570, note: "7-day cost per trial above band" },
    ],
  };
}

function mockChangeset(id, o) {
  return Object.assign({ id, title: "", status: "ready", directive: "", media_ids: [], created_at: new Date().toISOString(), published: null }, o,
    { current_version: o.versions.length });
}

function mockVersion(n, snapId, o) {
  const rows = [];
  const usd = (v) => (v === null || v === undefined ? null : `$${Number(v).toLocaleString("en-US")}/day`);
  if (o.small) {
    rows.push({ op: "op1", platform: "meta", entity_type: "ad_set", entity_id: "120210000000000101", entity_name: "Prospecting_Broad / Broad_US", action: "update", field: "status", before: "ACTIVE", after: "PAUSED", display_before: "ACTIVE", display_after: "PAUSED" });
    rows.push({ op: "op2", platform: "google", entity_type: "negative_keyword", entity_id: "customers/4445556666/campaigns/102", entity_name: "Search_NonBrand_US", action: "create", field: "keyword", before: null, after: { text: "seo jobs", match_type: "PHRASE" }, display_before: null, display_after: "\"seo jobs\" (PHRASE)" });
  } else {
    const brandAfter = o.brand;
    const moved = 450 - brandAfter;
    rows.push({ op: "op1", platform: "google", entity_type: "budget", entity_id: "customers/4445556666/campaignBudgets/201", entity_name: "Search_Brand_US budget", action: "update", field: "amount_micros", before: 450000000, after: brandAfter * 1e6, display_before: usd(450), display_after: usd(brandAfter) });
    rows.push({ op: "op2", platform: "google", entity_type: "budget", entity_id: "customers/4445556666/campaignBudgets/202", entity_name: "Search_NonBrand_US budget", action: "update", field: "amount_micros", before: 953000000, after: (953 + moved) * 1e6, display_before: usd(953), display_after: usd(953 + moved) });
    rows.push({ op: "op3", platform: "google", entity_type: "negative_keyword", entity_id: "customers/4445556666/campaigns/102", entity_name: "Search_NonBrand_US", action: "create", field: "keyword", before: null, after: { text: "free seo tool", match_type: "PHRASE" }, display_before: null, display_after: "\"free seo tool\" (PHRASE)" });
    rows.push({ op: "op4", platform: "google", entity_type: "keyword", entity_id: "customers/4445556666/adGroupCriteria/302~7712", entity_name: "NonBrand_Agency / seo software cheap", action: "remove", field: "keyword", before: "seo software cheap (BROAD)", after: null, display_before: "\"seo software cheap\" (BROAD)", display_after: null });
    rows.push({ op: "op5", platform: "meta", entity_type: "ad_set", entity_id: "120210000000000101", entity_name: "Prospecting_Broad / Broad_US", action: "update", field: "status", before: "ACTIVE", after: "PAUSED", display_before: "ACTIVE", display_after: "PAUSED" });
    rows.push({ op: "op6", platform: "meta", entity_type: "image", entity_id: "act_7778889999/adimages", entity_name: o.media || "IMG-0002", action: "create", field: "media_id", before: null, after: o.media || "IMG-0002", display_before: null, display_after: o.media || "IMG-0002" });
    rows.push({ op: "op7", platform: "meta", entity_type: "creative", entity_id: "act_7778889999/adcreatives", entity_name: "Core_TrialOffer_4x5", action: "create", field: "object_story_spec", before: null, after: { link: "https://searchatlas.com/trial" }, display_before: null, display_after: "Link ad: \"Start your 7-day trial\" · SIGN_UP · image $ref:op6.hash" });
    rows.push({ op: "op8", platform: "meta", entity_type: "ad", entity_id: "act_7778889999/ads", entity_name: "Core_TrialOffer_4x5 ad", action: "create", field: "status", before: null, after: "PAUSED", display_before: null, display_after: "PAUSED (new ads start paused)" });
  }
  const s = { creates: rows.filter((r) => r.action === "create").length, updates: rows.filter((r) => r.action === "update").length, removes: rows.filter((r) => r.action === "remove").length,
    daily_budget_delta: { google: 0, meta: o.small ? -180 : -180 } };
  const validation = [];
  if (o.err) validation.push({ op: "op1", level: "error", message: `Budget change of -${Math.round((1 - o.brand / 450) * 100)}% on Search_Brand_US budget is beyond the ±50% limit for one changeset.` });
  if (o.err || o.warn) validation.push({ op: "op2", level: "warn", message: `Search_NonBrand_US budget rises ${Math.round(((450 - o.brand) / 953) * 100)}%, above the ±20% warning line.` });
  if (o.warn) validation.push({ op: null, level: "warn", message: "IMG-0002 is approved for Meta feed placements only; Stories will crop it." });
  const yaml = o.small
    ? `changeset:\n  title: "Pause Prospecting_Broad and add two negatives"\n  based_on_snapshot: ${snapId}\n  rationale:\n    - "Broad_US: $1,140 for 2 trials in 7 days"\noperations:\n  - ref: op1\n    platform: meta\n    method: POST\n    path: /120210000000000101\n    params: {status: PAUSED}\n    reason: "legacy ad set over CPA band"\n  - ref: op2\n    platform: google\n    service: CampaignCriterionService\n    method: mutateCampaignCriteria\n    operation: create\n    fields:\n      campaign: customers/4445556666/campaigns/102\n      negative: true\n      keyword: {text: seo jobs, match_type: PHRASE}\n    reason: "search term with zero trials"\n`
    : `changeset:\n  title: "Shift budget from Brand US to NonBrand US"\n  based_on_snapshot: ${snapId}\n  rationale:\n    - "Brand US runs at 4.5x its planned daily budget"\n    - "NonBrand US is inside the CPA band and budget-limited"\noperations:\n  - ref: op1\n    platform: google\n    service: CampaignBudgetService\n    method: mutateCampaignBudgets\n    operation: update\n    resource_name: customers/4445556666/campaignBudgets/201\n    fields: {amount_micros: ${o.brand * 1000000}}\n    update_mask: [amount_micros]\n    reason: "plan rule: brand at $3K/month"\n  - ref: op2\n    platform: google\n    service: CampaignBudgetService\n    method: mutateCampaignBudgets\n    operation: update\n    resource_name: customers/4445556666/campaignBudgets/202\n    fields: {amount_micros: ${(953 + 450 - o.brand) * 1000000}}\n    update_mask: [amount_micros]\n  - ref: op5\n    platform: meta\n    method: POST\n    path: /120210000000000101\n    params: {status: PAUSED}\n  - ref: op6\n    platform: meta\n    method: POST\n    path: /act_7778889999/adimages\n    params: {media_id: ${o.media || "IMG-0002"}}\n  - ref: op7\n    platform: meta\n    method: POST\n    path: /act_7778889999/adcreatives\n    params:\n      name: Core_TrialOffer_4x5\n      object_story_spec:\n        page_id: "123456789012345"\n        link_data: {image_hash: "$ref:op6.hash", link: "https://searchatlas.com/trial", message: "Start your 7-day trial", call_to_action: {type: SIGN_UP}}\n  - ref: op8\n    platform: meta\n    method: POST\n    path: /act_7778889999/ads\n    params: {name: Core_TrialOffer_4x5 ad, adset_id: "120210000000000105", creative: {creative_id: "$ref:op7.id"}, status: PAUSED}\n`;
  const text_diff = o.small
    ? `--- ${snapId}.yaml (before)\n+++ ${snapId}.yaml (after)\n@@ -88,7 +88,7 @@\n     - id: as_broad_us\n       name: Broad_US\n-      status: ACTIVE\n+      status: PAUSED\n@@ -31,6 +31,7 @@\n     negatives:\n     - {text: jobs, match: PHRASE}\n+    - {text: seo jobs, match: PHRASE}`
    : `--- ${snapId}.yaml (before)\n+++ ${snapId}.yaml (after)\n@@ -14,7 +14,7 @@\n     bidding: {strategy: TARGET_CPA, target_cpa: 150.0}\n-    budget: {daily: 450.0, amount_micros: 450000000}\n+    budget: {daily: ${o.brand}.0, amount_micros: ${o.brand * 1000000}}\n     geo: [US]\n@@ -40,8 +40,9 @@\n   - id: g_search_nonbrand_us\n-    budget: {daily: 953.0, amount_micros: 953000000}\n+    budget: {daily: ${953 + 450 - o.brand}.0, amount_micros: ${(953 + 450 - o.brand) * 1000000}}\n     negatives:\n+    - {text: free seo tool, match: PHRASE}\n     keywords:\n-    - {text: seo software cheap, match: BROAD}\n@@ -88,7 +89,12 @@\n     - id: as_broad_us\n-      status: ACTIVE\n+      status: PAUSED\n+    ads:\n+    - name: Core_TrialOffer_4x5 ad\n+      status: PAUSED\n+      media_id: ${o.media || "IMG-0002"}`;
  return {
    n, created_at: new Date(Date.now() - (3 - n) * 600000).toISOString(), snapshot_id: snapId, yaml,
    summary: o.small ? ["Pause Broad_US (legacy) on Meta", "Negate \"seo jobs\" on Search_NonBrand_US"]
      : [`Search_Brand_US budget $450 -> $${o.brand}/day`, `Search_NonBrand_US budget $953 -> $${953 + 450 - o.brand}/day`, "Pause Broad_US; launch a paused trial-offer ad in Prospecting_Core", "Negate \"free seo tool\"; remove \"seo software cheap\" (BROAD)"],
    assumptions: o.small ? [] : ["\"Prospecting_Core\" means the Core_US ad set (the only one in that campaign).", "The new ad starts PAUSED; Vin enables it after review."],
    questions: o.err ? ["Should the Brand cut happen in one step or two?"] : o.small ? [] : ["Should Broad_US budget move to Prospecting_Core, or simply come off the account?"],
    validation, diff: { rows, text_diff, summary: s }, revision_note: o.note && n > 1 ? o.note : null, model: "claude-opus-5-5", duration_s: 24.6 + n,
  };
}

init();
