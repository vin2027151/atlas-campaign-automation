// Management page: needs action, test scoreboard, testing schedule, checklist, tracking, activity, lessons.
// (In play moved out: the same campaigns and controls live on Campaigns.)
// One GET (/api/management/) renders every section; checklist toggles and new
// lessons update the UI immediately, then reconcile with the server response.
import { api, fmt, toast, esc, badge, platformChip, withBusy, $ } from "/static/js/common.js";

const S = { data: null, selectedDay: null, tag: null, newLesson: null };
const TONE_BADGE = { good: "good", watch: "watch", bad: "bad", idle: "idle" };
const campLink = (id, name) => `<a href="/campaigns#${encodeURIComponent(id || "")}">${esc(name || id || fmt.none)}</a>`;
const cap = (s) => String(s || "").charAt(0).toUpperCase() + String(s || "").slice(1);

// ------------------------------------------------------------------ load
async function load({ quiet = false } = {}) {
  try {
    S.data = await api("/api/management/");
    if (S.selectedDay === null) S.selectedDay = S.data.checklist.today_day || 1;
    renderAll();
  } catch (e) {
    toast("Could not load management data: " + e.message, "error");
    if (!quiet) $("#mg-action-list").innerHTML = `<div class="action-empty">Could not load: ${esc(e.message)}</div>`;
  }
}

function renderAll() {
  renderNeedsAction();
  renderTests();
  renderSchedule();
  renderChecklist();
  renderTracking();
  renderLessons();
  renderActivity();
}

// ---------------------------------------------------------- 1. checklist
function renderChecklist() {
  const c = S.data.checklist;
  const rail = $("#mg-rail");
  rail.innerHTML = c.days.map((d) => {
    const pct = d.total ? Math.round((d.done / d.total) * 100) : 0;
    const open = d.when === "past" && d.done < d.total;
    const cls = ["mg-day", d.when, open ? "has-open" : "", d.day === S.selectedDay ? "selected" : ""].join(" ");
    return `<button type="button" class="${cls}" data-day="${d.day}" role="option" aria-selected="${d.day === S.selectedDay}" tabindex="${d.day === S.selectedDay ? 0 : -1}"
      title="Day ${d.day}, ${esc(fmt.date(d.date, { dow: true }))}: ${d.done} of ${d.total} done${d.when === "today" ? " (today)" : ""}">
      <span class="d-date">${d.when === "today" ? "Today" : esc(fmt.date(d.date))}</span>
      <span class="d-num">${d.day}</span>
      <span class="d-ct">${d.done}/${d.total}</span>
      <span class="d-dots"><span style="width:${pct}%"></span></span></button>`;
  }).join("");
  const doneAll = c.days.reduce((a, d) => a + d.done, 0);
  const totAll = c.days.reduce((a, d) => a + d.total, 0);
  $("#mg-checklist-sub").textContent = `${doneAll} of ${totAll} items done across 30 days`;
  renderDay();
  renderCarry();
}

function itemHtml(it, meta, metaCls) {
  return `<li class="${it.done ? "is-done" : ""}"><label>
    <input type="checkbox" data-item="${esc(it.id)}" ${it.done ? "checked" : ""}>
    <span class="t">${esc(it.text)}</span>${meta ? `<span class="meta ${metaCls || ""}">${meta}</span>` : ""}</label></li>`;
}

function renderDay() {
  const d = S.data.checklist.days.find((x) => x.day === S.selectedDay);
  if (!d) return;
  const label = d.when === "today" ? "Today" : d.when === "past" ? "Past" : "Upcoming";
  $("#mg-day-title").innerHTML = `Day ${d.day} <span class="card-sub">&middot; ${esc(fmt.date(d.date, { dow: true }))} &middot; ${label}</span>`;
  $("#mg-day-count").textContent = `${d.done} / ${d.total} done`;
  $("#mg-day-items").innerHTML = d.items.length ? d.items.map((it) => itemHtml(it)).join("") : `<li class="mg-empty">Nothing planned.</li>`;
}

