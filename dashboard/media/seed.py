"""Build data/media.json from the library manifest.

    python -m media.seed            # from dashboard/

Source: ``static/media/library/manifest.json`` (real Search Atlas creative, written by the
orchestrator). If it does not exist yet, ``manifest.dev.json`` is used instead, and its
brand-colored placeholder PNGs are generated under ``static/media/library/dev/``.

Always added on top of the manifest: the HTML5 sample ``H5-0001`` (and its Google Ads zip,
rebuilt here) and two open media requests with no file yet.

Writes only data/media.json (and the dev placeholders / H5 zip). Never touches state.json
and does not log activity.
"""

import json
import os
import struct
import sys
import zipfile
import zlib
from typing import Any, Dict, List, Optional

import media

MANIFEST = "manifest.json"
DEV_MANIFEST = "manifest.dev.json"
SEED_TS = "2026-11-05T14:00:00Z"
STEM_ID_RE = __import__("re").compile(r"^((?:IMG|VID|H5)-\d{4,})(?:-\d+)?$")
SEED_ONLY_MIME = {"webm": "video/webm", "avif": "image/avif"}

H5_SAMPLES = [{
    "id": "H5-0001",
    "dir": "H5-0001",
    "title": "Rank in Google and AI search, 300x250",
    "description": "Animated display banner: headline, rising bar chart, mint \"Start free trial\" CTA. "
                   "clickTag goes to searchatlas.com. Zip is ready for a Google Ads HTML5 upload.",
    "status": "approved",
    "platforms": ["google"],
    "placements": ["Google Display Network", "Display remarketing"],
    "tags": [],
    "history": [("requested", "Display banner for remarketing and GDN prospecting tests"),
                ("uploaded", "index.html + zip, 300x250"),
                ("approved", "Brand colors and clickTag checked")],
}]

REQUESTS = [
    {
        "kind": "video",
        "title": "9:16 UGC video: agency owner explains white-label reports, 20 s",
        "description": "Vertical selfie-style video for Meta Reels and Stories, agency segment.",
        "brief": "Agency owner on camera, phone held vertical, natural light. 0-3 s hook: \"My clients think "
                 "I built these reports myself.\" 3-15 s: screen recording of a white-label Search Atlas report "
                 "with the agency's own logo, scroll through rankings and AI visibility. 15-20 s: \"Start a free "
                 "trial at searchatlas.com\" end card. Burned-in captions, 1080x1920, MP4 under 50 MB.",
        "due": "2026-11-12",
        "platforms": ["meta"],
        "placements": ["Reels", "Stories"],
        "tags": ["m_prospecting_test", "m_retargeting_agency_14d"],
    },
    {
        "kind": "image",
        "title": "1080x1080 static: 'Rank in AI search' comparison card",
        "description": "Square comparison card for Meta feed and Google Demand Gen.",
        "brief": "Two-column card. Left \"Classic SEO tools\": rankings only. Right \"Search Atlas\": rankings "
                 "plus visibility in ChatGPT, Gemini and Google AI Overviews. Dark #121212 background, purple "
                 "#936BDA headers, mint #00FFD4 check marks, Inter Tight. Headline \"Rank in AI search\". "
                 "No competitor names or logos. PNG, 1080x1080.",
        "due": "2026-11-10",
        "platforms": ["meta", "google"],
        "placements": ["Facebook Feed", "Instagram Feed", "Demand Gen"],
        "tags": ["m_prospecting_core"],
    },
]

# Placeholder creative used only until the real manifest.json lands.
DEV_ASSETS = [
    {"file": "dev/IMG-DEV-1.png", "kind": "image", "w": 1080, "h": 1080, "status": "approved",
     "title": "All-in-one SEO platform, square feed card",
     "description": "Placeholder for a square Meta feed image (dev manifest).",
     "platforms": ["meta"], "placements": ["Facebook Feed", "Instagram Feed"], "tags": ["m_prospecting_core"]},
    {"file": "dev/IMG-DEV-2.png", "kind": "image", "w": 1080, "h": 1350, "status": "approved",
     "title": "Agency white-label reports, 4:5 portrait",
     "description": "Placeholder for a 4:5 Meta feed image aimed at agencies (dev manifest).",
     "platforms": ["meta"], "placements": ["Facebook Feed", "Instagram Feed"], "tags": ["m_retargeting_agency_14d"]},
    {"file": "dev/IMG-DEV-3.png", "kind": "image", "w": 1080, "h": 1920, "status": "in_review",
     "title": "Free trial story frame, 9:16",
     "description": "Placeholder for a 9:16 Stories image (dev manifest).",
     "platforms": ["meta"], "placements": ["Stories", "Reels"], "tags": []},
    {"file": "dev/IMG-DEV-4.png", "kind": "image", "w": 1200, "h": 628, "status": "in_review",
     "title": "Google + AI visibility, 1.91:1 landscape",
     "description": "Placeholder for a 1.91:1 landscape image for PMax / Demand Gen (dev manifest).",
     "platforms": ["google", "meta"], "placements": ["Performance Max", "Demand Gen"], "tags": ["g_pmax_us"]},
]


