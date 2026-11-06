// Management page: checklist, needs action, in play, then the scoreboard and logs.
// One GET (/api/management/) renders every section; checklist toggles and new
// lessons update the UI immediately, then reconcile with the server response.
import { api, fmt, toast, esc, badge, cptTone, platformChip, confirmButton, withBusy, $, $$ } from "/static/js/common.js";

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
  renderChecklist();
  renderNeedsAction();
  renderInPlay();
  renderTests();
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

// ------------------------------------------------------------- 3. in play
// "+10% / day": current daily budget x 1.10, rounded to cents.
const scaledBudget = (v) => Math.round(Number(v || 0) * 110) / 100;

function readPill(read, why) {
  return `<span class="read ${esc(read)}" title="${esc(why + " Rule: " + S.data.in_play.rule.reads[read])}">${esc(read)}</span>`;
}

function renderInPlay() {
  const ip = S.data.in_play;
  const band = S.data.band;
  const minTrials = Number(ip.rule.min_trials) || 3;
  $("#mg-read-counts").innerHTML = ["scaling", "holding", "watching", "failing"].map((r) =>
    `<span class="read ${r}" title="${esc(ip.rule.reads[r])}"><span class="n">${ip.counts[r]}</span> ${r}</span>`).join("");
  const rows = [];
  ip.groups.forEach((g) => {
    const t = g.totals;
    rows.push(`<tr class="mg-group-row"><td>${platformChip(g.platform)} ${esc(g.label)} <span class="muted">&middot; ${g.campaigns.length} active</span></td>
      <td class="num" data-l="Budget / day">${fmt.money(t.daily_budget)}</td><td class="num" data-l="Spend (7d)">${fmt.money(t.spend_7d)}</td>
      <td class="num ${cptTone(t.cpt_7d, band)}" data-l="Cost / trial (7d)">${fmt.cpt(t.cpt_7d)}</td><td class="num" data-l="Trials (7d)">${fmt.int(t.trials_7d)}</td><td></td><td></td><td></td></tr>`);
    if (!g.campaigns.length) rows.push(`<tr><td colspan="8" class="muted">No active campaigns.</td></tr>`);
    g.campaigns.forEach((c) => {
      const tags = [c.legacy ? `<span class="tag" title="Legacy campaign running at reduced budget alongside the new build">legacy</span>` : "",
        c.country && c.country !== "US" ? `<span class="tag">${esc(c.country)}</span>` : ""].join("");
      const n = Number(c.trials_7d) || 0;
      const thin = n < minTrials ? `<div class="caveat">${n === 0 ? "0 trials: CPT undefined" : `n=${n}: thin read`}</div>` : "";
      const scaleTo = scaledBudget(c.daily_budget);
      rows.push(`<tr>
        <td class="mg-camp">${platformChip(c.platform)} ${campLink(c.id, c.name)}${tags} <span class="muted small">${esc(c.type || "")}</span></td>
        <td class="num" data-l="Budget / day">${fmt.money(c.daily_budget)}</td>
        <td class="num" data-l="Spend (7d)">${fmt.money(c.spend_7d)}</td>
        <td data-l="Cost / trial (7d)" class="num strong mg-cpt ${cptTone(c.cpt_7d, band)}" title="${esc(`${fmt.money(c.spend_7d)} over ${n} PostHog trial${n === 1 ? "" : "s"}`)}">${fmt.cpt(c.cpt_7d)}${thin}</td>
        <td class="num" data-l="Trials (7d)">${fmt.int(c.trials_7d)}</td>
        <td data-l="Read">${readPill(c.read, c.why)}</td>
        <td class="mg-why">${esc(c.why)}</td>
        <td class="actions"><span class="mg-row-actions">
          ${c.read === "scaling" ? `<button class="btn btn-sm" type="button" data-mg-scale="${esc(c.id)}" aria-label="${esc(`+10% / day for ${c.name}`)}" title="${esc(`Raise daily budget from ${fmt.money(c.daily_budget)} to ${fmt.money(scaleTo)}`)}">+10% / day</button>` : ""}
          <button class="btn btn-sm btn-danger" type="button" data-mg-pause="${esc(c.id)}" data-name="${esc(c.name)}" data-confirm-label="Confirm pause?" aria-label="${esc(`Pause ${c.name}`)}">Pause</button>
        </span></td></tr>`);
    });
  });
  $("#mg-inplay-body").innerHTML = rows.join("");
  $$("#mg-inplay-body [data-mg-pause]").forEach((button) => confirmButton(button, async (el) => {
    await api(`/api/campaigns/${encodeURIComponent(el.dataset.mgPause)}/status`, { body: { status: "PAUSED" } });
    toast(`${el.dataset.name} paused`);
    await load({ quiet: true });
  }));

  const paused = ip.paused;
  const det = $("#mg-paused");
  det.querySelector("summary").textContent = `Paused campaigns (${paused.length})`;
  $("#mg-paused-body").innerHTML = paused.length
    ? `<div class="table-wrap" style="border:0;border-radius:0"><table class="table compact"><thead><tr><th>Campaign</th><th class="num">Daily budget</th><th class="num">7d spend</th><th class="num">7d CPT</th><th class="num">Trials 7d</th></tr></thead><tbody>${
      paused.map((c) => `<tr class="is-paused"><td class="mg-camp">${platformChip(c.platform)} ${campLink(c.id, c.name)} ${badge("paused")}</td>
        <td class="num">${fmt.money(c.daily_budget)}</td><td class="num">${fmt.money(c.spend_7d)}</td>
        <td class="num">${fmt.cpt(c.cpt_7d)}</td><td class="num">${fmt.int(c.trials_7d)}</td></tr>`).join("")}</tbody></table></div>`
    : `<p class="muted" style="padding:0 var(--s4) var(--s3)">No paused campaigns. Everything is live.</p>`;

  $("#mg-rule").innerHTML = ["scaling", "holding", "watching", "failing"].map((r) =>
    `<dt><span class="read ${r}">${r}</span></dt><dd>${esc(ip.rule.reads[r])}</dd>`).join("");
}

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

$("#mg-inplay").addEventListener("click", async (ev) => {
  const button = ev.target.closest("[data-mg-scale]");
  if (!button || button.disabled) return;
  const id = button.dataset.mgScale;
  const campaign = S.data.in_play.groups.flatMap((g) => g.campaigns).find((c) => String(c.id) === id);
  if (!campaign || campaign.read !== "scaling") return;
  const next = scaledBudget(campaign.daily_budget);
  if (!(next > 0)) return;
  button.disabled = true; button.classList.add("is-busy");
  try {
    await api(`/api/campaigns/${encodeURIComponent(id)}/budget`, { body: { daily_budget: next } });
    toast(`${campaign.name}: daily budget ${fmt.money(campaign.daily_budget)} → ${fmt.money(next)}`);
    await load({ quiet: true });
  } catch (e) {
    toast("Could not scale budget: " + e.message, "error");
    button.disabled = false; button.classList.remove("is-busy");
  }
});

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

load();