function renderCarry() {
  const items = S.data.checklist.carry_over;
  $("#mg-carry-count").textContent = items.length ? `${items.length} open` : "";
  $("#mg-carry").innerHTML = items.length
    ? items.map((it) => itemHtml(it, `Day ${it.day} &middot; ${it.age_days}d`, it.age_days >= 3 ? "old" : "")).join("")
    : `<li class="mg-empty">Nothing carried over. Every past item is done.</li>`;
}

// Apply a done flag to every copy of an item in local state, recompute counts.
function applyLocal(id, done) {
  const c = S.data.checklist;
  let found = null;
  c.days.forEach((d) => d.items.forEach((it) => { if (it.id === id) { it.done = done; found = d; } }));
  if (!found) return null;
  found.done = found.items.filter((i) => i.done).length;
  // carry-over: rebuild from past days, keeping items just ticked visible until reload
  const prev = new Map(c.carry_over.map((x) => [x.id, x]));
  const next = [];
  c.days.forEach((d) => {
    if (d.when !== "past") return;
    d.items.forEach((it) => {
      if (!it.done || prev.has(it.id)) {
        const base = prev.get(it.id) || { day: d.day, date: d.date, id: it.id, text: it.text,
          age_days: Math.round((new Date(S.data.today.date) - new Date(d.date)) / 864e5) };
        next.push({ ...base, done: it.done });
      }
    });
  });
  c.carry_over = next;
  const t = S.data.today;
  const today = c.days.find((d) => d.when === "today");
  if (today) { t.done = today.done; t.total = today.total; }
  t.carry_over = next.filter((x) => !x.done).length;
  return found;
}

async function toggleItem(input) {
  const id = input.dataset.item;
  const done = input.checked;
  const day = applyLocal(id, done);
  renderChecklist();
  try {
    const res = await api(`/api/management/checklist/${encodeURIComponent(id)}/toggle`, { body: { done } });
    S.data.today = res.today;
    S.data.today.carry_over = S.data.checklist.carry_over.filter((x) => !x.done).length;
    S.data.activity = res.activity;
    renderActivity();
    toast(`${done ? "Done" : "Reopened"}: ${res.item.text} (day ${res.day})`, "success");
  } catch (e) {
    applyLocal(id, !done);
    renderChecklist();
    toast("Could not update checklist: " + e.message, "error");
  }
  return day;
}

// ------------------------------------------------------------ 2. needs action
// Content waiting on a person (moved here from Calendar). Approve uses the
// existing Calendar move route; Open goes to the item on the Calendar.
function renderNeedsAction() {
  const N = S.data.needs_action;
  const c = N.counts;
  $("#mg-actions-sub").textContent = `${c.overdue} overdue · ${c.final_approval} final approval${c.final_approval === 1 ? "" : "s"} · ${c.feedback} feedback`;
  if (!N.items.length) {
    $("#mg-action-list").innerHTML = `<div class="action-empty">Nothing overdue or waiting for review.</div>`;
    return;
  }
  $("#mg-action-list").innerHTML = `<ul class="action-list">${N.items.map(({ item, kind, tone, approve }) => `
    <li class="action-item">
      ${badge(tone, kind)}
      <div class="action-copy">
        <div class="action-title">${platformChip(item.platform)} ${esc(item.name)}</div>
        <div class="action-meta">${esc(item.owner)} · due ${esc(fmt.date(item.due))} · ${esc(item.format)} / ${esc(item.segment)}${item.campaign_id ? ` · ${campLink(item.campaign_id, item.campaign_name)}` : ""}</div>
      </div>
      <div class="action-controls">
        ${approve ? `<button class="btn btn-sm btn-primary" type="button" data-mg-approve="${esc(item.id)}" data-name="${esc(item.name)}">Approve</button>` : ""}
        <a class="btn btn-sm" href="/calendar#${encodeURIComponent(item.id)}" aria-label="${esc(`Open ${item.name} on the calendar`)}">Open</a>
      </div>
    </li>`).join("")}</ul>`;
}

$("#mg-actions").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("[data-mg-approve]");
  if (!btn || btn.disabled) return;
  try {
    await withBusy(btn, () => api(`/api/calendar/content/${encodeURIComponent(btn.dataset.mgApprove)}/move`, { body: { status: "approved" } }),
      `Approved: ${btn.dataset.name}`);
    await load({ quiet: true });
  } catch (e) { /* withBusy toasted the error */ }
});

