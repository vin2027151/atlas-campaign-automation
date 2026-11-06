"""Management page API: the media buyer's daily cockpit.

GET  /api/management/                          everything the page needs, in one call
                                               (includes needs_action: content waiting on Vin)
POST /api/management/checklist/{item_id}/toggle  flip (or set, with {"done": bool}) a checklist item
POST /api/management/lessons                   {text, tags} -> append a lesson

Everything is computed from store.get_state(); mutations go through the store
helpers (which persist and log activity themselves).
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body

import store
from api.calendar import _decorate_content

router = APIRouter(prefix="/api/management", tags=["management"])

PLATFORM_LABELS = {"google": "Google Ads", "meta": "Meta"}

# ---------------------------------------------------------------- the "read"
# One-word read per active campaign, from 7-day PostHog cost per trial against
# the CPA band (meta.cpa_target, $250-$280) and how much it has spent.
MIN_TRIALS_FOR_READ = 3        # below this, CPT is noise
WATCH_CEILING = 1.15           # up to 15% over the band ceiling is "watching"
SCALE_MIN_SPEND = 1000.0       # need this much 7d spend before calling it "scaling"


def read_rule(band):
    # type: (List[float]) -> Dict[str, Any]
    lo, hi = float(band[0]), float(band[1])
    watch_hi = round(hi * WATCH_CEILING)
    dry = round(hi * 2)
    return {
        "band": [lo, hi],
        "watch_ceiling": watch_hi,
        "min_trials": MIN_TRIALS_FOR_READ,
        "scale_min_spend": SCALE_MIN_SPEND,
        "dry_spend": dry,
        "reads": {
            "scaling": "7d CPT below $%d with at least $%s spent and %d+ trials: room to add budget." % (
                lo, "{:,.0f}".format(SCALE_MIN_SPEND), MIN_TRIALS_FOR_READ),
            "holding": "7d CPT inside the $%d-$%d band (or below it on thin spend): leave it alone." % (lo, hi),
            "watching": "7d CPT $%d-$%d (up to 15%% over the band), or fewer than %d trials so far: check daily." % (
                hi, watch_hi, MIN_TRIALS_FOR_READ),
            "failing": "7d CPT over $%d with %d+ trials, or $%s+ spent in 7 days with zero trials: cut or fix." % (
                watch_hi, MIN_TRIALS_FOR_READ, "{:,.0f}".format(dry)),
        },
        "summary": ("scaling: CPT < $%d, spend >= $%s | holding: CPT $%d-$%d | watching: CPT $%d-$%d or < %d trials"
                    " | failing: CPT > $%d, or >= $%s spend and 0 trials" % (
                        lo, "{:,.0f}".format(SCALE_MIN_SPEND), lo, hi, hi, watch_hi, MIN_TRIALS_FOR_READ,
                        watch_hi, "{:,.0f}".format(dry))),
    }


def campaign_read(w7, band):
    # type: (Dict[str, Any], List[float]) -> Dict[str, str]
    lo, hi = float(band[0]), float(band[1])
    watch_hi = hi * WATCH_CEILING
    spend, trials, cpt = w7["spend"], w7["trials"], w7["cost_per_trial"]
    if trials == 0:
        if spend >= hi * 2:
            return {"read": "failing", "why": "$%s spent in 7 days with zero trials." % _n(spend)}
        return {"read": "watching", "why": "No trials yet on $%s of 7-day spend." % _n(spend)}
    if trials < MIN_TRIALS_FOR_READ:
        if cpt > watch_hi and spend >= hi * 2:
            return {"read": "failing", "why": "%d trial(s) at $%s each, already %s over the ceiling." % (
                trials, _n(cpt), _pct_over(cpt, hi))}
        return {"read": "watching", "why": "Only %d trial(s) in 7 days; $%s CPT is not a read yet." % (trials, _n(cpt))}
    if cpt < lo:
        if spend >= SCALE_MIN_SPEND:
            return {"read": "scaling", "why": "$%s CPT is under the $%d floor on $%s spend." % (_n(cpt), lo, _n(spend))}
        return {"read": "holding", "why": "$%s CPT is under the floor, but only $%s spent." % (_n(cpt), _n(spend))}
    if cpt <= hi:
        return {"read": "holding", "why": "$%s CPT is inside the $%d-$%d band." % (_n(cpt), lo, hi)}
    if cpt <= watch_hi:
        return {"read": "watching", "why": "$%s CPT is %s over the $%d ceiling." % (_n(cpt), _pct_over(cpt, hi), hi)}
    return {"read": "failing", "why": "$%s CPT is %s over the $%d ceiling." % (_n(cpt), _pct_over(cpt, hi), hi)}


def _n(x):
    # type: (Any) -> str
    return "{:,.0f}".format(float(x))


def _pct_over(v, base):
    # type: (float, float) -> str
    return "%d%%" % round((v / base - 1) * 100)


# ------------------------------------------------------------------ sections

def _checklist(today):
    # type: (str) -> Dict[str, Any]
    state = store.get_state()
    days = []
    carry = []
    today_day = None
    for d in sorted(state.get("checklist", []), key=lambda x: x["day"]):
        done = sum(1 for it in d["items"] if it["done"])
        when = "past" if d["date"] < today else ("today" if d["date"] == today else "future")
        days.append({"day": d["day"], "date": d["date"], "when": when, "done": done,
                     "total": len(d["items"]), "items": d["items"]})
        if when == "today":
            today_day = d["day"]
        if when == "past":
            for it in d["items"]:
                if not it["done"]:
                    carry.append({"day": d["day"], "date": d["date"], "id": it["id"], "text": it["text"],
                                  "done": False, "age_days": (store.parse_date(today) - store.parse_date(d["date"])).days})
    return {"days": days, "today_day": today_day, "carry_over": carry}


def _in_play(band):
    # type: (List[float]) -> Dict[str, Any]
    groups = {}  # type: Dict[str, List[Dict[str, Any]]]
    paused = []
    counts = {"scaling": 0, "holding": 0, "watching": 0, "failing": 0}
    for c in store.campaigns():
        w7 = store.window_totals(c["id"], 7)
        row = {
            "id": c["id"], "name": c["name"], "platform": c["platform"], "type": c.get("type"),
            "country": c.get("country"), "segment": c.get("segment"), "legacy": bool(c.get("legacy")),
            "start_date": c.get("start_date"), "status": c["status"],
            "daily_budget": c["daily_budget"], "spend_7d": w7["spend"], "trials_7d": w7["trials"],
            "cpt_7d": w7["cost_per_trial"], "clicks_7d": w7["clicks"], "click_to_trial_7d": w7["click_to_trial"],
        }
        if c["status"] != "ACTIVE":
            paused.append(row)
            continue
        r = campaign_read(w7, band)
        row.update(r)
        counts[r["read"]] += 1
        groups.setdefault(c["platform"], []).append(row)
    out = []
    for pl in ("google", "meta"):
        rows = groups.get(pl, [])
        rows.sort(key=lambda r: -r["spend_7d"])
        tot = store.window_totals(None, 7, platform=pl)
        out.append({"platform": pl, "label": PLATFORM_LABELS[pl], "campaigns": rows,
                    "totals": {"daily_budget": round(sum(r["daily_budget"] for r in rows), 2),
                               "spend_7d": tot["spend"], "trials_7d": tot["trials"], "cpt_7d": tot["cost_per_trial"]}})
    return {"groups": out, "paused": paused, "counts": counts, "rule": read_rule(band)}


def _test_verdict(t, today):
    # type: (Dict[str, Any], str) -> Dict[str, Any]
    b, cur = t["benchmark"], t["current"]
    v = cur.get("value")
    if "win_below" in b:
        target, direction = b["win_below"], "below"
        beating = v is not None and v < target
    else:
        target, direction = b.get("win_above"), "above"
        beating = v is not None and v > target
    enough_spend = cur.get("spend", 0) >= b.get("min_spend", 0)
    enough_trials = cur.get("trials", 0) >= b.get("min_trials", 0)
    days_left = (store.parse_date(t["ends"]) - store.parse_date(today)).days
    days_total = (store.parse_date(t["ends"]) - store.parse_date(t["started"])).days or 1
    elapsed = max(0, (store.parse_date(today) - store.parse_date(t["started"])).days)
    if v is None:
        verdict, tone, text = "no data", "idle", "No data yet."
    elif enough_spend and enough_trials:
        verdict, tone = ("winning", "good") if beating else ("losing", "bad")
        text = "Thresholds met; %s the benchmark." % ("beating" if beating else "missing")
    else:
        verdict, tone = ("trending win", "good") if beating else ("trending loss", "watch")
        need = []
        if not enough_spend:
            need.append("$%s more spend" % _n(b["min_spend"] - cur.get("spend", 0)))
        if not enough_trials:
            need.append("%d more trials" % (b["min_trials"] - cur.get("trials", 0)))
        text = "Too early to call: needs " + " and ".join(need) + "."
    return {"verdict": verdict, "tone": tone, "verdict_note": text, "target": target, "direction": direction,
            "days_left": days_left, "progress_pct": round(min(100.0, elapsed * 100.0 / days_total), 1),
            "spend_pct": round(min(100.0, cur.get("spend", 0) * 100.0 / (b.get("min_spend") or 1)), 1),
            "trials_pct": round(min(100.0, cur.get("trials", 0) * 100.0 / (b.get("min_trials") or 1)), 1)}


def _tests(today):
    # type: (str) -> Dict[str, Any]
    names = {c["id"]: c["name"] for c in store.campaigns()}
    running, ledger, queued = [], [], []
    for t in store.get_state().get("tests", []):
        row = dict(t)
        row["campaign_name"] = names.get(t.get("campaign_id"), t.get("campaign_id"))
        if t["status"] == "running":
            row.update(_test_verdict(t, today))
            running.append(row)
        elif t["status"] in ("won", "lost", "inconclusive"):
            b = t["benchmark"]
            row["target"] = b.get("win_below", b.get("win_above"))
            row["direction"] = "below" if "win_below" in b else "above"
            row["taught"] = t.get("notes", "")
            ledger.append(row)
        else:
            queued.append(row)
    running.sort(key=lambda r: r["ends"])
    ledger.sort(key=lambda r: r["ends"], reverse=True)
    tally = {k: sum(1 for r in ledger if r["status"] == k) for k in ("won", "lost", "inconclusive")}
    return {"running": running, "ledger": ledger, "queued": queued, "tally": tally}


def _ratio_status(ratio):
    # type: (Optional[float]) -> str
    if ratio is None:
        return "broken"
    if 0.85 <= ratio <= 1.15:
        return "ok"
    if 0.6 <= ratio <= 1.4:
        return "degraded"
    return "broken"


def _tracking(today):
    # type: (str) -> List[Dict[str, Any]]
    rows = []
    for pl, name, event in (("meta", "Meta StartTrial vs PostHog", "StartTrial"),
                            ("google", "Google conversions vs PostHog", "trial conversion action")):
        w = store.window_totals(None, 7, platform=pl)
        ratio = store.safe_div(w["platform_conversions"], w["trials"], 1.0, 2)
        st = _ratio_status(ratio)
        if ratio is None:
            note = "No PostHog trials in 7 days; cannot compare."
        else:
            direction = "under" if ratio < 1 else "over"
            note = "%s reports %s %s vs %d PostHog trials (7d): %d%% %s-counting." % (
                PLATFORM_LABELS[pl], "{:,.1f}".format(w["platform_conversions"]).rstrip("0").rstrip("."), event,
                w["trials"], abs(round((ratio - 1) * 100)), direction)
            if pl == "meta" and ratio < 0.85:
                note += " Meta deflation since 09-22; optimise on PostHog, not Ads Manager."
        rows.append({"id": "%s_ratio" % pl, "name": name, "status": st, "last_checked": today,
                     "ratio": ratio, "platform_value": w["platform_conversions"], "posthog_value": w["trials"],
                     "computed": True, "note": note})
    rows.extend([
        {"id": "uk_tag", "name": "UK signup tag (PostHog + Google)", "status": "ok", "last_checked": "2026-11-02",
         "computed": False, "note": "Fixed 11-02: tag was missing on the UK signup confirmation. Search_NonBrand_UK converting since."},
        {"id": "utm_coverage", "name": "UTM coverage on paid trials", "status": "degraded", "last_checked": "2026-11-04",
         "computed": False, "note": "~94% of paid-channel trials carry utm_source/utm_campaign; PMax asset links missing utm_content."},
        {"id": "paid_join_lag", "name": "Trial -> paid join lag", "status": "ok", "last_checked": "2026-11-05",
         "computed": False, "note": "Stripe -> PostHog join runs nightly; paid lags trials 7-14 days, so the last two weeks of trial-to-paid read low."},
    ])
    return rows


def _lessons():
    # type: () -> Dict[str, Any]
    ls = sorted(store.get_state().get("lessons", []), key=lambda l: (l["date"], l.get("id", "")), reverse=True)
    tags = {}  # type: Dict[str, int]
    for l in ls:
        for t in l.get("tags", []):
            tags[t] = tags.get(t, 0) + 1
    return {"items": ls, "tags": sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))}


def _needs_action():
    # type: () -> Dict[str, Any]
    """Content that is waiting on a person: overdue first, then final approvals, then Vin feedback.

    Same rules the Calendar page used for its queue (moved here); decoration comes from
    api.calendar so overdue / labels stay identical. Approve uses POST /api/calendar/content/{id}/move.
    """
    items = sorted((_decorate_content(c) for c in store.get_state()["content"]),
                   key=lambda c: (c.get("due") or "", c["id"]))
    out = []  # type: List[Dict[str, Any]]
    seen = set()
    for c in items:
        if c["overdue"]:
            seen.add(c["id"])
            out.append({"kind": "Overdue", "tone": "bad", "approve": c["status"] == "final_pending_approval", "item": c})
    for status, kind, approve in (("final_pending_approval", "Final approval", True),
                                  ("pending_feedback", "Vin feedback", False)):
        for c in items:
            if c["status"] == status and c["id"] not in seen:
                seen.add(c["id"])
                out.append({"kind": kind, "tone": "watch", "approve": approve, "item": c})
    return {"items": out, "counts": {
        "overdue": sum(1 for a in out if a["kind"] == "Overdue"),
        "final_approval": sum(1 for c in items if c["status"] == "final_pending_approval"),
        "feedback": sum(1 for c in items if c["status"] == "pending_feedback"),
    }}


def _today(today, checklist, band):
    # type: (str, Dict[str, Any], List[float]) -> Dict[str, Any]
    day = next((d for d in checklist["days"] if d["date"] == today), None)
    w7 = store.window_totals(None, 7)
    pace = store.pacing()
    cpt = w7["cost_per_trial"]
    lo, hi = band
    if cpt is None:
        cpt_state, cpt_tone = "no trials", "idle"
    elif cpt < lo:
        cpt_state, cpt_tone = "under band", "good"
    elif cpt <= hi:
        cpt_state, cpt_tone = "in band", "good"
    elif cpt <= hi * WATCH_CEILING:
        cpt_state, cpt_tone = "over band", "watch"
    else:
        cpt_state, cpt_tone = "well over band", "bad"
    pp = pace["pace_pct"]
    pace_tone = "idle" if pp is None else ("good" if 95 <= pp <= 105 else ("watch" if 90 <= pp <= 110 else "bad"))
    line = "7d CPT %s (%s, $%d-$%d) on %d trials; pacing %s of $%s." % (
        "$" + _n(cpt) if cpt is not None else "n/a", cpt_state, lo, hi, w7["trials"],
        ("%.1f%%" % pp) if pp is not None else "n/a", _n(pace["monthly_budget"]))
    return {
        "date": today, "day": day["day"] if day else None, "total_days": len(checklist["days"]),
        "done": day["done"] if day else 0, "total": day["total"] if day else 0,
        "carry_over": len(checklist["carry_over"]),
        "cpt_7d": cpt, "cpt_state": cpt_state, "cpt_tone": cpt_tone, "trials_7d": w7["trials"], "spend_7d": w7["spend"],
        "pace_pct": pp, "pace_tone": pace_tone, "projected": pace["projected_month_end"],
        "monthly_budget": pace["monthly_budget"], "status_line": line,
    }


def _schedule():
    # type: () -> List[Dict[str, Any]]
    """Every test decorated the way the Calendar page used to show it (benchmark text, verdict, progress)."""
    from api import calendar as cal
    tests = [cal._decorate_test(x) for x in store.get_state().get("tests", [])]
    order = {"running": 0, "queued": 1, "won": 2, "lost": 3, "inconclusive": 4}
    tests.sort(key=lambda x: (order.get(x["status"], 9), x.get("started") or ""))
    return tests


def build():
    # type: () -> Dict[str, Any]
    state = store.get_state()
    today = store.today()
    band = state["meta"].get("cpa_target", [250, 280])
    checklist = _checklist(today)
    return {
        "ok": True,
        "today": _today(today, checklist, band),
        "checklist": checklist,
        "needs_action": _needs_action(),
        "in_play": _in_play(band),        # not shown on Management any more; the Home page still reads it
        "tests": _tests(today),
        "schedule": _schedule(),          # testing schedule, moved here from the Calendar page
        "tracking": _tracking(today),
        "lessons": _lessons(),
        "activity": store.recent_activity(20),
        "band": band,
    }


# -------------------------------------------------------------------- routes

@router.get("/")
def index():
    return build()


@router.post("/checklist/{item_id}/toggle")
def toggle(item_id: str, body: Optional[Dict[str, Any]] = Body(default=None)):
    done = None
    if body and "done" in body:
        if not isinstance(body["done"], bool):
            raise store.BadInput("done must be true or false")
        done = body["done"]
    res = store.toggle_checklist(item_id, done)
    today = store.today()
    checklist = _checklist(today)
    day = next((d for d in checklist["days"] if d["day"] == res["day"]), None)
    return {"ok": True, "day": res["day"], "date": res["date"], "item": res["item"],
            "day_done": day["done"] if day else None, "day_total": day["total"] if day else None,
            "today": _today(today, checklist, store.get_state()["meta"].get("cpa_target", [250, 280])),
            "activity": store.recent_activity(20)}


@router.post("/lessons")
def add_lesson(body: Dict[str, Any] = Body(...)):
    tags = body.get("tags")
    if tags is not None and not isinstance(tags, (list, str)):
        raise store.BadInput("tags must be a list or a comma-separated string")
    lesson = store.add_lesson(body.get("text"), tags, source=str(body.get("source") or "manual"))
    return {"ok": True, "lesson": lesson, "lessons": _lessons(), "activity": store.recent_activity(20)}
