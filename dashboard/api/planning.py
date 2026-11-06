"""Plan & Adapt API (/api/planning).

Analyze (snapshot -> plan comparison -> Opus 5.5 bullets), draft and revise changesets from a
brief (Opus 5.5 writes JSON operations; code validates them, renders each as the exact HTTP
request and diffs them), and publish by hand. Publish calls
only planning.executor.publish with the stored version; the LLM is never on that path.
"""

import importlib
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

import store
from planning import jobs, llm, records

router = APIRouter(prefix="/api/planning", tags=["planning"])


class DraftBody(BaseModel):
    directive: Any = None
    media_ids: Any = None


class ReviseBody(BaseModel):
    text: Any = None


class PublishBody(BaseModel):
    version: Any = None
    confirm: Any = None


def _mod(name):
    return importlib.import_module("planning." + name)


def _conflict(msg, job=None):
    return JSONResponse({"ok": False, "error": msg, "busy": job}, status_code=409)


def _start(kind, target=None, **params):
    try:
        return {"ok": True, "job": jobs.start(kind, target, **params)}
    except jobs.Busy as exc:
        return _conflict(str(exc), jobs.busy())
    except jobs.CapReached as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=429)


def _snapshot_summary(s):
    # type: (Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]
    if not s:
        return None
    return {k: s.get(k) for k in ("id", "taken_at", "reason", "mode", "as_of", "counts", "totals")}


def _config():
    # type: () -> Dict[str, Any]
    try:
        return _mod("adapters").config_public()
    except Exception as exc:
        return {"error": "config unavailable: %s" % exc}


def _platform_mode(cfg):
    # type: (Dict[str, Any]) -> str
    return str(cfg.get("mode") or "sample") if isinstance(cfg, dict) else "sample"


# -------------------------------------------------------------------- index

@router.get("/")
def index():
    cfg = _config()
    try:
        latest = _mod("snapshot").latest()
    except Exception:
        latest = None
    return {"ok": True, "mode": _platform_mode(cfg), "llm_mode": llm.mode(), "llm_configured": llm.configured(),
            "model": llm.MODEL, "effort": llm.EFFORT, "config": cfg,
            "latest_snapshot": _snapshot_summary(latest), "latest_analysis": records.latest_analysis(),
            "changesets": [records.changeset_summary(c) for c in records.list_changesets()],
            "eta": jobs.etas(), "busy": jobs.busy(),
            "limits": {"max_chars": jobs.MAX_CHARS, "calls_left_today": jobs.calls_left(),
                       "max_calls_per_day": jobs.MAX_CALLS_PER_DAY}}


# ------------------------------------------------------------------ analyze

@router.post("/analyze")
def analyze():
    return _start("analyze")


@router.get("/jobs/{job_id}")
def job(job_id):
    # type: (str) -> Dict[str, Any]
    return {"ok": True, "job": jobs.get(job_id)}


@router.get("/analyses/latest")
def latest_analysis():
    return {"ok": True, "analysis": records.latest_analysis()}


@router.get("/analyses/{analysis_id}")
def analysis(analysis_id):
    # type: (str) -> Dict[str, Any]
    return {"ok": True, "analysis": records.get_analysis(analysis_id)}


# ---------------------------------------------------------------- snapshots

@router.get("/snapshots")
def snapshots():
    return {"ok": True, "snapshots": _mod("snapshot").list_snapshots()}


@router.get("/snapshots/{snapshot_id}")
def snapshot(snapshot_id):
    # type: (str) -> Dict[str, Any]
    return {"ok": True, "snapshot": _mod("snapshot").get(snapshot_id)}


@router.get("/snapshots/{snapshot_id}/yaml")
def snapshot_yaml(snapshot_id):
    # type: (str) -> Response
    snap_mod = _mod("snapshot")
    text = snap_mod.to_yaml(snap_mod.get(snapshot_id))
    return Response(text, media_type="text/yaml",
                    headers={"Content-Disposition": 'attachment; filename="%s.yaml"' % snapshot_id})


# --------------------------------------------------------------- changesets

def _media_ids(raw):
    # type: (Any) -> List[str]
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [x for x in raw.replace(",", " ").split()]
    if not isinstance(raw, list):
        raise store.BadInput("media_ids must be a list of media ids")
    out = []
    for x in raw:
        x = str(x).strip().upper()
        if x and x not in out:
            out.append(x)
    return out[:20]


@router.post("/changesets")
def create_changeset(body: DraftBody):
    directive = jobs.check_text(body.directive, "directive")
    media_ids = _media_ids(body.media_ids)
    busy = jobs.busy()
    if busy:
        return _conflict("a planning job is already running (%s, %s)" % (busy["id"], busy["kind"]), busy)
    if jobs.calls_left() <= 0:
        return JSONResponse({"ok": False, "error": "daily LLM call limit reached"}, status_code=429)
    cs = records.new_changeset(directive, media_ids)
    res = _start("draft", cs["id"])
    if isinstance(res, JSONResponse):  # lost a race: drop the empty record's draft state
        cs = records.get_changeset(cs["id"])
        cs["status"] = "discarded"
        cs["last_error"] = "not started: another job was running"
        records.save_changeset(cs)
        return res
    res["changeset"] = records.get_changeset(cs["id"])
    return res


