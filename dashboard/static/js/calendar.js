// Calendar page: action queue, content pipeline board, month calendar, next-14-days list, tests panel.
import { api, fmt, toast, badge, platformChip, esc, $, $$, tabs, modal, withBusy, parseDate, isoDate } from "/static/js/common.js";

const API = "/api/calendar";
let data = null;
let freshId = null; // highlight the item just created

const STATUS_SHORT = {
  running: "Running",
  scheduled: "Scheduled",
  pending_feedback: "Vin's feedback",
  final_pending_approval: "Final, approval",
  approved: "Approved",
};

// ------------------------------------------------------------------ load
async function load() {
  try {
    data = await api(API + "/");
  } catch (e) {
    toast("Could not load calendar: " + e.message, "error");
    $("#board").innerHTML = `<div class="empty">Could not load the calendar.</div>`;
    $("#cal-action-list").innerHTML = `<div class="action-empty">Could not load the action queue: ${esc(e.message)}</div>`;
    return;
  }
  renderSummary();
  renderActionQueue();
  renderBoard();
  renderCalendar();
  renderTests();
  fillFormOptions();
}

function renderSummary() {
  const c = data.counts;
  const ov = c.overdue ? `<span class="tone-bad"><b>${c.overdue}</b> overdue</span> · ` : "";
  $("#cal-summary").innerHTML = `${ov}<b>${c.by_status.running}</b> running · <b>${c.by_status.pending_feedback}</b> waiting on Vin · <b>${c.by_status.final_pending_approval}</b> awaiting approval · <b>${c.tests_running}</b> tests live`;
}

function renderActionQueue() {
  const actions = [];
  const seen = new Set();
  data.overdue.forEach((item) => {
    seen.add(item.id);
    actions.push({ item, kind: "Overdue", tone: "bad", approve: item.status === "final_pending_approval" });
  });
  data.content.filter((item) => item.status === "final_pending_approval" && !seen.has(item.id)).forEach((item) => {
    seen.add(item.id);
    actions.push({ item, kind: "Final approval", tone: "watch", approve: true });
  });
  data.content.filter((item) => item.status === "pending_feedback" && !seen.has(item.id)).forEach((item) => {
    actions.push({ item, kind: "Vin feedback", tone: "watch", approve: false });
  });
  const nFinal = data.counts.by_status.final_pending_approval;
  $("#cal-action-sub").textContent = `${data.overdue.length} overdue · ${nFinal} final approval${nFinal === 1 ? "" : "s"} · ${data.counts.by_status.pending_feedback} feedback`;
  if (!actions.length) {
    $("#cal-action-list").innerHTML = `<div class="action-empty">Nothing overdue or waiting for review. Use the board to inspect scheduled and running work.</div>`;
    return;
  }
  const shown = actions.slice(0, 8);
  const more = actions.length - shown.length;
  $("#cal-action-list").innerHTML = `<ul class="action-list">${shown.map(({ item, kind, tone, approve }) => `
    <li class="action-item">
      ${badge(tone, kind)}
      <div class="action-copy">
        <div class="action-title">${platformChip(item.platform)} ${esc(item.name)}</div>
        <div class="action-meta">${esc(item.owner)} · due ${esc(fmt.date(item.due))} · ${esc(item.format)} / ${esc(item.segment)}${item.campaign_name ? ` · ${esc(item.campaign_name)}` : ""}</div>
      </div>
      <div class="action-controls">
        ${approve ? `<button class="btn btn-sm btn-primary" type="button" data-cal-approve="${esc(item.id)}">Approve</button>` : ""}
        <button class="btn btn-sm" type="button" data-cal-open="${esc(item.id)}">Open on board</button>
      </div>
    </li>`).join("")}</ul>${more > 0 ? `<div class="action-empty">${more} more on the board.</div>` : ""}`;
}

$("#cal-actions").addEventListener("click", async (event) => {
  const approve = event.target.closest("[data-cal-approve]");
  if (approve) {
    await moveItem(approve.dataset.calApprove, "approved", approve);
    return;
  }
  const open = event.target.closest("[data-cal-open]");
  if (!open) return;
  tabsCtl.select("board");
  const card = $(`.ccard[data-id="${CSS.escape(open.dataset.calOpen)}"]`);
  if (card) {
    card.scrollIntoView({ block: "center", behavior: "smooth" });
    const edit = card.querySelector("[data-edit]");
    if (edit) edit.focus({ preventScroll: true });
  }
});