# ------------------------------------------------------------ placeholders

def _png(width, height, seed):
    # type: (int, int, int) -> bytes
    """A brand-colored placeholder PNG: dark ground, purple diagonal glow, mint bar. Pure Python."""
    purple = (147, 107, 218)
    mint = (0, 255, 212)
    ink = (18, 18, 18)
    rows = []
    bar_top, bar_bot = int(height * 0.78), int(height * 0.80)
    bar_right = int(width * (0.35 + 0.1 * seed))
    for y in range(height):
        row = bytearray(b"\x00")
        fy = y / float(height)
        for x in range(width):
            if bar_top <= y < bar_bot and int(width * 0.08) <= x < bar_right:
                row += bytes(mint)
                continue
            fx = x / float(width)
            t = max(0.0, 1.0 - ((1 - fx) ** 2 + fy ** 2) ** 0.5 * 1.1)
            row += bytes(int(ink[i] + (purple[i] - ink[i]) * t) for i in range(3))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def write_dev_manifest():
    # type: () -> str
    """Generate placeholder PNGs + manifest.dev.json (idempotent)."""
    lib = media.LIBRARY_DIR
    os.makedirs(os.path.join(lib, "dev"), exist_ok=True)
    out = []
    for i, a in enumerate(DEV_ASSETS):
        path = os.path.join(lib, a["file"])
        if not os.path.exists(path) or media.image_size(open(path, "rb").read(32)) != (a["w"], a["h"]):
            with open(path, "wb") as fh:
                fh.write(_png(a["w"], a["h"], i))
        out.append({"file": a["file"], "kind": a["kind"], "title": a["title"], "description": a["description"],
                    "status": a["status"], "source_url": None, "width": a["w"], "height": a["h"],
                    "duration_s": None, "platforms": a["platforms"], "placements": a["placements"],
                    "tags": a["tags"]})
    path = os.path.join(lib, DEV_MANIFEST)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"note": "Temporary placeholders until manifest.json (real creative) exists.", "assets": out},
                  fh, indent=1)
        fh.write("\n")
    return path


