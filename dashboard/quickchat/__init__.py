"""Quick Chat: one context document + a stateless chat call (Haiku 5.5, effort low).

The server keeps no chat history. Each browser stores its own history in localStorage
and sends at most the last 20 messages with every question. The API key never leaves
the Studio: calls go through planning.llm (ATLAS_LLM_CMD -> owner-vault secret.sh).
"""

import datetime
import hashlib
import json
import os
import threading
import time
from typing import Any, Dict, List, Tuple

import yaml

import store

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBSITE_PATH = os.path.join(BASE_DIR, "data", "context", "searchatlas-website.md")
PLAN_PATH = os.path.join(BASE_DIR, "data", "plan", "plan.yaml")
MEDIA_PATH = os.path.join(BASE_DIR, "data", "media.json")

MODEL = "claude-haiku-5-5"
EFFORT = "low"
MAX_HISTORY = 20          # messages (user + assistant) sent with each question
MAX_USER_CHARS = 4000
MAX_ASSISTANT_CHARS = 12000
MAX_TOKENS = 8000          # Haiku 5.5 thinks by default and thinking counts toward max_tokens
PER_IP_PER_HOUR = 40
GLOBAL_PER_DAY = 600

SYSTEM = """You are Quick Chat inside Search Atlas's Advertising Command Center, a paid-media dashboard for Google Ads and Meta.

Answer questions from the context document below: the company and its offerings (from searchatlas.com), the 30-day paid-media plan, the latest pulled state of the ad accounts, plan-vs-state facts, checklist progress, the latest analysis, the media library and recent activity.

- Be brief and direct. Lead with the answer. Use short bullets for lists.
- Use only facts and numbers in the context document or the conversation. If something is not there, say you don't have it.
- Say which source a number comes from when it matters (plan, account state as of the snapshot time, website).
- The ad-account data is sample data for a demo build, not a live account. Mention that only if asked or if it matters.
- Company context: the company and brand is Search Atlas. AgentStack is one Search Atlas offering (its own ads, landing page and 14-day-trial offer) and is what the 30-day plan sells.
- You cannot change anything in the accounts. For changes, point to the Plan & Adapt tab (brief, diff, manual publish)."""

_lock = threading.Lock()
_cache = {"key": None, "doc": None, "meta": None}
_rate = {"ip": {}, "day": None, "count": 0}


class ChatError(ValueError):
    pass


class RateLimited(RuntimeError):
    pass


# ----------------------------------------------------------------- context

def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


def _money(x):
    return "—" if x is None else "${:,.0f}".format(x)


def _num(x):
    return "—" if x is None else "{:,}".format(x)


def meta_campaign_daily(c):
    from planning.snapshot import meta_campaign_daily as f
    return f(c)


def _campaign_table(snap):
    rows = ["| Platform | Campaign | Status | Daily budget | Spend 7d | Trials 7d | CPT 7d | Spend MTD | Trials MTD | CPT MTD | Bidding |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for plat in ("google", "meta"):
        for c in (snap.get(plat) or {}).get("campaigns", []):
            m = c.get("metrics") or {}
            if plat == "google":
                daily = (c.get("budget") or {}).get("daily")
                bid = (c.get("bidding") or {}).get("strategy")
            else:
                daily = meta_campaign_daily(c)  # CBO budget, or its active ad sets' budgets (ABO)
                bid = c.get("bid_strategy")
            name = c["name"] + (" (legacy)" if c.get("legacy") else "")
            rows.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                "Google" if plat == "google" else "Meta", name, c.get("status"), _money(daily),
                _money(m.get("spend_7d")), _num(m.get("trials_7d")), _money(m.get("cpt_7d")),
                _money(m.get("spend_mtd")), _num(m.get("trials_mtd")), _money(m.get("cpt_mtd")), bid or "—"))
    return "\n".join(rows)


def _pacing_lines():
    out = []
    for label, plat in (("All", None), ("Google", "google"), ("Meta", "meta")):
        p = store.pacing(plat)
        out.append("- %s: MTD spend %s of %s monthly budget, pace %s%%, projected month end at current daily budgets %s (enabled daily budgets %s/day), day %s of %s." % (
            label, _money(p.get("month_to_date_spend")), _money(p.get("monthly_budget")), p.get("pace_pct"),
            _money(p.get("projected_month_end")), _money(p.get("active_daily_budget")), p.get("days_elapsed"), p.get("days_in_month")))
    mtd = store.month_to_date()
    w7 = store.window_totals(None, 7)
    out.append("- Trials MTD %s at %s per trial; last 7 days %s trials at %s per trial (PostHog-attributed)." % (
        _num(mtd.get("trials")), _money(mtd.get("cost_per_trial")), _num(w7.get("trials")), _money(w7.get("cost_per_trial"))))
    return "\n".join(out)


