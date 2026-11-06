"""State store for the Atlas Ops dashboard: the single source of truth.

Everything the dashboard shows lives in ``data/state.json``. This module loads
it, hands it out, mutates it, and writes it back atomically (temp file, then
``os.replace``) after every mutation.

Conventions every caller can rely on:

* Dates are ISO ``YYYY-MM-DD`` strings; money is USD floats.
* "Today" is ``meta.today`` in the state (``2026-11-05`` for the sample data),
  never the wall clock. Use :func:`today`.
* Rates (``ctr``, ``click_to_trial``, ``trial_to_paid``, ``pace_pct``) are
  **percentage points**: ``4.9`` means 4.9%. ``fmt.pct(4.9)`` renders "4.9%".
* Any derived metric whose denominator is zero is ``None`` (JSON ``null``),
  never ``inf`` or ``NaN``.
* Unknown ids raise :class:`NotFound`; bad input raises :class:`BadInput`.
  ``app.py`` turns these into HTTP 404 / 400 with ``{"ok": false, "error": msg}``,
  so API routes can simply let them propagate.
* The mutation helpers (``set_campaign_status`` ... ``add_lesson``) already call
  :func:`log_activity`. Do not log again after calling one of them. If you write
  your own mutation with :func:`mutate`, call :func:`log_activity` yourself.

The mutation helpers are the seam where a real Google Ads / Meta Marketing API
adapter would plug in: today they edit local sample state; a live adapter would
call the platform first and then record the result here.
"""

import calendar
import copy
import contextlib
import hashlib
import json
import os
import tempfile
import threading

try:  # POSIX advisory lock so two server processes never interleave a read-modify-write
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover (Windows)
    fcntl = None  # type: ignore
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "data", "state.json")

CAMPAIGN_STATUSES = ("ACTIVE", "PAUSED")
CONTENT_STATUSES = ("running", "scheduled", "pending_feedback", "final_pending_approval", "approved")
TEST_STATUSES = ("running", "won", "lost", "inconclusive", "queued")
NEGATIVE_MATCH_TYPES = ("exact", "phrase", "broad")
ACTIVITY_LIMIT = 1000

_lock = threading.RLock()
_state = None  # type: Optional[Dict[str, Any]]
_mtime = None  # type: Optional[float]


class NotFound(LookupError):
    """Raised when an id does not exist. Mapped to HTTP 404 by app.py."""


class BadInput(ValueError):
    """Raised for invalid arguments. Mapped to HTTP 400 by app.py."""


# --------------------------------------------------------------------------- io

def write_json_atomic(path, data):
    # type: (str, Any) -> None
    """Write ``data`` as JSON to ``path`` atomically (temp file in the same dir, then os.replace)."""
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".state-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _load_from_disk():
    # type: () -> None
    global _state, _mtime
    if not os.path.exists(STATE_PATH):
        raise RuntimeError("data/state.json is missing. Run: python3 -m data.seed")
    with open(STATE_PATH, "r", encoding="utf-8") as fh:
        _state = json.load(fh)
    _mtime = os.path.getmtime(STATE_PATH)


def get_state():
    # type: () -> Dict[str, Any]
    """Return the live state dict (loaded lazily; reloaded if state.json changed on disk, e.g. after a reseed).

    Treat the result as read-only. To change anything, use :func:`mutate` or a
    mutation helper so the change is persisted and logged.
    """
    with _lock:
        if _state is None:
            _load_from_disk()
        else:
            try:
                if os.path.getmtime(STATE_PATH) != _mtime:
                    _load_from_disk()
            except OSError:
                pass
        return _state  # type: ignore


def reload_state():
    # type: () -> Dict[str, Any]
    """Force a re-read of state.json from disk and return it."""
    with _lock:
        _load_from_disk()
        return _state  # type: ignore


def save_state():
    # type: () -> None
    """Write the in-memory state back to state.json atomically."""
    global _mtime
    with _lock:
        if _state is None:
            return
        write_json_atomic(STATE_PATH, _state)
        _mtime = os.path.getmtime(STATE_PATH)


