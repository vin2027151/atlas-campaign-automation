// Sample / Live data toggle (sidebar foot + mobile copy) and the admin passphrase
// prompt shared with link_accounts.js. The passphrase lives in sessionStorage for
// this browser tab only and is sent in the X-Admin-Key header; it is never logged.

const KEY = "atlas.adminKey";

export function storedKey() {
  try { return sessionStorage.getItem(KEY) || ""; } catch (e) { return ""; }
}
export function forgetKey() {
  try { sessionStorage.removeItem(KEY); } catch (e) { /* non-fatal */ }
}

function askPassphrase(reason) {
  return new Promise((resolve) => {
    const dlg = document.createElement("dialog");
    dlg.className = "admin-dialog";
    dlg.innerHTML = `
      <form method="dialog" class="admin-form">
        <h2 class="admin-title">Admin passphrase</h2>
        <p class="admin-why"></p>
        <input class="input" type="password" name="pw" autocomplete="current-password" required aria-label="Admin passphrase">
        <p class="admin-note">Kept for this browser session only.</p>
        <div class="admin-actions">
          <button class="btn btn-ghost" value="cancel" type="button" data-cancel>Cancel</button>
          <button class="btn btn-primary" value="ok" type="submit">Unlock</button>
        </div>
      </form>`;
    dlg.querySelector(".admin-why").textContent = reason || "Required to change linked accounts or the data mode.";
    document.body.appendChild(dlg);
    const input = dlg.querySelector("input");
    const done = (v) => { dlg.close(); dlg.remove(); resolve(v); };
    dlg.querySelector("[data-cancel]").addEventListener("click", () => done(""));
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); done(""); });
    dlg.querySelector("form").addEventListener("submit", (e) => { e.preventDefault(); done(input.value); });
    dlg.showModal();
    input.focus();
  });
}

/** POST with the admin header; asks once per session, re-asks after a 401. */
export async function adminPost(path, body, reason) {
  for (let attempt = 0; attempt < 2; attempt++) {
    let key = storedKey();
    if (!key) {
      key = await askPassphrase(attempt ? "Wrong passphrase. Try again." : reason);
      if (!key) { const e = new Error("Cancelled"); e.cancelled = true; throw e; }
    }
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-Admin-Key": key },
      body: JSON.stringify(body || {}),
    });
    let data = {};
    try { data = await res.json(); } catch (e) { /* empty */ }
    if (res.status === 401) { forgetKey(); continue; }
    if (res.ok) { try { sessionStorage.setItem(KEY, key); } catch (e) { /* non-fatal */ } }
    if (!res.ok) { const e = new Error(data.error || res.statusText); e.status = res.status; e.data = data; throw e; }
    return data;
  }
  const e = new Error("Wrong admin passphrase"); e.status = 401; throw e;
}

const LOCKED_TEXT = "Add API keys in Link Accounts to enable live data.";

function showMsg(group, text, ms) {
  const msg = group.querySelector(".mode-msg");
  if (!msg) return;
  msg.textContent = text;
  msg.hidden = false;
  clearTimeout(msg._t);
  if (ms !== 0) msg._t = setTimeout(() => { msg.hidden = true; }, ms || 4000);
}
function hideMsg(group) {
  const msg = group && group.querySelector(".mode-msg");
  if (!msg) return;
  clearTimeout(msg._t);
  msg.hidden = true;
}
function lockedLive(el) {
  return el && el.closest && el.closest('.mode-toggle [data-mode-set="live"].locked');
}

/* Desktop: the popup follows the mouse over the locked Live option. */
document.addEventListener("pointerover", (event) => {
  if (event.pointerType !== "mouse") return;
  const btn = lockedLive(event.target);
  if (btn) showMsg(btn.closest(".mode-toggle"), LOCKED_TEXT, 0);
});
document.addEventListener("pointerout", (event) => {
  if (event.pointerType !== "mouse") return;
  const btn = lockedLive(event.target);
  if (btn && !btn.contains(event.relatedTarget)) hideMsg(btn.closest(".mode-toggle"));
});
/* Keyboard focus gets the same popup. */
document.addEventListener("focusin", (event) => {
  const btn = lockedLive(event.target);
  if (btn) showMsg(btn.closest(".mode-toggle"), LOCKED_TEXT, 0);
});
document.addEventListener("focusout", (event) => {
  const btn = lockedLive(event.target);
  if (btn) hideMsg(btn.closest(".mode-toggle"));
});

document.addEventListener("click", async (event) => {
  const btn = event.target.closest && event.target.closest(".mode-toggle [data-mode-set]");
  if (!btn) return;
  const group = btn.closest(".mode-toggle");
  const want = btn.getAttribute("data-mode-set");
  if (want === group.getAttribute("data-mode")) return;
  if (want === "live" && group.getAttribute("data-live-available") !== "1") {
    /* Locked: never selects. A tap (mobile) or click shows the required action. */
    event.preventDefault();
    btn.blur();
    showMsg(group, LOCKED_TEXT);
    return;
  }
  try {
    await adminPost("/api/accounts/mode", { mode: want }, "Required to switch to " + (want === "live" ? "live" : "sample") + " data.");
    location.reload();
  } catch (e) {
    if (!e.cancelled) showMsg(group, String(e.message));
  }
});
