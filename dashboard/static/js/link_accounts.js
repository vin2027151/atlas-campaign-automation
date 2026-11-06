// Link Accounts page. Reads masked status from GET /api/accounts/; every change goes
// through adminPost (X-Admin-Key). Secret inputs are cleared after save and never
// pre-filled: the server only ever reports "set" / "not set".
import { adminPost } from "./datamode.js";
import { toast } from "/static/js/common.js";

const grid = document.getElementById("la-grid");
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const STATE = { not_linked: ["Not linked", "idle"], linked: ["Linked", "good"], error: ["Error", "error"] };
let data = null;

function fieldHtml(p, f) {
  const st = p.status.fields[f.key] || {};
  const tag = st.set ? `<span class="set">set${st.masked ? " · " + esc(st.masked) : ""}</span>` : `<span class="unset">not set</span>`;
  const ro = data.admin_set ? "" : " disabled";
  return `<div class="la-field"><label for="f-${p.id}-${f.key}"><span>${esc(f.label)}</span>${tag}</label>
    <input class="input" id="f-${p.id}-${f.key}" name="${esc(f.key)}" type="${f.secret ? "password" : "text"}"
      autocomplete="off" spellcheck="false" placeholder="${esc(st.set ? "leave blank to keep" : f.hint || "")}"${ro}></div>`;
}

function card(p) {
  const s = p.status;
  const [label, tone] = STATE[s.state] || STATE.not_linked;
  const ro = data.admin_set ? "" : " disabled";
  const ids = p.fields.filter((f) => !f.secret && s.fields[f.key] && s.fields[f.key].masked)
    .map((f) => `${esc(f.label)} <b>${esc(s.fields[f.key].masked)}</b>`).join(" · ");
  const meta = [
    s.linked ? `Linked ${esc((s.linked_at || "").slice(0, 10))}` : "",
    ids,
    s.tested_at ? `Last test ${esc(s.tested_at.slice(0, 16).replace("T", " "))} UTC: ${s.tested_ok ? "OK" : "failed"}` : "",
  ].filter(Boolean).join(" · ");
  const redirect = p.redirect_uri ? `<div class="la-sect">Redirect URI to register</div>
    <div class="la-redirect"><code>${esc(p.redirect_uri)}</code><button class="btn btn-sm" type="button" data-copy="${esc(p.redirect_uri)}">Copy</button></div>` : "";
  const note = p.built ? "" : `<p class="la-meta">Requirements listed, OAuth connection not built yet. Paste tokens below; Test connection works.</p>`;
  return `<section class="card la-card" id="card-${p.id}" data-platform="${p.id}">
    <div class="card-head"><h2 class="card-title">${esc(p.name)}</h2><span class="badge ${tone}">${label}</span></div>
    <div class="card-body">
      ${note}
      ${meta ? `<p class="la-meta">${meta}</p>` : ""}
      ${s.error ? `<p class="la-result bad">${esc(s.error)}</p>` : ""}
      <div class="la-sect">Requirements</div>
      <ul class="la-req">${p.requirements.map((r) => `<li><span>${esc(r)}</span></li>`).join("")}</ul>
      <p class="la-docs"><a href="${esc(p.docs)}" target="_blank" rel="noopener noreferrer">Official docs</a> · test call <code>${esc(p.test_call)}</code></p>
      ${redirect}
      <div class="la-sect">Credentials</div>
      <form class="la-fields" data-form autocomplete="off">${p.fields.map((f) => fieldHtml(p, f)).join("")}</form>
      <div class="la-actions">
        <button class="btn" type="button" data-act="save"${ro}>Save</button>
        ${p.oauth ? `<button class="btn btn-primary" type="button" data-act="connect"${ro}>Connect</button>` : ""}
        <button class="btn" type="button" data-act="test"${ro}${s.linked ? "" : " disabled"}>Test connection</button>
        <button class="btn btn-danger" type="button" data-act="unlink"${ro}${s.linked || Object.values(s.fields).some((x) => x.set) ? "" : " disabled"}>Unlink</button>
      </div>
      <div class="la-result" data-result></div>
    </div></section>`;
}

