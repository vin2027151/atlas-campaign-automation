"""Background planning jobs (analyze, draft, revise) with stages, ETA and cost guards.

One LLM job at a time (single flight, Busy -> 409), MAX_CALLS_PER_DAY model calls per day,
MAX_CHARS for directive / revision text. ETA = median of the last 5 measured durations of
that kind, DEFAULT_ETA until measured. The LLM only writes proposals; publishing is
planning.executor and never runs here.
"""

import importlib
import statistics
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple

import store
from planning import llm, prompts, records

MAX_CALLS_PER_DAY = 60
MAX_CHARS = 4000
DEFAULT_ETA = {"analyze": 20, "draft": 30, "revise": 25}
ETA_WINDOW = 5
KINDS = ("analyze", "draft", "revise")

STAGE_PULL = "Pulling account state"
STAGE_COMPARE = "Comparing to plan"
STAGE_ASK = "Asking Opus 5.5"
STAGE_VALIDATE = "Validating"
STAGE_DIFF = "Computing diff"


class Busy(Exception):
    def __init__(self, job):
        Exception.__init__(self, "a planning job is already running (%s, %s)" % (job.get("id"), job.get("kind")))
        self.job = job


class CapReached(Exception):
    pass


_lock = threading.RLock()
_active = None  # type: Optional[str]
_threads = {}  # type: Dict[str, threading.Thread]
_recovered_for = None  # type: Optional[str]


def _mod(name):
    return importlib.import_module("planning." + name)


# --------------------------------------------------------------- guards / eta

def eta(kind):
    # type: (str) -> int
    rows = records.durations(kind)[-ETA_WINDOW:]
    if not rows:
        return DEFAULT_ETA[kind]
    return max(1, int(round(statistics.median(rows))))


def etas():
    # type: () -> Dict[str, int]
    return {k: eta(k) for k in KINDS}


def calls_left():
    # type: () -> int
    return max(0, MAX_CALLS_PER_DAY - records.calls_today())


def _before_call():
    # type: () -> None
    if calls_left() <= 0:
        raise CapReached("daily LLM call limit reached (%d per day)" % MAX_CALLS_PER_DAY)
    records.count_call()


def check_text(text, label):
    # type: (Any, str) -> str
    if not isinstance(text, str) or not text.strip():
        raise store.BadInput("%s is required" % label)
    if len(text) > MAX_CHARS:
        raise store.BadInput("%s is %d characters; the limit is %d" % (label, len(text), MAX_CHARS))
    return text.strip()


# ---------------------------------------------------------------- job state

def _view(job):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    j = dict(job)
    if j.get("status") == "running" and j.get("started_ts"):
        j["elapsed_seconds"] = round(time.time() - float(j["started_ts"]), 1)
    return j


def recover():
    # type: () -> None
    """Mark jobs left running by a previous process as errored and unstick their changesets."""
    global _recovered_for
    with _lock:
        if _recovered_for == records.DATA_DIR:
            return
        _recovered_for = records.DATA_DIR
        for j in records.list_jobs():
            if j.get("status") in ("queued", "running") and j.get("id") != _active:
                j.update(status="error", error="interrupted (server restarted)", finished_at=records.now_iso())
                records.save_job(j)
        for cs in records.list_changesets():
            if cs.get("status") == "drafting" and not (_active and cs.get("job_id") == _active):
                _settle_status(cs, "interrupted (server restarted)")
                records.save_changeset(cs)


def busy():
    # type: () -> Optional[Dict[str, Any]]
    recover()
    with _lock:
        if _active is None:
            return None
        try:
            return _view(records.get_job(_active))
        except store.NotFound:
            return None


def get(job_id):
    # type: (str) -> Dict[str, Any]
    recover()
    return _view(records.get_job(job_id))


def _update(job, **fields):
    # type: (Dict[str, Any], Any) -> None
    job.update(fields)
    if job.get("started_ts"):
        job["elapsed_seconds"] = round(time.time() - float(job["started_ts"]), 1)
    records.save_job(job)