// ------------------------------------------------------------------ board
function cardHtml(item) {
  const st = data.statuses;
  const i = st.indexOf(item.status);
  const prev = i > 0 ? st[i - 1] : null;
  const next = i < st.length - 1 ? st[i + 1] : null;
  const opts = st.map((s) => `<option value="${s}"${s === item.status ? " selected" : ""}>${esc(data.status_labels[s])}</option>`).join("");
  const dueTxt = item.overdue ? `Overdue · ${fmt.date(item.due)}` : `Due ${fmt.date(item.due)}`;
  const links = [];
  if (item.campaign_name) links.push(`<span title="${esc(item.campaign_name)}">Campaign <b>${esc(item.campaign_name)}</b></span>`);
  if (item.test_name) links.push(`<span title="${esc(item.test_name)}">Test <b>${esc(item.test_name)}</b></span>`);
  return `<article class="ccard${item.overdue ? " is-overdue" : ""}${item.id === freshId ? " is-new" : ""}" draggable="true" data-id="${esc(item.id)}" title="${esc(item.notes || "")}">
    <div class="ccard-name">${esc(item.name)}</div>
    <div class="ccard-tags">${platformChip(item.platform)}<span class="tag">${esc(item.format)}</span><span class="tag">${esc(item.segment)}</span></div>
    <div class="ccard-meta"><span>${esc(item.owner)}</span><span class="due${item.overdue ? " overdue" : ""}">${esc(dueTxt)}</span></div>
    ${links.length ? `<div class="ccard-links">${links.join("")}</div>` : ""}
    ${item.notes ? `<details><summary>Notes</summary><p>${esc(item.notes)}</p></details>` : ""}
    <div class="ccard-move">
      <button class="btn btn-sm btn-icon" type="button" data-move="${prev || ""}" ${prev ? "" : "disabled"} aria-label="Move back${prev ? " to " + esc(data.status_labels[prev]) : ""}" title="${prev ? "← " + esc(data.status_labels[prev]) : ""}">&larr;</button>
      <select class="select" data-move-select aria-label="Move to status">${opts}</select>
      <button class="btn btn-sm btn-icon" type="button" data-move="${next || ""}" ${next ? "" : "disabled"} aria-label="Move forward${next ? " to " + esc(data.status_labels[next]) : ""}" title="${next ? esc(data.status_labels[next]) + " →" : ""}">&rarr;</button>
      <button class="btn btn-sm btn-ghost" type="button" data-edit>Edit</button>
    </div>
  </article>`;
}

function renderBoard() {
  $("#board").innerHTML = data.columns.map((col) => `
    <section class="col" data-status="${col.status}" aria-label="${esc(col.label)}">
      <div class="col-head"><span class="col-title">${esc(col.label)}</span><span class="col-count">${col.items.length}</span></div>
      <div class="col-body">${col.items.length ? col.items.map(cardHtml).join("") : `<div class="col-empty">Nothing here</div>`}</div>
    </section>`).join("");
}

async function moveItem(id, status, el) {
  if (!status) return;
  const item = data.content.find((c) => c.id === id);
  if (!item || item.status === status) return;
  try {
    await withBusy(el, () => api(`${API}/content/${encodeURIComponent(id)}/move`, { body: { status } }),
      `${item.name} → ${data.status_labels[status]}`);
    await load();
  } catch (e) {
    await load(); // restore select/board to the server state
  }
}