@contextlib.contextmanager
def _file_lock():
    """Exclusive advisory lock next to state.json (``.state-lock.json``, git-ignored).

    The thread lock covers one server process; this covers several (two uvicorn
    workers, a CLI script) so a read-modify-write is never interleaved. Writes are
    already atomic (temp file + os.replace), so readers never see a torn file.
    """
    if fcntl is None:
        yield
        return
    path = os.path.join(os.path.dirname(STATE_PATH) or ".", ".state-lock.json")
    fh = open(path, "a")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def mutate(fn):
    # type: (Callable[[Dict[str, Any]], Any]) -> Any
    """Run ``fn(state)`` under the store lock, save atomically, and return ``fn``'s result.

    The thread lock and a file lock are held for the whole read-modify-write, and
    state.json is re-read first if another process changed it, so concurrent edits
    from several browsers never overwrite each other or corrupt the file.
    If ``fn`` raises, nothing is saved (the in-memory state is restored from a
    snapshot), so a failed mutation never leaves a half-applied change.
    """
    global _state
    with _lock, _file_lock():
        state = get_state()
        snapshot = copy.deepcopy(state)
        try:
            result = fn(state)
        except BaseException:
            _state = snapshot
            raise
        save_state()
        return result


def log_activity(action, target, detail="", actor="vin"):
    # type: (str, str, str, str) -> Dict[str, Any]
    """Append an activity entry ``{ts, actor, action, target, detail}`` and persist it.

    ``action`` is a dotted verb such as ``"campaign.pause"``; ``target`` is the
    affected id. Newest entries are appended at the end; the list is capped at
    ACTIVITY_LIMIT entries. Returns the entry.
    """
    entry = {
        "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "actor": actor,
        "action": action,
        "target": target,
        "detail": detail,
    }

    def _append(state):
        log = state.setdefault("activity", [])
        log.append(entry)
        if len(log) > ACTIVITY_LIMIT:
            del log[: len(log) - ACTIVITY_LIMIT]
        return entry

    return mutate(_append)


def recent_activity(limit=50):
    # type: (int) -> List[Dict[str, Any]]
    """Return the newest ``limit`` activity entries, newest first."""
    return list(reversed(get_state().get("activity", [])[-limit:]))


# ------------------------------------------------------------------------ dates

def today():
    # type: () -> str
    """The sample data's "today" (``meta.today``) as an ISO string."""
    return get_state()["meta"]["today"]


def parse_date(s):
    # type: (str) -> date
    """Parse ``YYYY-MM-DD`` into a date; raises BadInput on a malformed string."""
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise BadInput("bad date: %r (expected YYYY-MM-DD)" % (s,))


def iso(d):
    # type: (date) -> str
    """Format a date as ``YYYY-MM-DD``."""
    return d.isoformat()


def shift(day, n):
    # type: (str, int) -> str
    """Return the ISO date ``n`` days after ``day`` (negative to go back)."""
    return iso(parse_date(day) + timedelta(days=n))


def date_range(start, end):
    # type: (str, str) -> List[str]
    """Inclusive list of ISO dates from ``start`` to ``end``."""
    a, b = parse_date(start), parse_date(end)
    out = []
    while a <= b:
        out.append(iso(a))
        a += timedelta(days=1)
    return out


# ---------------------------------------------------------------------- lookups

def _find(collection, item_id, label):
    # type: (str, str, str) -> Dict[str, Any]
    for item in get_state().get(collection, []):
        if item.get("id") == item_id:
            return item
    raise NotFound("unknown %s: %s" % (label, item_id))


def campaign(campaign_id):
    # type: (str) -> Dict[str, Any]
    """Return the campaign dict with this id, or raise NotFound."""
    return _find("campaigns", campaign_id, "campaign")


def campaigns(platform=None):
    # type: (Optional[str]) -> List[Dict[str, Any]]
    """All campaigns, optionally filtered by platform ("google" or "meta")."""
    return [c for c in get_state()["campaigns"] if platform is None or c["platform"] == platform]


def adset(adset_id):
    # type: (str) -> Dict[str, Any]
    """Return the ad set / ad group / asset group with this id, or raise NotFound."""
    return _find("adsets", adset_id, "adset")


def ad(ad_id):
    # type: (str) -> Dict[str, Any]
    """Return the ad with this id, or raise NotFound."""
    return _find("ads", ad_id, "ad")


def adsets_for(campaign_id):
    # type: (str) -> List[Dict[str, Any]]
    """Ad sets (Meta) / ad groups / asset groups (Google) under a campaign."""
    return [a for a in get_state()["adsets"] if a["campaign_id"] == campaign_id]


def ads_for(adset_id):
    # type: (str) -> List[Dict[str, Any]]
    """Ads under an ad set / ad group."""
    return [a for a in get_state()["ads"] if a["adset_id"] == adset_id]


def content_item(content_id):
    # type: (str) -> Dict[str, Any]
    """Return the content item with this id, or raise NotFound."""
    return _find("content", content_id, "content item")


