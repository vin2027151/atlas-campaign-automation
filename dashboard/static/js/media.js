// Media page: Requests / Ready for review / Approved board for numbered image, video and HTML5 assets.
import { api, fmt, toast, platformChip, esc, $, $$, withBusy, isoDate, parseDate } from "/static/js/common.js";

const API = "/api/media";
const COLUMNS = [
  { status: "requested", label: "Requests", empty: "No open requests. Use + New request to brief one." },
  { status: "in_review", label: "Ready for review", empty: "Nothing waiting for review." },
  { status: "approved", label: "Approved", empty: "Nothing approved yet." },
];
const KIND_LABEL = { image: "Image", video: "Video", html5: "HTML5" };
const ACCEPT = {
  image: "image/png,image/jpeg,image/webp,image/gif,.png,.jpg,.jpeg,.webp,.gif",
  video: "video/mp4,video/quicktime,.mp4,.mov,.m4v",
  html5: "text/html,application/zip,.html,.htm,.zip",
};
const FORMAT_LABEL = {
  "image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP", "image/gif": "GIF", "video/mp4": "MP4",
  "video/quicktime": "MOV", "video/webm": "WebM", "text/html": "HTML5", "application/zip": "HTML5 zip",
};

let data = null;
let kindFilter = "";
let freshId = null;
let targetId = (location.hash || "").replace(/^#/, "") || null;
const ui = { sendBack: {}, editing: {}, uploading: {}, expanded: {} };
let query = ""; // per-card drafts survive re-render
const today = document.body.dataset.today;

// ------------------------------------------------------------------ load
async function load() {
  try {
    data = await api(API + "/");
  } catch (e) {
    $("#board").innerHTML = `<div class="empty">Could not load the media library: ${esc(e.message)}</div>`;
    toast("Could not load media: " + e.message, "error");
    return;
  }
  render();
}

function campaignName(id) {
  const c = (data.campaigns || []).find((x) => x.id === id);
  return c ? c.name : id;
}

function humanSize(n) {
  if (n === null || n === undefined) return null;
  if (n >= 1048576) return (n / 1048576).toFixed(1) + " MB";
  if (n >= 1024) return Math.round(n / 1024) + " KB";
  return n + " B";
}

function specLine(a) {
  const parts = [];
  if (a.format) parts.push(FORMAT_LABEL[a.format] || a.format);
  if (a.width && a.height) parts.push(`${a.width}×${a.height}`);
  if (a.aspect && a.aspect !== `${a.width}x${a.height}`) parts.push(a.aspect);
  if (a.duration_s) parts.push(`${Math.round(a.duration_s * 10) / 10} s`);
  const size = humanSize(a.size_bytes);
  if (size) parts.push(size);
  return parts.join(" · ");
}

// ---------------------------------------------------------------- render
function render() {
  const all = data.assets;
  const q = query.trim().toLowerCase();
  const shown = all.filter((a) => (!kindFilter || a.kind === kindFilter) && (!q || haystack(a).includes(q)));
  $$("#kind-tabs [data-count]").forEach((el) => {
    const k = el.dataset.count;
    el.textContent = k ? all.filter((a) => a.kind === k).length : all.length;
  });
  const by = (s) => all.filter((a) => a.status === s).length;
  $("#md-summary").innerHTML = `<b>${by("requested")}</b> requested · <b>${by("in_review")}</b> waiting for review · <b>${by("approved")}</b> approved`;

  $("#board").innerHTML = COLUMNS.map((col) => {
    const items = shown.filter((a) => a.status === col.status);
    return `<section class="md-col" data-status="${col.status}" aria-labelledby="col-${col.status}">
      <div class="md-col-head"><h2 class="md-col-title" id="col-${col.status}">${esc(col.label)}</h2>
        <span class="md-col-count" aria-label="${items.length} items">${items.length}</span></div>
      <div class="md-col-body">${items.length ? items.map((a) => (a.status === "approved" && !ui.expanded[a.id] && !ui.editing[a.id] ? compactHtml(a) : cardHtml(a))).join("") : `<div class="md-col-empty">${esc(q || kindFilter ? "No matches here." : col.empty)}</div>`}</div>
    </section>`;
  }).join("");
  fitFrames();
  if (targetId) {
    const card = document.getElementById("asset-" + targetId);
    if (card) {
      card.classList.add("is-target");
      card.scrollIntoView({ block: "center" });
    }
    targetId = null;
  }
}

function haystack(a) {
  return [a.id, a.title, a.description, a.primary_text, a.headline, a.cta, a.meta_library_id, (a.placements || []).join(" "),
    (a.tags || []).map(campaignName).join(" ")].filter(Boolean).join(" ").toLowerCase();
}

function thumbOf(a) {
  if (a.cards && a.cards.length) return a.cards[0];
  return a.thumb_url || (a.kind === "image" ? a.file_url : null);
}

// Approved column: one-line cards so 16+ stay scannable; Expand shows the full card.
function compactHtml(a) {
  const id = esc(a.id);
  const thumb = thumbOf(a);
  const n = a.cards ? a.cards.length : 0;
  const visual = thumb ? `<img src="${esc(thumb)}" alt="" loading="lazy">`
    : `<span class="mthumb-label">${a.kind === "html5" ? esc(a.aspect || "HTML5") : esc(KIND_LABEL[a.kind])}</span>`;
  return `<article class="mcard mcard-compact${a.id === freshId ? " is-new" : ""}" id="asset-${id}" data-id="${id}" aria-labelledby="title-${id}">
    <button class="mthumb" type="button" data-expand aria-expanded="false" aria-label="Expand ${id}">${visual}
      ${a.kind === "video" ? `<span class="mthumb-play" aria-hidden="true">&#9654;</span>` : ""}${n ? `<span class="mthumb-count" aria-hidden="true">${n}</span>` : ""}</button>
    <div class="mcompact-info">
      <div class="mcard-top">
        <button class="idchip" type="button" data-copy="${id}" aria-label="Copy ID ${id}" title="Copy ID">${id}</button>
        <span class="tag kind-tag">${n ? "Carousel" : esc(KIND_LABEL[a.kind])}</span>
        ${Object.keys(a.platform_refs || {}).length ? `<span class="badge good">Published</span>` : ""}
      </div>
      <h3 class="mcard-title clamp-2" id="title-${id}">${esc(a.title)}</h3>
      <div class="mcard-spec">${esc(specLine(a))}${a.tags && a.tags.length ? ` · ${a.tags.length} campaign${a.tags.length === 1 ? "" : "s"}` : ""}</div>
      <div class="mcompact-actions">
        <a class="btn btn-sm btn-primary" href="/planning?media=${encodeURIComponent(a.id)}">Use in Campaign Planning</a>
        <button class="btn btn-sm" type="button" data-edit>Edit</button>
        <button class="btn btn-sm btn-ghost" type="button" data-expand aria-expanded="false">Details</button>
      </div>
    </div>
  </article>`;
}

function carouselHtml(a) {
  const n = a.cards.length;
  return `<div class="mprev mprev-carousel">
    <span class="mprev-kind"><span class="pill">Carousel · ${n} cards</span></span>
    <div class="mstrip" data-strip tabindex="0" role="group" aria-label="${esc(a.id)} carousel, ${n} cards; use arrow keys to scroll">
      ${a.cards.map((src, i) => `<img src="${esc(src)}" alt="${esc(a.title)}, card ${i + 1} of ${n}" loading="lazy"${a.width ? ` width="${a.width}" height="${a.height}"` : ""}>`).join("")}
    </div>
    <button class="btn btn-sm btn-icon mstrip-nav prev" type="button" data-strip-nav="-1" aria-label="Previous card">&larr;</button>
    <button class="btn btn-sm btn-icon mstrip-nav next" type="button" data-strip-nav="1" aria-label="Next card">&rarr;</button>
  </div>`;
}

function adCopyHtml(a) {
  if (!a.primary_text && !a.headline && !a.meta_library_id) return "";
  const rows = [];
  if (a.headline) rows.push(`<dt>Headline</dt><dd>${esc(a.headline)}</dd>`);
  if (a.cta) rows.push(`<dt>CTA</dt><dd>${esc(a.cta)}</dd>`);
  if (a.started_running) rows.push(`<dt>Running since</dt><dd>${esc(a.started_running)}</dd>`);
  if (a.meta_library_id) rows.push(`<dt>Ad Library ID</dt><dd>${a.source_url ? `<a href="${esc(a.source_url)}" target="_blank" rel="noopener noreferrer">${esc(a.meta_library_id)}</a>` : esc(a.meta_library_id)}</dd>`);
  return `<details class="mcard-copy"><summary>Ad copy</summary>
    ${rows.length ? `<dl class="dl mcard-dl">${rows.join("")}</dl>` : ""}
    ${a.primary_text ? `<p class="mcard-primary">${esc(a.primary_text)}</p>` : ""}
  </details>`;
}

function previewHtml(a) {
  const kindPill = `<span class="mprev-kind"><span class="pill">${esc(KIND_LABEL[a.kind])}</span></span>`;
  if (!a.file_url) {
    const ratio = a.kind === "video" ? "9 / 16" : a.kind === "html5" ? "6 / 5" : "1 / 1";
    return `<div class="mprev-request">
      <span class="frame" style="aspect-ratio:${ratio}" aria-hidden="true">${esc(KIND_LABEL[a.kind])}</span>
      <span class="lbl">No file yet</span>
      <span class="sub">${a.due ? (a.due < today ? `<span class="mcard-due overdue">Overdue · ${esc(fmt.date(a.due, { dow: true }))}</span>` : `Due ${esc(fmt.date(a.due, { dow: true }))}`) : "No due date"} · requested by ${esc(a.requested_by || "vin")}</span>
    </div>`;
  }
  if (a.missing_file) return `<div class="mprev">${kindPill}<div class="mprev-missing">File missing on disk: ${esc(a.file_url)}</div></div>`;
  if (a.kind === "image" && a.cards && a.cards.length > 1) return carouselHtml(a);
  if (a.kind === "image") {
    return `<div class="mprev">${kindPill}<img src="${esc(a.thumb_url || a.file_url)}" alt="${esc(a.title)}" loading="lazy"${a.width ? ` width="${a.width}" height="${a.height}"` : ""}></div>`;
  }
  if (a.kind === "video") {
    const type = a.format ? ` type="${esc(a.format)}"` : "";
    return `<div class="mprev">${kindPill}<video controls muted playsinline preload="metadata"${a.thumb_url ? ` poster="${esc(a.thumb_url)}"` : ""} aria-label="${esc(a.title)}"><source src="${esc(a.file_url)}"${type}>Video preview not supported in this browser.</video></div>`;
  }
  const w = a.width || 300, h = a.height || 250;
  return `<div class="mprev mprev-h5">${kindPill}
    <button class="btn btn-sm h5-replay" type="button" data-replay aria-label="Replay ${esc(a.id)} animation">Replay</button>
    <div class="h5-stage" data-w="${w}" data-h="${h}" style="width:${w}px;height:${h}px">
      <iframe src="${esc(a.file_url)}" width="${w}" height="${h}" sandbox="allow-scripts allow-popups" loading="lazy" title="${esc(a.id)} HTML5 preview, ${w}x${h}" scrolling="no"></iframe>
    </div></div>`;
}

function historyHtml(a) {
  const rows = (a.history || []).slice().reverse();
  if (!rows.length) return "";
  return `<details><summary>History (${rows.length})</summary><ul class="mcard-history">${rows.map((h) => `
    <li><time datetime="${esc(h.ts)}">${esc(fmt.datetime(h.ts))}</time><span><span class="act">${esc(h.action)}</span>${h.note ? ` · ${esc(h.note)}` : ""}</span></li>`).join("")}</ul></details>`;
}

function chipsHtml(a) {
  const plats = (a.platforms || []).map((p) => platformChip(p)).join("");
  const places = (a.placements || []).map((p) => `<span class="tag">${esc(p)}</span>`).join("");
  const tags = (a.tags || []).map((t) => `<span class="tag campaign" title="${esc(t)}">${esc(campaignName(t))}</span>`).join("");
  const out = [];
  if (plats || places) out.push(`<div class="mcard-chips">${plats}${places}</div>`);
  if (tags) out.push(`<div class="mcard-chips"><span class="mcard-label">Campaigns</span>${tags}</div>`);
  return out.join("");
}

function actionsHtml(a) {
  const id = esc(a.id);
  if (a.status === "requested") {
    if (ui.uploading[a.id]) {
      return `<div class="mcard-inline"><div class="upload-busy"><span>Uploading ${esc(ui.uploading[a.id])}</span><span class="meter"><span></span></span></div></div>`;
    }
    return `<div class="mcard-actions">
      <button class="btn btn-sm btn-primary" type="button" data-upload aria-describedby="title-${id}">Upload file</button>
      <input type="file" hidden data-file accept="${ACCEPT[a.kind]}" aria-label="Choose a file for ${id}">
      <span class="spacer"></span><span class="muted small">${esc(KIND_LABEL[a.kind])}, max 50 MB</span>
    </div>`;
  }
  if (a.status === "in_review") {
    if (ui.sendBack[a.id] !== undefined) {
      return `<div class="mcard-inline">
        <label class="label" for="sb-${id}">What needs to change? <span class="muted">(required)</span></label>
        <textarea class="textarea" id="sb-${id}" data-sendback-note maxlength="1000" placeholder="e.g. Hook is too slow; open on the report, not the logo">${esc(ui.sendBack[a.id])}</textarea>
        <div class="row"><button class="btn btn-sm btn-ghost" type="button" data-sendback-cancel>Cancel</button>
          <button class="btn btn-sm btn-danger" type="button" data-sendback-submit>Send back to requests</button></div>
      </div>`;
    }
    return `<div class="mcard-actions">
      <button class="btn btn-sm btn-primary" type="button" data-approve>Approve</button>
      <button class="btn btn-sm" type="button" data-sendback>Send back</button>
      <span class="spacer"></span>
      ${a.file_url ? `<a class="btn btn-sm btn-ghost" href="${esc(a.package_url || a.file_url)}" download>Download</a>` : ""}
    </div>`;
  }
  // approved
  if (ui.editing[a.id]) {
    const d = ui.editing[a.id];
    const picks = (data.campaigns || []).map((c) => `<label class="check"><input type="checkbox" data-edit-tag value="${esc(c.id)}"${d.tags.includes(c.id) ? " checked" : ""}>${platformChip(c.platform)}<span>${esc(c.name)}</span></label>`).join("");
    return `<div class="mcard-inline">
      <label class="label" for="et-${id}">Title</label>
      <input class="input" id="et-${id}" data-edit-title maxlength="140" value="${esc(d.title)}">
      <label class="label" for="ed-${id}">Description</label>
      <textarea class="textarea" id="ed-${id}" data-edit-desc maxlength="1000">${esc(d.description)}</textarea>
      <fieldset class="md-fieldset"><legend class="label">Campaign tags</legend><div class="mcard-tagpick">${picks}</div></fieldset>
      <div class="row"><button class="btn btn-sm btn-ghost" type="button" data-edit-cancel>Cancel</button>
        <button class="btn btn-sm btn-primary" type="button" data-edit-save>Save</button></div>
    </div>`;
  }
  return `<div class="mcard-actions">
    <a class="btn btn-sm btn-primary" href="/planning?media=${encodeURIComponent(a.id)}">Use in Campaign Planning</a>
    <button class="btn btn-sm" type="button" data-edit>Edit</button>
    <span class="spacer"></span>
    ${a.file_url ? `<a class="btn btn-sm btn-ghost" href="${esc(a.package_url || a.file_url)}" download aria-label="Download ${id}">Download</a>` : ""}
    <button class="btn btn-sm btn-ghost" type="button" data-collapse aria-expanded="true">Collapse</button>
  </div>`;
}

function cardHtml(a) {
  const id = esc(a.id);
  const overdue = a.status === "requested" && a.due && a.due < today;
  const refs = Object.keys(a.platform_refs || {});
  return `<article class="mcard${a.id === freshId ? " is-new" : ""}" id="asset-${id}" data-id="${id}" aria-labelledby="title-${id}">
    ${previewHtml(a)}
    <div class="mcard-body">
      <div class="mcard-top">
        <button class="idchip" type="button" data-copy="${id}" aria-label="Copy ID ${id}" title="Copy ID">${id}</button>
        <span class="tag kind-tag">${esc(KIND_LABEL[a.kind])}</span>
        ${refs.length ? `<span class="badge good" title="Uploaded to ${esc(refs.join(", "))}">Published</span>` : ""}
        <span class="spacer"></span>
        ${a.due && a.status === "in_review" ? `<span class="mcard-due${overdue ? " overdue" : ""}">${overdue ? "Overdue · " : "Due "}${esc(fmt.date(a.due))}</span>` : ""}
      </div>
      <h3 class="mcard-title" id="title-${id}">${esc(a.title)}</h3>
      ${a.description ? `<p class="mcard-desc">${esc(a.description)}</p>` : ""}
      ${a.file_url ? `<div class="mcard-spec">${esc(specLine(a))}</div>` : ""}
      ${chipsHtml(a)}
      ${a.status === "requested" && a.review_note ? `<div class="mcard-note"><b>Sent back:</b> ${esc(a.review_note)}</div>` : ""}
      ${a.brief ? `<details${a.status === "requested" ? " open" : ""}><summary>Brief</summary><p>${esc(a.brief)}</p></details>` : ""}
      ${adCopyHtml(a)}
      ${a.source_url && !a.meta_library_id ? `<div class="mcard-spec">Source: <a href="${esc(a.source_url)}" target="_blank" rel="noopener noreferrer">${esc(a.source || a.source_url)}</a></div>` : ""}
      ${historyHtml(a)}
      ${actionsHtml(a)}
    </div>
  </article>`;
}

// HTML5 previews render at native size, scaled down to the card width.
function fitFrames() {
  $$(".h5-stage").forEach((stage) => {
    const w = Number(stage.dataset.w), h = Number(stage.dataset.h);
    const avail = stage.parentElement.clientWidth - 24;
    const scale = Math.min(1, avail > 0 ? avail / w : 1);
    stage.style.width = Math.round(w * scale) + "px";
    stage.style.height = Math.round(h * scale) + "px";
    const frame = stage.querySelector("iframe");
    if (frame) frame.style.transform = scale < 1 ? `scale(${scale})` : "";
  });
}
let resizeTimer = null;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(fitFrames, 80); });

// --------------------------------------------------------------- actions
function asset(id) { return data.assets.find((a) => a.id === id); }

async function refreshAfter(id) {
  freshId = id;
  await load();
}

async function copyId(id) {
  let ok = false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(id);
      ok = true;
    }
  } catch (e) { ok = false; }
  if (!ok) {
    const ta = document.createElement("textarea");
    ta.value = id;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    ta.remove();
  }
  toast(ok ? `${id} copied` : `Could not copy; the ID is ${id}`, ok ? "success" : "warn");
}

async function uploadFile(id, file) {
  const a = asset(id);
  if (!file || !a) return;
  if (file.size > data.max_upload_bytes) {
    toast(`${file.name} is ${humanSize(file.size)}; the limit is 50 MB`, "error");
    return;
  }
  ui.uploading[id] = file.name;
  render();
  const form = new FormData();
  form.append("file", file, file.name);
  try {
    const res = await fetch(`${API}/${encodeURIComponent(id)}/upload`, { method: "POST", body: form, headers: { Accept: "application/json" } });
    let body = null;
    try { body = await res.json(); } catch (e) { body = null; }
    if (!res.ok) throw new Error((body && (body.error || body.detail)) || res.statusText || "Upload failed");
    delete ui.uploading[id];
    toast(`${id} uploaded, ready for review`);
    await refreshAfter(id);
    const card = document.getElementById("asset-" + id);
    if (card) card.querySelector("[data-approve]")?.focus({ preventScroll: false });
  } catch (e) {
    delete ui.uploading[id];
    toast(`Upload failed: ${e.message}`, "error");
    render();
  }
}

function focusIn(id, sel) {
  const card = document.getElementById("asset-" + id);
  const el = card && card.querySelector(sel);
  if (el) el.focus();
  return el;
}

function wireBoard() {
  const board = $("#board");
  board.addEventListener("click", async (e) => {
    const copy = e.target.closest("[data-copy]");
    if (copy) return copyId(copy.dataset.copy);
    const card = e.target.closest(".mcard");
    if (!card) return;
    const id = card.dataset.id;
    const a = asset(id);

    if (e.target.closest("[data-replay]")) {
      const frame = card.querySelector("iframe");
      if (frame) frame.src = frame.src;
      return;
    }
    if (e.target.closest("[data-upload]")) return card.querySelector("[data-file]").click();
    if (e.target.closest("[data-expand]")) {
      ui.expanded[id] = true;
      render();
      return focusIn(id, "[data-collapse]");
    }
    if (e.target.closest("[data-collapse]")) {
      delete ui.expanded[id];
      render();
      return focusIn(id, "button[data-expand].btn");
    }
    const nav = e.target.closest("[data-strip-nav]");
    if (nav) {
      const strip = card.querySelector("[data-strip]");
      strip.scrollBy({ left: Number(nav.dataset.stripNav) * strip.clientWidth, behavior: "smooth" });
      return;
    }

    const approveBtn = e.target.closest("[data-approve]");
    if (approveBtn) {
      try {
        await withBusy(approveBtn, () => api(`${API}/${encodeURIComponent(id)}/approve`, { body: {} }), `${id} approved`);
        await refreshAfter(id);
      } catch (err) { /* toasted */ }
      return;
    }
    if (e.target.closest("[data-sendback]")) {
      ui.sendBack[id] = "";
      render();
      return focusIn(id, "[data-sendback-note]");
    }
    if (e.target.closest("[data-sendback-cancel]")) {
      delete ui.sendBack[id];
      render();
      return focusIn(id, "[data-sendback]");
    }
    const sbSubmit = e.target.closest("[data-sendback-submit]");
    if (sbSubmit) {
      const ta = card.querySelector("[data-sendback-note]");
      const note = ta.value.trim();
      if (!note) {
        ta.setAttribute("aria-invalid", "true");
        ta.focus();
        toast("Add a note so the creator knows what to change", "warn");
        return;
      }
      try {
        await withBusy(sbSubmit, () => api(`${API}/${encodeURIComponent(id)}/reject`, { body: { note } }), `${id} sent back to requests`);
        delete ui.sendBack[id];
        await refreshAfter(id);
      } catch (err) { /* toasted */ }
      return;
    }
    if (e.target.closest("[data-edit]")) {
      ui.editing[id] = { title: a.title, description: a.description || "", tags: (a.tags || []).slice() };
      render();
      return focusIn(id, "[data-edit-title]");
    }
    if (e.target.closest("[data-edit-cancel]")) {
      delete ui.editing[id];
      delete ui.expanded[id];
      render();
      return focusIn(id, "[data-edit]");
    }
    const save = e.target.closest("[data-edit-save]");
    if (save) {
      const d = ui.editing[id];
      if (!d.title.trim()) {
        const t = card.querySelector("[data-edit-title]");
        t.setAttribute("aria-invalid", "true");
        t.focus();
        toast("Title is required", "warn");
        return;
      }
      try {
        await withBusy(save, () => api(`${API}/${encodeURIComponent(id)}`, { body: { title: d.title, description: d.description, tags: d.tags } }), `${id} saved`);
        delete ui.editing[id];
        delete ui.expanded[id];
        await refreshAfter(id);
        focusIn(id, "[data-edit]");
      } catch (err) { /* toasted */ }
    }
  });

  board.addEventListener("input", (e) => {
    const card = e.target.closest(".mcard");
    if (!card) return;
    const id = card.dataset.id;
    if (e.target.matches("[data-sendback-note]")) { ui.sendBack[id] = e.target.value; e.target.removeAttribute("aria-invalid"); }
    if (e.target.matches("[data-edit-title]")) { ui.editing[id].title = e.target.value; e.target.removeAttribute("aria-invalid"); }
    if (e.target.matches("[data-edit-desc]")) ui.editing[id].description = e.target.value;
  });

  board.addEventListener("change", (e) => {
    const card = e.target.closest(".mcard");
    if (!card) return;
    const id = card.dataset.id;
    if (e.target.matches("[data-file]")) {
      const f = e.target.files && e.target.files[0];
      e.target.value = "";
      uploadFile(id, f);
    }
    if (e.target.matches("[data-edit-tag]")) {
      const tags = ui.editing[id].tags;
      const v = e.target.value;
      if (e.target.checked && !tags.includes(v)) tags.push(v);
      if (!e.target.checked) ui.editing[id].tags = tags.filter((t) => t !== v);
    }
  });

  board.addEventListener("keydown", (e) => {
    const strip = e.target.closest && e.target.closest("[data-strip]");
    if (strip && (e.key === "ArrowRight" || e.key === "ArrowLeft")) {
      e.preventDefault();
      strip.scrollBy({ left: (e.key === "ArrowRight" ? 1 : -1) * strip.clientWidth, behavior: "smooth" });
      return;
    }
    if (e.key !== "Escape") return;
    const card = e.target.closest(".mcard");
    if (!card) return;
    const id = card.dataset.id;
    if (ui.sendBack[id] !== undefined) { delete ui.sendBack[id]; render(); focusIn(id, "[data-sendback]"); }
    else if (ui.editing[id]) { delete ui.editing[id]; delete ui.expanded[id]; render(); focusIn(id, "[data-edit]"); }
    else if (ui.expanded[id]) { delete ui.expanded[id]; render(); focusIn(id, "button[data-expand].btn"); }
  });
}

// ---------------------------------------------------------------- filter
function wireTabs() {
  $("#kind-tabs").addEventListener("click", (e) => {
    const tab = e.target.closest(".tab[data-kind]");
    if (!tab) return;
    kindFilter = tab.dataset.kind;
    $$("#kind-tabs .tab").forEach((t) => {
      const on = t === tab;
      t.classList.toggle("active", on);
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
    });
    if (data) render();
  });
  $$("#kind-tabs .tab").forEach((t, i) => { t.tabIndex = i === 0 ? 0 : -1; });
  let timer = null;
  $("#md-search").addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => { query = e.target.value; if (data) render(); }, 120);
  });
}

// ------------------------------------------------------------ new request
function wireNewForm() {
  const toggle = $("#new-toggle");
  const card = $("#new-card");
  const form = $("#new-form");
  const due = $("#nr-due");
  const d = parseDate(today);
  d.setDate(d.getDate() + 7);
  due.value = isoDate(d);

  const open = (on) => {
    card.hidden = !on;
    toggle.setAttribute("aria-expanded", on ? "true" : "false");
    if (on) $("#nr-kind").focus(); else toggle.focus();
  };
  toggle.addEventListener("click", () => open(card.hidden));
  $$("[data-close-new]", card).forEach((b) => b.addEventListener("click", () => open(false)));
  card.addEventListener("keydown", (e) => { if (e.key === "Escape") open(false); });
  $("#nr-title").addEventListener("input", (e) => e.target.removeAttribute("aria-invalid"));

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const title = $("#nr-title");
    if (!title.value.trim()) {
      title.setAttribute("aria-invalid", "true");
      title.focus();
      toast("Give the request a title", "warn");
      return;
    }
    const fd = new FormData(form);
    const body = {
      kind: fd.get("kind"),
      title: title.value.trim(),
      due: fd.get("due") || null,
      platforms: fd.getAll("platforms"),
      placements: String(fd.get("placements") || "").split(",").map((s) => s.trim()).filter(Boolean),
      description: String(fd.get("description") || "").trim(),
      brief: String(fd.get("brief") || "").trim(),
    };
    try {
      const res = await withBusy($("#nr-submit"), () => api(`${API}/requests`, { body }));
      toast(`${res.asset.id} requested`);
      form.reset();
      due.value = isoDate(d);
      card.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
      if (kindFilter && kindFilter !== res.asset.kind) $(`#kind-tabs .tab[data-kind=""]`).click();
      await refreshAfter(res.asset.id);
      const el = document.getElementById("asset-" + res.asset.id);
      if (el) { el.scrollIntoView({ block: "center" }); el.querySelector("[data-upload]")?.focus({ preventScroll: true }); }
    } catch (err) { /* toasted */ }
  });
}

window.addEventListener("hashchange", () => {
  targetId = location.hash.replace(/^#/, "") || null;
  if (data) render();
});

wireTabs();
wireBoard();
wireNewForm();
load();