def _checklist():
    st = store.get_state()
    today = store.today()
    done = total = 0
    overdue, todays = [], []
    for day in st.get("checklist", []):
        for it in day.get("items", []):
            total += 1
            done += 1 if it.get("done") else 0
            if day.get("date") == today:
                todays.append("%s [%s]" % (it.get("text"), "done" if it.get("done") else "open"))
            elif day.get("date") < today and not it.get("done"):
                overdue.append("%s (%s)" % (it.get("text"), day.get("date")))
    lines = ["- %d of %d items done across the 30 days." % (done, total)]
    lines.append("- Today (%s): %s" % (today, "; ".join(todays) or "nothing scheduled"))
    lines.append("- Overdue: %s" % ("; ".join(overdue) or "none"))
    return "\n".join(lines)


def _latest_analysis():
    try:
        from planning import records
        a = records.latest_analysis() if hasattr(records, "latest_analysis") else None
    except Exception:
        a = None
    if not a:
        return "No Analyze run yet."
    parts = ["From Analyze %s (%s, snapshot %s):" % (a.get("id"), a.get("created_at"), a.get("snapshot_id"))]
    for it in a.get("items") or []:
        parts.append("- [%s] %s. Plan: %s Running: %s Testing: %s Evidence: %s Recommendation: %s%s" % (
            it.get("priority"), it.get("title"), it.get("plan"), it.get("running"), it.get("testing"), it.get("evidence"),
            it.get("recommendation"), (" Further research: " + it["research"]) if it.get("research") else ""))
    if a.get("items"):
        parts.extend("- Note: " + n for n in a.get("notes") or [])
        return "\n".join(parts)
    for key, title in (("plan_status", "Where the plan stands"), ("state_summary", "What the account shows")):
        parts.append("%s:" % title)
        parts.extend("- " + b for b in a.get(key) or [])
    parts.append("Recommendations:")
    parts.extend("- [%s] %s" % (r.get("priority"), r.get("text")) for r in a.get("recommendations") or [])
    return "\n".join(parts)


def _media():
    try:
        assets = json.load(open(MEDIA_PATH)).get("assets", [])
    except (OSError, ValueError):
        return "Media library unavailable."
    lines = []
    for a in assets:
        lines.append("- %s | %s | %s | %s%s" % (a.get("id"), a.get("status"), a.get("kind"), a.get("title"),
                                              (" | Ad Library ID " + a["meta_library_id"]) if a.get("meta_library_id") else ""))
    return "\n".join(lines)


def _activity():
    acts = store.recent_activity(15)
    if not acts:
        return "No changes logged."
    return "\n".join("- %s %s: %s %s" % (a.get("ts"), a.get("actor"), a.get("action"), a.get("target")) for a in acts)


def _account_inputs():
    # type: () -> Tuple[Any, ...]
    """What the account state is built from: state.json and the sample overlay (bids,
    targets and other platform fields that state.json does not hold). Their content
    hashes key the cache, so any direct control change or publish rebuilds the context
    (an mtime can repeat within a second; a hash cannot miss a change)."""
    from planning.adapters import sample
    out = []
    for path in (store.STATE_PATH, sample.overlay_path()):
        try:
            with open(path, "rb") as fh:
                out.append(hashlib.sha256(fh.read()).hexdigest())
        except OSError:
            out.append(None)
    return tuple(out)


def _snapshot():
    """The account state as it is now (built from the live sample state, not saved), plus
    the latest saved Analyze snapshot for reference. Quick Chat must never answer from a
    snapshot older than the last change."""
    from planning import snapshot
    snap = snapshot.build()
    try:
        saved = snapshot.latest()
    except Exception:
        saved = None
    label = "current account state"
    if saved:
        label += "; latest Analyze snapshot %s (%s)" % (saved.get("id"), saved.get("taken_at"))
    return snap, label