def start(kind, target=None, **params):
    # type: (str, Optional[str], Any) -> Dict[str, Any]
    """Create and launch a job. Raises Busy, CapReached, llm.LLMNotConfigured is reported by the job."""
    global _active
    recover()
    with _lock:
        if _active is not None:
            try:
                raise Busy(records.get_job(_active))
            except store.NotFound:
                _active = None
        if calls_left() <= 0:
            raise CapReached("daily LLM call limit reached (%d per day)" % MAX_CALLS_PER_DAY)
        existing = [j.get("id", "") for j in records.list_jobs()]
        job_id = "JOB-%s-%03d" % (time.strftime("%Y%m%d-%H%M%S"), len(existing) % 1000)
        while job_id in existing:
            job_id = job_id + "x"
        job = {"id": job_id, "kind": kind, "status": "queued", "stage": STAGE_PULL, "target": target,
               "started_at": records.now_iso(), "started_ts": time.time(), "finished_at": None,
               "eta_seconds": eta(kind), "elapsed_seconds": 0.0, "result": None, "error": None}
        records.save_job(job)
        _active = job_id
        if kind in ("draft", "revise") and target:
            cs = records.get_changeset(target)
            cs["job_id"] = job_id
            cs["status"] = "drafting"
            records.save_changeset(cs)
        t = threading.Thread(target=_run, args=(job, kind, target, params), name="planning-" + job_id, daemon=True)
        _threads[job_id] = t
        t.start()
        return _view(job)


def wait(job_id, timeout=60.0):
    # type: (str, float) -> Dict[str, Any]
    """Block until the job thread finishes (tests and CLI use)."""
    t = _threads.get(job_id)
    if t is not None:
        t.join(timeout)
    return get(job_id)


def _run(job, kind, target, params):
    # type: (Dict[str, Any], str, Optional[str], Dict[str, Any]) -> None
    global _active
    t0 = time.time()
    try:
        _update(job, status="running")
        if not llm.configured():
            llm._command()  # raises LLMNotConfigured with the setup hint
        if kind == "analyze":
            result = _run_analyze(job)
        elif kind == "draft":
            result = _run_changeset(job, target, revision_note=None)
        elif kind == "revise":
            result = _run_changeset(job, target, revision_note=params.get("text"))
        else:
            raise ValueError("unknown job kind %s" % kind)
        seconds = round(time.time() - t0, 2)
        records.record_duration(kind, seconds)
        _update(job, status="done", result=result, finished_at=records.now_iso())
    except Exception as exc:
        if isinstance(exc, (llm.LLMError, CapReached, store.BadInput, store.NotFound)):
            msg = str(exc)
        else:
            msg = "%s: %s" % (type(exc).__name__, exc)
            traceback.print_exc()
        if kind in ("draft", "revise") and target:
            try:
                cs = records.get_changeset(target)
                _settle_status(cs, msg)
                records.save_changeset(cs)
            except Exception:
                pass
        _update(job, status="error", error=msg, finished_at=records.now_iso())
    finally:
        with _lock:
            if _active == job["id"]:
                _active = None
            _threads.pop(job["id"], None)


# ------------------------------------------------------------------ helpers

def _settle_status(cs, error=None):
    # type: (Dict[str, Any], Optional[str]) -> None
    """Status from the current version (ready when it has zero validation errors)."""
    if error is not None:
        cs["last_error"] = error
    if cs.get("status") in ("published", "discarded"):
        return
    v = records.current_version(cs)
    if v is None:
        cs["status"] = "invalid"
    else:
        errs = [x for x in v.get("validation") or [] if x.get("level") == "error"]
        cs["status"] = "invalid" if errs else "ready"
    cs.pop("job_id", None)


def checklist_progress():
    # type: () -> Dict[str, Any]
    st = store.get_state()
    today = store.today()
    days, overdue, due_today = [], [], []
    for d in st.get("checklist", []):
        items = d.get("items", [])
        done = sum(1 for i in items if i.get("done"))
        days.append({"day": d.get("day"), "date": d.get("date"), "done": done, "total": len(items)})
        for i in items:
            if i.get("done"):
                continue
            row = {"id": i.get("id"), "date": d.get("date"), "text": i.get("text")}
            if d.get("date", "") < today:
                overdue.append(row)
            elif d.get("date") == today:
                due_today.append(row)
    elapsed = [x for x in days if (x["date"] or "") <= today]
    return {"today": today,
            "to_date": {"done": sum(x["done"] for x in elapsed), "total": sum(x["total"] for x in elapsed)},
            "overdue": overdue, "due_today": due_today,
            "remaining_days": len(days) - len(elapsed)}