// --------------------------------------------------------------- 4. tests
function metricVal(metric, v) {
  if (v === null || v === undefined) return fmt.none;
  return metric === "cost_per_trial" ? fmt.cpt(v) : fmt.pct(v, 2);
}
const METRIC_LABEL = { cost_per_trial: "Cost per trial", ctr: "CTR", click_to_trial: "Click to trial" };

function renderTests() {
  const T = S.data.tests;
  $("#mg-tests-sub").textContent = `${T.running.length} running · ${T.ledger.length} finished · ${T.queued.length} queued`;
  const queued = T.queued.map((q) => `<div class="mg-test" style="background:var(--surface-2)">
      <div class="row-between">${badge("queued")}<span class="muted small">starts ${esc(fmt.date(q.started))}</span></div>
      <h3>${esc(q.name)}</h3><div class="hyp">${esc(q.hypothesis)}</div>
      <div class="small">${platformChip(q.platform)} ${campLink(q.campaign_id, q.campaign_name)}</div>
      ${q.notes ? `<div class="small muted">${esc(q.notes)}</div>` : ""}</div>`).join("");
  $("#mg-running").innerHTML = T.running.map((t) => {
    const b = t.benchmark, cur = t.current;
    const toneCls = { good: "tone-good", watch: "tone-watch", bad: "tone-bad", idle: "tone-idle" }[t.tone];
    const bench = `${t.direction === "below" ? "win below" : "win above"} ${metricVal(t.metric, t.target)}`;
    return `<article class="mg-test">
      <div class="row-between">${badge("running")}<span class="badge ${TONE_BADGE[t.tone]}" title="${esc(t.verdict_note)}">${esc(t.verdict)}</span></div>
      <h3>${esc(t.name)}</h3>
      <div class="small">${platformChip(t.platform)} ${campLink(t.campaign_id, t.campaign_name)}</div>
      <div class="mg-test-nums">
        <div><div class="lbl">${esc(METRIC_LABEL[t.metric] || t.metric)} now</div><div class="v ${toneCls}">${metricVal(t.metric, cur.value)}</div></div>
        <div><div class="lbl">Benchmark</div><div class="v">${metricVal(t.metric, t.target)}</div></div>
        <div><div class="lbl">Days left</div><div class="v">${t.days_left < 0 ? "ended" : t.days_left}</div></div>
      </div>
      <div class="mg-gates">
        <span>Spend</span><div class="meter ${t.spend_pct >= 100 ? "good" : ""}"><span style="width:${t.spend_pct}%"></span></div><span>${fmt.money(cur.spend)} / ${fmt.money(b.min_spend)}</span>
        <span>Trials</span><div class="meter ${t.trials_pct >= 100 ? "good" : ""}"><span style="width:${t.trials_pct}%"></span></div><span>${cur.trials} / ${b.min_trials}</span>
        <span>Time</span><div class="meter"><span style="width:${t.progress_pct}%"></span></div><span>${esc(fmt.date(t.started))}&ndash;${esc(fmt.date(t.ends))}</span>
      </div>
      <div class="small ink-2">${esc(t.verdict_note)} <span class="muted">(${esc(bench)})</span></div>
      <div class="hyp">${esc(t.hypothesis)}</div>
    </article>`;
  }).join("") + queued || `<div class="empty">No tests running.</div>`;

  $("#mg-tally").innerHTML = ["won", "lost", "inconclusive"].map((k) => `${badge(k, `${T.tally[k]} ${k}`)}`).join("");
  $("#mg-ledger").innerHTML = T.ledger.length ? T.ledger.map((t) => `<tr>
      <td>${badge(t.status)}</td>
      <td class="wrap"><span class="strong">${esc(t.name)}</span><div class="muted small">${esc(t.hypothesis)}</div></td>
      <td>${platformChip(t.platform)} ${campLink(t.campaign_id, t.campaign_name)}</td>
      <td class="num">${t.direction === "below" ? "&lt;" : "&gt;"} ${metricVal(t.metric, t.target)}</td>
      <td class="num strong ${t.status === "won" ? "tone-good" : t.status === "lost" ? "tone-bad" : "tone-watch"}">${metricVal(t.metric, t.current.value)}</td>
      <td class="num">${fmt.money(t.current.spend)}</td>
      <td class="num">${fmt.int(t.current.trials)}</td>
      <td class="nowrap">${esc(fmt.date(t.ends))}</td>
      <td class="wrap">${esc(t.taught)}</td></tr>`).join("")
    : `<tr><td colspan="9" class="table-empty">No finished tests yet.</td></tr>`;
}