def test(test_id):
    # type: (str) -> Dict[str, Any]
    """Return the test with this id, or raise NotFound."""
    return _find("tests", test_id, "test")


test.__test__ = False  # keep pytest from collecting this helper


# ---------------------------------------------------------------------- metrics

def safe_div(num, den, scale=1.0, digits=2):
    # type: (float, float, float, int) -> Optional[float]
    """``num / den * scale`` rounded, or None when ``den`` is 0 or None."""
    if not den:
        return None
    return round(num / den * scale, digits)


def derive(totals):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    """Add derived metrics to a dict of raw sums, in place, and return it.

    Needs ``spend, impressions, clicks, trials, paid, platform_conversions``.
    Adds ``cost_per_trial, cost_per_paid, cpc, cpm`` (USD), ``ctr,
    click_to_trial, trial_to_paid`` (percentage points) and
    ``platform_cost_per_conversion``. Any zero denominator gives None.
    """
    t = totals
    t["cost_per_trial"] = safe_div(t["spend"], t["trials"])
    t["cost_per_paid"] = safe_div(t["spend"], t["paid"])
    t["cpc"] = safe_div(t["spend"], t["clicks"])
    t["cpm"] = safe_div(t["spend"], t["impressions"], 1000.0)
    t["ctr"] = safe_div(t["clicks"], t["impressions"], 100.0)
    t["click_to_trial"] = safe_div(t["trials"], t["clicks"], 100.0)
    t["trial_to_paid"] = safe_div(t["paid"], t["trials"], 100.0)
    t["platform_cost_per_conversion"] = safe_div(t["spend"], t["platform_conversions"])
    return t


def aggregate(rows):
    # type: (List[Dict[str, Any]]) -> Dict[str, Any]
    """Sum daily rows and return the totals with :func:`derive` metrics applied."""
    t = {"spend": 0.0, "impressions": 0, "clicks": 0, "platform_conversions": 0.0, "trials": 0, "paid": 0}
    for r in rows:
        t["spend"] += r["spend"]
        t["impressions"] += r["impressions"]
        t["clicks"] += r["clicks"]
        t["platform_conversions"] += r["platform_conversions"]
        t["trials"] += r["trials"]
        t["paid"] += r["paid"]
    t["spend"] = round(t["spend"], 2)
    t["platform_conversions"] = round(t["platform_conversions"], 1)
    return derive(t)


def daily_for(campaign_id=None, platform=None, start=None, end=None):
    # type: (Optional[str], Optional[str], Optional[str], Optional[str]) -> List[Dict[str, Any]]
    """Daily rows filtered by campaign, platform and inclusive date range, sorted by date.

    Each row: ``date, campaign_id, spend, impressions, clicks,
    platform_conversions, trials, paid``. Rows are the live dicts; do not edit.
    """
    ids = None
    if platform is not None:
        ids = set(c["id"] for c in campaigns(platform))
    out = []
    for r in get_state()["daily"]:
        if campaign_id is not None and r["campaign_id"] != campaign_id:
            continue
        if ids is not None and r["campaign_id"] not in ids:
            continue
        if start is not None and r["date"] < start:
            continue
        if end is not None and r["date"] > end:
            continue
        out.append(r)
    out.sort(key=lambda r: (r["date"], r["campaign_id"]))
    return out


def daily_series(campaign_id=None, platform=None, start=None, end=None):
    # type: (Optional[str], Optional[str], Optional[str], Optional[str]) -> List[Dict[str, Any]]
    """One aggregated row per date (summed across matching campaigns), with derived metrics.

    Every date in the range appears, even with no rows (zeros, None ratios).
    ``start`` defaults to the first date in the data, ``end`` to today.
    """
    rows = daily_for(campaign_id, platform, start, end)
    by_date = {}  # type: Dict[str, List[Dict[str, Any]]]
    for r in rows:
        by_date.setdefault(r["date"], []).append(r)
    if start is None:
        start = min(by_date) if by_date else today()
    if end is None:
        end = today()
    out = []
    for d in date_range(start, end):
        t = aggregate(by_date.get(d, []))
        t["date"] = d
        out.append(t)
    return out