def approved_media():
    # type: () -> List[Dict[str, Any]]
    try:
        media = importlib.import_module("media")
        assets = media.list_assets(status="approved")
    except Exception:
        return []
    keep = ("id", "kind", "title", "aspect", "format")
    return [{k: a.get(k) for k in keep} for a in assets or []]


def _meta_page_id():
    # type: () -> str
    try:
        pid = str(_mod("adapters").config_public().get("meta", {}).get("page_id", ""))
        if pid.isdigit():
            return pid
    except Exception:
        pass
    return "123456789012345"


def _norm_list(x, limit=12):
    # type: (Any, int) -> List[str]
    if not isinstance(x, list):
        return []
    return [str(i).strip() for i in x if str(i).strip()][:limit]


def _norm_recs(x):
    # type: (Any) -> List[Dict[str, Any]]
    out = []
    for r in x if isinstance(x, list) else []:
        if isinstance(r, str):
            r = {"text": r}
        if not isinstance(r, dict) or not str(r.get("text", "")).strip():
            continue
        pr = str(r.get("priority", "medium")).lower()
        pl = str(r.get("platform", "both")).lower()
        out.append({"text": str(r["text"]).strip(),
                    "priority": pr if pr in ("high", "medium", "low") else "medium",
                    "platform": pl if pl in ("google", "meta", "both") else "both",
                    "campaign_id": r.get("campaign_id") or None})
    return out[:12]


ITEM_FIELDS = ("title", "plan", "running", "testing", "evidence", "recommendation", "research")


def _norm_items(x):
    # type: (Any) -> List[Dict[str, Any]]
    out = []
    for r in x if isinstance(x, list) else []:
        if not isinstance(r, dict) or not str(r.get("recommendation", "")).strip():
            continue
        it = {k: str(r.get(k) or "").strip() for k in ITEM_FIELDS}
        pr = str(r.get("priority", "medium")).lower()
        pl = str(r.get("platform", "both")).lower()
        it.update(priority=pr if pr in ("high", "medium", "low") else "medium",
                  platform=pl if pl in ("google", "meta", "both") else "both",
                  campaign_id=r.get("campaign_id") or None, test_id=r.get("test_id") or None)
        out.append(it)
    return out[:10]


# ------------------------------------------------------------------ analyze

def _run_analyze(job):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    snapshot, plan_compare = _mod("snapshot"), _mod("plan_compare")
    t0 = time.time()
    _update(job, stage=STAGE_PULL)
    snap = snapshot.pull(reason="analyze")
    _update(job, stage=STAGE_COMPARE)
    plan = plan_compare.load_plan()
    facts = plan_compare.compare(plan, snap)
    _update(job, stage=STAGE_ASK)
    fixtures = importlib.import_module("planning.fixtures")
    test_reads = importlib.import_module("planning.test_stats").read_all()
    msgs = prompts.analyze_messages(plan, snapshot.compact(snap), facts, checklist_progress(), test_reads)
    obj, res = llm.ask_json(prompts.ANALYZE_SYSTEM, msgs, stub=lambda: fixtures.analysis_text(facts, test_reads),
                            before_call=_before_call)
    items = _norm_items(obj.get("items"))
    a = records.add_analysis({
        "snapshot_id": snap["id"], "created_at": records.now_iso(), "model": res.get("model", llm.MODEL),
        "effort": llm.EFFORT, "duration_s": round(time.time() - t0, 2),
        "items": items, "notes": _norm_list(obj.get("notes"), limit=6), "test_reads": test_reads,
        # kept for older readers (Quick Chat, exports): one line per item
        "recommendations": [{"text": it["recommendation"], "priority": it["priority"], "platform": it["platform"],
                             "campaign_id": it["campaign_id"]} for it in items],
        "facts": facts, "usage": res.get("usage") or {}})
    return {"analysis_id": a["id"]}


# --------------------------------------------------------- draft / revise

def _validate(yaml_text, snap):
    # type: (Any, Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]
    changeset = _mod("changeset")
    if not isinstance(yaml_text, str) or not yaml_text.strip():
        return None, [{"op": None, "level": "error", "message": "reply had no changeset YAML"}]
    doc, errs = changeset.parse(yaml_text)
    if errs or doc is None:
        return None, [{"op": None, "level": "error", "message": e} for e in (errs or ["could not parse YAML"])]
    return doc, list(changeset.validate(doc, snap) or [])