function wireBoard() {
  const board = $("#board");
  board.addEventListener("click", (e) => {
    const card = e.target.closest(".ccard");
    if (!card) return;
    const btn = e.target.closest("[data-move]");
    if (btn && btn.dataset.move) return moveItem(card.dataset.id, btn.dataset.move, btn);
    if (e.target.closest("[data-edit]")) return openEdit(card.dataset.id);
  });
  board.addEventListener("change", (e) => {
    const sel = e.target.closest("[data-move-select]");
    if (sel) moveItem(sel.closest(".ccard").dataset.id, sel.value, sel);
  });
  // optional drag and drop
  board.addEventListener("dragstart", (e) => {
    const card = e.target.closest(".ccard");
    if (!card || e.target.closest("select, button, details")) return;
    card.classList.add("dragging");
    e.dataTransfer.setData("text/plain", card.dataset.id);
    e.dataTransfer.effectAllowed = "move";
  });
  board.addEventListener("dragend", (e) => {
    const card = e.target.closest(".ccard");
    if (card) card.classList.remove("dragging");
    $$(".col.drop-over", board).forEach((c) => c.classList.remove("drop-over"));
  });
  board.addEventListener("dragover", (e) => {
    const col = e.target.closest(".col");
    if (!col) return;
    e.preventDefault();
    $$(".col.drop-over", board).forEach((c) => c !== col && c.classList.remove("drop-over"));
    col.classList.add("drop-over");
  });
  board.addEventListener("drop", (e) => {
    const col = e.target.closest(".col");
    if (!col) return;
    e.preventDefault();
    col.classList.remove("drop-over");
    const id = e.dataTransfer.getData("text/plain");
    if (id) moveItem(id, col.dataset.status, null);
  });
}

function openEdit(id) {
  const item = data.content.find((c) => c.id === id);
  if (!item) return;
  const body = `<form class="stack-sm" id="edit-form" autocomplete="off">
    <div class="field"><label for="ef-name">Name</label><input class="input" id="ef-name" name="name" maxlength="200" value="${esc(item.name)}"></div>
    <div class="grid grid-2">
      <div class="field"><label for="ef-owner">Owner</label><input class="input" id="ef-owner" name="owner" maxlength="60" value="${esc(item.owner)}"></div>
      <div class="field"><label for="ef-due">Due</label><input class="input" id="ef-due" name="due" type="date" value="${esc(item.due)}"></div>
    </div>
    <div class="field"><label for="ef-notes">Notes</label><textarea class="textarea" id="ef-notes" name="notes" maxlength="2000">${esc(item.notes || "")}</textarea></div>
  </form>`;
  modal({
    title: "Edit " + item.name,
    body,
    actions: [
      { label: "Cancel", kind: "ghost" },
      {
        label: "Save", kind: "primary",
        onClick: async (close, m) => {
          const f = $("#edit-form", m);
          const payload = {};
          ["name", "owner", "due", "notes"].forEach((k) => {
            const v = f.elements[k].value;
            if (v !== (item[k] || "")) payload[k] = v;
          });
          if (!Object.keys(payload).length) return true;
          await api(`${API}/content/${encodeURIComponent(id)}`, { body: payload });
          toast("Saved " + (payload.name || item.name));
          await load();
          return true;
        },
      },
    ],
  });
}

// --------------------------------------------------------------- calendar
function renderCalendar() {
  const today = parseDate(data.today);
  const y = today.getFullYear(), m = today.getMonth();
  const first = new Date(y, m, 1);
  const last = new Date(y, m + 1, 0);
  $("#month-title").textContent = first.toLocaleString("en-US", { month: "long", year: "numeric" });
  $("#legend").innerHTML = data.statuses.map((s) => `<span><span class="ev ${s}"></span>${esc(STATUS_SHORT[s])}</span>`).join("");

  const byDate = {};
  data.content.forEach((c) => { (byDate[c.due] = byDate[c.due] || []).push(c); });

  const start = new Date(y, m, 1 - first.getDay());
  const end = new Date(y, m, last.getDate() + (6 - last.getDay()));
  const cells = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => `<div class="dow" role="columnheader">${d}</div>`);
  for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
    const iso = isoDate(d);
    const items = byDate[iso] || [];
    const cls = ["day"];
    if (d.getMonth() !== m) cls.push("out");
    if (iso === data.today) cls.push("today");
    const evs = items.map((c) => `<span class="ev ${c.status}${c.overdue ? " overdue" : ""}" title="${esc(`${c.name} · ${c.status_label}${c.overdue ? " · OVERDUE" : ""} · ${c.owner}`)}">${esc(c.name)}</span>`).join("");
    cells.push(`<div class="${cls.join(" ")}" role="gridcell" aria-label="${esc(fmt.date(iso, { dow: true }))}: ${items.length} item(s)"><span class="day-num">${d.getDate()}</span>${evs}</div>`);
  }
  $("#month").innerHTML = cells.join("");

  const up = data.upcoming_14d;
  const endIso = isoDate(new Date(y, m, today.getDate() + 13));
  $("#upcoming-range").textContent = `${fmt.date(data.today)} – ${fmt.date(endIso)}`;
  const overdue = data.overdue.map((c) => rowHtml(c, true)).join("");
  $("#upcoming").innerHTML = (overdue + up.map((c) => rowHtml(c, false)).join("")) || `<li class="empty">Nothing due in the next 14 days.</li>`;
}

