// Quick Chat: history lives only in this browser's localStorage; the server is stateless.
import { api, esc, toast, confirmButton, $ } from "/static/js/common.js";

const KEY = "atlas.quickchat.v1";
const STORE_MAX = 200;     // messages kept in this browser
const SEND_MAX = 20;       // messages sent with each question
const STARTERS = [
  "Where does the plan stand today?",
  "Which campaigns are over the $350 cost-per-trial ceiling?",
  "What does Search Atlas sell, and at what prices?",
  "How is Meta pacing against its budget?",
];

const log = $("#qc-log"), form = $("#qc-form"), input = $("#qc-input"), sendBtn = $("#qc-send");
let history = load();
let busy = false;

function load() {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(v) ? v.filter(m => m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string") : [];
  } catch (e) { return []; }
}
function save() {
  try { localStorage.setItem(KEY, JSON.stringify(history.slice(-STORE_MAX))); } catch (e) { /* storage off: chat still works this visit */ }
}

// Minimal, safe Markdown: escape first, then bold, inline code, bullets, paragraphs.
function render(text) {
  const lines = esc(text).split("\n");
  let html = "", list = null;
  const inline = s => s.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  for (const raw of lines) {
    const line = raw.trimEnd();
    const m = line.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)$/);
    if (m) {
      const tag = /^\s*\d+\./.test(line) ? "ol" : "ul";
      if (list !== tag) { if (list) html += `</${list}>`; html += `<${tag}>`; list = tag; }
      html += `<li>${inline(m[1])}</li>`;
      continue;
    }
    if (list) { html += `</${list}>`; list = null; }
    if (/^#{1,4}\s+/.test(line)) html += `<p class="qc-h">${inline(line.replace(/^#{1,4}\s+/, ""))}</p>`;
    else if (line.trim()) html += `<p>${inline(line)}</p>`;
  }
  if (list) html += `</${list}>`;
  return html;
}

function bubble(m) {
  const div = document.createElement("div");
  div.className = `qc-msg qc-${m.role}${m.error ? " qc-error" : ""}`;
  const who = m.role === "user" ? "You" : "Quick Chat";
  const meta = m.meta ? `<span class="muted"> · ${esc(m.meta)}</span>` : "";
  div.innerHTML = `<div class="qc-who">${who}${meta}</div><div class="qc-text">${m.role === "user" ? `<p>${esc(m.content).replace(/\n/g, "<br>")}</p>` : render(m.content)}</div>`;
  return div;
}

function empty() {
  log.innerHTML = `<div class="qc-empty"><p class="muted">Ask anything about the plan, the account state or the offerings.</p>
    <div class="qc-starters">${STARTERS.map(s => `<button type="button" class="btn btn-sm btn-ghost" data-starter="${esc(s)}">${esc(s)}</button>`).join("")}</div></div>`;
}

// The log grows with the conversation (no inner scroll region); keep the newest turn and the input in view.
function reveal() {
  const last = log.lastElementChild;
  if (last) last.scrollIntoView({ block: "nearest" });
  form.scrollIntoView({ block: "nearest" });
}

function draw() {
  if (!history.length) { empty(); return; }
  log.innerHTML = "";
  history.forEach(m => log.appendChild(bubble(m)));
}

function payload() {
  const msgs = history.filter(m => !m.error).map(m => ({ role: m.role, content: m.content })).slice(-SEND_MAX);
  while (msgs.length && msgs[0].role !== "user") msgs.shift();
  return msgs;
}

async function ask(text) {
  if (busy || !text.trim()) return;
  busy = true; sendBtn.disabled = true; input.value = ""; count();
  if (!history.length) log.innerHTML = "";
  const userMsg = { role: "user", content: text.trim(), ts: Date.now() };
  history.push(userMsg); save();
  log.appendChild(bubble(userMsg));
  const typing = document.createElement("div");
  typing.className = "qc-msg qc-assistant qc-typing";
  typing.innerHTML = `<div class="qc-who">Quick Chat</div><div class="qc-text"><span class="qc-dots"><i></i><i></i><i></i></span></div>`;
  log.appendChild(typing); reveal();
  try {
    const res = await api("/api/chat/send", { method: "POST", body: { messages: payload() } });
    typing.remove();
    const m = { role: "assistant", content: res.reply || "(no answer)", ts: Date.now(),
                meta: res.seconds ? `${Number(res.seconds).toFixed(1)} s` : "" };
    history.push(m); save();
    log.appendChild(bubble(m));
  } catch (err) {
    typing.remove();
    // Failed turn: drop the question from what gets sent next time, show the error, put the text back.
    history.pop(); save();
    const e = { role: "assistant", content: (err.data && err.data.error) || err.message || "Request failed", error: true };
    log.appendChild(bubble({ ...userMsg, meta: "not sent" }));
    log.appendChild(bubble(e));
    input.value = text; count();
    toast("Quick Chat could not answer", "error");
  } finally {
    busy = false; sendBtn.disabled = false; reveal(); input.focus({ preventScroll: true });
  }
}

function count() { $("#qc-count").textContent = `${input.value.length.toLocaleString()} / 4,000`; }

form.addEventListener("submit", e => { e.preventDefault(); ask(input.value); });
input.addEventListener("input", count);
input.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(input.value); }
});
log.addEventListener("click", e => {
  const b = e.target.closest("[data-starter]");
  if (b) ask(b.getAttribute("data-starter"));
});
confirmButton($("#qc-clear"), () => {
  history = []; save();
  try { localStorage.removeItem(KEY); } catch (e) { /* ignore */ }
  draw(); toast("Chat cleared in this browser", "success");
}, { label: "Click again to clear" });

window.addEventListener("storage", e => { if (e.key === KEY) { history = load(); draw(); } });

(async function init() {
  draw(); count();
  // Only warn when the server cannot answer; model, effort and context details stay off the page.
  try {
    const info = await api("/api/chat/");
    $("#qc-config").hidden = !!info.llm_configured;
  } catch (e) { /* the send path reports errors */ }
})();