@router.get("/changesets")
def list_changesets():
    return {"ok": True, "changesets": [records.changeset_summary(c) for c in records.list_changesets()]}


@router.get("/changesets/{cs_id}")
def get_changeset(cs_id):
    # type: (str) -> Dict[str, Any]
    jobs.recover()
    return {"ok": True, "changeset": _with_requests(records.get_changeset(cs_id))}


def _with_requests(cs):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    """Versions stored before requests were rendered get them rendered now (not saved)."""
    for v in cs.get("versions") or []:
        if "requests" in v and "changeset_json" in v:
            continue
        v["changeset_json"] = jobs.version_json(v)
        v.pop("yaml", None)
        doc, errs = _mod("changeset").parse(v["changeset_json"])
        snap = None
        try:
            snap = _mod("snapshot").get(v.get("snapshot_id"))
        except store.NotFound:
            pass
        v["requests"] = _mod("executor").preview_requests(doc, snap) if doc and not errs else []
    return cs


@router.post("/changesets/{cs_id}/revise")
def revise(cs_id, body: ReviseBody):
    cs = records.get_changeset(cs_id)
    text = jobs.check_text(body.text, "revision text")
    if cs.get("status") in ("published", "discarded"):
        raise store.BadInput("changeset %s is %s; start a new one" % (cs_id, cs["status"]))
    if cs.get("status") == "drafting":
        return _conflict("changeset %s is still drafting" % cs_id, jobs.busy())
    if not cs.get("versions"):
        raise store.BadInput("changeset %s has no version to revise" % cs_id)
    res = _start("revise", cs_id, text=text)
    if isinstance(res, JSONResponse):
        return res
    res["changeset"] = records.get_changeset(cs_id)
    return res


@router.post("/changesets/{cs_id}/publish")
def publish(cs_id, body: PublishBody):
    cs = records.get_changeset(cs_id)
    if body.confirm is not True:
        raise store.BadInput("publish needs confirm: true")
    if isinstance(body.version, bool) or not isinstance(body.version, int):
        raise store.BadInput("version must be the integer version number you reviewed")
    if cs.get("status") != "ready":
        raise store.BadInput("changeset %s is %s; only a ready changeset can be published" % (cs_id, cs.get("status")))
    if body.version != cs.get("current_version"):
        raise store.BadInput("version %s is not the current version (v%s); review the current diff first"
                             % (body.version, cs.get("current_version")))
    v = records.current_version(cs)
    if v is None or any(x.get("level") == "error" for x in v.get("validation") or []):
        raise store.BadInput("version %s has validation errors" % body.version)
    changeset, executor = _mod("changeset"), _mod("executor")
    doc, errs = changeset.parse(jobs.version_json(v))
    if errs or doc is None:
        raise store.BadInput("stored changeset no longer parses: %s" % "; ".join(errs or ["empty"]))
    rows = ((v.get("diff") or {}).get("rows")) or []
    # the exact requests the reviewer saw; publish refuses if a fresh render differs
    result = executor.publish(doc, rows, v["snapshot_id"], expected_requests=v.get("requests") or None)
    attempt = {"version": v["n"], "at": records.now_iso(), "ok": bool(result.get("ok")),
               "verified": result.get("verified"), "drift": len(result.get("drift") or []),
               "post_snapshot_id": result.get("post_snapshot_id")}
    cs = records.get_changeset(cs_id)
    cs.setdefault("publish_attempts", []).append(attempt)
    cs["last_publish"] = result
    if result.get("ok"):
        cs["published"] = dict(result, version=v["n"], published_at=attempt["at"])
        cs["status"] = "published"
    records.save_changeset(cs)
    store.log_activity("planning.publish" if result.get("ok") else "planning.publish_refused", cs_id,
                       "v%s %s" % (v["n"], "applied" if result.get("ok") else
                                   ("drift on %d field(s)" % attempt["drift"] if attempt["drift"] else "failed")))
    return {"ok": bool(result.get("ok")), "publish": result, "changeset": cs}


@router.post("/changesets/{cs_id}/discard")
def discard(cs_id):
    # type: (str) -> Dict[str, Any]
    cs = records.get_changeset(cs_id)
    if cs.get("status") == "published":
        raise store.BadInput("changeset %s is already published" % cs_id)
    if cs.get("status") == "drafting":
        b = jobs.busy()
        if b and b.get("target") == cs_id:
            return _conflict("changeset %s is drafting; wait for the job to finish" % cs_id, b)
    cs["status"] = "discarded"
    records.save_changeset(cs)
    store.log_activity("planning.discard", cs_id, cs.get("title") or "")
    return {"ok": True, "changeset": cs}
