"""Adapter base interface and helpers shared by the sample and live adapters.

    build_request(op, ctx) -> {"method", "url", "headers" (masked), "body"}
    execute(op, ctx) -> response dict (API-shaped)

ctx = {"mode", "config", "snapshot" (fresh pre-publish doc), "outputs": {ref: {...}}}.
``outputs`` holds what earlier ops produced (Google: resource_name/id; Meta: id/hash) and
is what ``$ref:<ref>.<field>`` resolves against.
"""

import copy
import re
from typing import Any, Dict, Optional

REF_RE = re.compile(r"^\$ref:([A-Za-z0-9_\-]+)\.([A-Za-z_]+)$")


class AdapterError(RuntimeError):
    """An operation the adapter could not apply (becomes a 'failed' result)."""


def resolve_refs(obj, outputs, strict=False):
    # type: (Any, Dict[str, Dict[str, Any]], bool) -> Any
    """Deep copy of ``obj`` with every "$ref:<ref>.<field>" string replaced from ``outputs``.

    Unresolvable refs stay as text unless ``strict``, which raises AdapterError.
    """
    if isinstance(obj, dict):
        return dict((k, resolve_refs(v, outputs, strict)) for k, v in obj.items())
    if isinstance(obj, list):
        return [resolve_refs(v, outputs, strict) for v in obj]
    if isinstance(obj, str):
        m = REF_RE.match(obj.strip())
        if m:
            ref, field = m.group(1), m.group(2)
            if ref in outputs and field in outputs[ref]:
                return outputs[ref][field]
            if strict:
                raise AdapterError("unresolved reference %s" % obj)
    return obj


def snake_to_camel(name):
    # type: (str) -> str
    parts = name.split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


def camelize(obj):
    # type: (Any) -> Any
    """Recursively convert dict keys from snake_case to lowerCamelCase (Google Ads REST JSON)."""
    if isinstance(obj, dict):
        return dict((snake_to_camel(str(k)), camelize(v)) for k, v in obj.items())
    if isinstance(obj, list):
        return [camelize(v) for v in obj]
    return obj


def flatten_paths(fields, prefix=""):
    # type: (Dict[str, Any], str) -> Dict[str, Any]
    """{"a": {"b": 1}} -> {"a.b": 1}. Lists and scalars are leaves."""
    out = {}  # type: Dict[str, Any]
    for k, v in (fields or {}).items():
        key = "%s.%s" % (prefix, k) if prefix else str(k)
        if isinstance(v, dict) and v:
            out.update(flatten_paths(v, key))
        else:
            out[key] = v
    return out


def nest_paths(fields):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    """Accept both {"target_cpa.target_cpa_micros": 1} and nested dicts; return nested."""
    out = {}  # type: Dict[str, Any]
    for k, v in (fields or {}).items():
        if isinstance(v, dict):
            v = nest_paths(v)
        parts = str(k).split(".")
        cur = out
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        if isinstance(v, dict) and isinstance(cur.get(parts[-1]), dict):
            cur[parts[-1]].update(v)
        else:
            cur[parts[-1]] = v
    return out


def outputs_from_response(op, response):
    # type: (Dict[str, Any], Dict[str, Any]) -> Dict[str, Any]
    """What a later op can reference via $ref: Google {resource_name, id}; Meta {id} or {hash}."""
    out = {}  # type: Dict[str, Any]
    if not isinstance(response, dict):
        return out
    if op.get("platform") == "google":
        results = response.get("results") or []
        if results and results[0].get("resourceName"):
            rn = results[0]["resourceName"]
            out["resource_name"] = rn
            out["id"] = rn.rsplit("/", 1)[-1]
        return out
    if "images" in response and isinstance(response["images"], dict):
        for _name, info in response["images"].items():
            if isinstance(info, dict) and info.get("hash"):
                out["hash"] = info["hash"]
                out["id"] = info.get("id") or info["hash"]
                break
    if response.get("id") is not None:
        out["id"] = str(response["id"])
    return out


class Adapter(object):
    """Base interface. Subclasses set ``platform`` and ``mode``."""

    platform = ""  # type: str
    mode = "sample"  # type: str

    def __init__(self, cfg):
        # type: (Dict[str, Any]) -> None
        self.cfg = copy.deepcopy(cfg)

    def build_request(self, op, ctx):
        # type: (Dict[str, Any], Dict[str, Any]) -> Dict[str, Any]
        raise NotImplementedError

    def execute(self, op, ctx):
        # type: (Dict[str, Any], Dict[str, Any]) -> Dict[str, Any]
        raise NotImplementedError


def media_asset(media_id):
    # type: (Any) -> Optional[Dict[str, Any]]
    """Look up a Media library asset; None if the library is not importable or the id is unknown."""
    try:
        import media  # lazy: written by the media agent, may not exist yet
    except Exception:
        return None
    try:
        return media.get_asset(media_id)
    except Exception:
        return None


def mark_media_published(media_id, platform, ref):
    # type: (Any, str, Dict[str, Any]) -> Optional[str]
    """Record a platform reference on a Media asset. Returns an error message or None."""
    try:
        import media
        media.mark_published(media_id, platform, ref)
        return None
    except Exception as exc:  # never fail a publish over bookkeeping
        return "media.mark_published failed: %s" % exc
