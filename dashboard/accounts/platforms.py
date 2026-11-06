"""Per-platform requirements, fields, OAuth URLs and one read-only test call.

Research and sources: docs/LINK-ACCOUNTS.md. Every call here is read-only.
Errors returned to the client go through ``_clean()`` so no secret is echoed.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from accounts import store

GOOGLE_VERSION = "v26"
META_VERSION = "v27.0"
LINKEDIN_VERSION = "202610"
X_VERSION = "12"
TIKTOK_VERSION = "v1.3"


def F(key, label, secret=False, hint=""):
    return {"key": key, "label": label, "secret": secret, "hint": hint}


PLATFORMS = [
    {
        "id": "google", "name": "Google Ads", "oauth": True, "built": True,
        "docs": "https://developers.google.com/google-ads/api/docs/api-policy/developer-token",
        "requirements": [
            "Google Cloud project with the Google Ads API enabled (no developer token: sunset 2026-09-09; existing tokens are ignored).",
            "API access level on that Cloud project: Test (test accounts only) by default; apply for Explorer, Basic or Standard in Cloud Console to reach a production account. Brand verification for Basic/Standard.",
            "OAuth client ID of type Web application (client ID + client secret).",
            "Authorized redirect URI: the exact callback below (HTTPS, no wildcards, exact match).",
            "OAuth scope https://www.googleapis.com/auth/adwords; consent with access_type=offline, prompt=consent to get a refresh token.",
            "Access tokens last about 1 hour and refresh from the refresh token; refresh tokens last until revoked (7 days if the consent screen is still in Testing status).",
            "Customer ID: 10 digits, no dashes. Manager (MCC) login-customer-id only when access goes through a manager account.",
        ],
        "fields": [F("client_id", "OAuth client ID", hint="…apps.googleusercontent.com"),
                   F("client_secret", "OAuth client secret", True),
                   F("customer_id", "Customer ID", hint="10 digits, no dashes"),
                   F("login_customer_id", "Manager (MCC) ID, optional", hint="10 digits")],
        "test": "GET /%s/customers:listAccessibleCustomers" % GOOGLE_VERSION,
    },
    {
        "id": "meta", "name": "Meta Ads", "oauth": True, "built": True,
        "docs": "https://developers.facebook.com/docs/marketing-api/get-started/authorization",
        "requirements": [
            "Meta app of type Business with the Marketing API product added (App ID + App Secret).",
            "Facebook Login for Business: add the callback below to Valid OAuth Redirect URIs (HTTPS, strict mode).",
            "Permissions ads_read (test connection) and ads_management (changes); standard access is enough for your own ad accounts, advanced access via App Review for others'.",
            "Marketing API access tier: Limited (development) by default; Full needs 500+ calls in 15 days with under 15% errors.",
            "Business verification if the app touches sensitive data.",
            "User tokens: short-lived (hours), exchanged server-side for a long-lived ~60-day token. For unattended use, a System User token from Business Settings does not expire.",
            "Ad account ID: act_ followed by digits. Graph API %s." % META_VERSION,
        ],
        "fields": [F("app_id", "App ID", hint="digits"),
                   F("app_secret", "App secret", True),
                   F("ad_account_id", "Ad account ID", hint="act_1234567890"),
                   F("access_token", "System user token (optional, instead of Connect)", True)],
        "test": "GET /%s/{ad_account_id}?fields=name,account_status" % META_VERSION,
    },
    {
        "id": "linkedin", "name": "LinkedIn Ads", "oauth": True, "built": True,
        "docs": "https://learn.microsoft.com/en-us/linkedin/marketing/getting-started",
        "requirements": [
            "LinkedIn developer app tied to a Company Page, with the Advertising API product approved (Development tier: up to 5 ad accounts, added in the app's Products tab; Standard tier by application).",
            "Client ID + client secret from the app's Auth tab; add the callback below as an authorized redirect URL (absolute HTTPS, no #).",
            "3-legged OAuth only. Scopes r_ads and r_ads_reporting (read), rw_ads (changes). The member needs an ad account role (VIEWER or higher).",
            "Access tokens last 60 days; programmatic refresh tokens (365 days) only for approved partners, otherwise re-run Connect.",
            "Ad account ID: digits (URN urn:li:sponsoredAccount:{id}). Versioned API header LinkedIn-Version: %s." % LINKEDIN_VERSION,
        ],
        "fields": [F("client_id", "Client ID"), F("client_secret", "Client secret", True),
                   F("ad_account_id", "Ad account ID", hint="digits")],
        "test": "GET /rest/adAccounts/{id}",
    },
    {
        "id": "tiktok", "name": "TikTok Ads", "oauth": True, "built": True,
        "docs": "https://business-api.tiktok.com/portal/docs/obtain-a-long-term-access-token/v1.3",
        "requirements": [
            "TikTok for Business developer account and an app approved in the Marketing API portal (App ID + Secret), with the Ad Account Management / Reporting scopes ticked.",
            "Advertiser redirect URL set on the app: the callback below.",
            "The advertiser authorizes in the browser; the auth_code is valid 1 hour, single use, and is exchanged for a long-term access token.",
            "Long-term tokens do not expire; they stop working if the advertiser revokes authorization.",
            "Advertiser ID: digits (returned by the token exchange and by /oauth2/advertiser/get/).",
        ],
        "fields": [F("app_id", "App ID"), F("secret", "App secret", True),
                   F("advertiser_id", "Advertiser ID", hint="digits")],
        "test": "GET /open_api/%s/oauth2/advertiser/get/" % TIKTOK_VERSION,
    },
    {
        "id": "x", "name": "X Ads", "oauth": False, "built": False,
        "docs": "https://docs.x.com/x-ads-api/getting-started/step-by-step-guide",
        "requirements": [
            "Approved X developer account and a developer app, plus an Ads API access request approved for that app.",
            "API key + API key secret (consumer key/secret) for the app.",
            "User access token + access token secret for a user with access to the ads account (3-legged or PIN-based OAuth 1.0a). These tokens do not expire until revoked.",
            "Every request is OAuth 1.0a signed (HMAC-SHA1) to ads-api.x.com.",
            "Ads account ID: short alphanumeric (e.g. 18ce54d4x5t).",
        ],
        "fields": [F("consumer_key", "API key"), F("consumer_secret", "API key secret", True),
                   F("access_token", "Access token", True), F("access_token_secret", "Access token secret", True),
                   F("account_id", "Ads account ID")],
        "test": "GET /%s/accounts" % X_VERSION,
    },
]
BY_ID = dict((p["id"], p) for p in PLATFORMS)


class LinkError(Exception):
    """Message is safe to show (secrets stripped)."""


def _clean(msg, platform):
    # type: (str, str) -> str
    msg = str(msg)[:300]
    for k in [f["key"] for f in BY_ID[platform]["fields"]] + ["access_token", "refresh_token"]:
        v = store._secret(platform, k)
        if v and len(v) >= 6:
            msg = msg.replace(v, "‹redacted›")
    return msg


def _http(method, url, headers=None, form=None, body=None, timeout=20):
    # type: (str, str, Optional[Dict[str, str]], Optional[Dict[str, str]], Any, int) -> Dict[str, Any]
    data = None
    headers = dict(headers or {})
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            j = json.loads(raw)
            err = j.get("error")
            if isinstance(err, dict):
                err = err.get("message") or err.get("status")
            msg = err or j.get("message") or j.get("error_description") or raw
        except ValueError:
            msg = raw
        raise LinkError("HTTP %s: %s" % (e.code, str(msg)[:200]))
    except (urllib.error.URLError, OSError) as e:
        raise LinkError("network error: %s" % getattr(e, "reason", e))
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        raise LinkError("non-JSON response")


def _need(platform, *keys):
    vals = []
    for k in keys:
        v = store._secret(platform, k)
        if not v:
            label = [f["label"] for f in BY_ID[platform]["fields"] if f["key"] == k]
            raise LinkError("%s is not set" % (label[0] if label else k))
        if "EXAMPLE" in v:
            raise LinkError("%s is an EXAMPLE value" % k)
        vals.append(v)
    return vals


# ------------------------------------------------------------------- OAuth

def authorize_url(platform, redirect_uri, state):
    # type: (str, str, str) -> str
    q = urllib.parse.urlencode
    if platform == "google":
        (cid,) = _need("google", "client_id")
        return "https://accounts.google.com/o/oauth2/v2/auth?" + q({
            "client_id": cid, "redirect_uri": redirect_uri, "response_type": "code",
            "scope": "https://www.googleapis.com/auth/adwords", "access_type": "offline",
            "prompt": "consent", "include_granted_scopes": "true", "state": state})
    if platform == "meta":
        (aid,) = _need("meta", "app_id")
        return "https://www.facebook.com/%s/dialog/oauth?" % META_VERSION + q({
            "client_id": aid, "redirect_uri": redirect_uri, "state": state,
            "scope": "ads_read,ads_management,business_management", "response_type": "code"})
    if platform == "linkedin":
        (cid,) = _need("linkedin", "client_id")
        return "https://www.linkedin.com/oauth/v2/authorization?" + q({
            "response_type": "code", "client_id": cid, "redirect_uri": redirect_uri,
            "state": state, "scope": "r_ads r_ads_reporting"})
    if platform == "tiktok":
        (aid,) = _need("tiktok", "app_id")
        return "https://business-api.tiktok.com/portal/auth?" + q({
            "app_id": aid, "state": state, "redirect_uri": redirect_uri})
    raise LinkError("OAuth is not built for this platform")


def exchange_code(platform, code, redirect_uri):
    # type: (str, str, str) -> None
    """Swap the auth code for tokens and store them. Nothing is returned."""
    now = store._now()
    if platform == "google":
        cid, sec = _need("google", "client_id", "client_secret")
        r = _http("POST", "https://oauth2.googleapis.com/token", form={
            "code": code, "client_id": cid, "client_secret": sec, "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"})
        if not r.get("refresh_token"):
            raise LinkError("Google returned no refresh token; remove the app's access at myaccount.google.com/permissions and Connect again")
        store.save_fields("google", {"refresh_token": r["refresh_token"]})
    elif platform == "meta":
        aid, sec = _need("meta", "app_id", "app_secret")
        base = "https://graph.facebook.com/%s/oauth/access_token?" % META_VERSION
        r = _http("GET", base + urllib.parse.urlencode({
            "client_id": aid, "client_secret": sec, "redirect_uri": redirect_uri, "code": code}))
        short = r.get("access_token")
        if not short:
            raise LinkError("Meta returned no access token")
        r2 = _http("GET", base + urllib.parse.urlencode({
            "grant_type": "fb_exchange_token", "client_id": aid, "client_secret": sec, "fb_exchange_token": short}))
        store.save_fields("meta", {"access_token": r2.get("access_token") or short})
        if r2.get("expires_in"):
            store.set_status("meta", token_expires=int(time.time()) + int(r2["expires_in"]))
    elif platform == "linkedin":
        cid, sec = _need("linkedin", "client_id", "client_secret")
        r = _http("POST", "https://www.linkedin.com/oauth/v2/accessToken", form={
            "grant_type": "authorization_code", "code": code, "client_id": cid,
            "client_secret": sec, "redirect_uri": redirect_uri})
        if not r.get("access_token"):
            raise LinkError("LinkedIn returned no access token")
        store.save_fields("linkedin", {"access_token": r["access_token"], "refresh_token": r.get("refresh_token") or ""})
        store.set_status("linkedin", token_expires=int(time.time()) + int(r.get("expires_in") or 0))
    elif platform == "tiktok":
        aid, sec = _need("tiktok", "app_id", "secret")
        r = _http("POST", "https://business-api.tiktok.com/open_api/%s/oauth2/access_token/" % TIKTOK_VERSION,
                  body={"app_id": aid, "secret": sec, "auth_code": code})
        d = r.get("data") or {}
        if r.get("code") not in (0, None) or not d.get("access_token"):
            raise LinkError("TikTok: %s" % (r.get("message") or "no access token"))
        store.save_fields("tiktok", {"access_token": d["access_token"]})
        ids = d.get("advertiser_ids") or []
        if ids and not store._secret("tiktok", "advertiser_id"):
            store.save_fields("tiktok", {"advertiser_id": str(ids[0])})
    else:
        raise LinkError("OAuth is not built for this platform")
    store.set_status(platform, linked=True, linked_at=now, error=None, tested_ok=False)


def has_token(platform):
    # type: (str) -> bool
    key = {"google": "refresh_token", "x": "access_token_secret"}.get(platform, "access_token")
    return bool(store._secret(platform, key))


# --------------------------------------------------------------- test call

def test_connection(platform):
    # type: (str) -> str
    """One read-only call. Returns a short safe label (account name). Raises LinkError."""
    try:
        return _test(platform)
    except LinkError as e:
        raise LinkError(_clean(str(e), platform))


def _test(platform):
    # type: (str) -> str
    if platform == "google":
        cid, sec, rt = _need("google", "client_id", "client_secret", "refresh_token")
        tok = _http("POST", "https://oauth2.googleapis.com/token", form={
            "client_id": cid, "client_secret": sec, "refresh_token": rt, "grant_type": "refresh_token"})
        if not tok.get("access_token"):
            raise LinkError("token refresh returned no access token")
        r = _http("GET", "https://googleads.googleapis.com/%s/customers:listAccessibleCustomers" % GOOGLE_VERSION,
                  headers={"Authorization": "Bearer " + tok["access_token"]})
        names = r.get("resourceNames") or []
        want = (store._secret("google", "customer_id") or "").replace("-", "")
        if want and ("customers/" + want) not in names:
            raise LinkError("customer %s is not accessible to this Google user (%d accessible)" % (store.mask(want), len(names)))
        return "%d accessible customer(s)" % len(names)
    if platform == "meta":
        tok, acct = _need("meta", "access_token", "ad_account_id")
        if not acct.startswith("act_"):
            acct = "act_" + acct
        r = _http("GET", "https://graph.facebook.com/%s/%s?fields=name,account_status" % (META_VERSION, acct),
                  headers={"Authorization": "Bearer " + tok})
        return "%s (status %s)" % (r.get("name") or "ad account", r.get("account_status"))
    if platform == "linkedin":
        tok, acct = _need("linkedin", "access_token", "ad_account_id")
        r = _http("GET", "https://api.linkedin.com/rest/adAccounts/%s" % urllib.parse.quote(acct), headers={
            "Authorization": "Bearer " + tok, "LinkedIn-Version": LINKEDIN_VERSION,
            "X-Restli-Protocol-Version": "2.0.0"})
        return "%s (%s)" % (r.get("name") or "ad account", r.get("status") or "?")
    if platform == "tiktok":
        aid, sec, tok = _need("tiktok", "app_id", "secret", "access_token")
        r = _http("GET", "https://business-api.tiktok.com/open_api/%s/oauth2/advertiser/get/?" % TIKTOK_VERSION +
                  urllib.parse.urlencode({"app_id": aid, "secret": sec}), headers={"Access-Token": tok})
        if r.get("code") not in (0, None):
            raise LinkError("TikTok: %s" % r.get("message"))
        n = len(((r.get("data") or {}).get("list")) or [])
        return "%d authorized advertiser(s)" % n
    if platform == "x":
        ck, cs, at, ats = _need("x", "consumer_key", "consumer_secret", "access_token", "access_token_secret")
        url = "https://ads-api.x.com/%s/accounts" % X_VERSION
        r = _http("GET", url, headers={"Authorization": oauth1_header("GET", url, {}, ck, cs, at, ats)})
        return "%d ads account(s)" % len(r.get("data") or [])
    raise LinkError("unknown platform")


def oauth1_header(method, url, params, ck, cs, at, ats, nonce=None, ts=None):
    # type: (str, str, Dict[str, str], str, str, str, str, Optional[str], Optional[str]) -> str
    """OAuth 1.0a HMAC-SHA1 Authorization header (RFC 5849)."""
    enc = lambda s: urllib.parse.quote(str(s), safe="~")
    oauth = {"oauth_consumer_key": ck, "oauth_nonce": nonce or secrets.token_hex(16),
             "oauth_signature_method": "HMAC-SHA1", "oauth_timestamp": ts or str(int(time.time())),
             "oauth_token": at, "oauth_version": "1.0"}
    allp = dict(params)
    allp.update(oauth)
    pstr = "&".join("%s=%s" % (enc(k), enc(v)) for k, v in sorted(allp.items()))
    base = "&".join([method.upper(), enc(url), enc(pstr)])
    key = "%s&%s" % (enc(cs), enc(ats))
    oauth["oauth_signature"] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join('%s="%s"' % (enc(k), enc(v)) for k, v in sorted(oauth.items()))


def specs():
    # type: () -> List[Dict[str, Any]]
    return PLATFORMS
