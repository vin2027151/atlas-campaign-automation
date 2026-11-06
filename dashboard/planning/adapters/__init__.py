"""Platform adapters: the only code that turns a changeset operation into an API call.

    load_config() -> dict            # config/platforms.yaml
    config_public() -> dict          # same, every secret masked to 4 chars + "…"
    mode() -> "sample" | "live"
    live_allowed() -> (bool, reason)
    get_adapter(platform) -> Adapter # sample adapter, or live_google / live_meta in live mode

Never imports planning.llm, planning.llm_worker, planning.prompts or anthropic.
"""

import copy
import os
from typing import Any, Dict, Tuple

import yaml

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "platforms.yaml")

PLATFORMS = ("google", "meta")
SECRET_KEYS = ("developer_token", "client_id", "client_secret", "refresh_token",
               "app_secret", "access_token")

DEFAULT_CONFIG = {
    "mode": "sample",
    "google_ads": {"api_version": "v26", "send_developer_token": False, "customer_id": "4445556666", "login_customer_id": "1112223333"},
    "meta": {"api_version": "v27.0", "ad_account_id": "act_7778889999", "page_id": "123456789012345"},
}  # type: Dict[str, Any]


class LiveRefused(RuntimeError):
    """Raised when a live adapter is asked to send but live sending is not allowed."""


def load_config():
    # type: () -> Dict[str, Any]
    """Read config/platforms.yaml (falls back to DEFAULT_CONFIG if the file is missing)."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        for k, v in raw.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    cfg["mode"] = str(cfg.get("mode") or "sample").strip().lower()
    if cfg["mode"] not in ("sample", "live"):
        cfg["mode"] = "sample"
    return cfg


def mask(value):
    # type: (Any) -> Any
    """Mask a secret to its first 4 characters + "…"."""
    if value is None or value == "":
        return value
    s = str(value)
    return s[:4] + "…"


def config_public():
    # type: () -> Dict[str, Any]
    """The config with every secret masked (safe for the UI and for prompts)."""
    cfg = load_config()
    for section in ("google_ads", "meta"):
        sec = cfg.get(section) or {}
        for k in list(sec.keys()):
            if k in SECRET_KEYS:
                sec[k] = mask(sec[k])
    allowed, reason = live_allowed(cfg)
    cfg["live_allowed"] = allowed
    cfg["live_reason"] = reason
    return cfg


def mode(cfg=None):
    # type: (Any) -> str
    return (cfg or load_config())["mode"]


def _has_example_values(cfg, section):
    # type: (Dict[str, Any], str) -> bool
    sec = cfg.get(section) or {}
    for k in SECRET_KEYS:
        v = sec.get(k)
        if v is not None and "example" in str(v).lower():
            return True
    return False


def live_allowed(cfg=None, platform=None):
    # type: (Any, Any) -> Tuple[bool, str]
    """True only when mode == live AND env ATLAS_ALLOW_LIVE == "1" AND credentials are not EXAMPLE values."""
    cfg = cfg or load_config()
    if cfg.get("mode") != "live":
        return False, "config mode is %r, not 'live'" % cfg.get("mode")
    if os.environ.get("ATLAS_ALLOW_LIVE") != "1":
        return False, "env ATLAS_ALLOW_LIVE is not '1'"
    sections = {"google": ["google_ads"], "meta": ["meta"]}.get(platform or "", ["google_ads", "meta"])
    for sec in sections:
        if _has_example_values(cfg, sec):
            return False, "%s credentials are EXAMPLE placeholders" % sec
    return True, "live sending allowed"


def get_adapter(platform, cfg=None):
    """Adapter for a platform under the current mode: SampleAdapter, LiveGoogleAdapter or LiveMetaAdapter."""
    if platform not in PLATFORMS:
        raise ValueError("unknown platform: %r" % (platform,))
    cfg = cfg or load_config()
    if cfg["mode"] == "live":
        if platform == "google":
            from planning.adapters.live_google import LiveGoogleAdapter
            return LiveGoogleAdapter(cfg)
        from planning.adapters.live_meta import LiveMetaAdapter
        return LiveMetaAdapter(cfg)
    from planning.adapters.sample import SampleAdapter
    return SampleAdapter(platform, cfg)
