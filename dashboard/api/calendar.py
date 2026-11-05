"""Calendar page API: the content pipeline and the test board.

GET  /api/calendar/                       content grouped by status, flat list, tests with verdicts
POST /api/calendar/content                create a content item
POST /api/calendar/content/{id}/move      {"status": one of store.CONTENT_STATUSES}
POST /api/calendar/content/{id}           edit name / due / owner / notes (and format/segment/platform)
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body

import store

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

STATUS_LABELS = {
    "running": "Running",
    "scheduled": "Scheduled to build",
    "pending_feedback": "Pending Vin's feedback",
    "final_pending_approval": "Final pending approval",
    "approved": "Approved",
}
PLATFORMS = ("google", "meta")
SEGMENTS = ("agency", "individual", "brand", "mixed")
# A due date only means "late" while the item is still in the build/review pipeline.
OPEN_STATUSES = ("scheduled", "pending_feedback", "final_pending_approval")
EDITABLE = ("name", "due", "owner", "notes", "format", "segment", "platform", "campaign_id", "test_id")

METRICS = {
    "cost_per_trial": {"label": "cost per trial", "unit": "money"},
    "ctr": {"label": "CTR", "unit": "pct"},
    "click_to_trial": {"label": "click-to-trial rate", "unit": "pct"},
}


# ------------------------------------------------------------------- helpers

def _fmt_value(v, unit):
    # type: (Any, str) -> str
    if v is None:
        return "n/a"
    if unit == "money":
        return "${:,.0f}".format(v)
    if unit == "pct":
        return "{:g}%".format(round(v, 2))
    return str(v)


def _campaign_name(cid):
    # type: (Optional[str]) -> Optional[str]
    if not cid:
        return None
    try:
        return store.campaign(cid)["name"]
    except store.NotFound:
        return None


def _test_name(tid):
    # type: (Optional[str]) -> Optional[str]
    if not tid:
        return None
    try:
        return store.test(tid)["name"]
    except store.NotFound:
        return None


def _decorate_content(item):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    out = dict(item)
    t = store.today()
    due = item.get("due")
    out["campaign_name"] = _campaign_name(item.get("campaign_id"))
    out["test_name"] = _test_name(item.get("test_id"))
    out["status_label"] = STATUS_LABELS.get(item["status"], item["status"])
    out["overdue"] = bool(due and due < t and item["status"] in OPEN_STATUSES)
    out["days_until_due"] = (store.parse_date(due) - store.parse_date(t)).days if due else None
    return out


def benchmark_text(test):
    # type: (Dict[str, Any]) -> str
    """Plain-words benchmark, e.g. 'WIN if cost per trial < $260 after >= $4,000 spend and >= 15 trials'."""
    m = METRICS.get(test.get("metric"), {"label": test.get("metric", "metric"), "unit": ""})
    b = test.get("benchmark") or {}
    if "win_below" in b:
        cond = "%s < %s" % (m["label"], _fmt_value(b["win_below"], m["unit"]))
    elif "win_above" in b:
        cond = "%s > %s" % (m["label"], _fmt_value(b["win_above"], m["unit"]))
    else:
        cond = m["label"]
    gates = []
    if b.get("min_spend"):
        gates.append(u"≥ ${:,.0f} spend".format(b["min_spend"]))
    if b.get("min_trials"):
        gates.append(u"≥ %d trials" % b["min_trials"])
    return "WIN if %s%s" % (cond, (" after " + " and ".join(gates)) if gates else "")


def evaluate(test):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    """Verdict for a test against its benchmark.

    verdict: "on_track" | "failing" | "not_enough_data" for running tests, else the
    test's own status ("queued" | "won" | "lost" | "inconclusive"). ``leaning`` is the
    direction the metric points right now, even before the data gates are cleared.
    """
    b = test.get("benchmark") or {}
    cur = test.get("current") or {}
    spend = float(cur.get("spend") or 0)
    trials = int(cur.get("trials") or 0)
    value = cur.get("value")
    min_spend = float(b.get("min_spend") or 0)
    min_trials = int(b.get("min_trials") or 0)
    spend_pct = min(100.0, round(spend / min_spend * 100.0, 1)) if min_spend else 100.0
    trials_pct = min(100.0, round(trials / float(min_trials) * 100.0, 1)) if min_trials else 100.0

    passing = None  # type: Optional[bool]
    if value is not None:
        if "win_below" in b:
            passing = value < b["win_below"]
        elif "win_above" in b:
            passing = value > b["win_above"]
    readable = spend >= min_spend and trials >= min_trials
    leaning = None if passing is None else ("on_track" if passing else "failing")

    status = test.get("status")
    if status in ("won", "lost", "inconclusive", "queued"):
        verdict = status
    elif not readable or passing is None:
        verdict = "not_enough_data"
    else:
        verdict = leaning

    m = METRICS.get(test.get("metric"), {"label": test.get("metric"), "unit": ""})
    need = []
    if spend < min_spend:
        need.append("${:,.0f} more spend".format(min_spend - spend))
    if trials < min_trials:
        need.append("%d more trial%s" % (min_trials - trials, "" if min_trials - trials == 1 else "s"))
    shown = _fmt_value(value, m["unit"])

    if verdict == "on_track":
        line = "On track: %s %s beats the benchmark, with enough data to call it." % (m["label"], shown)
    elif verdict == "failing":
        line = "Failing: %s %s misses the benchmark, with enough data to call it." % (m["label"], shown)
    elif verdict == "not_enough_data":
        lean = ""
        if leaning:
            lean = ", leaning %s (%s %s)" % ("on track" if leaning == "on_track" else "failing", m["label"], shown)
        line = "Not enough data%s. Needs %s." % (lean, " and ".join(need) or "a metric reading")
    elif verdict == "queued":
        line = "Queued: starts %s." % test.get("started")
    else:
        line = test.get("notes") or verdict.capitalize()

    return {
        "verdict": verdict,
        "leaning": leaning,
        "readable": readable,
        "passing": passing,
        "spend_pct": spend_pct,
        "trials_pct": trials_pct,
        "verdict_line": line,
        "benchmark_text": benchmark_text(test),
        "metric_label": m["label"],
        "metric_unit": m["unit"],
        "metric_display": shown,
        "target": b.get("win_below", b.get("win_above")),
        "direction": "below" if "win_below" in b else ("above" if "win_above" in b else None),
    }


def _decorate_test(test):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    out = dict(test)
    out["campaign_name"] = _campaign_name(test.get("campaign_id"))
    out.update(evaluate(test))
    out["content_ids"] = [c["id"] for c in store.get_state()["content"] if c.get("test_id") == test["id"]]
    return out


def _clean_str(v, field, required=False, maxlen=200):
    # type: (Any, str, bool, int) -> str
    if field == "notes":
        s = str(v or "").strip()
        maxlen = 2000
    else:
        s = " ".join(str(v).split()) if v is not None else ""
    if required and not s:
        raise store.BadInput("%s is required" % field)
    if len(s) > maxlen:
        raise store.BadInput("%s is too long (max %d characters)" % (field, maxlen))
    return s


def _validate_fields(body, creating):
    # type: (Dict[str, Any], bool) -> Dict[str, Any]
    out = {}  # type: Dict[str, Any]
    if creating or "name" in body:
        out["name"] = _clean_str(body.get("name"), "name", required=True)
    if creating or "platform" in body:
        p = str(body.get("platform") or "").lower()
        if p not in PLATFORMS:
            raise store.BadInput("platform must be one of %s" % ", ".join(PLATFORMS))
        out["platform"] = p
    if creating or "format" in body:
        out["format"] = _clean_str(body.get("format"), "format", required=True, maxlen=40).lower()
    if creating or "segment" in body:
        s = str(body.get("segment") or "").lower()
        if s not in SEGMENTS:
            raise store.BadInput("segment must be one of %s" % ", ".join(SEGMENTS))
        out["segment"] = s
    if creating or "owner" in body:
        out["owner"] = _clean_str(body.get("owner"), "owner", required=True, maxlen=60)
    if creating or "due" in body:
        d = body.get("due")
        store.parse_date(d)  # BadInput on malformed
        out["due"] = d
    if creating:
        st = str(body.get("status") or "scheduled").lower()
        if st not in store.CONTENT_STATUSES:
            raise store.BadInput("status must be one of %s" % ", ".join(store.CONTENT_STATUSES))
        out["status"] = st
    if creating or "notes" in body:
        out["notes"] = _clean_str(body.get("notes"), "notes")
    for key in ("campaign_id", "test_id"):
        if key in body:
            v = body.get(key) or None
            if v:
                if key == "campaign_id":
                    store.campaign(v)  # NotFound -> 404
                else:
                    store.test(v)
            out[key] = v
    return out


# -------------------------------------------------------------------- routes

@router.get("/")
def index():
    state = store.get_state()
    t = store.today()
    items = sorted((_decorate_content(c) for c in state["content"]), key=lambda c: (c.get("due") or "", c["id"]))
    columns = [{"status": s, "label": STATUS_LABELS[s], "items": [c for c in items if c["status"] == s]}
               for s in store.CONTENT_STATUSES]
    tests = [_decorate_test(x) for x in state["tests"]]
    order = {"running": 0, "queued": 1, "won": 2, "lost": 3, "inconclusive": 4}
    tests.sort(key=lambda x: (order.get(x["status"], 9), x.get("started") or ""))
    horizon = store.shift(t, 13)  # today + next 13 = 14 days
    upcoming = [c for c in items if c.get("due") and t <= c["due"] <= horizon]
    overdue = [c for c in items if c["overdue"]]
    return {
        "ok": True,
        "today": t,
        "statuses": list(store.CONTENT_STATUSES),
        "status_labels": STATUS_LABELS,
        "platforms": list(PLATFORMS),
        "segments": list(SEGMENTS),
        "columns": columns,
        "content": items,
        "upcoming_14d": upcoming,
        "overdue": overdue,
        "tests": tests,
        "counts": {
            "content": len(items),
            "by_status": dict((col["status"], len(col["items"])) for col in columns),
            "tests_running": sum(1 for x in tests if x["status"] == "running"),
            "overdue": len(overdue),
        },
        "campaigns": [{"id": c["id"], "name": c["name"], "platform": c["platform"]} for c in state["campaigns"]],
    }


@router.post("/content")
def create_content(body: Dict[str, Any] = Body(...)):
    fields = _validate_fields(body, creating=True)
    existing = set(c["id"] for c in store.get_state()["content"])
    n = len(existing) + 1
    while "c%02d" % n in existing:
        n += 1
    item = {"id": "c%02d" % n, "name": fields["name"], "platform": fields["platform"],
            "format": fields["format"], "segment": fields["segment"], "status": fields["status"],
            "owner": fields["owner"], "due": fields["due"],
            "campaign_id": fields.get("campaign_id"), "test_id": fields.get("test_id"),
            "notes": fields["notes"]}

    def _apply(state):
        state["content"].append(item)
        return item

    store.mutate(_apply)
    store.log_activity("content.create", item["id"], "%s (%s, %s, due %s)" % (
        item["name"], item["platform"], STATUS_LABELS[item["status"]], item["due"]))
    return {"ok": True, "item": _decorate_content(item)}


@router.post("/content/{content_id}/move")
def move_content(content_id: str, body: Dict[str, Any] = Body(...)):
    status = str(body.get("status") or "").lower()
    if status not in store.CONTENT_STATUSES:
        raise store.BadInput("status must be one of %s" % ", ".join(store.CONTENT_STATUSES))
    item = store.move_content(content_id, status)  # 404 on unknown id; persists and logs content.move
    return {"ok": True, "item": _decorate_content(item)}


@router.post("/content/{content_id}")
def edit_content(content_id: str, body: Dict[str, Any] = Body(...)):
    store.content_item(content_id)  # 404 first
    unknown = [k for k in body if k not in EDITABLE]
    if unknown:
        raise store.BadInput("cannot edit %s here (editable: %s; use /move for status)" % (
            ", ".join(unknown), ", ".join(EDITABLE)))
    fields = _validate_fields(body, creating=False)
    if not fields:
        raise store.BadInput("nothing to change")

    def _apply(state):
        for c in state["content"]:
            if c["id"] == content_id:
                changed = [k for k in fields if c.get(k) != fields[k]]
                c.update(fields)
                return c, changed

    item, changed = store.mutate(_apply)
    store.log_activity("content.edit", content_id, "%s: %s" % (item["name"], ", ".join(changed) or "no change"))
    return {"ok": True, "item": _decorate_content(item)}