def build_h5_zip(sample_dir):
    # type: (str) -> str
    """Zip an HTML5 sample folder (files at the zip root, as Google Ads expects)."""
    src = os.path.join(media.LIBRARY_DIR, sample_dir)
    dest = os.path.join(media.LIBRARY_DIR, sample_dir + ".zip")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(src):
            for name in sorted(files):
                if name.startswith("."):
                    continue
                full = os.path.join(root, name)
                info = zipfile.ZipInfo(os.path.relpath(full, src), date_time=(2026, 11, 5, 12, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(full, "rb") as fh:
                    zf.writestr(info, fh.read())
    return dest


# -------------------------------------------------------------------- seed

def _manifest_path():
    # type: () -> str
    real = os.path.join(media.LIBRARY_DIR, MANIFEST)
    if os.path.exists(real):
        return real
    return write_dev_manifest()


def _guess_kind(entry):
    # type: (Dict[str, Any]) -> str
    kind = entry.get("kind")
    if kind in media.KINDS:
        return kind
    mime = media.normalize_mime("", entry.get("file", ""))
    return media.MIME_KIND.get(mime or "", "image")


def _history(pairs, ts=SEED_TS):
    return [{"ts": ts, "action": a, "note": n} for a, n in pairs]


def _asset_from_entry(doc, entry):
    # type: (Dict[str, Any], Dict[str, Any]) -> Dict[str, Any]
    kind = _guess_kind(entry)
    rel = entry["file"].lstrip("/")
    path = os.path.join(media.LIBRARY_DIR, rel)
    stem = os.path.splitext(os.path.basename(rel))[0]
    m_stem = STEM_ID_RE.match(stem)  # "IMG-0004-1" (first carousel card) -> IMG-0004
    explicit = entry.get("id") or (m_stem.group(1) if m_stem else stem)
    if media.ID_RE.match(explicit) and media.kind_of(explicit) == kind and \
            not any(a["id"] == explicit for a in doc["assets"]):
        asset_id = explicit
        n = int(media.ID_RE.match(explicit).group(2))
        doc["counters"][kind] = max(doc["counters"][kind], n)
    else:
        asset_id = media.next_id(doc, kind)

    ext = os.path.splitext(rel)[1].lower().lstrip(".")
    # library-only formats (not accepted for upload) keep their real mime, e.g. WebM site cuts
    mime = (media.normalize_mime(entry.get("format") or "", rel) or SEED_ONLY_MIME.get(ext)
            or "application/octet-stream")
    size = os.path.getsize(path) if os.path.exists(path) else None
    width, height, duration = entry.get("width"), entry.get("height"), entry.get("duration_s")
    if os.path.exists(path) and (not width or not height or (kind == "video" and duration is None)):
        with open(path, "rb") as fh:
            data = fh.read() if kind != "image" else fh.read(256 * 1024)
        info = media.inspect_bytes(mime, data)
        width = width or info.get("width")
        height = height or info.get("height")
        if duration is None:
            duration = info.get("duration_s")
    status = entry.get("status") if entry.get("status") in ("approved", "in_review") else "in_review"
    file_url = "%s/%s" % (media.LIBRARY_URL, rel)
    thumb = entry.get("thumb") or entry.get("thumb_file") or entry.get("poster")
    thumb_url = ("%s/%s" % (media.LIBRARY_URL, thumb.lstrip("/"))) if thumb else (file_url if kind == "image" else None)
    asset = media.blank_asset(asset_id, kind, entry.get("title") or asset_id)
    hist = [("requested", "Imported from the Search Atlas creative library"),
            ("uploaded", os.path.basename(rel))]
    if status == "approved":
        hist.append(("approved", "Live in the Meta Ad Library" if entry.get("meta_library_id") else "Live Search Atlas creative"))
    asset.update({
        "status": status, "description": entry.get("description") or "", "brief": entry.get("brief") or "",
        "format": mime, "file_url": file_url, "thumb_url": thumb_url,
        "width": width, "height": height, "duration_s": duration, "size_bytes": size,
        "aspect": entry.get("aspect") or media.aspect_for(width, height, kind),
        "platforms": [p for p in (entry.get("platforms") or ["meta"]) if p in media.PLATFORMS] or ["meta"],
        "placements": list(entry.get("placements") or []),
        "source": entry.get("source") or "library", "source_url": entry.get("source_url"),
        "requested_by": "vin", "created_at": SEED_TS, "updated_at": SEED_TS,
        "history": _history(hist), "tags": list(entry.get("tags") or []),
    })
    cards = entry.get("cards") or []
    asset["cards"] = ["%s/%s" % (media.LIBRARY_URL, c.lstrip("/")) for c in cards] if cards else None
    for key in ("meta_library_id", "started_running", "primary_text", "headline", "cta"):
        asset[key] = entry.get(key)
    if cards:
        asset["size_bytes"] = sum(os.path.getsize(os.path.join(media.LIBRARY_DIR, c)) for c in cards
                                  if os.path.exists(os.path.join(media.LIBRARY_DIR, c))) or size
    if not os.path.exists(path):
        asset["missing_file"] = True
    return asset


def build(manifest_path=None):
    # type: (Optional[str]) -> Dict[str, Any]
    manifest_path = manifest_path or _manifest_path()
    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    doc = media._empty()
    doc["source_manifest"] = os.path.relpath(manifest_path, media.BASE_DIR)
    entries = list(manifest.get("assets", []))
    # reserve explicit ids (file stems like IMG-0001) before numbering the rest
    entries.sort(key=lambda e: 0 if STEM_ID_RE.match(e.get("id") or os.path.splitext(os.path.basename(e["file"]))[0]) else 1)
    for entry in entries:
        doc["assets"].append(_asset_from_entry(doc, entry))

    for h5 in H5_SAMPLES:
        index = os.path.join(media.LIBRARY_DIR, h5["dir"], "index.html")
        zip_path = build_h5_zip(h5["dir"])
        with open(index, "rb") as fh:
            dims = media.html5_size(fh.read())
        asset = media.blank_asset(h5["id"], "html5", h5["title"])
        asset.update({
            "status": h5["status"], "description": h5["description"], "format": "application/zip",
            "file_url": "%s/%s/index.html" % (media.LIBRARY_URL, h5["dir"]),
            "package_url": "%s/%s.zip" % (media.LIBRARY_URL, h5["dir"]),
            "width": dims.get("width"), "height": dims.get("height"),
            "size_bytes": os.path.getsize(zip_path), "aspect": media.aspect_for(dims.get("width"), dims.get("height"), "html5"),
            "platforms": h5["platforms"], "placements": h5["placements"], "source": "built",
            "created_at": SEED_TS, "updated_at": SEED_TS, "history": _history(h5["history"]), "tags": h5["tags"],
        })
        n = int(media.ID_RE.match(h5["id"]).group(2))
        doc["counters"]["html5"] = max(doc["counters"]["html5"], n)
        doc["assets"].append(asset)

    for req in REQUESTS:
        asset = media.blank_asset(media.next_id(doc, req["kind"]), req["kind"], req["title"])
        asset.update({k: req[k] for k in ("description", "brief", "due", "platforms", "placements", "tags")})
        asset.update({"created_at": SEED_TS, "updated_at": SEED_TS,
                      "history": _history([("requested", "Due %s" % req["due"])])})
        doc["assets"].append(asset)

    order = {k: i for i, k in enumerate(media.KINDS)}
    doc["assets"].sort(key=lambda a: (order[a["kind"]], a["id"]))
    return doc


def main(argv=None):
    # type: (Optional[List[str]]) -> int
    argv = argv if argv is not None else sys.argv[1:]
    doc = build(argv[0] if argv else None)
    media.save(doc)
    c = media.counts(doc["assets"])
    print("wrote %s from %s: %d assets %s %s" % (os.path.relpath(media.MEDIA_PATH, media.BASE_DIR),
                                                 doc["source_manifest"], c["total"], c["by_status"], c["by_kind"]))
    for a in doc["assets"]:
        print("  %-9s %-10s %s%s" % (a["id"], a["status"], a["title"], "  [missing file]" if a.get("missing_file") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
