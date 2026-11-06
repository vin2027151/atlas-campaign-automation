"""Publish a reviewed changeset. Deterministic, no LLM: a human triggers this by hand.

    publish(doc, expected_rows, base_snapshot_id, expected_requests=None) -> {
        "ok", "mode", "pre_snapshot_id", "post_snapshot_id",
        "drift": [{"op", "field", "expected_before", "actual"}],   # non-empty => nothing applied
        "results": [{"op", "step", "status": "applied"|"failed"|"skipped",
                     "request": {method, url, headers, body, curl}, "response", "message"}],
        "verified": bool,                                          # post snapshot matches the dry run
        "error": str | None }
    preview_requests(doc, snapshot=None) -> [rendered request]     # planning.api_requests.render_all

Order: re-validate -> fresh snapshot -> drift check (values AND the rendered requests the
reviewer saw) -> send each rendered request in order through the adapter (stop at the first
failure, mark the rest skipped) -> post snapshot -> verify. What runs is the rendered request:
the sample adapter parses it back and applies it, a live adapter sends it.

Never imports planning.llm, planning.llm_worker, planning.prompts or anthropic.
"""

import copy
from typing import Any, Dict, List, Optional

import planning
import store
from planning import adapters, api_requests, changeset, snapshot
from planning.adapters.base import outputs_from_response

FLOAT_TOL = 0.005


def _same(a, b):
    # type: (Any, Any) -> bool
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= FLOAT_TOL
    if isinstance(a, dict) and isinstance(b, dict):
        keys = set(a) | set(b)
        return all(_same(a.get(k), b.get(k)) for k in keys)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def _as_doc(doc):
    if isinstance(doc, str):
        parsed, errors = changeset.parse(doc)
        return parsed, errors
    return copy.deepcopy(doc), []


def _row_key(r):
    return (r.get("op"), r.get("entity_id"), r.get("field"), r.get("action"))


def _drift(expected_rows, fresh_rows):
    # type: (List[Dict[str, Any]], List[Dict[str, Any]]) -> List[Dict[str, Any]]
    fresh = dict((_row_key(r), r) for r in fresh_rows)
    out = []
    for r in expected_rows or []:
        if r.get("action") == "create":
            if _row_key(r) not in fresh:
                out.append({"op": r.get("op"), "field": r.get("field"), "expected_before": None,
                            "actual": "create no longer valid"})
            continue
        f = fresh.get(_row_key(r))
        if f is None:
            out.append({"op": r.get("op"), "field": r.get("field"), "expected_before": r.get("before"),
                        "actual": "entity no longer in the account"})
        elif not _same(f.get("before"), r.get("before")):
            out.append({"op": r.get("op"), "field": r.get("field"), "expected_before": r.get("before"),
                        "actual": f.get("before")})
    return out


def _find_created(post, row):
    # type: (Dict[str, Any], Dict[str, Any]) -> bool
    a = row.get("after") or {}
    et = row.get("entity_type")
    g, m = post.get("google") or {}, post.get("meta") or {}
    if et == "keyword":
        hit = changeset.find_entity(post, a.get("ad_group_id"))
        return bool(hit) and any(k["text"] == a.get("text") and k["match"] == a.get("match")
                                 for k in hit[1].get("keywords") or [])
    if et == "negative_keyword":
        hit = changeset.find_entity(post, a.get("campaign_id"))
        return bool(hit) and any(n["text"] == a.get("text") and n["match"] == a.get("match")
                                 for n in hit[1].get("negatives") or [])
    if et == "ad" and row.get("platform") == "google":
        hit = changeset.find_entity(post, a.get("ad_group_id"))
        return bool(hit) and any(x.get("headlines") == a.get("headlines") and x.get("status") == a.get("status")
                                 for x in hit[1].get("ads") or [])
    if et == "ad":
        hit = changeset.find_entity(post, a.get("ad_set_id"))
        return bool(hit) and any(x["name"] == a.get("name") and x["status"] == a.get("status") and
                                 x.get("media_id") == a.get("media_id") for x in hit[1].get("ads") or [])
    if et == "image":
        return any(i.get("media_id") == a.get("media_id") for i in m.get("images") or [])
    if et == "video":
        return any(v.get("media_id") == a.get("media_id") for v in m.get("videos") or [])
    if et == "creative":
        return any(c.get("name") == a.get("name") for c in m.get("creatives") or [])
    if et == "asset":
        return any(x.get("media_id") == a.get("media_id") for x in g.get("assets") or [])
    return False


def verify(rows, post):
    # type: (List[Dict[str, Any]], Dict[str, Any]) -> List[str]
    """Rows whose dry-run "after" is not what the post snapshot shows (empty list = verified)."""
    bad = []
    for r in rows:
        if r["action"] == "create":
            if not _find_created(post, r):
                bad.append("%s: created %s not found" % (r["op"], r["entity_type"]))
            continue
        hit = changeset.find_entity(post, r["entity_id"])
        if r["action"] == "remove":
            if hit is not None:
                bad.append("%s: %s still present" % (r["op"], r["entity_name"]))
            continue
        if hit is None:
            bad.append("%s: %s missing after publish" % (r["op"], r["entity_name"]))
            continue
        actual = changeset.read_field(hit[1], r["field"])
        if not _same(actual, r["after"]):
            bad.append("%s: %s %s is %r, expected %r" % (r["op"], r["entity_name"], r["field"], actual, r["after"]))
    return bad


def _ctx(cfg, snap, outputs):
    return {"mode": cfg["mode"], "config": cfg, "snapshot": snap, "outputs": outputs}


