// Atlas Ops shared front-end helpers. ES module.
//
//   import { api, fmt, toast, confirmButton, chartDefaults, platformChip } from "/static/js/common.js";
//
// base.html also loads this file, and every export is mirrored on window.atlas
// for inline scripts. Rates (ctr, click_to_trial, trial_to_paid, pace_pct) arrive
// from the API as percentage points: fmt.pct(4.9) -> "4.9%".

const NONE = "—"; // em dash for null / missing values

// ------------------------------------------------------------------ api()
/**
 * Fetch JSON from the dashboard API.
 * api("/api/campaigns/") -> GET; api(path, {method: "POST", body: {...}}) -> JSON POST.
 * A body without a method implies POST. Throws Error(message) on non-2xx, using the
 * server's `error` (store.NotFound/BadInput) or FastAPI `detail`; err.status and
 * err.data are attached.
 */
export async function api(path, { method, body, headers } = {}) {
  const opts = { method: method || (body !== undefined ? "POST" : "GET"), headers: { Accept: "application/json", ...(headers || {}) } };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = typeof body === "string" ? body : JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    const err = new Error("Network error: could not reach the dashboard server");
    err.status = 0;
    throw err;
  }
  const text = await res.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch (e) { data = { error: text.slice(0, 300) }; }
  }
  if (!res.ok) {
    let msg = (data && (data.error || data.detail)) || res.statusText || "Request failed";
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg || JSON.stringify(d)).join("; ");
    if (typeof msg !== "string") msg = JSON.stringify(msg);
    const err = new Error(msg);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

// -------------------------------------------------------------------- fmt
const nf0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const bad = (v) => v === null || v === undefined || v === "" || (typeof v === "number" && !isFinite(v));

/** Parse "YYYY-MM-DD" as a local date (no UTC shift). */
export function parseDate(s) {
  if (s instanceof Date) return s;
  const [y, m, d] = String(s).slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
}