function rowHtml(c, overdue) {
  const when = overdue ? `<span class="when tone-bad">Overdue ${esc(fmt.date(c.due))}</span>`
    : `<span class="when${c.due === data.today ? " today" : ""}">${c.due === data.today ? "Today" : esc(fmt.date(c.due, { dow: true }))}</span>`;
  const sub = [c.owner, c.format, c.segment, c.campaign_name].filter(Boolean).map(esc).join(" · ");
  return `<li>${when}<span class="what"><span class="truncate strong">${platformChip(c.platform)} ${esc(c.name)}</span><span class="truncate muted small">${sub}</span></span>${badge(c.status)}</li>`;
}

// ------------------------------------------------------------------ tests
function metricFmt(t, v) {
  if (v === null || v === undefined) return fmt.none;
  return t.metric_unit === "money" ? fmt.cpt(v) : fmt.pct(v, 2);
}

function meterTone(pct) { return pct >= 100 ? "good" : pct >= 50 ? "" : "watch"; }

function runningTest(t) {
  const b = t.benchmark || {}, cur = t.current || {};
  const target = t.target === null || t.target === undefined ? "" :
    ` <span class="muted small">target ${t.direction === "below" ? "<" : ">"} ${esc(metricFmt(t, t.target))}</span>`;
  const valTone = t.passing === null ? "" : t.passing ? "tone-good" : "tone-bad";
  return `<article class="tcard">
    <div class="tcard-head"><div class="tcard-name">${esc(t.name)}</div>${badge(t.status)}</div>
    <div class="tcard-sub">${platformChip(t.platform)}<span>${esc(t.campaign_name || t.campaign_id)}</span><span>·</span><span class="nowrap">${esc(fmt.date(t.started))} → ${esc(fmt.date(t.ends))}</span></div>
    <div class="tcard-hyp">${esc(t.hypothesis)}</div>
    <div class="bench">${esc(t.benchmark_text)}</div>
    <div class="tstats">
      <div><div class="tstat-label">Spend</div><div class="tstat-value">${fmt.money(cur.spend)}</div></div>
      <div><div class="tstat-label">Trials</div><div class="tstat-value">${fmt.int(cur.trials)}</div></div>
      <div><div class="tstat-label">${esc(t.metric_label)}</div><div class="tstat-value ${valTone}">${esc(metricFmt(t, cur.value))}</div>${target}</div>
    </div>
    <div class="tprog"><span>Spend</span><div class="meter ${meterTone(t.spend_pct)}" role="progressbar" aria-valuenow="${t.spend_pct}" aria-valuemin="0" aria-valuemax="100" aria-label="Spend toward minimum"><span style="width:${t.spend_pct}%"></span></div><span class="num">${fmt.money(cur.spend)} / ${fmt.money(b.min_spend)}</span></div>
    <div class="tprog"><span>Trials</span><div class="meter ${meterTone(t.trials_pct)}" role="progressbar" aria-valuenow="${t.trials_pct}" aria-valuemin="0" aria-valuemax="100" aria-label="Trials toward minimum"><span style="width:${t.trials_pct}%"></span></div><span class="num">${fmt.int(cur.trials)} / ${fmt.int(b.min_trials)}</span></div>
    <div class="verdict ${t.verdict}">${esc(t.verdict_line)}</div>
    ${t.notes ? `<div class="muted small">${esc(t.notes)}</div>` : ""}
  </article>`;
}

