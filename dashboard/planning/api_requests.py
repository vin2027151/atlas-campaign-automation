"""Operations -> the exact HTTP requests that carry them out, and back.

Every account write (a Plan & Adapt changeset or a Campaigns-page control) is rendered
here as the real Google Ads REST / Meta Graph API request: method, full URL, headers with
secrets redacted, and the JSON (Google) or form (Meta) body. That rendered request is
what the reviewer sees and what publish runs: the sample adapter applies the request
itself to the sample account (``to_op`` parses it back), a live adapter sends it.

    render(op, ctx=None, cfg=None, step=None) -> request
    render_all(doc, snapshot=None, cfg=None) -> [request]        # one per op, in run order
    resolve(request, outputs) -> request                         # "$ref:opN.field" filled in
    to_op(request) -> op                                         # inverse of render
    same_call(a, b) -> bool                                      # method, url and body equal
    curl(request) -> str                                         # copy-paste curl, secrets as env vars
    log_line(request) -> str                                     # METHOD URL body, for the activity log

request = {"step", "op", "platform", "method", "url", "headers", "content_type",
           "body", "depends_on": [ref], "reason", "curl"}

Deterministic. Never imports planning.llm, planning.llm_worker, planning.prompts or anthropic.
"""

import copy
import json
import re
from typing import Any, Dict, List, Optional

from planning import adapters
from planning.adapters.base import REF_RE, AdapterError, resolve_refs
from planning.adapters.live_google import (ENDPOINT as GOOGLE_ENDPOINT, RESOURCE_SERVICE, SERVICE_RESOURCE,
                                           build_google_request)
from planning.adapters.live_meta import ENDPOINT as META_ENDPOINT, build_meta_request

GOOGLE_URL_RE = re.compile(r"^%s/(v\d+(?:_\d+)?)/customers/(\d+)/([A-Za-z]+):mutate$" % re.escape(GOOGLE_ENDPOINT))
META_URL_RE = re.compile(r"^%s/(v\d+\.\d+)(/[^?#]*)$" % re.escape(META_ENDPOINT))
MEDIA_PLACEHOLDER_RE = re.compile(r"^<(?:base64 bytes|multipart file) of ([A-Z0-9]+-\d+)>$")
FORM = "application/x-www-form-urlencoded"
JSON_CT = "application/json"
CURL_SECRETS = {"google": "${GOOGLE_ADS_ACCESS_TOKEN}", "meta": "${META_ACCESS_TOKEN}"}
DEV_TOKEN_VAR = "${GOOGLE_ADS_DEVELOPER_TOKEN}"


# ----------------------------------------------------------------- helpers