// ------------------------------------------------- 4b. testing schedule
// Moved from the Calendar page: running tests with their win benchmarks, queued and finished tests.
function schedMetric(t, v) {
  if (v === null || v === undefined) return fmt.none;
  return t.metric_unit === "money" ? fmt.cpt(v) : fmt.pct(v, 2);
}
const meterTone = (pct) => (pct >= 100 ? "good" : pct >= 50 ? "" : "watch");

function schedRunning(t) {
  const b = t.benchmark || {}, cur = t.current || {};
  const target = t.target === null || t.target === undefined ? "" :
    ` <span class="muted small">target ${t.direction === "below" ? "&lt;" : "&gt;"} ${esc(schedMetric(t, t.target))}</span>`;
  const valTone = t.passing === null ? "" : t.passing ? "tone-good" : "tone-bad";
  return `<article class="tcard">
    <div class="tcard-head"><div class="tcard-name">${esc(t.name)}</div>${badge(t.status)}</div>
    <div class="tcard-sub">${platformChip(t.platform)}<span>${esc(t.campaign_name || t.campaign_id)}</span><span>·</span><span class="nowrap">${esc(fmt.date(t.started))} → ${esc(fmt.date(t.ends))}</span></div>
    <div class="tcard-hyp">${esc(t.hypothesis)}</div>
    <div class="bench">${esc(t.benchmark_text)}</div>
    <div class="tstats">
      <div><div class="tstat-label">Spend</div><div class="tstat-value">${fmt.money(cur.spend)}</div></div>
      <div><div class="tstat-label">Trials</div><div class="tstat-value">${fmt.int(cur.trials)}</div></div>
      <div><div class="tstat-label">${esc(t.metric_label)}</div><div class="tstat-value ${valTone}">${esc(schedMetric(t, cur.value))}</div>${target}</div>
    </div>
    <div class="tprog"><span>Spend</span><div class="meter ${meterTone(t.spend_pct)}" role="progressbar" aria-valuenow="${t.spend_pct}" aria-valuemin="0" aria-valuemax="100" aria-label="Spend toward minimum"><span style="width:${t.spend_pct}%"></span></div><span class="num">${fmt.money(cur.spend)} / ${fmt.money(b.min_spend)}</span></div>
    <div class="tprog"><span>Trials</span><div class="meter ${meterTone(t.trials_pct)}" role="progressbar" aria-valuenow="${t.trials_pct}" aria-valuemin="0" aria-valuemax="100" aria-label="Trials toward minimum"><span style="width:${t.trials_pct}%"></span></div><span class="num">${fmt.int(cur.trials)} / ${fmt.int(b.min_trials)}</span></div>
    <div class="verdict ${esc(t.verdict)}">${esc(t.verdict_line)}</div>
    ${t.notes ? `<div class="muted small">${esc(t.notes)}</div>` : ""}
  </article>`;
}

function schedQueued(t) {
  return `<article class="tcard">
    <div class="tcard-head"><div class="tcard-name">${esc(t.name)}</div>${badge(t.status)}</div>
    <div class="tcard-sub">${platformChip(t.platform)}<span>${esc(t.campaign_name || t.campaign_id)}</span><span>·</span><span class="nowrap">${esc(fmt.date(t.started))} → ${esc(fmt.date(t.ends))}</span></div>
    <div class="tcard-hyp">${esc(t.hypothesis)}</div>
    <div class="bench">${esc(t.benchmark_text)}</div>
    <div class="verdict"><b>Starts when:</b> ${esc(t.notes || "scheduled start " + fmt.date(t.started))} Planned start ${esc(fmt.date(t.started, { dow: true }))}.</div>
  </article>`;
}