def window_totals(campaign_id=None, days=7, platform=None, end=None):
    # type: (Optional[str], int, Optional[str], Optional[str]) -> Dict[str, Any]
    """Totals for the trailing ``days`` days ending ``end`` (default today), inclusive.

    ``campaign_id=None`` means all campaigns (optionally narrowed by
    ``platform``). Returns ``start, end, days, spend, impressions, clicks,
    platform_conversions, trials, paid`` plus everything :func:`derive` adds:
    ``cost_per_trial, cost_per_paid, click_to_trial, trial_to_paid, ctr, cpc,
    cpm, platform_cost_per_conversion``. Zero trials gives ``cost_per_trial=None``.
    """
    if days < 1:
        raise BadInput("days must be >= 1")
    end = end or today()
    start = shift(end, -(days - 1))
    t = aggregate(daily_for(campaign_id, platform, start, end))
    t.update({"start": start, "end": end, "days": days})
    return t


def rolling_cost_per_trial(campaign_id=None, days=3, platform=None, start=None, end=None):
    # type: (Optional[str], int, Optional[str], Optional[str], Optional[str]) -> List[Dict[str, Any]]
    """Trailing ``days``-day cost per trial for each date from ``start`` to ``end``.

    Returns ``[{"date", "spend", "trials", "cost_per_trial"}]`` where spend and
    trials are the trailing-window sums ending on that date and
    ``cost_per_trial`` is None when the window has zero trials. Typical calls:
    ``rolling_cost_per_trial(cid, days=3)`` and ``rolling_cost_per_trial(cid, days=7)``.
    ``start`` defaults to the first date in the data, ``end`` to today.
    """
    if days < 1:
        raise BadInput("days must be >= 1")
    series = daily_series(campaign_id, platform, None, end)
    out = []
    for i, row in enumerate(series):
        window = series[max(0, i - days + 1): i + 1]
        spend = round(sum(w["spend"] for w in window), 2)
        trials = sum(w["trials"] for w in window)
        if start is not None and row["date"] < start:
            continue
        out.append({"date": row["date"], "spend": spend, "trials": trials,
                    "cost_per_trial": safe_div(spend, trials)})
    return out


def platform_budget(platform=None):
    # type: (Optional[str]) -> float
    """Monthly budget for a platform (``meta.platform_budgets``) or the account total."""
    meta = get_state()["meta"]
    if platform is None:
        return float(meta["monthly_budget"])
    try:
        return float(meta["platform_budgets"][platform])
    except KeyError:
        raise BadInput("unknown platform: %s" % platform)


# Money rule (one rule, used everywhere): every budget is held in whole cents per
# entity (what the platform stores: Google micros are a multiple of 10,000, Meta
# takes cents). A total is the sum of those cent amounts, added as integers, never
# a re-derived figure (monthly / days) and never a rounded sum of unrounded floats.
# Source of truth for a Meta campaign with ad-set budgets (ABO) is its ad sets;
# the campaign's own ``daily_budget`` field in state.json is only a mirror.

def cents(v):
    # type: (Any) -> int
    """Dollars -> whole cents (half away from zero on the cent)."""
    return int(round(float(v or 0) * 100 + (1e-9 if float(v or 0) >= 0 else -1e-9)))


def money_sum(values):
    # type: (Any) -> float
    """Sum of dollar amounts, each taken to the cent first, added as integer cents."""
    return sum(cents(v) for v in values) / 100.0


def uses_adset_budgets(c, sets=None):
    # type: (Dict[str, Any], Optional[List[Dict[str, Any]]]) -> bool
    """A Meta campaign whose budget lives on its ad sets (ABO)."""
    if c.get("platform") != "meta":
        return False
    sets = adsets_for(c["id"]) if sets is None else sets
    return any(a.get("daily_budget") is not None for a in sets)


def adset_delivers(a):
    # type: (Dict[str, Any]) -> bool
    """An ad set / ad group / asset group can spend: it is ACTIVE and, if it has ads, one is ACTIVE."""
    if a.get("status") != "ACTIVE":
        return False
    ads = ads_for(a["id"])
    return not ads or any(x.get("status") == "ACTIVE" for x in ads)


def campaign_daily_budget(c):
    # type: (Dict[str, Any]) -> float
    """A campaign's configured daily budget (what its budget control shows).

    Meta ABO: the sum of its ACTIVE ad sets' budgets (the set the budget control
    scales). Everything else: the campaign's own daily budget.
    """
    sets = adsets_for(c["id"])
    if uses_adset_budgets(c, sets):
        return money_sum(a.get("daily_budget") for a in sets if a.get("status") == "ACTIVE")
    return money_sum([c.get("daily_budget")])