def build_context(force=False):
    # type: (bool) -> Tuple[str, Dict[str, Any]]
    """The single context document (Markdown) and its metadata. Cached until an input changes."""
    from planning import snapshot as snapmod, plan_compare
    try:
        from planning import records
        analyses_m = _mtime(records.path(records.ANALYSES_FILE))
    except Exception:
        analyses_m = 0
    key = (_account_inputs(), store.today(), _mtime(PLAN_PATH), _mtime(MEDIA_PATH), _mtime(WEBSITE_PATH),
           analyses_m, store.STATE_PATH)
    with _lock:
        if not force and _cache["key"] == key:
            return _cache["doc"], _cache["meta"]
    snap, label = _snapshot()
    plan_text = open(PLAN_PATH).read()
    try:
        facts = plan_compare.compare(plan_compare.load_plan(), snap)
    except Exception as exc:
        facts = [{"kind": "error", "note": "plan comparison failed: %s" % exc}]
    website = open(WEBSITE_PATH).read() if os.path.exists(WEBSITE_PATH) else "Website summary not available."
    taken = snap.get("taken_at") or "now"
    generated = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    compact = yaml.safe_dump(snapmod.compact(snap), sort_keys=False, allow_unicode=True, width=120)
    doc = "\n\n".join([
        "# Search Atlas: Quick Chat context document",
        "Generated %s. Account data is SAMPLE data (no live ad account is connected). Sample-data today is %s.\n"
        "Sections: 1 Company and offerings, 2 Account state summary, 3 Plan vs state facts, 4 Checklist, "
        "5 Latest analysis, 6 Media library, 7 Recent changes, 8 The 30-day plan (YAML), 9 Full account state (YAML)." % (generated, store.today()),
        "## 1. Company and offerings (searchatlas.com)\n\n" + website.strip(),
        "## 2. Account state summary\n\nState document %s, pulled %s%s.\n\n%s\n\n%s" % (
            snap.get("id"), taken, (" (" + label + ")") if label else "", _pacing_lines(), _campaign_table(snap)),
        "## 3. Plan vs state facts (computed by code)\n\n" + "\n".join(
            "- [%s] %s%s" % (f.get("kind"), (f.get("campaign") + ": ") if f.get("campaign") else "", f.get("note") or "") for f in facts),
        "## 4. 30-day checklist\n\n" + _checklist(),
        "## 5. Latest analysis\n\n" + _latest_analysis(),
        "## 6. Media library (IDs usable in Plan & Adapt briefs)\n\n" + _media(),
        "## 7. Recent changes (activity log)\n\n" + _activity(),
        "## 8. The 30-day plan (plan.yaml)\n\n```yaml\n" + plan_text.strip() + "\n```",
        "## 9. Full account state (state document %s, compact)\n\n```yaml\n%s```" % (snap.get("id"), compact),
    ])
    meta = {"generated_at": generated, "snapshot_id": snap.get("id"), "snapshot_taken_at": snap.get("taken_at"),
            "snapshot_note": label, "chars": len(doc)}
    with _lock:
        _cache.update(key=key, doc=doc, meta=meta)
    return doc, meta


# -------------------------------------------------------------------- chat

def _check_rate(ip):
    now = time.time()
    day = datetime.date.today().isoformat()
    with _lock:
        if _rate["day"] != day:
            _rate.update(day=day, count=0)
        if _rate["count"] >= GLOBAL_PER_DAY:
            raise RateLimited("Quick Chat hit its daily limit (%d messages). Try again tomorrow." % GLOBAL_PER_DAY)
        hits = [t for t in _rate["ip"].get(ip, []) if now - t < 3600]
        if len(hits) >= PER_IP_PER_HOUR:
            raise RateLimited("Too many messages from this connection in the last hour (limit %d)." % PER_IP_PER_HOUR)
        hits.append(now)
        _rate["ip"][ip] = hits
        _rate["count"] += 1


def clean_messages(messages):
    # type: (Any) -> List[Dict[str, str]]
    if not isinstance(messages, list) or not messages:
        raise ChatError("messages must be a non-empty list")
    msgs = []
    for m in messages[-MAX_HISTORY:]:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant") or not isinstance(m.get("content"), str):
            raise ChatError("each message needs role user|assistant and string content")
        text = m["content"].strip()
        if not text:
            continue
        limit = MAX_USER_CHARS if m["role"] == "user" else MAX_ASSISTANT_CHARS
        if len(text) > limit:
            if m["role"] == "user":
                raise ChatError("a message is over %d characters" % MAX_USER_CHARS)
            text = text[:limit]
        if msgs and msgs[-1]["role"] == m["role"]:
            msgs[-1]["content"] += "\n\n" + text      # merge back-to-back turns of the same role
        else:
            msgs.append({"role": m["role"], "content": text})
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    if not msgs or msgs[-1]["role"] != "user":
        raise ChatError("the last message must be the user's question")
    return msgs


def send(messages, ip="unknown"):
    # type: (Any, str) -> Dict[str, Any]
    from planning import llm
    msgs = clean_messages(messages)
    _check_rate(ip)
    doc, meta = build_context()
    system = [{"type": "text", "text": SYSTEM},
              {"type": "text", "text": doc, "cache_control": {"type": "ephemeral"}}]

    def _stub():
        return ("Stub reply (ATLAS_LLM_MODE=stub). Context document %s from state document %s, %s characters. "
                "You asked: %s" % (meta["generated_at"], meta["snapshot_id"], meta["chars"], msgs[-1]["content"][:200]))
    res = llm.call(system, msgs, max_tokens=MAX_TOKENS, stub=_stub, model=MODEL, effort=EFFORT)
    return {"reply": res.get("text", "").strip(), "model": res.get("model"), "seconds": res.get("seconds"),
            "usage": res.get("usage") or {}, "context": meta}
