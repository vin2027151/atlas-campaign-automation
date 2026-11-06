"""Media library: numbered image, video and HTML5 assets for the ad accounts.

Persisted in ``data/media.json`` (atomic writes via ``store.write_json_atomic``).
Files live under ``static/media/library/`` (seeded creative) and
``static/media/library/uploads/`` (files uploaded against a request).

Planning code imports this module, so it stays import-light: stdlib + ``store``
only, no FastAPI. The three functions planning relies on:

    list_assets(status=None, kind=None) -> [asset]
    get_asset(asset_id) -> asset                     # store.NotFound if missing
    mark_published(asset_id, platform, ref_dict) -> asset

Asset lifecycle: ``requested`` (brief, no file) -> upload -> ``in_review``
-> approve -> ``approved``; reject sends ``in_review`` back to ``requested``
with a note. IDs are per kind: ``IMG-0001``, ``VID-0001``, ``H5-0001``.

Path constants are module level so tests can repoint them at temp copies.
"""

import copy
import io
import json
import os
import re
import shutil
import struct
import threading
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import store

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEDIA_PATH = os.path.join(BASE_DIR, "data", "media.json")
LIBRARY_DIR = os.path.join(BASE_DIR, "static", "media", "library")
UPLOAD_DIR = os.path.join(LIBRARY_DIR, "uploads")
LIBRARY_URL = "/static/media/library"
UPLOAD_URL = LIBRARY_URL + "/uploads"

KINDS = ("image", "video", "html5")
STATUSES = ("requested", "in_review", "approved")
STATUS_LABELS = {"requested": "Requests", "in_review": "Ready for review", "approved": "Approved"}
KIND_PREFIX = {"image": "IMG", "video": "VID", "html5": "H5"}
PREFIX_KIND = {v: k for k, v in KIND_PREFIX.items()}
PLATFORMS = ("meta", "google")
ID_RE = re.compile(r"^(IMG|VID|H5)-(\d{4,})$")

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MIME_KIND = {
    "image/png": "image",
    "image/jpeg": "image",
    "image/webp": "image",
    "image/gif": "image",
    "video/mp4": "video",
    "video/quicktime": "video",
    "text/html": "html5",
    "application/zip": "html5",
}
MIME_EXT = {
    "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif",
    "video/mp4": "mp4", "video/quicktime": "mov", "text/html": "html", "application/zip": "zip",
}
EXT_MIME = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif",
    "mp4": "video/mp4", "m4v": "video/mp4", "mov": "video/quicktime", "html": "text/html", "htm": "text/html",
    "zip": "application/zip",
}
MIME_ALIASES = {"image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg", "application/x-zip-compressed": "application/zip",
                "application/x-zip": "application/zip"}

TEXT_LIMITS = {"title": 140, "description": 1000, "brief": 2000, "note": 1000}

_lock = threading.RLock()


# ------------------------------------------------------------------- helpers

def now_iso():
    # type: () -> str
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def kind_of(asset_id):
    # type: (str) -> Optional[str]
    m = ID_RE.match(str(asset_id or ""))
    return PREFIX_KIND.get(m.group(1)) if m else None


def aspect_for(width, height, kind=None):
    # type: (Optional[int], Optional[int], Optional[str]) -> Optional[str]
    """Nearest named ad aspect ("1:1", "4:5", "9:16", "16:9", "1.91:1"...); HTML5 uses its slot size."""
    if not width or not height:
        return None
    if kind == "html5":
        return "%dx%d" % (width, height)
    ratio = float(width) / float(height)
    named = [("1:1", 1.0), ("4:5", 0.8), ("9:16", 9 / 16.0), ("16:9", 16 / 9.0), ("1.91:1", 1.91),
             ("2:3", 2 / 3.0), ("3:2", 1.5), ("4:3", 4 / 3.0), ("3:4", 0.75)]
    best = min(named, key=lambda n: abs(n[1] - ratio))
    if abs(best[1] - ratio) / best[1] <= 0.03:
        return best[0]
    return "%dx%d" % (width, height)


def _text(value, field, required=False):
    # type: (Any, str, bool) -> str
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise store.BadInput("%s must be text" % field)
    value = value.strip()
    if required and not value:
        raise store.BadInput("%s is required" % field)
    limit = TEXT_LIMITS.get(field, 1000)
    if len(value) > limit:
        raise store.BadInput("%s is longer than %d characters" % (field, limit))
    return value