def _errors(validation):
    # type: (List[Dict[str, Any]]) -> List[str]
    return [("%s: %s" % (v["op"], v["message"])) if v.get("op") else v.get("message", "")
            for v in validation if v.get("level") == "error"]


def _run_changeset(job, cs_id, revision_note=None):
    # type: (Dict[str, Any], str, Optional[str]) -> Dict[str, Any]
    snapshot, changeset, plan_compare = _mod("snapshot"), _mod("changeset"), _mod("plan_compare")
    fixtures = importlib.import_module("planning.fixtures")
    t0 = time.time()
    cs = records.get_changeset(cs_id)
    prior = records.current_version(cs)
    revision = len(cs.get("versions") or [])

    _update(job, stage=STAGE_PULL)
    snap = snapshot.pull(reason="revise" if revision_note else "draft")
    compact = snapshot.compact(snap)
    plan = plan_compare.load_plan()
    media_assets = approved_media()
    tagged = list(cs.get("media_ids") or [])
    landing = ((plan or {}).get("account") or {}).get("landing_url") or "https://www.agentstack.example/trial"

    if revision_note:
        msgs = prompts.revise_messages(cs["directive"], revision_note, (prior or {}).get("yaml", ""), compact,
                                       changeset.SCHEMA_DOC, media_assets, plan, tagged,
                                       prior_validation=(prior or {}).get("validation"))
    else:
        msgs = prompts.draft_messages(cs["directive"], compact, changeset.SCHEMA_DOC, media_assets, plan, tagged)

    def stub():
        return fixtures.changeset(snap, media_assets, tagged, revision=revision, revision_note=revision_note,
                                  page_id=_meta_page_id(), landing_url=landing)

    _update(job, stage=STAGE_ASK)
    obj, res = llm.ask_json(prompts.CHANGESET_SYSTEM, msgs, stub=stub, before_call=_before_call)
    llm_seconds = float(res.get("seconds") or 0)

    _update(job, stage=STAGE_VALIDATE)
    doc, validation = _validate(obj.get("yaml"), snap)
    repaired = False
    errs = _errors(validation)
    if errs:  # one repair round, then store whatever comes back
        _update(job, stage=STAGE_ASK)
        rmsgs = prompts.repair_messages(msgs, res.get("text", ""), errs)
        try:
            obj2, res2 = llm.ask_json(prompts.CHANGESET_SYSTEM, rmsgs, stub=stub, before_call=_before_call)
            llm_seconds += float(res2.get("seconds") or 0)
            if isinstance(obj2.get("yaml"), str) and obj2["yaml"].strip():
                obj, res, repaired = obj2, res2, True
                _update(job, stage=STAGE_VALIDATE)
                doc, validation = _validate(obj.get("yaml"), snap)
        except (llm.LLMError, CapReached) as exc:
            validation.append({"op": None, "level": "warn", "message": "repair round failed: %s" % exc})

    _update(job, stage=STAGE_DIFF)
    diff = None
    if doc is not None:
        try:
            d = changeset.dry_run(doc, snap)
            diff = {k: v for k, v in d.items() if k != "after"}
        except Exception as exc:
            validation.append({"op": None, "level": "error", "message": "dry run failed: %s" % exc})

    ops = len((doc or {}).get("operations") or []) if isinstance(doc, dict) else 0
    n = revision + 1
    version = {"n": n, "created_at": records.now_iso(), "snapshot_id": snap["id"], "yaml": obj.get("yaml") or "",
               "summary": _norm_list(obj.get("summary")), "assumptions": _norm_list(obj.get("assumptions")),
               "questions": _norm_list(obj.get("questions")), "validation": validation, "diff": diff,
               "revision_note": revision_note, "model": res.get("model", llm.MODEL), "effort": llm.EFFORT,
               "duration_s": round(time.time() - t0, 2), "llm_seconds": round(llm_seconds, 2),
               "repaired": repaired, "op_count": ops}
    cs = records.get_changeset(cs_id)
    cs.setdefault("versions", []).append(version)
    cs["current_version"] = n
    title = ((doc or {}).get("changeset") or {}).get("title") if isinstance(doc, dict) else None
    if title:
        cs["title"] = str(title)[:120]
    cs["last_error"] = None
    _settle_status(cs)
    records.save_changeset(cs)
    return {"changeset_id": cs_id, "version": n}
