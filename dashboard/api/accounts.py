"""Link Accounts API.

Read side (no passphrase): GET /api/accounts/ -> requirements + masked status.
Write side (header X-Admin-Key): save, OAuth start, test, unlink, data mode.
No response, log line or error message ever contains a secret value.
"""

import logging
import os
import secrets
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse, RedirectResponse

from accounts import platforms as P
from accounts import store as S

router = APIRouter()
log = logging.getLogger("atlas.accounts")

STATE_TTL = 600            # OAuth state lifetime, seconds
FAIL_LIMIT = 5             # failed passphrase attempts per IP ...
FAIL_WINDOW = 900          # ... per 15 minutes
COOKIE = "atlas_oauth_sid"

_lock = threading.Lock()
_fails = {}   # type: Dict[str, List[float]]
_states = {}  # type: Dict[str, Dict[str, Any]]


class Denied(Exception):
    def __init__(self, status, msg):
        Exception.__init__(self, msg)
        self.status = status


def client_ip(request):
    # type: (Request) -> str
    return (request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "") or "?").strip()


def _require_admin(request):
    # type: (Request) -> None
    if not S.admin_is_set():
        raise Denied(403, "Read-only: no admin passphrase is set. On the server run: .venv/bin/python -m accounts.set_admin_key")
    ip = client_ip(request)
    now = time.time()
    with _lock:
        recent = [t for t in _fails.get(ip, []) if now - t < FAIL_WINDOW]
        _fails[ip] = recent
        if len(recent) >= FAIL_LIMIT:
            raise Denied(429, "Too many wrong passphrases from this address. Try again in 15 minutes.")
    if not S.check_admin_passphrase(request.headers.get("x-admin-key")):
        with _lock:
            _fails.setdefault(ip, []).append(now)
        log.warning("accounts: wrong admin passphrase from %s", ip)
        raise Denied(401, "Wrong admin passphrase")
    with _lock:
        _fails.pop(ip, None)


def _guard(request, fn):
    try:
        _require_admin(request)
        return fn()
    except Denied as e:
        return JSONResponse({"ok": False, "error": str(e), "auth": True}, status_code=e.status)
    except P.LinkError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    except (ValueError, PermissionError) as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


def _spec(platform):
    # type: (str) -> Dict[str, Any]
    if platform not in P.BY_ID:
        raise P.LinkError("unknown platform")
    return P.BY_ID[platform]


def public_base(request):
    # type: (Request) -> str
    env = os.environ.get("ATLAS_PUBLIC_URL")
    if env:
        return env.rstrip("/")
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return "%s://%s" % (proto.split(",")[0].strip(), host)


def redirect_uri(request, platform):
    # type: (Request, str) -> str
    return "%s/link-accounts/callback/%s" % (public_base(request), platform)


def overview(request):
    # type: (Request) -> Dict[str, Any]
    out = []
    for p in P.specs():
        out.append({"id": p["id"], "name": p["name"], "oauth": p["oauth"], "built": p["built"],
                    "docs": p["docs"], "requirements": p["requirements"], "test_call": p["test"],
                    "fields": [{"key": f["key"], "label": f["label"], "secret": f["secret"], "hint": f["hint"]}
                               for f in p["fields"]],
                    "redirect_uri": redirect_uri(request, p["id"]) if p["oauth"] else None,
                    "status": S.public_status(p["id"], p["fields"])})
    return {"ok": True, "admin_set": S.admin_is_set(), "data_mode": S.get_data_mode(),
            "live_available": S.any_tested(), "secrets_dir": S.secrets_dir(), "platforms": out,
            "writes_note": "Live data is read-only. Writes to ad accounts stay off unless env ATLAS_ALLOW_LIVE=1 is set on the server."}


@router.get("/api/accounts/")
def accounts_list(request: Request):
    return overview(request)


@router.post("/api/accounts/verify")
def accounts_verify(request: Request):
    return _guard(request, lambda: {"ok": True})


@router.post("/api/accounts/mode")
def accounts_mode(request: Request, payload: Dict[str, Any] = Body(...)):
    def run():
        mode = S.set_data_mode(str(payload.get("mode") or ""))
        return {"ok": True, "data_mode": mode}
    return _guard(request, run)


