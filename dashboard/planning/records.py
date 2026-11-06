"""Persistent planning records: analyses, changesets, jobs, measured durations, daily call count.

Everything lives in JSON files under DATA_DIR (data/planning/), written atomically with
store.write_json_atomic. Paths are resolved from DATA_DIR at call time, so tests can repoint
DATA_DIR at a temp directory.
"""

import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import store

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data", "planning")

ANALYSES_FILE = "analyses.json"
CHANGESETS_FILE = "changesets.json"
JOBS_FILE = "jobs.json"
DURATIONS_FILE = "durations.json"
CALLS_FILE = "llm_calls.json"

MAX_ANALYSES = 50
MAX_JOBS = 200
MAX_DURATIONS = 20

_lock = threading.RLock()


def now_iso():
    # type: () -> str
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def path(name):
    # type: (str) -> str
    return os.path.join(DATA_DIR, name)


def _load(name, default):
    # type: (str, Any) -> Any
    import json
    p = path(name)
    if not os.path.exists(p):
        return default
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError:
        return default


def _save(name, data):
    # type: (str, Any) -> None
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
    store.write_json_atomic(path(name), data)


def _next_id(prefix, existing, width=4):
    # type: (str, List[str], int) -> str
    n = 0
    for i in existing:
        try:
            n = max(n, int(str(i).rsplit("-", 1)[-1]))
        except ValueError:
            pass
    return "%s-%0*d" % (prefix, width, n + 1)


# ----------------------------------------------------------------- analyses

def add_analysis(a):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    with _lock:
        rows = _load(ANALYSES_FILE, [])
        a = dict(a)
        a["id"] = _next_id("AN", [r.get("id", "") for r in rows])
        rows.append(a)
        _save(ANALYSES_FILE, rows[-MAX_ANALYSES:])
        return a


def get_analysis(analysis_id):
    # type: (str) -> Dict[str, Any]
    with _lock:
        for r in _load(ANALYSES_FILE, []):
            if r.get("id") == analysis_id:
                return r
    raise store.NotFound("analysis %s not found" % analysis_id)


def latest_analysis():
    # type: () -> Optional[Dict[str, Any]]
    with _lock:
        rows = _load(ANALYSES_FILE, [])
        return rows[-1] if rows else None


# --------------------------------------------------------------- changesets

def _all_changesets():
    # type: () -> Dict[str, Dict[str, Any]]
    return _load(CHANGESETS_FILE, {})


def new_changeset(directive, media_ids):
    # type: (str, List[str]) -> Dict[str, Any]
    with _lock:
        rows = _all_changesets()
        cs_id = _next_id("CS", list(rows.keys()))
        title = " ".join(directive.split())
        if len(title) > 70:
            title = title[:67].rstrip() + "..."
        cs = {"id": cs_id, "title": title, "status": "drafting", "directive": directive,
              "media_ids": list(media_ids), "created_at": now_iso(), "updated_at": now_iso(),
              "current_version": 0, "published": None, "publish_attempts": [], "last_error": None,
              "versions": []}
        rows[cs_id] = cs
        _save(CHANGESETS_FILE, rows)
        return cs


def save_changeset(cs):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    with _lock:
        rows = _all_changesets()
        cs["updated_at"] = now_iso()
        rows[cs["id"]] = cs
        _save(CHANGESETS_FILE, rows)
        return cs


def get_changeset(cs_id):
    # type: (str) -> Dict[str, Any]
    with _lock:
        cs = _all_changesets().get(cs_id)
    if cs is None:
        raise store.NotFound("changeset %s not found" % cs_id)
    return cs


def list_changesets():
    # type: () -> List[Dict[str, Any]]
    with _lock:
        rows = list(_all_changesets().values())
    rows.sort(key=lambda c: c.get("created_at", ""), reverse=True)
    return rows


def current_version(cs):
    # type: (Dict[str, Any]) -> Optional[Dict[str, Any]]
    n = cs.get("current_version") or 0
    for v in cs.get("versions", []):
        if v.get("n") == n:
            return v
    return None


def changeset_summary(cs):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    v = current_version(cs)
    validation = (v or {}).get("validation") or []
    diff = (v or {}).get("diff") or {}
    s = diff.get("summary") or {}
    ops = None
    if s:
        ops = int(s.get("creates", 0)) + int(s.get("updates", 0)) + int(s.get("removes", 0))
    return {"id": cs["id"], "title": cs.get("title"), "status": cs.get("status"),
            "current_version": cs.get("current_version", 0), "created_at": cs.get("created_at"),
            "ops": (v or {}).get("op_count", ops),
            "errors": sum(1 for x in validation if x.get("level") == "error"),
            "warnings": sum(1 for x in validation if x.get("level") == "warn")}


# --------------------------------------------------------------------- jobs

def save_job(job):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    with _lock:
        rows = _load(JOBS_FILE, [])
        rows = [r for r in rows if r.get("id") != job["id"]]
        rows.append(job)
        _save(JOBS_FILE, rows[-MAX_JOBS:])
        return job


def get_job(job_id):
    # type: (str) -> Dict[str, Any]
    with _lock:
        for r in _load(JOBS_FILE, []):
            if r.get("id") == job_id:
                return r
    raise store.NotFound("job %s not found" % job_id)


def list_jobs():
    # type: () -> List[Dict[str, Any]]
    with _lock:
        return list(_load(JOBS_FILE, []))


# ---------------------------------------------------------------- durations

def record_duration(kind, seconds):
    # type: (str, float) -> None
    with _lock:
        d = _load(DURATIONS_FILE, {})
        rows = d.get(kind, [])
        rows.append(round(float(seconds), 2))
        d[kind] = rows[-MAX_DURATIONS:]
        _save(DURATIONS_FILE, d)


def durations(kind):
    # type: (str) -> List[float]
    with _lock:
        return list(_load(DURATIONS_FILE, {}).get(kind, []))


# -------------------------------------------------------------- daily calls

def _day():
    # type: () -> str
    return datetime.now().strftime("%Y-%m-%d")  # real calendar day, not the sample "today"


def calls_today():
    # type: () -> int
    with _lock:
        return int(_load(CALLS_FILE, {}).get(_day(), 0))


def count_call():
    # type: () -> int
    with _lock:
        d = _load(CALLS_FILE, {})
        day = _day()
        d = {day: int(d.get(day, 0)) + 1}  # keep only today
        _save(CALLS_FILE, d)
        return d[day]
