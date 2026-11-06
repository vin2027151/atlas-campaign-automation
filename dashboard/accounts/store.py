"""Secret storage, admin passphrase and data mode for Link Accounts.

Everything lives OUTSIDE the repo, in ``secrets_dir()``:
    ~/.config/atlas-dashboard/   (override with env ATLAS_SECRETS_DIR)   dir 0700
        credentials.json   per-platform fields, tokens and link status   0600
        admin.json         PBKDF2-HMAC-SHA256 hash + salt of the passphrase 0600
        settings.json      {"data_mode": "sample" | "live"}              0600

Secret values are write-only: the only reader that returns them is ``_secret()``,
used by the platform calls in accounts/platforms.py. ``public_status()`` returns
masked IDs (last 4 characters) and set / not set, never a value.
"""

import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
from typing import Any, Dict, Optional

_LOCK = threading.RLock()

# hashlib.scrypt is missing from this Python 3.9 build (LibreSSL), so PBKDF2-HMAC-SHA256
# with the OWASP 2023 iteration count. Iterations are stored per hash, so raising this later is safe.
PBKDF2_ITERS = 600000
MIN_PASSPHRASE = 12


def secrets_dir():
    # type: () -> str
    d = os.environ.get("ATLAS_SECRETS_DIR") or os.path.join(os.path.expanduser("~"), ".config", "atlas-dashboard")
    return os.path.abspath(d)


def _ensure_dir():
    # type: () -> str
    d = secrets_dir()
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def _path(name):
    # type: (str) -> str
    return os.path.join(secrets_dir(), name)


def _read(name):
    # type: (str) -> Dict[str, Any]
    p = _path(name)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(name, data):
    # type: (str, Dict[str, Any]) -> None
    """Atomic write: temp file (0600) in the same dir, fsync, rename."""
    d = _ensure_dir()
    fd, tmp = tempfile.mkstemp(prefix=".%s." % name, dir=d)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, _path(name))
        os.chmod(_path(name), 0o600)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ----------------------------------------------------------------- masking

def mask(value):
    # type: (Any) -> Optional[str]
    if value is None or value == "":
        return None
    s = str(value)
    if len(s) <= 4:
        return "•" * len(s)
    return "••••" + s[-4:]


# ------------------------------------------------------------- credentials

def _all():
    # type: () -> Dict[str, Any]
    return _read("credentials.json")


def _platform(platform):
    # type: (str) -> Dict[str, Any]
    return dict(_all().get(platform) or {})


def _secret(platform, key):
    # type: (str, str) -> Optional[str]
    """Internal reader for outbound API calls only. Never return this to a client."""
    v = (_platform(platform).get("fields") or {}).get(key)
    return v if v else None


def save_fields(platform, fields):
    # type: (str, Dict[str, str]) -> None
    """Merge fields. Empty strings are ignored (leave a field blank to keep it)."""
    with _LOCK:
        data = _all()
        rec = data.setdefault(platform, {})
        cur = rec.setdefault("fields", {})
        for k, v in fields.items():
            if isinstance(v, str) and v.strip():
                cur[k] = v.strip()
        rec["updated"] = _now()
        _write("credentials.json", data)


def set_status(platform, **kw):
    # type: (str, Any) -> None
    with _LOCK:
        data = _all()
        rec = data.setdefault(platform, {})
        rec.update(kw)
        _write("credentials.json", data)


def unlink(platform):
    # type: (str) -> None
    with _LOCK:
        data = _all()
        data.pop(platform, None)
        _write("credentials.json", data)
        if not any_tested():
            set_data_mode("sample")


def public_status(platform, field_specs):
    # type: (str, Any) -> Dict[str, Any]
    """Masked view. Secret fields: set / not set only. ID fields: last 4 characters."""
    rec = _platform(platform)
    vals = rec.get("fields") or {}
    out_fields = {}
    for f in field_specs:
        v = vals.get(f["key"])
        out_fields[f["key"]] = {"set": bool(v), "masked": (None if f.get("secret") else mask(v))}
    for k in ("access_token", "refresh_token"):
        if k not in out_fields:
            out_fields[k] = {"set": bool(vals.get(k)), "masked": None}
    linked = bool(rec.get("linked"))
    state = "error" if rec.get("error") else ("linked" if linked else "not_linked")
    return {"state": state, "linked": linked, "linked_at": rec.get("linked_at"),
            "tested_ok": bool(rec.get("tested_ok")), "tested_at": rec.get("tested_at"),
            "error": rec.get("error"), "fields": out_fields, "account_label": rec.get("account_label")}


def any_tested():
    # type: () -> bool
    return any(bool(r.get("linked") and r.get("tested_ok")) for r in _all().values() if isinstance(r, dict))


def any_linked():
    # type: () -> bool
    return any(bool(r.get("linked")) for r in _all().values() if isinstance(r, dict))


# --------------------------------------------------------------- data mode

def get_data_mode():
    # type: () -> str
    """'sample' or 'live'. 'live' only while a linked account has passed Test connection.

    This is a READ selector only. It never enables writes to ad accounts:
    env ATLAS_ALLOW_LIVE=1 (+ config mode: live) stays the only switch for that.
    """
    mode = _read("settings.json").get("data_mode")
    if mode == "live" and any_tested():
        return "live"
    return "sample"


def set_data_mode(mode):
    # type: (str) -> str
    if mode not in ("sample", "live"):
        raise ValueError("mode must be sample or live")
    if mode == "live" and not any_tested():
        raise PermissionError("Link an account to view live data")
    with _LOCK:
        s = _read("settings.json")
        s["data_mode"] = mode
        _write("settings.json", s)
    return mode


# ---------------------------------------------------------- admin passphrase

def admin_is_set():
    # type: () -> bool
    return bool(_read("admin.json").get("hash"))


def _kdf(passphrase, salt, iters):
    # type: (str, bytes, int) -> bytes
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, iters, dklen=32)


def set_admin_passphrase(passphrase):
    # type: (str) -> None
    if len(passphrase or "") < MIN_PASSPHRASE:
        raise ValueError("passphrase must be at least %d characters" % MIN_PASSPHRASE)
    salt = secrets.token_bytes(16)
    rec = {"kdf": "pbkdf2-sha256", "iterations": PBKDF2_ITERS, "salt": salt.hex(),
           "hash": _kdf(passphrase, salt, PBKDF2_ITERS).hex(), "set_at": _now()}
    with _LOCK:
        _write("admin.json", rec)


def check_admin_passphrase(passphrase):
    # type: (Optional[str]) -> bool
    rec = _read("admin.json")
    if not rec.get("hash") or not passphrase:
        return False
    try:
        if rec.get("kdf") != "pbkdf2-sha256":
            return False
        got = _kdf(passphrase, bytes.fromhex(rec["salt"]), int(rec["iterations"]))
    except (KeyError, ValueError):
        return False
    return hmac.compare_digest(got.hex(), rec["hash"])


def _now():
    # type: () -> str
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