/** Format a Date as "YYYY-MM-DD". */
export function isoDate(d) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export const fmt = {
  /** $1,234 (cents with {cents: true}: $1,234.56). Null -> em dash. */
  money(v, { cents = false } = {}) {
    if (bad(v)) return NONE;
    const n = Number(v);
    const s = cents ? nf2.format(Math.abs(n)) : nf0.format(Math.abs(n));
    return (n < 0 ? "-$" : "$") + s;
  },
  /** Compact money for axes: $1.2K, $120K. */
  moneyShort(v) {
    if (bad(v)) return NONE;
    const n = Number(v), a = Math.abs(n);
    const s = a >= 1e6 ? (a / 1e6).toFixed(1) + "M" : a >= 1e3 ? (a / 1e3).toFixed(a >= 1e4 ? 0 : 1) + "K" : nf0.format(a);
    return (n < 0 ? "-$" : "$") + s;
  },
  /** 12,345 */
  int(v) { return bad(v) ? NONE : nf0.format(Math.round(Number(v))); },
  /** Percentage points: pct(4.93) -> "4.9%"; pct(4.93, 2) -> "4.93%". */
  pct(v, digits = 1) { return bad(v) ? NONE : Number(v).toFixed(digits) + "%"; },
  /** Signed delta in points: "+2.1%" / "-0.4%". */
  delta(v, digits = 1) { return bad(v) ? NONE : (v > 0 ? "+" : "") + Number(v).toFixed(digits) + "%"; },
  /** Cost per trial/paid: $287, em dash when null (zero trials). */
  cpt(v) { return bad(v) ? NONE : "$" + nf0.format(Math.round(Number(v))); },
  /** "2026-11-05" -> "Nov 5"; {year:true} -> "Nov 5, 2026"; {dow:true} -> "Thu Nov 5". */
  date(v, { year = false, dow = false } = {}) {
    if (bad(v)) return NONE;
    const d = parseDate(v);
    if (isNaN(d)) return String(v);
    let s = `${MONTHS[d.getMonth()]} ${d.getDate()}`;
    if (year) s += `, ${d.getFullYear()}`;
    if (dow) s = `${DOW[d.getDay()]} ${s}`;
    return s;
  },
  /** ISO timestamp -> "Nov 5, 14:02" (local time). */
  datetime(v) {
    if (bad(v)) return NONE;
    const d = new Date(v);
    if (isNaN(d)) return String(v);
    const p = (n) => String(n).padStart(2, "0");
    return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${p(d.getHours())}:${p(d.getMinutes())}`;
  },
  none: NONE,
};

// ------------------------------------------------------------------ DOM bits
/** Escape text for safe interpolation into innerHTML. */
export function esc(v) {
  return String(v === null || v === undefined ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/** Shorthand querySelector / querySelectorAll (array). */
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/** HTML for the platform chip: "G" for google, "M" for meta. */
export function platformChip(platform) {
  const p = String(platform || "").toLowerCase();
  if (p === "google") return '<span class="chip chip-google" title="Google Ads">G</span>';
  if (p === "meta") return '<span class="chip chip-meta" title="Meta">M</span>';
  return "";
}

const BADGE_LABELS = {
  pending_feedback: "Pending feedback",
  final_pending_approval: "Final, pending approval",
};
/** HTML for a status badge: badge("ACTIVE") -> <span class="badge active">Active</span>. */
export function badge(status, label) {
  const s = String(status || "").toLowerCase();
  const text = label || BADGE_LABELS[s] || (s.charAt(0).toUpperCase() + s.slice(1)).replace(/_/g, " ");
  return `<span class="badge ${esc(s)}">${esc(text)}</span>`;
}

/** Tone class for a cost per trial against the CPA target band [low, high]. */
export function cptTone(v, target = [250, 280]) {
  if (bad(v)) return "tone-idle";
  if (v <= target[1]) return "tone-good";
  if (v <= target[1] * 1.15) return "tone-watch";
  return "tone-bad";
}

// ------------------------------------------------------------------- toast
/** Show a toast. kind: "success" (default) | "error" | "warn" | "info". */
export function toast(msg, kind = "success", ms) {
  let stack = document.getElementById("toast-stack");
  if (!stack) {
    stack = document.createElement("div");
    stack.id = "toast-stack";
    stack.className = "toast-stack";
    stack.setAttribute("aria-live", "polite");
    document.body.appendChild(stack);
  }
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.setAttribute("role", kind === "error" ? "alert" : "status");
  el.textContent = msg;
  stack.appendChild(el);
  const life = ms || (kind === "error" ? 6000 : 3200);
  const close = () => { el.classList.add("leaving"); setTimeout(() => el.remove(), 220); };
  el.addEventListener("click", close);
  setTimeout(close, life);
  return el;
}

// ------------------------------------------------------------ confirmButton
/**
 * Two-click inline confirm (no window.confirm). First click arms the button
 * (red, label becomes "Confirm <label>?" or data-confirm-label) for 4 s; the
 * second click runs onConfirm(el). While onConfirm's promise is pending the
 * button is disabled. Errors thrown by onConfirm are toasted. Returns a
 * function that detaches the handler.
 */
export function confirmButton(el, onConfirm, { label, timeout = 4000 } = {}) {
  if (!el) return () => {};
  let armed = false, timer = null, original = "", confirmText = "";
  const disarm = () => {
    armed = false;
    clearTimeout(timer);
    el.classList.remove("is-confirming");
    // Restore the label only if onConfirm did not already relabel the button.
    if (el.textContent === confirmText) el.innerHTML = original;
  };
  const handler = async (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    if (el.disabled) return;
    if (!armed) {
      armed = true;
      original = el.innerHTML;
      confirmText = label || el.dataset.confirmLabel || `Confirm ${el.textContent.trim().toLowerCase()}?`;
      el.classList.add("is-confirming");
      el.textContent = confirmText;
      timer = setTimeout(disarm, timeout);
      return;
    }
    clearTimeout(timer);
    el.disabled = true;
    el.classList.add("is-busy");
    try {
      await onConfirm(el);
    } catch (e) {
      toast(e.message || String(e), "error");
    } finally {
      el.disabled = false;
      el.classList.remove("is-busy");
      disarm();
    }
  };
  const blur = () => { if (armed) setTimeout(() => { if (armed && document.activeElement !== el) disarm(); }, 150); };
  el.addEventListener("click", handler);
  el.addEventListener("blur", blur);
  return () => { el.removeEventListener("click", handler); el.removeEventListener("blur", blur); };
}

/**
 * Run an async action with a busy button and a toast:
 * withBusy(btn, () => api(...), "Saved").
 */
export async function withBusy(el, fn, successMsg) {
  if (el) { el.disabled = true; el.classList.add("is-busy"); }
  try {
    const out = await fn();
    if (successMsg) toast(successMsg, "success");
    return out;
  } catch (e) {
    toast(e.message || String(e), "error");
    throw e;
  } finally {
    if (el) { el.disabled = false; el.classList.remove("is-busy"); }
  }
}

// -------------------------------------------------------------------- modal
/**
 * Open a modal. body is an HTML string or a Node. actions: [{label, kind:"primary"|"ghost"|"danger",
 * onClick(close, modalEl) -> any; return false to keep it open}]. Returns {el, close}.
 * Esc and backdrop click close it.
 */
export function modal({ title = "", body = "", actions = [], wide = false } = {}) {
  const back = document.createElement("div");
  back.className = "modal-backdrop";
  back.innerHTML = `<div class="modal${wide ? " wide" : ""}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="modal-head"><div class="modal-title">${esc(title)}</div>
        <button class="btn btn-ghost btn-sm btn-icon" data-close aria-label="Close">&times;</button></div>
      <div class="modal-body"></div>
      <div class="modal-foot"></div></div>`;
  const m = back.querySelector(".modal");
  const bodyEl = m.querySelector(".modal-body");
  if (typeof body === "string") bodyEl.innerHTML = body; else if (body) bodyEl.appendChild(body);
  const foot = m.querySelector(".modal-foot");
  const onKey = (e) => { if (e.key === "Escape") close(); };
  function close() { document.removeEventListener("keydown", onKey); back.remove(); }
  if (!actions.length) foot.remove();
  actions.forEach((a) => {
    const b = document.createElement("button");
    b.className = "btn" + (a.kind ? " btn-" + a.kind : "");
    b.textContent = a.label;
    b.addEventListener("click", async () => {
      if (!a.onClick) return close();
      try {
        b.disabled = true;
        const r = await a.onClick(close, m);
        if (r !== false) close();
      } catch (e) {
        toast(e.message || String(e), "error");
      } finally { b.disabled = false; }
    });
    foot.appendChild(b);
  });
  back.addEventListener("click", (e) => { if (e.target === back || e.target.closest("[data-close]")) close(); });
  document.addEventListener("keydown", onKey);
  document.body.appendChild(back);
  const first = m.querySelector("input, select, textarea, .modal-foot .btn-primary");
  if (first) first.focus();
  return { el: m, close };
}

// --------------------------------------------------------------------- tabs
/**
 * Wire a .tabs bar: buttons with data-tab="x" show the element with
 * data-panel="x" inside root and hide the others. onChange(name) is called.
 * Returns {select(name)}.
 */
export function tabs(root, onChange) {
  const btns = $$(".tab[data-tab]", root);
  const panels = $$("[data-panel]", root);
  function select(name) {
    btns.forEach((b) => { const on = b.dataset.tab === name; b.classList.toggle("active", on); b.setAttribute("aria-selected", on); });
    panels.forEach((p) => { p.hidden = p.dataset.panel !== name; });
    if (onChange) onChange(name);
  }
  btns.forEach((b) => { b.setAttribute("role", "tab"); b.addEventListener("click", () => select(b.dataset.tab)); });
  const initial = btns.find((b) => b.classList.contains("active")) || btns[0];
  if (initial) select(initial.dataset.tab);
  return { select };
}

// ------------------------------------------------------------------- charts
/** Read a CSS custom property from :root. */
export function token(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Series colors from the design tokens, in order. */
export function seriesColors() {
  return [1, 2, 3, 4, 5, 6].map((i) => token("--series-" + i));
}

/** Platform colors: {google, meta}. */
export function platformColors() {
  return { google: token("--google"), meta: token("--meta") };
}

/**
 * Apply design tokens to Chart.js global defaults (font, colors, grid, tooltip,
 * legend). Safe to call repeatedly; returns the tokens it used. Called
 * automatically when this module loads if Chart.js is present.
 */
export function chartDefaults() {
  const Chart = window.Chart;
  const t = {
    ink: token("--ink"), ink2: token("--ink-2"), muted: token("--muted"), line: token("--line"),
    surface: token("--surface"), font: token("--font"), series: seriesColors(),
  };
  if (!Chart) return t;
  const d = Chart.defaults;
  d.font.family = t.font;
  d.font.size = 11;
  d.color = t.muted;
  d.borderColor = t.line;
  d.maintainAspectRatio = false;
  d.responsive = true;
  d.animation = { duration: 250 };
  d.interaction = { mode: "index", intersect: false };
  d.plugins.legend.position = "bottom";
  d.plugins.legend.align = "start";
  d.plugins.legend.labels.boxWidth = 10;
  d.plugins.legend.labels.boxHeight = 10;
  d.plugins.legend.labels.color = t.ink2;
  d.plugins.tooltip.backgroundColor = t.ink;
  d.plugins.tooltip.titleColor = t.surface;
  d.plugins.tooltip.bodyColor = t.surface;
  d.plugins.tooltip.padding = 8;
  d.plugins.tooltip.cornerRadius = 4;
  d.plugins.tooltip.boxPadding = 4;
  d.elements.line.borderWidth = 2;
  d.elements.line.tension = 0.25;
  d.elements.point.radius = 0;
  d.elements.point.hoverRadius = 4;
  d.elements.bar.borderRadius = 2;
  d.scale.grid.color = t.line;
  d.scale.border = Object.assign({}, d.scale.border, { color: t.line });
  d.scale.ticks.color = t.muted;
  return t;
}

/** Axis tick formatter helpers for Chart.js: ticks: { callback: tick.money }. */
export const tick = {
  money: (v) => fmt.moneyShort(v),
  pct: (v) => fmt.pct(v, 0),
  int: (v) => fmt.int(v),
};

// ------------------------------------------------------------------- boot
chartDefaults();
if (window.matchMedia) {
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  const re = () => {
    chartDefaults();
    if (window.Chart) Object.values(window.Chart.instances || {}).forEach((c) => c.update("none"));
  };
  if (mq.addEventListener) mq.addEventListener("change", re);
}

window.atlas = {
  api, fmt, toast, confirmButton, withBusy, modal, tabs, chartDefaults, platformChip, badge,
  cptTone, esc, $, $$, token, seriesColors, platformColors, tick, parseDate, isoDate,
};
