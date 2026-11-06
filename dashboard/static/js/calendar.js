// Calendar page: month calendar (prev / next month) with content items and test start / end
// markers, plus the next-14-days list. Items open an edit modal (fields + status). The
// needs-action queue and the testing schedule live on Management.
import { api, fmt, toast, badge, platformChip, esc, $, $$, modal, withBusy, parseDate, isoDate } from "/static/js/common.js";

const API = "/api/calendar";
let data = null;
let view = null; // { y, m } of the month on screen; starts at the sample-data month

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
    $("#month").innerHTML = `<div class="empty" style="grid-column:1/-1">Could not load the calendar.</div>`;
    return;
  }
  if (!view) { const t = parseDate(data.today); view = { y: t.getFullYear(), m: t.getMonth() }; }
  renderSummary();
  renderCalendar();
  renderUpcoming();
  fillFormOptions();
}

function renderSummary() {
  const c = data.counts;
  const ov = c.overdue ? `<span class="tone-bad"><b>${c.overdue}</b> overdue</span> · ` : "";
  $("#cal-summary").innerHTML = `${ov}<b>${c.by_status.running}</b> running · <b>${c.by_status.pending_feedback}</b> waiting on Vin · <b>${c.by_status.final_pending_approval}</b> awaiting approval · <b>${c.tests_running}</b> tests live · <a href="/management#mg-actions">Needs action in Management</a>`;
}

async function moveItem(id, status) {
  const item = data.content.find((c) => c.id === id);
  if (!item || !status || item.status === status) return;
  await api(`${API}/content/${encodeURIComponent(id)}/move`, { body: { status } });
  toast(`${item.name} → ${data.status_labels[status]}`, "success");
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
    <div class="field"><label for="ef-status">Status</label><select class="select" id="ef-status" name="status">${data.statuses.map((s) => `<option value="${s}"${s === item.status ? " selected" : ""}>${esc(data.status_labels[s])}</option>`).join("")}</select></div>
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
          const status = f.elements.status.value;
          if (!Object.keys(payload).length && status === item.status) return true;
          if (Object.keys(payload).length) {
            await api(`${API}/content/${encodeURIComponent(id)}`, { body: payload });
            toast("Saved " + (payload.name || item.name), "success");
          }
          if (status !== item.status) await moveItem(id, status);
          await load();
          return true;
        },
      },
    ],
  });
}

// --------------------------------------------------------------- calendar
function shiftMonth(delta) {
  const d = new Date(view.y, view.m + delta, 1);
  view = { y: d.getFullYear(), m: d.getMonth() };
  renderCalendar();
}

function testMarker(t, kind) {
  const label = kind === "start" ? "Test starts" : "Test ends";
  return `<a class="ev test" href="/management#mg-schedule-card" title="${esc(`${label}: ${t.name} · ${t.status}`)}">${kind === "start" ? "&#9656;" : "&#9632;"} ${esc(t.name)}</a>`;
}

function renderCalendar() {
  const today = parseDate(data.today);
  const y = view.y, m = view.m;
  const first = new Date(y, m, 1);
  const last = new Date(y, m + 1, 0);
  const label = first.toLocaleString("en-US", { month: "long", year: "numeric" });
  $("#month-title").textContent = label;
  $("#month-today").hidden = y === today.getFullYear() && m === today.getMonth();
  $("#legend").innerHTML = data.statuses.map((s) => `<span><span class="ev ${s}"></span>${esc(STATUS_SHORT[s])}</span>`).join("")
    + `<span><span class="ev test"></span>Test start / end</span>`;

  const byDate = {};
  data.content.forEach((c) => { (byDate[c.due] = byDate[c.due] || []).push(c); });
  const testsBy = {};
  (data.tests || []).forEach((t) => {
    if (t.started) (testsBy[t.started] = testsBy[t.started] || []).push(testMarker(t, "start"));
    if (t.ends) (testsBy[t.ends] = testsBy[t.ends] || []).push(testMarker(t, "end"));
  });

  const start = new Date(y, m, 1 - first.getDay());
  const end = new Date(y, m, last.getDate() + (6 - last.getDay()));
  const cells = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => `<div class="dow" role="columnheader">${d}</div>`);
  for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
    const iso = isoDate(d);
    const items = byDate[iso] || [];
    const cls = ["day"];
    if (d.getMonth() !== m) cls.push("out");
    if (iso === data.today) cls.push("today");
    const evs = items.map((c) => `<button type="button" class="ev ${c.status}${c.overdue ? " overdue" : ""}" data-open="${esc(c.id)}" title="${esc(`${c.name} · ${c.status_label}${c.overdue ? " · OVERDUE" : ""} · ${c.owner}`)}">${esc(c.name)}</button>`).join("");
    const tests = testsBy[iso] || [];
    cells.push(`<div class="${cls.join(" ")}" role="gridcell" aria-label="${esc(fmt.date(iso, { dow: true }))}: ${items.length} item(s)${tests.length ? `, ${tests.length} test date(s)` : ""}"><span class="day-num">${d.getDate()}</span>${evs}${tests.join("")}</div>`);
  }
  $("#month").innerHTML = cells.join("");
}

// The next-14-days list always counts from today, whatever month is on screen.
function renderUpcoming() {
  const today = parseDate(data.today);
  const up = data.upcoming_14d;
  const endIso = isoDate(new Date(today.getFullYear(), today.getMonth(), today.getDate() + 13));
  $("#upcoming-range").textContent = `${fmt.date(data.today)} – ${fmt.date(endIso)}`;
  const overdue = data.overdue.map((c) => rowHtml(c, true)).join("");
  $("#upcoming").innerHTML = (overdue + up.map((c) => rowHtml(c, false)).join("")) || `<li class="empty">Nothing due in the next 14 days.</li>`;
}

function rowHtml(c, overdue) {
  const when = overdue ? `<span class="when tone-bad">Overdue ${esc(fmt.date(c.due))}</span>`
    : `<span class="when${c.due === data.today ? " today" : ""}">${c.due === data.today ? "Today" : esc(fmt.date(c.due, { dow: true }))}</span>`;
  const sub = [c.owner, c.format, c.segment, c.campaign_name].filter(Boolean).map(esc).join(" · ");
  return `<li>${when}<button type="button" class="what up-open" data-open="${esc(c.id)}" aria-label="${esc(`Edit ${c.name}`)}"><span class="truncate strong">${platformChip(c.platform)} ${esc(c.name)}</span><span class="truncate muted small">${sub}</span></button>${badge(c.status)}</li>`;
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
      await withBusy($("#nf-submit"), () => api(API + "/content", { body }), `Created ${body.name}`);
      form.reset();
      $("#nf-due").value = data.today;
      show(false);
      await load();
    } catch (err) { /* withBusy toasted it */ }
  });
}

// ------------------------------------------------------------------- boot
// Click any item (month grid or next-14-days list) to edit it; /calendar#<content id>
// (linked from Management's Needs action) opens that item directly.
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-open]");
  if (b) openEdit(b.dataset.open);
});
function openFromHash() {
  const id = decodeURIComponent(location.hash.slice(1));
  if (id && data && data.content.some((c) => c.id === id)) openEdit(id);
}
window.addEventListener("hashchange", openFromHash);

$("#month-prev").addEventListener("click", () => { if (view) shiftMonth(-1); });
$("#month-next").addEventListener("click", () => { if (view) shiftMonth(1); });
$("#month-today").addEventListener("click", () => {
  const t = parseDate(data.today);
  view = { y: t.getFullYear(), m: t.getMonth() };
  renderCalendar();
});

wireForm();
load().then(openFromHash);