def _str_list(value, field, allowed=None, limit=20):
    # type: (Any, str, Optional[Tuple[str, ...]], int) -> List[str]
    if value is None:
        return []
    if isinstance(value, str):
        value = [v for v in re.split(r"[,\n]", value)]
    if not isinstance(value, list):
        raise store.BadInput("%s must be a list" % field)
    out = []  # type: List[str]
    for v in value:
        if not isinstance(v, str):
            raise store.BadInput("%s must be a list of text" % field)
        v = v.strip()
        if not v:
            continue
        if allowed is not None and v not in allowed:
            raise store.BadInput("%s: unknown value %r (allowed: %s)" % (field, v, ", ".join(allowed)))
        if len(v) > 80:
            raise store.BadInput("%s: %r is too long" % (field, v[:20]))
        if v not in out:
            out.append(v)
    if len(out) > limit:
        raise store.BadInput("%s: at most %d values" % (field, limit))
    return out


def _date(value):
    # type: (Any) -> Optional[str]
    if value in (None, ""):
        return None
    try:
        return store.iso(store.parse_date(str(value)))
    except Exception:
        raise store.BadInput("due must be a date YYYY-MM-DD")


# ------------------------------------------------------------------------ io

def _empty():
    # type: () -> Dict[str, Any]
    return {"version": 1, "updated_at": None, "counters": {k: 0 for k in KINDS}, "assets": []}