function schedDone(t) {
  const cur = t.current || {};
  return `<details class="tdone">
    <summary>${badge(t.status)}<span class="tdone-name">${esc(t.name)}</span>
      <span class="tdone-result">${esc(t.metric_label)} ${esc(schedMetric(t, cur.value))} · ${fmt.money(cur.spend)} · ${fmt.int(cur.trials)} trials</span></summary>
    <div class="tdone-body">
      <div class="tcard-sub">${platformChip(t.platform)}<span>${esc(t.campaign_name || t.campaign_id)}</span><span>·</span><span>${esc(fmt.date(t.started))} → ${esc(fmt.date(t.ends))}</span></div>
      <div class="tcard-hyp">${esc(t.hypothesis)}</div>
      <div class="bench">${esc(t.benchmark_text)}</div>
      <div class="verdict ${t.status === "won" ? "on_track" : t.status === "lost" ? "failing" : "not_enough_data"}"><b>Result:</b> ${esc(t.notes || t.status)}</div>
    </div>
  </details>`;
}

function renderSchedule() {
  const tests = S.data.schedule || [];
  const running = tests.filter((t) => t.status === "running");
  const queued = tests.filter((t) => t.status === "queued");
  const done = tests.filter((t) => ["won", "lost", "inconclusive"].includes(t.status));
  $("#mg-schedule-sub").textContent = `${running.length} running · ${queued.length} queued · ${done.length} finished`;
  const parts = [];
  parts.push(`<div><h3 class="section-label">Running (${running.length})</h3>${running.length ? `<div class="tests-grid">${running.map(schedRunning).join("")}</div>` : `<div class="empty">No tests running.</div>`}</div>`);
  if (queued.length) parts.push(`<div><h3 class="section-label">Queued (${queued.length})</h3><div class="tests-grid">${queued.map(schedQueued).join("")}</div></div>`);
  if (done.length) parts.push(`<div><h3 class="section-label">Finished (${done.length})</h3>${done.map(schedDone).join("")}</div>`);
  $("#mg-schedule").innerHTML = parts.join("");
}

// ------------------------------------------------------------ 5. tracking
function renderTracking() {
  $("#mg-tracking-body").innerHTML = S.data.tracking.map((r) => {
    const tone = r.status === "ok" ? "good" : r.status === "degraded" ? "watch" : "bad";
    const ratio = r.computed && r.ratio !== null ? ` <span class="muted num">${r.ratio.toFixed(2)}x</span>` : "";
    return `<tr>
      <td><span class="mg-dot ${esc(r.status)}"></span><span class="strong">${esc(r.name)}</span>${ratio}</td>
      <td><span class="badge ${tone}">${esc(r.status)}</span></td>
      <td class="nowrap">${esc(fmt.date(r.last_checked))}</td>
      <td class="wrap ink-2">${esc(r.note)}${r.computed ? ' <span class="tag" title="Computed live from daily data (trailing 7 days)">computed</span>' : ""}</td></tr>`;
  }).join("");
}

// ------------------------------------------------------------- 6. lessons
function renderLessons() {
  const L = S.data.lessons;
  if (S.tag && !L.tags.some(([t]) => t === S.tag)) S.tag = null;
  $("#mg-tag-filter").innerHTML = `<button type="button" class="mg-chip ${S.tag ? "" : "active"}" data-tag="">All <span class="c">${L.items.length}</span></button>` +
    L.tags.map(([t, n]) => `<button type="button" class="mg-chip ${S.tag === t ? "active" : ""}" data-tag="${esc(t)}">${esc(t)} <span class="c">${n}</span></button>`).join("");
  $("#mg-tag-list").innerHTML = L.tags.map(([t]) => `<option value="${esc(t)}">`).join("");
  const items = S.tag ? L.items.filter((l) => (l.tags || []).includes(S.tag)) : L.items;
  $("#mg-lessons-sub").textContent = S.tag ? `${items.length} tagged "${S.tag}" · newest first` : `${L.items.length} lessons · newest first`;
  $("#mg-lessons").innerHTML = items.length ? items.map((l) => `<li class="${l.id === S.newLesson ? "is-new" : ""}">
      <div class="when">${esc(fmt.date(l.date))}<div class="small">${esc(String(l.date).slice(0, 4))}</div></div>
      <div><div>${esc(l.text)}</div>
        <div class="tags">${(l.tags || []).map((t) => `<button type="button" class="mg-chip ${S.tag === t ? "active" : ""}" data-tag="${esc(t)}">${esc(t)}</button>`).join("")}
          <span class="src">&middot; ${esc(l.source || "manual")}</span></div></div></li>`).join("")
    : `<li class="mg-empty">No lessons with this tag.</li>`;
}