def effective_daily_budget(c):
    # type: (Dict[str, Any]) -> float
    """What a campaign can spend per day right now; this is what pacing projects.

    0 unless the campaign is ACTIVE and at least one of its ad sets delivers (a
    paused parent stops its active children; an active parent whose children are
    all paused, or whose ad sets have no active ad, spends nothing). Meta ABO counts
    only its delivering ad sets' budgets. A campaign with no ad sets counts its budget.
    """
    if c.get("status") != "ACTIVE":
        return 0.0
    sets = adsets_for(c["id"])
    live = [a for a in sets if adset_delivers(a)]
    if sets and not live:
        return 0.0
    if uses_adset_budgets(c, sets):
        return money_sum(a.get("daily_budget") for a in live)
    return money_sum([c.get("daily_budget")])


def active_daily_budget(platform=None):
    # type: (Optional[str]) -> float
    """Sum of the effective daily budgets (:func:`effective_daily_budget`), account or one platform."""
    return money_sum(effective_daily_budget(c) for c in campaigns(platform))


def pacing(platform=None):
    # type: (Optional[str]) -> Dict[str, Any]
    """Month-to-date pacing for the account or one platform, as of today.

    The projection is **month-to-date spend + days remaining x the current daily
    budgets of what is enabled now**, so pausing a campaign or changing a budget
    moves it immediately (a trailing-7-day rate would take a week to react).

    Returns ``month`` ("YYYY-MM"), ``month_to_date_spend``, ``days_elapsed``
    (today counts as elapsed), ``days_in_month``, ``days_remaining``,
    ``active_daily_budget`` (see :func:`active_daily_budget`),
    ``projected_month_end`` (MTD + active_daily_budget x days remaining),
    ``projection_basis`` ("current_daily_budgets"), ``monthly_budget``,
    ``pace_pct`` (projected / budget, percentage points), ``budget_to_date``
    (straight-line budget through today), ``mtd_vs_plan_pct`` (MTD /
    budget_to_date), ``daily_target`` (budget left / days left) and, for
    reference only, ``daily_rate_7d`` (avg spend/day over the trailing 7 days).
    """
    t = parse_date(today())
    month_start = iso(t.replace(day=1))
    dim = calendar.monthrange(t.year, t.month)[1]
    elapsed = t.day
    remaining = dim - elapsed
    mtd = money_sum(r["spend"] for r in daily_for(None, platform, month_start, today()))
    rate = round(window_totals(None, 7, platform)["spend"] / 7.0, 2)
    daily = active_daily_budget(platform)
    projected = (cents(mtd) + cents(daily) * remaining) / 100.0
    budget = platform_budget(platform)
    to_date = round(budget * elapsed / float(dim), 2)
    return {
        "platform": platform,
        "month": t.strftime("%Y-%m"),
        "month_to_date_spend": mtd,
        "days_elapsed": elapsed,
        "days_in_month": dim,
        "days_remaining": remaining,
        "active_daily_budget": daily,
        "projected_month_end": projected,
        "projection_basis": "current_daily_budgets",
        "projection_label": "Projected month-end at current daily budgets",
        "daily_rate_7d": rate,
        "monthly_budget": budget,
        "pace_pct": safe_div(projected, budget, 100.0, 1),
        "budget_to_date": to_date,
        "mtd_vs_plan_pct": safe_div(mtd, to_date, 100.0, 1),
        "daily_target": safe_div(budget - mtd, remaining) if remaining else None,
    }


# ------------------------------------------------------------ ad-level metrics
# The sample data has daily rows per campaign only. Each ad carries a seeded
# ``metrics_split``: its share of its ad set's spend, impressions, clicks,
# platform conversions, trials and paid. Shares within an ad set sum to 1 per
# metric, so ads add up to their ad set and ad sets to the campaign. Different
# shares per metric give each ad its own CTR and cost per trial.

AD_SPLIT_KEYS = ("spend", "impressions", "clicks", "platform_conversions", "trials", "paid")


def _seeded(ad_id, salt, lo, hi):
    # type: (str, str, float, float) -> float
    h = hashlib.sha256(("atlas-ad-split:%s:%s" % (ad_id, salt)).encode("utf-8")).hexdigest()
    return lo + (hi - lo) * (int(h[:8], 16) / float(0xFFFFFFFF))


