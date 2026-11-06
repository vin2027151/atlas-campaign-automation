"""Meta Marketing (Graph) API adapter.

Builds the real requests:

    POST https://graph.facebook.com/{api_version}/{path}
    headers: Authorization: Bearer <system user token>
    body:    form fields; nested objects (targeting, object_story_spec, creative, ...)
             JSON-encoded, as the Graph API expects.

/act_{id}/adimages gets the file as base64 ``bytes``; /act_{id}/advideos gets ``file_url``
when the asset is public, else a multipart ``source`` upload. Refuses to send unless config
mode == live AND env ATLAS_ALLOW_LIVE == "1" (and credentials are not EXAMPLE values).
"""

import base64
import copy
import json
import os
import re
import uuid
from typing import Any, Dict

from planning.adapters import LiveRefused, live_allowed
from planning.adapters.base import Adapter, AdapterError, media_asset, resolve_refs
from planning.adapters.live_google import _asset_file

ENDPOINT = "https://graph.facebook.com"
DEFAULT_VERSION = "v27.0"  # confirmed 2026-11-06 on developers.facebook.com/docs/marketing-api/marketing-api-changelog
REDACTED = "\u2039redacted\u203a"
EDGE_RE = re.compile(r"^/(act_\d+)/(adimages|advideos|adcreatives|ads)$")
NODE_RE = re.compile(r"^/(\d+)$")


def normalize_path(path):
    # type: (Any) -> str
    p = str(path or "").strip()
    if not p.startswith("/"):
        p = "/" + p
    return p.rstrip("/") or "/"


def _snapshot_targeting(ctx, node_id):
    snap = (ctx or {}).get("snapshot") or {}
    for c in (snap.get("meta") or {}).get("campaigns", []):
        for s in c.get("ad_sets", []):
            if str(s.get("meta_id")) == str(node_id):
                return s.get("targeting") or {}
    return None


def api_params(op, ctx, inline_bytes=False):
    # type: (Dict[str, Any], Dict[str, Any], bool) -> Dict[str, Any]
    """Params as the Graph API takes them (media ids turned into upload fields, full targeting)."""
    resolved = resolve_refs(op, (ctx or {}).get("outputs") or {})
    path = normalize_path(resolved.get("path"))
    params = copy.deepcopy(resolved.get("params") or {})
    m = EDGE_RE.match(path)
    if m and m.group(2) in ("adimages", "advideos"):
        media_id = params.pop("media_id", None)
        asset = media_asset(media_id) if media_id else None
        if m.group(2) == "adimages":
            if inline_bytes:
                fpath = _asset_file(asset)
                if not fpath:
                    raise AdapterError("media %s has no local file to upload" % media_id)
                with open(fpath, "rb") as fh:
                    params["bytes"] = base64.b64encode(fh.read()).decode("ascii")
            else:
                params["bytes"] = "<base64 bytes of %s>" % media_id
            params.setdefault("name", media_id)
        else:
            src = (asset or {}).get("source_url") or ""
            if src.startswith("https://"):
                params["file_url"] = src
            else:
                params["source"] = "<multipart file %s>" % media_id
            params.setdefault("name", (asset or {}).get("title") or media_id)
    n = NODE_RE.match(path)
    if n and isinstance(params.get("targeting"), dict):
        current = _snapshot_targeting(ctx, n.group(1))
        if current is not None:
            full = {"geo_locations": current.get("geo_locations"),
                    "age_min": current.get("age_min"), "age_max": current.get("age_max")}
            ca = current.get("custom_audiences") or []
            if ca and all(str(x).isdigit() for x in ca):
                full["custom_audiences"] = [{"id": str(x)} for x in ca]
            full.update(params["targeting"])
            params["targeting"] = dict((k, v) for k, v in full.items() if v is not None)
    return params


def build_meta_request(op, ctx, cfg, secrets_visible=False, inline_bytes=False):
    # type: (Dict[str, Any], Dict[str, Any], Dict[str, Any], bool, bool) -> Dict[str, Any]
    m = cfg.get("meta") or {}
    method = str(op.get("method") or "POST").upper()
    path = normalize_path(op.get("path"))
    url = "%s/%s%s" % (ENDPOINT, m.get("api_version") or DEFAULT_VERSION, path)
    token = m.get("access_token")
    headers = {"Authorization": "Bearer %s" % (token if secrets_visible else REDACTED),
               "Content-Type": "application/x-www-form-urlencoded"}
    return {"method": method, "url": url, "headers": headers, "body": api_params(op, ctx, inline_bytes)}


def _form_encode(params):
    return dict((k, v if isinstance(v, str) else json.dumps(v)) for k, v in params.items())


def _send(req, multipart_file=None):
    import urllib.error
    import urllib.parse
    import urllib.request
    headers = dict(req["headers"])
    form = _form_encode(req["body"])
    if multipart_file:
        boundary = uuid.uuid4().hex
        chunks = []
        for k, v in form.items():
            if k == "source":
                continue
            chunks.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                           % (boundary, k, v)).encode("utf-8"))
        with open(multipart_file, "rb") as fh:
            blob = fh.read()
        chunks.append(("--%s\r\nContent-Disposition: form-data; name=\"source\"; filename=\"%s\"\r\n"
                       "Content-Type: application/octet-stream\r\n\r\n"
                       % (boundary, os.path.basename(multipart_file))).encode("utf-8") + blob + b"\r\n")
        chunks.append(("--%s--\r\n" % boundary).encode("utf-8"))
        data = b"".join(chunks)
        headers["Content-Type"] = "multipart/form-data; boundary=%s" % boundary
    else:
        data = urllib.parse.urlencode(form).encode("utf-8")
    r = urllib.request.Request(req["url"], data=data, method=req["method"], headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=300) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:2000]
        raise AdapterError("HTTP %s from Graph API: %s" % (exc.code, detail))


class LiveMetaAdapter(Adapter):
    platform = "meta"
    mode = "live"

    def build_request(self, op, ctx):
        return build_meta_request(op, ctx, self.cfg)

    def execute(self, op, ctx):
        allowed, reason = live_allowed(self.cfg, "meta")
        if not allowed:
            raise LiveRefused("live Meta send refused: %s" % reason)
        req = build_meta_request(op, ctx, self.cfg, secrets_visible=True, inline_bytes=True)
        multipart = None
        if str(req["body"].get("source", "")).startswith("<multipart file "):
            media_id = (op.get("params") or {}).get("media_id")
            multipart = _asset_file(media_asset(media_id))
            if not multipart:
                raise AdapterError("media %s has no local file to upload" % media_id)
        return _send(req, multipart)

    def execute_request(self, req, ctx):
        """Send a rendered request (planning.api_requests). It is parsed back into its op and
        rebuilt by the same builder with real secrets (and media bytes) filled in, so the
        wire request is the reviewed one plus credentials. ``execute`` keeps the live gate."""
        from planning import api_requests
        op = api_requests.to_op(api_requests.resolve(req, (ctx or {}).get("outputs") or {}))
        return self.execute(op, dict(ctx or {}, outputs={}))
