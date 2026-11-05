// Home: a cross-page exception queue assembled from existing Management and
// Calendar responses. Final content approvals use the existing move mutation.
import { api, fmt, toast, esc, badge, platformChip, cptTone, $ } from "/static/js/common.js";

let management = null;
let calendar = null;

function actionItem({ tone = "idle", label, title, meta, href, linkText = "Review", approveId = null }) {
  const controls = approveId
    ? `<button class="btn btn-sm btn-primary" type="button" data-home-approve="${esc(approveId)}">Approve</button>
       <a class="btn btn-sm" href="/calendar">Open</a>`
    : `<a class="btn btn-sm" href="${esc(href)}">${esc(linkText)}</a>`;
  return `<li class="action-item">
    ${badge(tone, label)}
    <div class="action-copy">
      <div class="action-title">${title}</div>
      <div class="action-meta">${meta}</div>
    </div>
    <div class="action-controls">${controls}</div>
  </li>`;
}

function campaignAction(c) {
  const trials = Number(c.trials_7d || 0);
  const thin = trials < 3 ? " · thin read" : "";
  return actionItem({
    tone: "bad",
    label: "Failing",
    title: `${platformChip(c.platform)} ${esc(c.name)}`,
    meta: `7d CPT <strong class="${cptTone(c.cpt_7d)}">${fmt.cpt(c.cpt_7d)}</strong> · ${fmt.money(c.spend_7d)} spend · ${fmt.int(trials)} trials${thin}. ${esc(c.why)}`,
    href: `/campaigns#${encodeURIComponent(c.id)}`,
    linkText: "Controls",
  });
}

function buildActions() {
  const actions = [];
  const active = management.in_play.groups.flatMap((g) => g.campaigns);
  active.filter((c) => c.read === "failing")
    .sort((a, b) => (b.spend_7d || 0) - (a.spend_7d || 0))
    .forEach((c) => actions.push(campaignAction(c)));

  const seenContent = new Set();
  calendar.overdue.forEach((item) => {
    seenContent.add(item.id);
    actions.push(actionItem({
      tone: "bad",
      label: "Overdue",
      title: esc(item.name),
      meta: `${esc(item.owner)} · due ${fmt.date(item.due)} · ${esc(item.status_label)}`,
      href: "/calendar",
      linkText: "Open board",
    }));
  });

  calendar.content.filter((item) => item.status === "final_pending_approval" && !seenContent.has(item.id))
    .forEach((item) => {
      seenContent.add(item.id);
      actions.push(actionItem({
        tone: "watch",
        label: "Approval",
        title: esc(item.name),
        meta: `${platformChip(item.platform)} ${esc(item.owner)} · due ${fmt.date(item.due)} · ${esc(item.format)} / ${esc(item.segment)}`,
        approveId: item.id,
      }));
    });

  calendar.content.filter((item) => item.status === "pending_feedback" && !seenContent.has(item.id))
    .slice(0, 3)
    .forEach((item) => actions.push(actionItem({
      tone: "watch",
      label: "Feedback",
      title: esc(item.name),
      meta: `${esc(item.owner)} · due ${fmt.date(item.due)} · waiting on Vin`,
      href: "/calendar",
      linkText: "Review",
    })));

  management.tests.running.filter((t) => t.verdict === "losing").forEach((t) => {
    actions.push(actionItem({
      tone: "bad",
      label: "Test",
      title: esc(t.name),
      meta: `${esc(t.campaign_name || t.campaign_id)} · ${esc(t.verdict_note)}`,
      href: "/management#mg-tests",
      linkText: "Scoreboard",
    }));
  });

  const carry = management.today.carry_over || 0;
  if (carry) {
    actions.push(actionItem({
      tone: "watch",
      label: "Checklist",
      title: `${carry} checklist item${carry === 1 ? "" : "s"} carried over`,
      meta: "Open work from earlier days is still incomplete.",
      href: "/management#mg-checklist",
      linkText: "Clear items",
    }));
  }

  const pace = management.today.pace_pct;
  if (pace !== null && pace !== undefined && (pace > 105 || pace < 90)) {
    actions.push(actionItem({
      tone: "bad",
      label: "Pacing",
      title: `Account projecting at ${fmt.pct(pace)} of budget`,
      meta: `${fmt.money(management.today.projected)} projected against ${fmt.money(management.today.monthly_budget)}.`,
      href: "/reporting",
      linkText: "Pacing",
    }));
  }

  return actions;
}

function renderQueue() {
  const actions = buildActions();
  const failing = management.in_play.counts.failing || 0;
  const approvals = calendar.content.filter((c) => c.status === "final_pending_approval").length;
  const overdue = calendar.overdue.length;
  $("#home-queue-sub").textContent = `${failing} failing · ${approvals} final approval${approvals === 1 ? "" : "s"} · ${overdue} overdue`;

  if (!actions.length) {
    $("#home-queue").innerHTML = `<div class="action-empty">
      <strong>No urgent exceptions.</strong>
      <div class="mt-2">Review watching campaigns, today’s checklist and upcoming creative before making budget changes.</div>
      <div class="row mt-4"><a class="btn btn-sm" href="/management">Open morning cockpit</a><a class="btn btn-sm" href="/calendar">Content schedule</a></div>
    </div>`;
    return;
  }

  const visible = actions.slice(0, 8);
  const remainder = actions.length - visible.length;
  $("#home-queue").innerHTML = `<ul class="action-list">${visible.join("")}</ul>` +
    (remainder > 0 ? `<div class="card-foot">${remainder} more lower-priority item${remainder === 1 ? "" : "s"} on Management and Calendar.</div>` : "");
}

async function loadBrief() {
  try {
    [management, calendar] = await Promise.all([api("/api/management/"), api("/api/calendar/")]);
    renderQueue();
  } catch (e) {
    $("#home-queue-sub").textContent = "Could not refresh";
    $("#home-queue").innerHTML = `<div class="card-body"><div class="callout bad">
      The exception queue could not load: ${esc(e.message)}. KPI tiles above are still available.
      <div class="mt-2"><button class="btn btn-sm" type="button" id="home-retry">Retry</button></div>
    </div></div>`;
    toast("Could not load the morning brief: " + e.message, "error");
  }
}

$("#home-queue").addEventListener("click", async (event) => {
  if (event.target.closest("#home-retry")) {
    await loadBrief();
    return;
  }
  const button = event.target.closest("[data-home-approve]");
  if (!button) return;
  const id = button.dataset.homeApprove;
  const item = calendar && calendar.content.find((c) => c.id === id);
  button.disabled = true;
  try {
    await api(`/api/calendar/content/${encodeURIComponent(id)}/move`, { body: { status: "approved" } });
    toast(`Approved: ${item ? item.name : id}`);
    await loadBrief();
  } catch (e) {
    toast("Could not approve item: " + e.message, "error");
    button.disabled = false;
  }
});

loadBrief();