def load():
    # type: () -> Dict[str, Any]
    """Read the library document (a fresh copy every call; the file is small)."""
    with _lock:
        if not os.path.exists(MEDIA_PATH):
            return _empty()
        with open(MEDIA_PATH, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        doc.setdefault("assets", [])
        counters = doc.setdefault("counters", {})
        for k in KINDS:
            counters.setdefault(k, 0)
        return doc


def save(doc):
    # type: (Dict[str, Any]) -> None
    with _lock:
        doc["updated_at"] = now_iso()
        directory = os.path.dirname(MEDIA_PATH)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        store.write_json_atomic(MEDIA_PATH, doc)


def _mutate(asset_id, fn):
    # type: (str, Any) -> Dict[str, Any]
    """Load, find asset, run fn(asset, doc), stamp updated_at, save, return a copy."""
    with _lock:
        doc = load()
        asset = _find(doc, asset_id)
        fn(asset, doc)
        asset["updated_at"] = now_iso()
        save(doc)
        return copy.deepcopy(asset)


def _find(doc, asset_id):
    # type: (Dict[str, Any], str) -> Dict[str, Any]
    for a in doc["assets"]:
        if a["id"] == asset_id:
            return a
    raise store.NotFound("media asset %r not found" % asset_id)


def next_id(doc, kind):
    # type: (Dict[str, Any], str) -> str
    if kind not in KINDS:
        raise store.BadInput("kind must be one of %s" % ", ".join(KINDS))
    prefix = KIND_PREFIX[kind]
    used = [int(ID_RE.match(a["id"]).group(2)) for a in doc["assets"]
            if ID_RE.match(a["id"]) and a["id"].startswith(prefix + "-")]
    n = max([doc["counters"].get(kind, 0)] + used) + 1
    doc["counters"][kind] = n
    return "%s-%04d" % (prefix, n)


def _history(asset, action, note=""):
    # type: (Dict[str, Any], str, str) -> None
    asset.setdefault("history", []).append({"ts": now_iso(), "action": action, "note": note or ""})


def _log(action, target, detail=""):
    # type: (str, str, str) -> None
    try:
        store.log_activity(action, target, detail)
    except Exception:  # activity log is best effort; the media change already saved
        pass


def blank_asset(asset_id, kind, title):
    # type: (str, str, str) -> Dict[str, Any]
    ts = now_iso()
    return {
        "id": asset_id, "kind": kind, "status": "requested", "title": title, "description": "", "brief": "",
        "format": None, "file_url": None, "thumb_url": None, "package_url": None,
        "width": None, "height": None, "duration_s": None, "size_bytes": None, "aspect": None,
        "platforms": [], "placements": [], "source": "request", "source_url": None,
        "requested_by": "vin", "due": None, "created_at": ts, "updated_at": ts,
        "history": [], "tags": [], "platform_refs": {},
    }


# ------------------------------------------------------------- public reads

def list_assets(status=None, kind=None):
    # type: (Optional[str], Optional[str]) -> List[Dict[str, Any]]
    """All assets (copies), optionally filtered by status and/or kind, ordered by id within kind."""
    if status is not None and status not in STATUSES:
        raise store.BadInput("status must be one of %s" % ", ".join(STATUSES))
    if kind is not None and kind not in KINDS:
        raise store.BadInput("kind must be one of %s" % ", ".join(KINDS))
    out = [a for a in load()["assets"]
           if (status is None or a.get("status") == status) and (kind is None or a.get("kind") == kind)]
    return copy.deepcopy(out)


def get_asset(asset_id):
    # type: (str) -> Dict[str, Any]
    """One asset by id (a copy). Raises store.NotFound."""
    return copy.deepcopy(_find(load(), asset_id))


def counts(assets=None):
    # type: (Optional[List[Dict[str, Any]]]) -> Dict[str, Any]
    if assets is None:
        assets = load()["assets"]
    by_status = {s: 0 for s in STATUSES}
    by_kind = {k: 0 for k in KINDS}
    for a in assets:
        by_status[a.get("status")] = by_status.get(a.get("status"), 0) + 1
        by_kind[a.get("kind")] = by_kind.get(a.get("kind"), 0) + 1
    return {"total": len(assets), "by_status": by_status, "by_kind": by_kind}


def file_path(asset):
    # type: (Dict[str, Any]) -> Optional[str]
    """Local filesystem path of an asset's main file (for adapters uploading to the platforms)."""
    url = asset.get("package_url") if asset.get("kind") == "html5" and asset.get("package_url") else asset.get("file_url")
    if not url or not url.startswith(LIBRARY_URL + "/"):
        return None
    rel = url[len(LIBRARY_URL) + 1:]
    path = os.path.normpath(os.path.join(LIBRARY_DIR, rel))
    if not path.startswith(os.path.normpath(LIBRARY_DIR) + os.sep):
        return None
    return path


# ------------------------------------------------------------ public writes

def create_request(title, description="", kind="image", brief="", due=None, platforms=None, placements=None,
                   requested_by="vin"):
    # type: (Any, Any, Any, Any, Any, Any, Any, str) -> Dict[str, Any]
    """New asset in status ``requested`` (no file yet)."""
    if kind not in KINDS:
        raise store.BadInput("kind must be one of %s" % ", ".join(KINDS))
    title = _text(title, "title", required=True)
    description = _text(description, "description")
    brief = _text(brief, "brief")
    due = _date(due)
    platforms = _str_list(platforms, "platforms", PLATFORMS) or ["meta"]
    placements = _str_list(placements, "placements")
    with _lock:
        doc = load()
        asset = blank_asset(next_id(doc, kind), kind, title)
        asset.update({"description": description, "brief": brief, "due": due, "platforms": platforms,
                      "placements": placements, "requested_by": requested_by or "vin"})
        _history(asset, "requested", brief[:200])
        doc["assets"].append(asset)
        save(doc)
        out = copy.deepcopy(asset)
    _log("media.request", out["id"], "%s: %s" % (kind, title))
    return out


def normalize_mime(content_type, filename=""):
    # type: (Optional[str], str) -> Optional[str]
    """Canonical whitelisted mime, falling back to the file extension for generic types."""
    mime = (content_type or "").split(";")[0].strip().lower()
    mime = MIME_ALIASES.get(mime, mime)
    if mime in MIME_KIND:
        return mime
    if mime in ("", "application/octet-stream", "binary/octet-stream"):
        ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
        return EXT_MIME.get(ext)
    return None


def attach_file(asset_id, filename, content_type, data):
    # type: (str, str, Optional[str], bytes) -> Dict[str, Any]
    """Store an uploaded file for a request (or replace one in review) and move it to ``in_review``."""
    mime = normalize_mime(content_type, filename)
    if mime is None:
        raise store.BadInput("unsupported file type %r: use PNG, JPEG, WEBP, GIF, MP4, MOV, HTML or ZIP"
                             % (content_type or filename))
    if not data:
        raise store.BadInput("the file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise store.BadInput("file is larger than 50 MB")
    asset = get_asset(asset_id)
    if asset["status"] not in ("requested", "in_review"):
        raise store.BadInput("%s is already approved; create a new request for a new file" % asset_id)
    file_kind = MIME_KIND[mime]
    if file_kind != asset["kind"]:
        raise store.BadInput("%s is a %s request; a %s file does not fit it" % (asset_id, asset["kind"], mime))

    meta = inspect_bytes(mime, data)
    if mime.startswith("image/") and not meta.get("width"):
        raise store.BadInput("could not read the image: the file is not a valid %s" % MIME_EXT[mime].upper())

    if mime == "application/zip":
        _check_html5_zip(data)  # validate before touching any previous upload

    if not os.path.isdir(UPLOAD_DIR):
        os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = MIME_EXT[mime]
    _clear_uploads(asset_id)
    dest = os.path.join(UPLOAD_DIR, "%s.%s" % (asset_id, ext))
    with open(dest, "wb") as fh:
        fh.write(data)
    file_url = "%s/%s.%s" % (UPLOAD_URL, asset_id, ext)
    package_url = None
    if mime == "application/zip":
        index_rel, dims = _extract_html5_zip(asset_id, data)
        package_url = file_url
        file_url = "%s/%s/%s" % (UPLOAD_URL, asset_id, index_rel)
        meta.update(dims)

    def apply(a, doc):
        a.update({
            "status": "in_review", "format": mime, "file_url": file_url, "package_url": package_url,
            "thumb_url": file_url if a["kind"] == "image" else None,
            "width": meta.get("width"), "height": meta.get("height"), "duration_s": meta.get("duration_s"),
            "size_bytes": len(data), "aspect": aspect_for(meta.get("width"), meta.get("height"), a["kind"]),
            "source": "upload", "original_filename": os.path.basename(filename or "")[:200],
        })
        _history(a, "uploaded", "%s, %s" % (os.path.basename(filename or "file")[:120], _human_size(len(data))))

    out = _mutate(asset_id, apply)
    _log("media.upload", asset_id, "%s %s" % (mime, _human_size(len(data))))
    return out


def approve(asset_id, note=""):
    # type: (str, Any) -> Dict[str, Any]
    note = _text(note, "note")

    def apply(a, doc):
        if a["status"] != "in_review":
            raise store.BadInput("%s is %s; only assets ready for review can be approved" % (asset_id, a["status"]))
        a["status"] = "approved"
        _history(a, "approved", note)

    out = _mutate(asset_id, apply)
    _log("media.approve", asset_id, note)
    return out


def reject(asset_id, note):
    # type: (str, Any) -> Dict[str, Any]
    """Send an asset in review back to requests. A note is required."""
    note = _text(note, "note", required=True)

    def apply(a, doc):
        if a["status"] != "in_review":
            raise store.BadInput("%s is %s; only assets ready for review can be sent back" % (asset_id, a["status"]))
        a["status"] = "requested"
        a["review_note"] = note
        _history(a, "sent back", note)

    out = _mutate(asset_id, apply)
    _log("media.reject", asset_id, note)
    return out


EDITABLE = ("title", "description", "brief", "tags", "due", "platforms", "placements")


def update(asset_id, fields):
    # type: (str, Dict[str, Any]) -> Dict[str, Any]
    """Edit title / description / brief / tags (campaign ids) / due / platforms / placements."""
    if not isinstance(fields, dict):
        raise store.BadInput("body must be an object")
    unknown = [k for k in fields if k not in EDITABLE]
    if unknown:
        raise store.BadInput("cannot edit %s (editable: %s)" % (", ".join(unknown), ", ".join(EDITABLE)))
    if not fields:
        raise store.BadInput("nothing to change")
    clean = {}  # type: Dict[str, Any]
    if "title" in fields:
        clean["title"] = _text(fields["title"], "title", required=True)
    for k in ("description", "brief"):
        if k in fields:
            clean[k] = _text(fields[k], k)
    if "tags" in fields:
        tags = _str_list(fields["tags"], "tags", limit=30)
        known = set(c["id"] for c in store.get_state().get("campaigns", []))
        bad = [t for t in tags if t not in known]
        if bad:
            raise store.BadInput("unknown campaign id(s): %s" % ", ".join(bad))
        clean["tags"] = tags
    if "due" in fields:
        clean["due"] = _date(fields["due"])
    if "platforms" in fields:
        clean["platforms"] = _str_list(fields["platforms"], "platforms", PLATFORMS)
    if "placements" in fields:
        clean["placements"] = _str_list(fields["placements"], "placements")
    changed = []  # type: List[str]

    def apply(a, doc):
        for k, v in clean.items():
            if a.get(k) != v:
                a[k] = v
                changed.append(k)
        if changed:
            _history(a, "edited", ", ".join(changed))

    out = _mutate(asset_id, apply)
    if changed:
        _log("media.edit", asset_id, ", ".join(changed))
    return out


def mark_published(asset_id, platform, ref_dict):
    # type: (str, str, Dict[str, Any]) -> Dict[str, Any]
    """Record a platform reference after the executor uploaded the asset.

    meta: {"image_hash": ...} or {"video_id": ...}; google: {"asset_resource": ...}. Merges into
    ``platform_refs[platform]``.
    """
    if platform not in PLATFORMS:
        raise store.BadInput("platform must be one of %s" % ", ".join(PLATFORMS))
    if not isinstance(ref_dict, dict) or not ref_dict:
        raise store.BadInput("ref_dict must be a non-empty object")
    refs = {str(k): v for k, v in ref_dict.items()}

    def apply(a, doc):
        if a["status"] != "approved":
            raise store.BadInput("%s is %s; only approved media can be published" % (asset_id, a["status"]))
        a.setdefault("platform_refs", {}).setdefault(platform, {}).update(refs)
        _history(a, "published", "%s %s" % (platform, ", ".join("%s=%s" % (k, v) for k, v in refs.items())))

    out = _mutate(asset_id, apply)
    _log("media.publish", asset_id, "%s %s" % (platform, json.dumps(refs, sort_keys=True)))
    return out


# ------------------------------------------------------- upload file helpers

def _clear_uploads(asset_id):
    # type: (str) -> None
    if not os.path.isdir(UPLOAD_DIR):
        return
    for name in os.listdir(UPLOAD_DIR):
        path = os.path.join(UPLOAD_DIR, name)
        if name == asset_id and os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.splitext(name)[0] == asset_id and os.path.isfile(path):
            os.unlink(path)


def _check_html5_zip(data):
    # type: (bytes) -> Tuple[zipfile.ZipFile, List[str], str]
    """Open an HTML5 ad zip and pick its entry page; BadInput if it is not a usable ad package."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise store.BadInput("the zip file could not be read")
    names = [n for n in zf.namelist() if not n.endswith("/")]
    if len(names) > 200:
        raise store.BadInput("the zip holds more than 200 files")
    if sum(i.file_size for i in zf.infolist()) > MAX_UPLOAD_BYTES * 2:
        raise store.BadInput("the zip expands to more than 100 MB")
    html = [n for n in names if n.lower().endswith((".html", ".htm")) and not n.startswith("__MACOSX")]
    if not html:
        raise store.BadInput("the zip has no .html file (an HTML5 ad needs index.html)")
    index = sorted(html, key=lambda n: (os.path.basename(n).lower() != "index.html", n.count("/"), n))[0]
    for name in names:
        norm = os.path.normpath(name)
        if name.startswith("/") or norm.startswith("..") or "\\" in name:
            raise store.BadInput("the zip contains an unsafe path: %s" % name[:80])
    return zf, names, index


def _extract_html5_zip(asset_id, data):
    # type: (str, bytes) -> Tuple[str, Dict[str, Any]]
    """Unpack an HTML5 ad zip under uploads/<ID>/ (path-safe) and return (index path, dims)."""
    zf, names, index = _check_html5_zip(data)
    root = os.path.join(UPLOAD_DIR, asset_id)
    os.makedirs(root, exist_ok=True)
    real_root = os.path.realpath(root)
    for name in names:
        if name.startswith("__MACOSX"):
            continue
        target = os.path.realpath(os.path.join(root, name))
        if not target.startswith(real_root + os.sep):
            raise store.BadInput("the zip contains an unsafe path: %s" % name[:80])
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with zf.open(name) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
    dims = html5_size(zf.read(index))
    return index, dims


def html5_size(html_bytes):
    # type: (bytes) -> Dict[str, Any]
    """Read the slot size from <meta name="ad.size" content="width=300,height=250">."""
    text = html_bytes[:20000].decode("utf-8", "replace")
    m = re.search(r'name=["\']ad\.size["\'][^>]*content=["\']\s*width\s*=\s*(\d+)\s*,\s*height\s*=\s*(\d+)', text, re.I)
    if not m:
        m = re.search(r'content=["\']\s*width\s*=\s*(\d+)\s*,\s*height\s*=\s*(\d+)["\'][^>]*name=["\']ad\.size', text, re.I)
    if m:
        return {"width": int(m.group(1)), "height": int(m.group(2))}
    return {}


def inspect_bytes(mime, data):
    # type: (str, bytes) -> Dict[str, Any]
    """Width / height (images, MP4/MOV, HTML5) and duration (MP4/MOV) from the file header."""
    if mime.startswith("image/"):
        dims = image_size(data)
        return {"width": dims[0], "height": dims[1]} if dims else {}
    if mime.startswith("video/"):
        return mp4_info(data)
    if mime == "text/html":
        return html5_size(data)
    return {}


def image_size(data):
    # type: (bytes) -> Optional[Tuple[int, int]]
    """(width, height) from a PNG, JPEG, GIF or WEBP header; None if unrecognised."""
    if len(data) < 24:
        return None
    # PNG: signature then IHDR
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        w, h = struct.unpack(">II", data[16:24])
        return (w, h)
    # GIF87a / GIF89a: logical screen size
    if data[:6] in (b"GIF87a", b"GIF89a"):
        w, h = struct.unpack("<HH", data[6:10])
        return (w, h)
    # WEBP: RIFF....WEBP + VP8 / VP8L / VP8X chunk
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        chunk = data[12:16]
        if chunk == b"VP8X":
            w = 1 + int.from_bytes(data[24:27], "little")
            h = 1 + int.from_bytes(data[27:30], "little")
            return (w, h)
        if chunk == b"VP8L" and data[20:21] == b"\x2f":
            b = data[21:25]
            w = 1 + (((b[1] & 0x3F) << 8) | b[0])
            h = 1 + (((b[3] & 0x0F) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
            return (w, h)
        if chunk == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
            w, h = struct.unpack("<HH", data[26:30])
            return (w & 0x3FFF, h & 0x3FFF)
        return None
    # JPEG: walk markers to the first SOFn
    if data[:2] == b"\xff\xd8":
        i = 2
        n = len(data)
        while i + 9 < n:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker == 0xFF:
                i += 1
                continue
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return (w, h)
            i += 2 + seg_len
        return None
    return None


def mp4_info(data):
    # type: (bytes) -> Dict[str, Any]
    """Duration (mvhd) and the largest track size (tkhd) from an MP4 / MOV; {} if not found."""
    out = {}  # type: Dict[str, Any]

    def boxes(start, end):
        i = start
        while i + 8 <= end:
            size, typ = struct.unpack(">I4s", data[i:i + 8])
            header = 8
            if size == 1 and i + 16 <= end:
                size = struct.unpack(">Q", data[i + 8:i + 16])[0]
                header = 16
            elif size == 0:
                size = end - i
            if size < header or i + size > end:
                return
            yield typ, i + header, i + size
            i += size

    try:
        for typ, body, end in boxes(0, len(data)):
            if typ != b"moov":
                continue
            best = (0, 0)
            for t2, b2, e2 in boxes(body, end):
                if t2 == b"mvhd":
                    version = data[b2]
                    if version == 1:
                        timescale, duration = struct.unpack(">IQ", data[b2 + 20:b2 + 32])
                    else:
                        timescale, duration = struct.unpack(">II", data[b2 + 12:b2 + 20])
                    if timescale:
                        out["duration_s"] = round(duration / float(timescale), 2)
                elif t2 == b"trak":
                    for t3, b3, e3 in boxes(b2, e2):
                        if t3 == b"tkhd":
                            version = data[b3]
                            off = b3 + (88 if version == 1 else 76)
                            w, h = struct.unpack(">II", data[off:off + 8])
                            w, h = w >> 16, h >> 16
                            if w * h > best[0] * best[1]:
                                best = (w, h)
            if best[0]:
                out["width"], out["height"] = best
            break
    except (struct.error, IndexError):
        pass
    return out


def _human_size(n):
    # type: (int) -> str
    if n >= 1024 * 1024:
        return "%.1f MB" % (n / 1048576.0)
    if n >= 1024:
        return "%d KB" % round(n / 1024.0)
    return "%d B" % n
