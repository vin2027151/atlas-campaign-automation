"""Google Ads API (REST) adapter.

Builds the real mutate requests:

    POST https://googleads.googleapis.com/{api_version}/customers/{customer_id}/{resource}:mutate
    headers: Authorization: Bearer <OAuth access token from the refresh token>,
             developer-token, login-customer-id (MCC), Content-Type: application/json
    body:    {"operations": [{"update": {...}, "updateMask": "a,b"} | {"create": {...}} | {"remove": rn}]}

and refuses to send unless config mode == live AND env ATLAS_ALLOW_LIVE == "1" (and the
credentials are not the committed EXAMPLE values). The preview is built either way.
"""

import base64
import copy
import json
import os
from typing import Any, Dict, List

from planning.adapters import LiveRefused, live_allowed, mask
from planning.adapters.base import (Adapter, AdapterError, camelize, flatten_paths, media_asset,
                                    nest_paths, resolve_refs)

ENDPOINT = "https://googleads.googleapis.com"
TOKEN_URL = "https://oauth2.googleapis.com/token"

SERVICE_RESOURCE = {
    "CampaignService": ("mutateCampaigns", "campaigns"),
    "CampaignBudgetService": ("mutateCampaignBudgets", "campaignBudgets"),
    "AdGroupService": ("mutateAdGroups", "adGroups"),
    "AdGroupAdService": ("mutateAdGroupAds", "adGroupAds"),
    "AdGroupCriterionService": ("mutateAdGroupCriteria", "adGroupCriteria"),
    "CampaignCriterionService": ("mutateCampaignCriteria", "campaignCriteria"),
    "AssetService": ("mutateAssets", "assets"),
}


def normalize_fields(op):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    """Op fields as nested snake_case dicts, with RSA text lists as [{"text": ...}] and
    image assets as {"name", "type": "IMAGE", "image_asset": {"media_id"}}."""
    fields = nest_paths(copy.deepcopy(op.get("fields") or {}))
    if op.get("service") == "AdGroupAdService" and op.get("operation") == "create":
        ad = fields.setdefault("ad", {})
        rsa = ad.get("responsive_search_ad")
        if rsa is None and "responsive_search_ad" in fields:
            rsa = ad["responsive_search_ad"] = fields.pop("responsive_search_ad")
        if "final_urls" in fields and "final_urls" not in ad:
            ad["final_urls"] = fields.pop("final_urls")
        if isinstance(rsa, dict):
            for key in ("headlines", "descriptions"):
                items = rsa.get(key) or []
                rsa[key] = [x if isinstance(x, dict) else {"text": str(x)} for x in items]
    if op.get("service") == "AssetService" and op.get("operation") == "create":
        media_id = fields.pop("media_id", None)
        img = fields.get("image_asset") or {}
        if media_id and not img.get("media_id"):
            img["media_id"] = media_id
        fields["image_asset"] = img
        fields.setdefault("type", "IMAGE")
    return fields


def update_mask(op):
    # type: (Dict[str, Any]) -> List[str]
    m = op.get("update_mask")
    if isinstance(m, str):
        m = [x.strip() for x in m.split(",") if x.strip()]
    if not m:
        m = sorted(flatten_paths(normalize_fields(op)).keys())
    return [str(x) for x in m]


def _mask_path(path):
    # type: (str) -> str
    return ".".join(_camel(p) for p in path.split("."))


def _camel(name):
    parts = name.split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


def _media_payload(fields, inline_bytes):
    # type: (Dict[str, Any], bool) -> Dict[str, Any]
    img = fields.get("image_asset") or {}
    media_id = img.get("media_id")
    if not media_id:
        return fields
    out = dict(fields)
    if inline_bytes:
        asset = media_asset(media_id)
        path = _asset_file(asset)
        if not path:
            raise AdapterError("media %s has no local file to upload" % media_id)
        with open(path, "rb") as fh:
            data = base64.b64encode(fh.read()).decode("ascii")
        out["image_asset"] = {"data": data}
    else:
        out["image_asset"] = {"data": "<base64 bytes of %s>" % media_id}
    out.setdefault("name", media_id)
    return out


def _asset_file(asset):
    if not asset:
        return None
    url = asset.get("file_url") or ""
    if url.startswith("/"):
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        path = os.path.join(base, url.lstrip("/"))
        if os.path.exists(path):
            return path
    return None


def build_google_request(op, ctx, cfg, secrets_visible=False, inline_bytes=False):
    # type: (Dict[str, Any], Dict[str, Any], Dict[str, Any], bool, bool) -> Dict[str, Any]
    """The REST request for one Google op. Headers are masked unless ``secrets_visible``."""
    g = cfg.get("google_ads") or {}
    service = op.get("service")
    if service not in SERVICE_RESOURCE:
        raise AdapterError("service not supported: %s" % service)
    _method, resource = SERVICE_RESOURCE[service]
    resolved = resolve_refs(op, (ctx or {}).get("outputs") or {})
    kind = resolved.get("operation")
    fields = normalize_fields(resolved)
    if kind == "update":
        body_op = {"update": dict([("resourceName", resolved.get("resource_name"))] +
                                  list(camelize(fields).items())),
                   "updateMask": ",".join(_mask_path(p) for p in update_mask(resolved))}
    elif kind == "create":
        if service == "AssetService":
            fields = _media_payload(fields, inline_bytes)
        body_op = {"create": camelize(fields)}
    elif kind == "remove":
        body_op = {"remove": resolved.get("resource_name")}
    else:
        raise AdapterError("operation must be update, create or remove")
    url = "%s/%s/customers/%s/%s:mutate" % (ENDPOINT, g.get("api_version", "v22"),
                                           g.get("customer_id"), resource)
    token = (ctx or {}).get("_access_token") or "<oauth access token from refresh_token>"
    headers = {
        "Authorization": "Bearer %s" % (token if secrets_visible else mask(token)),
        "developer-token": g.get("developer_token") if secrets_visible else mask(g.get("developer_token")),
        "login-customer-id": str(g.get("login_customer_id") or ""),
        "Content-Type": "application/json",
    }
    return {"method": "POST", "url": url, "headers": headers,
            "body": {"operations": [body_op], "partialFailure": False, "validateOnly": False}}


def _http_json(method, url, headers, body=None, form=None, timeout=60):
    import urllib.error
    import urllib.parse
    import urllib.request
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:2000]
        raise AdapterError("HTTP %s from %s: %s" % (exc.code, url.split("?")[0], detail))


class LiveGoogleAdapter(Adapter):
    platform = "google"
    mode = "live"

    def build_request(self, op, ctx):
        return build_google_request(op, ctx, self.cfg)

    def _access_token(self):
        g = self.cfg.get("google_ads") or {}
        res = _http_json("POST", TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, form={
            "client_id": g.get("client_id"), "client_secret": g.get("client_secret"),
            "refresh_token": g.get("refresh_token"), "grant_type": "refresh_token"})
        if not res.get("access_token"):
            raise AdapterError("OAuth token exchange returned no access_token")
        return res["access_token"]

    def execute(self, op, ctx):
        allowed, reason = live_allowed(self.cfg, "google")
        if not allowed:
            raise LiveRefused("live Google Ads send refused: %s" % reason)
        ctx = dict(ctx or {})
        ctx["_access_token"] = self._access_token()
        req = build_google_request(op, ctx, self.cfg, secrets_visible=True, inline_bytes=True)
        return _http_json(req["method"], req["url"], req["headers"], body=req["body"])