@router.post("/api/accounts/{platform}/save")
def accounts_save(platform: str, request: Request, payload: Dict[str, Any] = Body(...)):
    def run():
        spec = _spec(platform)
        allowed = set(f["key"] for f in spec["fields"])
        raw = payload.get("fields") or {}
        fields = dict((k, str(v)) for k, v in raw.items() if k in allowed and isinstance(v, (str, int)))
        for k, v in fields.items():
            if "EXAMPLE" in v:
                raise P.LinkError("%s looks like an EXAMPLE value" % k)
        S.save_fields(platform, fields)
        if P.has_token(platform):
            rec = S._platform(platform)
            S.set_status(platform, linked=True, linked_at=rec.get("linked_at") or S._now(), tested_ok=False, error=None)
        return {"ok": True, "status": S.public_status(platform, spec["fields"])}
    return _guard(request, run)


@router.post("/api/accounts/{platform}/oauth/start")
def accounts_oauth_start(platform: str, request: Request):
    holder = {}

    def run():
        spec = _spec(platform)
        if not spec["oauth"]:
            raise P.LinkError("Connect is not built for %s; enter tokens instead" % spec["name"])
        sid = request.cookies.get(COOKIE) or secrets.token_urlsafe(24)
        state = secrets.token_urlsafe(24)
        now = time.time()
        with _lock:
            for k in [k for k, v in _states.items() if v["exp"] < now]:
                _states.pop(k, None)
            _states[state] = {"platform": platform, "sid": sid, "exp": now + STATE_TTL}
        url = P.authorize_url(platform, redirect_uri(request, platform), state)
        holder["sid"] = sid
        return {"ok": True, "url": url}

    res = _guard(request, run)
    if isinstance(res, dict):
        resp = JSONResponse(res)
        resp.set_cookie(COOKIE, holder["sid"], max_age=STATE_TTL, httponly=True, samesite="lax",
                        secure=public_base(request).startswith("https://"), path="/link-accounts")
        return resp
    return res


def check_state(state, sid, platform):
    # type: (Optional[str], Optional[str], str) -> bool
    """One-time use; must match the browser session cookie, platform and expiry."""
    if not state or not sid:
        return False
    with _lock:
        rec = _states.pop(state, None)
    return bool(rec and rec["platform"] == platform and rec["exp"] >= time.time()
                and secrets.compare_digest(rec["sid"], sid))


@router.get("/link-accounts/callback/{platform}", include_in_schema=False)
def accounts_callback(platform: str, request: Request):
    q = request.query_params
    back = "/link-accounts"
    if platform not in P.BY_ID:
        return RedirectResponse(back + "?error=unknown+platform", status_code=303)
    if not check_state(q.get("state"), request.cookies.get(COOKIE), platform):
        return RedirectResponse(back + "?platform=%s&error=state" % platform, status_code=303)
    if q.get("error"):
        return RedirectResponse(back + "?platform=%s&error=denied" % platform, status_code=303)
    code = q.get("code") or q.get("auth_code")
    if not code:
        return RedirectResponse(back + "?platform=%s&error=nocode" % platform, status_code=303)
    try:
        P.exchange_code(platform, code, redirect_uri(request, platform))
    except P.LinkError as e:
        S.set_status(platform, error=P._clean(str(e), platform))
        return RedirectResponse(back + "?platform=%s&error=exchange" % platform, status_code=303)
    resp = RedirectResponse(back + "?platform=%s&linked=1" % platform, status_code=303)
    resp.delete_cookie(COOKIE, path="/link-accounts")
    return resp


@router.post("/api/accounts/{platform}/test")
def accounts_test(platform: str, request: Request):
    def run():
        spec = _spec(platform)
        try:
            label = P.test_connection(platform)
        except P.LinkError as e:
            S.set_status(platform, tested_ok=False, tested_at=S._now(), error=str(e))
            return JSONResponse({"ok": False, "error": str(e), "status": S.public_status(platform, spec["fields"])},
                                status_code=400)
        S.set_status(platform, tested_ok=True, tested_at=S._now(), error=None, account_label=label[:120],
                     linked=True, linked_at=S._platform(platform).get("linked_at") or S._now())
        return {"ok": True, "result": label, "status": S.public_status(platform, spec["fields"])}
    return _guard(request, run)


@router.post("/api/accounts/{platform}/unlink")
def accounts_unlink(platform: str, request: Request):
    def run():
        spec = _spec(platform)
        S.unlink(platform)
        return {"ok": True, "status": S.public_status(platform, spec["fields"]), "data_mode": S.get_data_mode()}
    return _guard(request, run)