def _ad_split_weights(ad_id):
    # type: (str) -> Dict[str, float]
    w = {}
    w["spend"] = _seeded(ad_id, "spend", 0.45, 1.55)
    w["impressions"] = w["spend"] * _seeded(ad_id, "cpm", 0.85, 1.15)
    w["clicks"] = w["impressions"] * _seeded(ad_id, "ctr", 0.70, 1.30)
    w["trials"] = w["clicks"] * _seeded(ad_id, "cvr", 0.55, 1.45)
    w["platform_conversions"] = w["trials"] * _seeded(ad_id, "pconv", 0.80, 1.25)
    w["paid"] = w["trials"] * _seeded(ad_id, "paid", 0.65, 1.35)
    return w


def _normalize_shares(weights):
    # type: (List[float]) -> List[float]
    total = sum(weights)
    if total <= 0:
        return [0.0 for _ in weights]
    shares = [round(x / total, 4) for x in weights]
    shares[-1] = round(1.0 - sum(shares[:-1]), 4)
    return shares


def ensure_ad_splits():
    # type: () -> int
    """Give every ad a seeded ``metrics_split`` once (deterministic). Returns ads changed.

    Ad sets where no ad has a split get shares across all their ads. An ad added
    later (a new ad from a publish) gets zero shares: it has no history yet, and
    its siblings' shares still sum to 1.
    """
    st = get_state()
    if all("metrics_split" in a for a in st.get("ads", [])):
        return 0

    def _apply(state):
        changed = 0
        by_set = {}  # type: Dict[str, List[Dict[str, Any]]]
        for a in state["ads"]:
            by_set.setdefault(a["adset_id"], []).append(a)
        for sid, ads in by_set.items():
            todo = [a for a in ads if "metrics_split" not in a]
            if not todo:
                continue
            if len(todo) < len(ads):  # siblings already split: newcomers start at zero
                for a in todo:
                    a["metrics_split"] = dict([(k, 0.0) for k in AD_SPLIT_KEYS] + [("sample_derived", True)])
                    changed += 1
                continue
            ws = [_ad_split_weights(a["id"]) for a in ads]
            per = dict((k, _normalize_shares([w[k] for w in ws])) for k in AD_SPLIT_KEYS)
            for i, a in enumerate(ads):
                a["metrics_split"] = dict([(k, per[k][i]) for k in AD_SPLIT_KEYS] + [("sample_derived", True)])
                changed += 1
        return changed

    return mutate(_apply)


# How each apportioned metric is rounded: spend to cents, counts to whole numbers,
# trials / paid / platform conversions to tenths (the sample splits are fractional).
SPLIT_DIGITS = {"spend": 2, "impressions": 0, "clicks": 0, "platform_conversions": 1, "trials": 1, "paid": 1}


def apportion(total, weights, digits):
    # type: (Any, List[float], int) -> List[Any]
    """Split ``total`` by ``weights`` into parts rounded to ``digits`` that add up to ``total`` exactly.

    Largest-remainder method on integer units (cents for digits=2), so the parts of a
    rounded total always sum back to it, whatever the weights."""
    scale = 10 ** digits
    units = int(round(float(total or 0) * scale))
    wsum = float(sum(max(0.0, float(w or 0)) for w in weights))
    if not weights:
        return []
    if wsum <= 0:
        raw = [0.0] * len(weights)
        raw[0] = float(units)
    else:
        raw = [units * max(0.0, float(w or 0)) / wsum for w in weights]
    base = [int(x // 1) for x in raw]
    left = units - sum(base)
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - base[i]), -raw[i], i))
    for i in order[:max(0, left)]:
        base[i] += 1
    if digits == 0:
        return [int(b) for b in base]
    return [round(b / float(scale), digits) for b in base]


def split_totals(totals, weights_by_key):
    # type: (Dict[str, Any], Dict[str, List[float]]) -> List[Dict[str, Any]]
    """Apportion every AD_SPLIT_KEYS total by its own weights; parts sum to the totals exactly."""
    n = len(next(iter(weights_by_key.values()))) if weights_by_key else 0
    parts = [dict() for _ in range(n)]  # type: List[Dict[str, Any]]
    for k in AD_SPLIT_KEYS:
        for p, v in zip(parts, apportion(totals.get(k) or 0, weights_by_key[k], SPLIT_DIGITS[k])):
            p[k] = v
    return [derive(p) for p in parts]


def split_ad_metrics(adset_totals, ads):
    # type: (Dict[str, Any], List[Dict[str, Any]]) -> List[Dict[str, Any]]
    """Split an ad set's totals across its ads by ``metrics_split``; derived metrics added.

    Returns one dict per ad (same order) with the raw sums and :func:`derive` metrics.
    Every metric is apportioned with :func:`apportion`, so the ads add up to the ad
    set's (already rounded) totals exactly, metric by metric.
    """
    if not ads:
        return []
    weights = dict((k, [float((a.get("metrics_split") or {}).get(k) or 0) for a in ads]) for k in AD_SPLIT_KEYS)
    return split_totals(adset_totals, weights)