async function submitLesson(ev) {
  ev.preventDefault();
  const textEl = $("#mg-lesson-text"), tagsEl = $("#mg-lesson-tags"), btn = $("#mg-lesson-submit");
  const text = textEl.value.trim();
  if (!text) { toast("Write the lesson first.", "warn"); textEl.focus(); return; }
  const tags = tagsEl.value.split(",").map((t) => t.trim().toLowerCase()).filter(Boolean);
  btn.disabled = true; btn.classList.add("is-busy");
  try {
    const res = await api("/api/management/lessons", { body: { text, tags } });
    S.data.lessons = res.lessons;
    S.data.activity = res.activity;
    S.newLesson = res.lesson.id;
    if (S.tag && !tags.includes(S.tag)) S.tag = null;
    renderLessons(); renderActivity();
    textEl.value = ""; tagsEl.value = "";
    toast("Lesson added", "success");
  } catch (e) {
    toast("Could not add lesson: " + e.message, "error");
  } finally {
    btn.disabled = false; btn.classList.remove("is-busy");
  }
}

// ------------------------------------------------------------ 7. activity
function renderActivity() {
  const A = S.data.activity;
  $("#mg-activity").innerHTML = A.length ? A.map((a) => `<li>
      <span class="ts" title="${esc(a.ts)}">${esc(fmt.datetime(a.ts))}</span>
      <span class="act" title="${esc(a.action)} · ${esc(a.target)}">${esc(a.action)}</span>
      <span>${esc(a.detail || a.target)} <span class="muted">&middot; ${esc(a.actor)}</span></span></li>`).join("")
    : `<li class="mg-empty" style="display:block">No changes yet. Toggles, pauses, budget moves and new lessons show up here.</li>`;
}

// --------------------------------------------------------------- events
document.addEventListener("change", (ev) => {
  const el = ev.target;
  if (el.matches && el.matches("input[data-item]")) toggleItem(el);
});
$("#mg-rail").addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-day]");
  if (!b) return;
  S.selectedDay = Number(b.dataset.day);
  renderChecklist();
});
$("#mg-goto-today").addEventListener("click", () => {
  S.selectedDay = S.data.checklist.today_day || 1;
  renderChecklist();
});
$("#mg-lessons-card").addEventListener("click", (ev) => {
  const c = ev.target.closest("[data-tag]");
  if (!c) return;
  S.tag = c.dataset.tag || null;
  S.newLesson = null;
  renderLessons();
});
$("#mg-lesson-form").addEventListener("submit", submitLesson);
$("#mg-lesson-text").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) submitLesson(ev);
});
$("#mg-refresh").addEventListener("click", async () => { await load({ quiet: true }); toast("Refreshed", "info"); });

// Listbox keyboard: arrows move the selection, Home/End jump to the ends.
$("#mg-rail").addEventListener("keydown", (ev) => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(ev.key) || !S.data) return;
  const days = S.data.checklist.days;
  if (!days.length) return;
  ev.preventDefault();
  let i = days.findIndex((d) => d.day === S.selectedDay);
  if (ev.key === "Home") i = 0;
  else if (ev.key === "End") i = days.length - 1;
  else i = Math.max(0, Math.min(days.length - 1, i + (ev.key === "ArrowRight" ? 1 : -1)));
  S.selectedDay = days[i].day;
  renderChecklist();
  const sel = $(`#mg-rail [data-day="${S.selectedDay}"]`);
  if (sel) sel.focus({ preventScroll: true });
});

// /management#mg-schedule-card (linked from the Calendar's test markers) opens the testing schedule.
function openScheduleFromHash() {
  if (location.hash !== "#mg-schedule-card") return;
  $("#mg-schedule-fold").open = true;
  $("#mg-schedule-card").scrollIntoView({ block: "start" });
}
window.addEventListener("hashchange", openScheduleFromHash);

load().then(openScheduleFromHash);