def _refs_in(obj, found=None):
    # type: (Any, Optional[List[str]]) -> List[str]
    found = [] if found is None else found
    if isinstance(obj, dict):
        for v in obj.values():
            _refs_in(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _refs_in(v, found)
    elif isinstance(obj, str):
        m = REF_RE.match(obj.strip())
        if m and m.group(1) not in found:
            found.append(m.group(1))
    return found


def _camel_to_snake(name):
    # type: (str) -> str
    return re.sub(r"(?<=[a-z0-9])([A-Z])", lambda m: "_" + m.group(1).lower(), name)


def snakeize(obj):
    # type: (Any) -> Any
    """Recursively convert dict keys from lowerCamelCase (REST JSON) back to snake_case."""
    if isinstance(obj, dict):
        return dict((_camel_to_snake(str(k)), snakeize(v)) for k, v in obj.items())
    if isinstance(obj, list):
        return [snakeize(v) for v in obj]
    return obj


def _media_from_placeholder(v):
    # type: (Any) -> Optional[str]
    m = MEDIA_PLACEHOLDER_RE.match(str(v or ""))
    return m.group(1) if m else None


# ------------------------------------------------------------------ render

def render(op, ctx=None, cfg=None, step=None):
    # type: (Dict[str, Any], Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[int]) -> Dict[str, Any]
    """The exact request for one op. Secrets are redacted; "$ref:" values stay as text
    unless ``ctx["outputs"]`` already holds what they point to."""
    cfg = cfg or adapters.load_config()
    ctx = ctx or {"mode": cfg["mode"], "config": cfg, "snapshot": None, "outputs": {}}
    platform = op.get("platform")
    if platform == "google":
        req = build_google_request(op, ctx, cfg)
        ctype = JSON_CT
    elif platform == "meta":
        req = build_meta_request(op, ctx, cfg)
        ctype = FORM
    else:
        raise AdapterError("platform must be google or meta")
    out = {"step": step, "op": op.get("ref"), "platform": platform, "method": req["method"], "url": req["url"],
           "headers": req["headers"], "content_type": ctype, "body": req["body"],
           "depends_on": _refs_in(req["body"]), "reason": op.get("reason") or ""}
    out["curl"] = curl(out)
    return out


def render_all(doc, snap=None, cfg=None):
    # type: (Dict[str, Any], Optional[Dict[str, Any]], Optional[Dict[str, Any]]) -> List[Dict[str, Any]]
    """One rendered request per operation, numbered in run order. A failing op renders
    as ``{"step", "op", "platform", "error"}``."""
    cfg = cfg or adapters.load_config()
    ctx = {"mode": cfg["mode"], "config": cfg, "snapshot": snap, "outputs": {}}
    out = []
    for i, op in enumerate((doc or {}).get("operations") or []):
        if not isinstance(op, dict):
            continue
        try:
            out.append(render(op, ctx, cfg, step=i + 1))
        except Exception as exc:
            out.append({"step": i + 1, "op": op.get("ref"), "platform": op.get("platform"), "error": str(exc)})
    return out


def resolve(req, outputs):
    # type: (Dict[str, Any], Dict[str, Dict[str, Any]]) -> Dict[str, Any]
    """The request with every "$ref:<op>.<field>" filled from earlier responses (strict)."""
    r = copy.deepcopy(req)
    r["body"] = resolve_refs(r.get("body"), outputs or {}, strict=True)
    r["curl"] = curl(r)
    return r


def same_call(a, b):
    # type: (Dict[str, Any], Dict[str, Any]) -> bool
    """True when two rendered requests are the same call (method, URL and body)."""
    def key(r):
        return (str(r.get("method")), str(r.get("url")), json.dumps(r.get("body"), sort_keys=True))
    return key(a) == key(b)


# ------------------------------------------------------------------ inverse

def to_op(req):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    """Parse a rendered request back into the operation it carries (what the sample adapter
    applies). Raises AdapterError for anything that is not a request this module renders."""
    url = str(req.get("url") or "")
    method = str(req.get("method") or "").upper()
    body = copy.deepcopy(req.get("body") or {})
    if method != "POST":
        raise AdapterError("only POST requests are supported (got %s)" % method)
    g = GOOGLE_URL_RE.match(url)
    if g:
        resource = g.group(3)
        service = RESOURCE_SERVICE.get(resource)
        if not service:
            raise AdapterError("unsupported Google Ads resource %s" % resource)
        ops = body.get("operations") or []
        if len(ops) != 1 or not isinstance(ops[0], dict):
            raise AdapterError("expected exactly one operation in the mutate body")
        o = ops[0]
        op = {"ref": req.get("op"), "platform": "google", "service": service,
              "method": SERVICE_RESOURCE[service][0], "reason": req.get("reason") or ""}
        if "update" in o:
            upd = dict(o["update"])
            op["operation"] = "update"
            op["resource_name"] = upd.pop("resourceName", None)
            op["fields"] = snakeize(upd)
            mask = str(o.get("updateMask") or "")
            op["update_mask"] = [".".join(_camel_to_snake(p) for p in x.strip().split("."))
                                 for x in mask.split(",") if x.strip()]
        elif "create" in o:
            op["operation"] = "create"
            fields = snakeize(o["create"])
            if service == "AssetService":
                img = fields.get("image_asset") or {}
                media_id = _media_from_placeholder(img.get("data"))
                if media_id:
                    fields["image_asset"] = {"media_id": media_id}
            op["fields"] = fields
        elif "remove" in o:
            op["operation"] = "remove"
            op["resource_name"] = o["remove"]
        else:
            raise AdapterError("mutate operation needs update, create or remove")
        return op
    m = META_URL_RE.match(url)
    if m:
        path = m.group(2).rstrip("/") or "/"
        params = body
        if path.endswith("/adimages"):
            media_id = _media_from_placeholder(params.pop("bytes", None))
            if media_id:
                params["media_id"] = media_id
                if params.get("name") == media_id:
                    params.pop("name")
        elif path.endswith("/advideos"):
            media_id = _media_from_placeholder(params.pop("source", None))
            if not media_id and params.get("file_url"):
                media_id = _media_for_url(params.get("file_url"))
            params.pop("file_url", None)
            if media_id:
                params["media_id"] = media_id
        return {"ref": req.get("op"), "platform": "meta", "method": "POST", "path": path, "params": params,
                "reason": req.get("reason") or ""}
    raise AdapterError("not a Google Ads mutate or Graph API URL: %s" % url)


def _media_for_url(url):
    # type: (Any) -> Optional[str]
    try:
        import media  # lazy
        for a in media.list_assets():
            if a.get("source_url") == url:
                return a.get("id")
    except Exception:
        return None
    return None


def log_line(req, limit=900):
    # type: (Dict[str, Any], int) -> str
    """One activity-log line: METHOD URL body (compact JSON, truncated)."""
    body = json.dumps(req.get("body"), separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    if len(body) > limit:
        body = body[:limit] + "…"
    return "%s %s %s" % (req.get("method"), req.get("url"), body)


# --------------------------------------------------------------------- curl

def _sq(s):
    # type: (str) -> str
    return "'" + str(s).replace("'", "'\\''") + "'"


def curl(req):
    # type: (Dict[str, Any]) -> str
    """A copy-paste curl for the request. Secrets become shell variables
    (${GOOGLE_ADS_ACCESS_TOKEN}, ${META_ACCESS_TOKEN}), never their values."""
    if req.get("error"):
        return ""
    platform = req.get("platform")
    lines = ["curl -X %s %s" % (req.get("method") or "POST", _sq(req.get("url")))]
    for k, v in (req.get("headers") or {}).items():
        if k.lower() == "authorization":
            lines.append('-H "Authorization: Bearer %s"' % CURL_SECRETS.get(platform, "${ACCESS_TOKEN}"))
        elif k.lower() == "developer-token":
            lines.append('-H "developer-token: %s"' % DEV_TOKEN_VAR)
        elif k.lower() == "content-type" and platform == "meta":
            continue  # curl sets it for --data-urlencode
        else:
            lines.append("-H %s" % _sq("%s: %s" % (k, v)))
    body = req.get("body")
    if platform == "meta":
        for k, v in (body or {}).items():
            val = v if isinstance(v, str) else json.dumps(v, separators=(",", ":"))
            lines.append("--data-urlencode %s" % _sq("%s=%s" % (k, val)))
    elif body is not None:
        lines.append("--data %s" % _sq(json.dumps(body, indent=2)))
    return " \\\n  ".join(lines)