def month_to_date(campaign_id=None, platform=None):
    # type: (Optional[str], Optional[str]) -> Dict[str, Any]
    """Totals (with derived metrics) from the 1st of today's month through today."""
    t = today()
    start = t[:8] + "01"
    out = aggregate(daily_for(campaign_id, platform, start, t))
    out.update({"start": start, "end": t})
    return out


# -------------------------------------------------------------------- mutations
# Each helper validates, applies the change through mutate(), logs it, and
# returns the updated object. These are the adapter seam for live platform APIs.

def _check_status(status, allowed):
    # type: (Any, tuple) -> str
    s = str(status or "").strip()
    if s.upper() in allowed:
        return s.upper()
    if s.lower() in allowed:
        return s.lower()
    raise BadInput("status must be one of %s" % ", ".join(allowed))


def _set_status(collection, item_id, status, label, action):
    # type: (str, str, Any, str, str) -> Dict[str, Any]
    new = _check_status(status, CAMPAIGN_STATUSES)
    _find(collection, item_id, label)  # NotFound before we touch anything

    def _apply(state):
        for item in state[collection]:
            if item["id"] == item_id:
                old = item["status"]
                item["status"] = new
                return item, old

    item, old = mutate(_apply)
    log_activity(action, item_id, "%s: %s -> %s" % (item.get("name", item_id), old, new))
    return item


def set_campaign_status(campaign_id, status):
    # type: (str, str) -> Dict[str, Any]
    """Set a campaign to "ACTIVE" or "PAUSED". Returns the campaign. Logs ``campaign.status``."""
    return _set_status("campaigns", campaign_id, status, "campaign", "campaign.status")


def set_campaign_budget(campaign_id, daily_budget=None, monthly_budget=None):
    # type: (str, Optional[float], Optional[float]) -> Dict[str, Any]
    """Change a campaign's budget. Pass either ``daily_budget`` or ``monthly_budget``.

    The other is derived with the current month's day count (daily x days in
    month, or monthly / days in month). Values must be positive numbers.
    Returns the campaign. Logs ``campaign.budget``.
    """
    campaign(campaign_id)
    if daily_budget is None and monthly_budget is None:
        raise BadInput("give daily_budget or monthly_budget")
    t = parse_date(today())
    dim = calendar.monthrange(t.year, t.month)[1]
    try:
        if daily_budget is not None:
            daily = round(float(daily_budget), 2)
            monthly = round(daily * dim, 2)
        else:
            monthly = round(float(monthly_budget), 2)  # type: ignore
            daily = round(monthly / dim, 2)
    except (TypeError, ValueError):
        raise BadInput("budget must be a number")
    if daily <= 0:
        raise BadInput("budget must be greater than 0")

    def _apply(state):
        for c in state["campaigns"]:
            if c["id"] == campaign_id:
                old = (c["daily_budget"], c["monthly_budget"])
                c["daily_budget"] = daily
                if daily_budget is not None and c.get("monthly_budget") is not None:
                    # move the monthly figure by the same delta x days (not daily x days), so a
                    # change and its undo, in any order, restore the stored figures exactly
                    m = (cents(c["monthly_budget"]) + (cents(daily) - cents(old[0])) * dim) / 100.0
                    c["monthly_budget"] = int(m) if float(m).is_integer() else m
                else:
                    c["monthly_budget"] = monthly
                return c, old

    c, old = mutate(_apply)
    log_activity("campaign.budget", campaign_id, "%s: $%s/day -> $%s/day ($%s/mo)" % (
        c["name"], _n(old[0]), _n(daily), _n(c["monthly_budget"])))
    return c


def set_adset_status(adset_id, status):
    # type: (str, str) -> Dict[str, Any]
    """Set an ad set / ad group / asset group to "ACTIVE" or "PAUSED". Logs ``adset.status``."""
    return _set_status("adsets", adset_id, status, "adset", "adset.status")


def set_ad_status(ad_id, status):
    # type: (str, str) -> Dict[str, Any]
    """Set an ad to "ACTIVE" or "PAUSED". Returns the ad. Logs ``ad.status``."""
    return _set_status("ads", ad_id, status, "ad", "ad.status")