function queuedTest(t) {
  return `<article class="tcard">
    <div class="tcard-head"><div class="tcard-name">${esc(t.name)}</div>${badge(t.status)}</div>
    <div class="tcard-sub">${platformChip(t.platform)}<span>${esc(t.campaign_name || t.campaign_id)}</span><span>·</span><span class="nowrap">${esc(fmt.date(t.started))} → ${esc(fmt.date(t.ends))}</span></div>
    <div class="tcard-hyp">${esc(t.hypothesis)}</div>
    <div class="bench">${esc(t.benchmark_text)}</div>
    <div class="verdict"><b>Starts when:</b> ${esc(t.notes || "scheduled start " + fmt.date(t.started))} Planned start ${esc(fmt.date(t.started, { dow: true }))}.</div>
  </article>`;
}

function doneTest(t) {
  const cur = t.current || {};
  return `<details class="tdone">
    <summary>${badge(t.status)}<span class="tdone-name">${esc(t.name)}</span>
      <span class="tdone-result">${esc(t.metric_label)} ${esc(metricFmt(t, cur.value))} · ${fmt.money(cur.spend)} · ${fmt.int(cur.trials)} trials</span></summary>
    <div class="tdone-body">
      <div class="tcard-sub">${platformChip(t.platform)}<span>${esc(t.campaign_name || t.campaign_id)}</span><span>·</span><span>${esc(fmt.date(t.started))} → ${esc(fmt.date(t.ends))}</span></div>
      <div class="tcard-hyp">${esc(t.hypothesis)}</div>
      <div class="bench">${esc(t.benchmark_text)}</div>
      <div class="verdict ${t.status === "won" ? "on_track" : t.status === "lost" ? "failing" : "not_enough_data"}"><b>Result:</b> ${esc(t.notes || t.status)}</div>
    </div>
  </details>`;
}

function renderTests() {
  const running = data.tests.filter((t) => t.status === "running");
  const queued = data.tests.filter((t) => t.status === "queued");
  const done = data.tests.filter((t) => ["won", "lost", "inconclusive"].includes(t.status));
  const parts = [];
  parts.push(`<div><h3 class="section-label">Running (${running.length})</h3>${running.length ? `<div class="tests-grid">${running.map(runningTest).join("")}</div>` : `<div class="empty">No tests running.</div>`}</div>`);
  if (queued.length) parts.push(`<div><h3 class="section-label">Queued (${queued.length})</h3><div class="tests-grid">${queued.map(queuedTest).join("")}</div></div>`);
  if (done.length) parts.push(`<div><h3 class="section-label">Finished (${done.length})</h3>${done.map(doneTest).join("")}</div>`);
  $("#tests").innerHTML = parts.join("");
}

// ------------------------------------------------------------------- form
let optionsFilled = false;
function fillFormOptions() {
  if (optionsFilled) return;
  optionsFilled = true;
  const camp = $("#nf-campaign");
  data.campaigns.forEach((c) => camp.insertAdjacentHTML("beforeend", `<option value="${esc(c.id)}">${c.platform === "google" ? "G" : "M"} · ${esc(c.name)}</option>`));
  const test = $("#nf-test");
  data.tests.filter((t) => ["running", "queued"].includes(t.status))
    .forEach((t) => test.insertAdjacentHTML("beforeend", `<option value="${esc(t.id)}">${esc(t.name)}</option>`));
}

function wireForm() {
  const card = $("#new-card"), toggle = $("#new-toggle"), form = $("#new-form");
  const show = (on) => {
    card.hidden = !on;
    toggle.setAttribute("aria-expanded", on);
    if (on) $("#nf-name").focus();
  };
  toggle.addEventListener("click", () => show(card.hidden));
  $$("[data-close-new]").forEach((b) => b.addEventListener("click", () => show(false)));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const body = {};
    fd.forEach((v, k) => { body[k] = typeof v === "string" ? v.trim() : v; });
    if (!body.campaign_id) delete body.campaign_id;
    if (!body.test_id) delete body.test_id;
    try {
      const res = await withBusy($("#nf-submit"), () => api(API + "/content", { body }), `Created ${body.name}`);
      freshId = res.item.id;
      form.reset();
      $("#nf-due").value = data.today;
      show(false);
      await load();
      tabsCtl.select("board");
      const el = $(`.ccard[data-id="${CSS.escape(freshId)}"]`);
      if (el) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    } catch (err) { /* withBusy toasted it */ }
  });
}

// ------------------------------------------------------------------- boot
const tabsCtl = tabs($("#views"));
wireBoard();
wireForm();
load();