function render() {
  const admin = document.getElementById("la-admin");
  if (!data.admin_set) {
    admin.hidden = false;
    admin.className = "la-banner warn";
    admin.innerHTML = `<b>Read-only.</b> No admin passphrase is set. On the server, as the app user, run
      <code>.venv/bin/python -m accounts.set_admin_key</code> from the dashboard folder, then reload this page.`;
  } else admin.hidden = true;
  document.getElementById("la-mode").innerHTML = `Data mode: <b>${data.data_mode === "live" ? "Live data" : "Sample data"}</b>.
    ${data.live_available ? "Live can be selected in the sidebar." : "Live unlocks once an account is linked and passes Test connection."}
    ${esc(data.writes_note)}`;
  grid.innerHTML = data.platforms.map(card).join("");
}

async function load() {
  const res = await fetch("/api/accounts/", { headers: { Accept: "application/json" } });
  data = await res.json();
  render();
}

function result(cardEl, msg, tone) {
  const el = cardEl.querySelector("[data-result]");
  el.className = "la-result " + (tone || "");
  el.textContent = msg;
}

async function save(cardEl, pid) {
  const fields = {};
  cardEl.querySelectorAll("[data-form] input").forEach((i) => { if (i.value.trim()) fields[i.name] = i.value.trim(); });
  if (!Object.keys(fields).length) return false;
  await adminPost(`/api/accounts/${pid}/save`, { fields }, "Required to save credentials.");
  cardEl.querySelectorAll("[data-form] input").forEach((i) => { i.value = ""; });
  return true;
}

grid.addEventListener("click", async (event) => {
  const copy = event.target.closest("[data-copy]");
  if (copy) {
    try { await navigator.clipboard.writeText(copy.getAttribute("data-copy")); toast("Redirect URI copied"); } catch (e) { /* ignore */ }
    return;
  }
  const btn = event.target.closest("[data-act]");
  if (!btn) return;
  const cardEl = btn.closest("[data-platform]");
  const pid = cardEl.getAttribute("data-platform");
  const act = btn.getAttribute("data-act");
  if (act === "unlink" && !btn.classList.contains("is-confirming")) {
    btn.classList.add("is-confirming"); btn.textContent = "Confirm unlink";
    setTimeout(() => { btn.classList.remove("is-confirming"); btn.textContent = "Unlink"; }, 4000);
    return;
  }
  btn.disabled = true;
  try {
    if (act === "save") {
      if (!(await save(cardEl, pid))) { result(cardEl, "Nothing to save: fill in at least one field."); return; }
      toast("Saved");
    } else if (act === "connect") {
      await save(cardEl, pid);
      const r = await adminPost(`/api/accounts/${pid}/oauth/start`, {}, "Required to connect an account.");
      location.assign(r.url);
      return;
    } else if (act === "test") {
      result(cardEl, "Testing…");
      const r = await adminPost(`/api/accounts/${pid}/test`, {}, "Required to test the connection.");
      toast("Connection OK: " + r.result);
    } else if (act === "unlink") {
      await adminPost(`/api/accounts/${pid}/unlink`, {}, "Required to unlink.");
      toast("Unlinked");
    }
    await load();
    if (act === "test" || act === "unlink") { setTimeout(() => location.reload(), 600); }
  } catch (e) {
    if (e.cancelled) return;
    await load();
    const again = document.getElementById("card-" + pid);
    if (again) result(again, e.message, "bad");
  } finally {
    btn.disabled = false;
  }
});

const q = new URLSearchParams(location.search);
const ERR = { state: "OAuth check failed (state missing, expired or from another browser). Click Connect again.",
  denied: "Authorization was cancelled on the platform.", nocode: "The platform returned no authorization code.",
  exchange: "Code exchange failed; see the error on the card." };
load().then(() => {
  if (q.get("linked")) toast("Linked. Run Test connection to unlock live data.");
  if (q.get("error")) toast(ERR[q.get("error")] || "Connection failed", "error", 8000);
  if (q.get("linked") || q.get("error")) history.replaceState(null, "", "/link-accounts");
});