def _entity_label(op, rows):
    for r in rows:
        if r["op"] == op.get("ref"):
            return r.get("entity_name") or str(r.get("entity_id"))
    return str(op.get("resource_name") or op.get("path") or op.get("ref"))


def preview_requests(doc, snap=None):
    # type: (Any, Optional[Dict[str, Any]]) -> List[Dict[str, Any]]
    """The exact request each op sends, numbered in run order (secrets redacted, refs as $ref text)."""
    d, _errors = _as_doc(doc)
    return api_requests.render_all(d or {}, snap)


def _request_mismatch(expected, fresh):
    # type: (List[Dict[str, Any]], List[Dict[str, Any]]) -> List[Dict[str, Any]]
    out = []
    by_op = dict((r.get("op"), r) for r in fresh)
    for r in expected or []:
        f = by_op.get(r.get("op"))
        if f is None or f.get("error") or not api_requests.same_call(r, f):
            out.append({"op": r.get("op"), "field": "request",
                        "expected_before": "%s %s" % (r.get("method"), r.get("url")),
                        "actual": (f or {}).get("error") or ("request differs from the reviewed one" if f else "op missing")})
    return out


def publish(doc, expected_rows, base_snapshot_id, expected_requests=None):
    # type: (Any, Optional[List[Dict[str, Any]]], Optional[str], Optional[List[Dict[str, Any]]]) -> Dict[str, Any]
    with planning.ACCOUNT_LOCK:
        return _publish(doc, expected_rows, base_snapshot_id, expected_requests)


def _publish(doc, expected_rows, base_snapshot_id, expected_requests):
    cfg = adapters.load_config()
    res = {"ok": False, "mode": cfg["mode"], "pre_snapshot_id": None, "post_snapshot_id": None,
           "drift": [], "results": [], "verified": False, "error": None}  # type: Dict[str, Any]
    d, perrs = _as_doc(doc)
    if d is None or perrs:
        res["error"] = "changeset does not parse: %s" % "; ".join(perrs)
        return res
    ops = d.get("operations") or []

    # 1. re-validate against the snapshot the diff was reviewed on
    base = None
    if base_snapshot_id:
        try:
            base = snapshot.get(base_snapshot_id)
        except store.NotFound as exc:
            res["error"] = str(exc)
            return res
        errs = [i for i in changeset.validate(d, base) if i["level"] == "error"]
        if errs:
            res["error"] = "changeset has validation errors: %s" % "; ".join(
                "%s: %s" % (i["op"], i["message"]) for i in errs)
            return res
        if expected_rows is None:
            expected_rows = changeset.dry_run(d, base)["rows"]
    if expected_rows is None:
        res["error"] = "expected_rows or base_snapshot_id is required"
        return res

    # 2. fresh snapshot
    try:
        pre = snapshot.pull(reason="pre-publish")
    except Exception as exc:
        res["error"] = "could not pull account state: %s" % exc
        return res
    res["pre_snapshot_id"] = pre["id"]
    errs = [i for i in changeset.validate(d, pre) if i["level"] == "error"
            and "based on" not in i["message"]]
    if errs:
        res["error"] = "changeset no longer validates against the account: %s" % "; ".join(
            "%s: %s" % (i["op"], i["message"]) for i in errs)
        return res

    # 3. drift: the values the diff showed, and the requests the reviewer read
    fresh = changeset.dry_run(d, pre)
    res["drift"] = _drift(expected_rows, fresh["rows"])
    rendered = api_requests.render_all(d, pre, cfg)
    if expected_requests:
        res["drift"] += _request_mismatch(expected_requests, rendered)
    if res["drift"]:
        res["error"] = "account changed since the diff was reviewed; nothing applied"
        return res

    # 4. send the rendered requests in order
    outputs = {}  # type: Dict[str, Dict[str, Any]]
    stopped = False
    for op, req in zip(ops, rendered):
        ref = op.get("ref")
        entry = {"op": ref, "step": req.get("step"), "status": "skipped", "request": None, "response": None,
                 "message": ""}
        res["results"].append(entry)
        if stopped:
            entry["request"] = req if not req.get("error") else None
            entry["message"] = "skipped after an earlier failure"
            continue
        try:
            if req.get("error"):
                raise ValueError(req["error"])
            adapter = adapters.get_adapter(op.get("platform"), cfg)
            ctx = _ctx(cfg, pre, outputs)
            sent = api_requests.resolve(req, outputs)
            entry["request"] = sent
        except Exception as exc:
            entry["status"] = "failed"
            entry["message"] = "could not build request: %s" % exc
            stopped = True
            continue
        try:
            response = adapter.execute_request(req, ctx)
        except Exception as exc:
            entry["status"] = "failed"
            entry["message"] = str(exc)
            stopped = True
            continue
        entry["status"] = "applied"
        entry["response"] = response
        entry["message"] = op.get("reason") or ""
        outputs[ref] = outputs_from_response(op, response)
        label = _entity_label(op, fresh["rows"])
        store.log_activity("api publish", label, "%s %s" % (ref, api_requests.log_line(sent)), actor="vin")

    # 5. post snapshot + verify
    try:
        post = snapshot.pull(reason="post-publish")
        res["post_snapshot_id"] = post["id"]
        problems = verify(fresh["rows"], post) if not stopped else ["publish stopped at a failed op"]
    except Exception as exc:
        problems = ["could not pull post-publish state: %s" % exc]
    res["verified"] = not problems
    res["ok"] = (not stopped) and res["verified"]
    if problems:
        res["error"] = "; ".join(problems)
    return res