def add_negative(campaign_id, text, match="phrase", source="manual"):
    # type: (str, str, str, str) -> Dict[str, Any]
    """Add a negative keyword to a Google campaign.

    ``match`` is "exact", "phrase" or "broad"; ``source`` is "manual" or
    "recommended". Raises BadInput for empty text, a Meta campaign, or a
    duplicate (same campaign, text and match). Matching search terms are marked
    ``negated: true``. Returns the new negative. Logs ``negative.add``.
    """
    c = campaign(campaign_id)
    if c["platform"] != "google":
        raise BadInput("negative keywords apply to Google campaigns only")
    text = " ".join(str(text or "").lower().split())
    if not text:
        raise BadInput("negative text is empty")
    match = str(match or "phrase").lower()
    if match not in NEGATIVE_MATCH_TYPES:
        raise BadInput("match must be one of %s" % ", ".join(NEGATIVE_MATCH_TYPES))
    if source not in ("manual", "recommended"):
        raise BadInput("source must be manual or recommended")
    for n in get_state()["negatives"]:
        if n["campaign_id"] == campaign_id and n["text"] == text and n["match"] == match:
            raise BadInput("negative already exists: %s [%s]" % (text, match))
    neg = {"campaign_id": campaign_id, "text": text, "match": match, "added": today(), "source": source}

    def _apply(state):
        state["negatives"].append(neg)
        for st in state["search_terms"]:
            if st["campaign_id"] == campaign_id and _negative_hits(text, match, st["term"]):
                st["negated"] = True
        return neg

    mutate(_apply)
    log_activity("negative.add", campaign_id, "%s [%s] on %s (%s)" % (text, match, c["name"], source))
    return neg


def _negative_hits(text, match, term):
    # type: (str, str, str) -> bool
    term = term.lower()
    if match == "exact":
        return term == text
    if match == "phrase":
        return (" %s " % text) in (" %s " % term)
    return all(w in term.split() for w in text.split())


def move_content(content_id, status):
    # type: (str, str) -> Dict[str, Any]
    """Move a content item to a pipeline status (one of CONTENT_STATUSES). Logs ``content.move``."""
    new = _check_status(status, CONTENT_STATUSES)
    content_item(content_id)

    def _apply(state):
        for item in state["content"]:
            if item["id"] == content_id:
                old = item["status"]
                item["status"] = new
                return item, old

    item, old = mutate(_apply)
    log_activity("content.move", content_id, "%s: %s -> %s" % (item["name"], old, new))
    return item


def toggle_checklist(item_id, done=None):
    # type: (str, Optional[bool]) -> Dict[str, Any]
    """Flip a checklist item's ``done`` flag (or set it when ``done`` is given).

    Returns ``{"day", "date", "item": {...}}``. Logs ``checklist.toggle``.
    """
    found = None
    for day in get_state()["checklist"]:
        for it in day["items"]:
            if it["id"] == item_id:
                found = day
    if found is None:
        raise NotFound("unknown checklist item: %s" % item_id)

    def _apply(state):
        for day in state["checklist"]:
            for it in day["items"]:
                if it["id"] == item_id:
                    it["done"] = (not it["done"]) if done is None else bool(done)
                    return {"day": day["day"], "date": day["date"], "item": it}

    res = mutate(_apply)
    log_activity("checklist.toggle", item_id, "Day %s: %s -> %s" % (
        res["day"], res["item"]["text"], "done" if res["item"]["done"] else "open"))
    return res


def add_lesson(text, tags=None, source="manual", date_=None):
    # type: (str, Optional[List[str]], str, Optional[str]) -> Dict[str, Any]
    """Append a lesson ``{id, date, text, tags, source}`` (date defaults to today). Logs ``lesson.add``."""
    text = str(text or "").strip()
    if not text:
        raise BadInput("lesson text is empty")
    if tags is None:
        tags = []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    tags = [str(t).strip().lower() for t in tags if str(t).strip()]
    d = date_ or today()
    parse_date(d)
    existing = get_state()["lessons"]
    lesson = {"id": "l%02d" % (len(existing) + 1), "date": d, "text": text, "tags": tags, "source": source}
    ids = set(x.get("id") for x in existing)
    n = len(existing) + 1
    while lesson["id"] in ids:
        n += 1
        lesson["id"] = "l%02d" % n

    def _apply(state):
        state["lessons"].append(lesson)
        return lesson

    mutate(_apply)
    log_activity("lesson.add", lesson["id"], text[:120])
    return lesson


def _n(x):
    # type: (Any) -> str
    try:
        return "{:,.0f}".format(float(x))
    except (TypeError, ValueError):
        return str(x)
