"""Deterministic reads of every test's statistical standing (no LLM).

For each test in state.json: observed value, a 95% interval, whether the minimum
spend/trials in its benchmark are met, and a verdict the analysis must quote, not redo.
- cost_per_trial: spend is fixed, trials are Poisson -> exact Poisson interval on trials,
  inverted to a cost-per-trial interval.
- click_to_trial: trials out of clicks (clicks derived from the test's own value) -> Wilson interval.
- ctr: clicks out of impressions for the test campaign since the test started (daily rows) -> Wilson interval.
"""

import math
from typing import Any, Dict, List, Optional, Tuple

import store

Z = 1.959964


def _pois_cdf(k, lam):
    # P(X <= k), X ~ Poisson(lam)
    if lam <= 0:
        return 1.0
    term = math.exp(-lam)
    total = term
    for i in range(1, k + 1):
        term *= lam / i
        total += term
    return min(total, 1.0)


def _bisect(f, lo, hi, iters=80):
    for _ in range(iters):
        mid = (lo + hi) / 2.0
        if f(mid):
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0


def poisson_ci(k, alpha=0.05):
    # type: (int, float) -> Tuple[float, float]
    """Exact (Garwood) interval for a Poisson count k."""
    hi_cap = max(10.0, k * 4.0 + 20)
    lower = 0.0 if k == 0 else _bisect(lambda lam: 1 - _pois_cdf(k - 1, lam) >= alpha / 2, 0.0, hi_cap)
    upper = _bisect(lambda lam: _pois_cdf(k, lam) <= alpha / 2, 0.0, hi_cap)
    return lower, upper


def wilson_ci(successes, n):
    # type: (float, float) -> Optional[Tuple[float, float]]
    if not n or n <= 0:
        return None
    p = successes / n
    denom = 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / denom
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def _campaign_totals_since(campaign_id, start):
    rows = store.daily_for(campaign_id=campaign_id, start=start)
    return store.aggregate(rows) if rows else {}


def read_test(t):
    # type: (Dict[str, Any]) -> Dict[str, Any]
    b = t.get("benchmark") or {}
    cur = t.get("current") or {}
    metric = t.get("metric")
    spend = float(cur.get("spend") or 0)
    trials = int(cur.get("trials") or 0)
    value = cur.get("value")
    win_below, win_above = b.get("win_below"), b.get("win_above")
    target = win_below if win_below is not None else win_above
    direction = "below" if win_below is not None else "above"
    min_spend, min_trials = float(b.get("min_spend") or 0), int(b.get("min_trials") or 0)
    out = {"test_id": t.get("id"), "name": t.get("name"), "hypothesis": t.get("hypothesis"),
           "platform": t.get("platform"), "campaign_id": t.get("campaign_id"), "status": t.get("status"),
           "started": t.get("started"), "ends": t.get("ends"), "metric": metric,
           "win_rule": "%s %s %s" % (metric, direction, target), "observed": value,
           "spend": round(spend, 2), "trials": trials, "min_spend": min_spend, "min_trials": min_trials,
           "minimums_met": spend >= min_spend and trials >= min_trials, "ci95": None, "sample": None}

    ci = None
    if metric == "cost_per_trial" and trials >= 0 and spend > 0:
        lo_k, hi_k = poisson_ci(trials)
        # CPT interval: spend / upper count .. spend / lower count (lower count 0 => unbounded)
        ci = (round(spend / hi_k, 2) if hi_k > 0 else None, round(spend / lo_k, 2) if lo_k > 0 else None)
        out["sample"] = "%d trials on $%s spend" % (trials, "{:,.0f}".format(spend))
    elif metric == "click_to_trial" and value:
        clicks = trials * 100.0 / float(value)
        w = wilson_ci(trials, clicks)
        ci = (round(w[0] * 100, 2), round(w[1] * 100, 2)) if w else None
        out["sample"] = "%d trials from about %s clicks" % (trials, "{:,.0f}".format(clicks))
    elif metric == "ctr":
        tot = _campaign_totals_since(t.get("campaign_id"), t.get("started"))
        clicks, imps = tot.get("clicks") or 0, tot.get("impressions") or 0
        w = wilson_ci(clicks, imps)
        ci = (round(w[0] * 100, 2), round(w[1] * 100, 2)) if w else None
        out["sample"] = "%s clicks on %s impressions, campaign level since %s" % (
            "{:,.0f}".format(clicks), "{:,.0f}".format(imps), t.get("started"))
    out["ci95"] = list(ci) if ci else None

    status = t.get("status")
    if status in ("won", "lost", "inconclusive"):
        out["verdict"] = "closed_" + status
        out["verdict_text"] = "Closed as %s. %s" % (status, t.get("notes") or "")
        return out
    if status == "queued":
        out["verdict"] = "not_started"
        out["verdict_text"] = "Queued, starts %s. %s" % (t.get("started"), t.get("notes") or "")
        return out

    clears_win = clears_loss = False
    if ci and target is not None:
        lo, hi = ci
        if direction == "below":
            clears_win = hi is not None and hi < target
            clears_loss = lo is not None and lo > target
        else:
            clears_win = lo is not None and lo > target
            clears_loss = hi is not None and hi < target
    shortfall = []
    if spend < min_spend:
        shortfall.append("spend $%s of $%s" % ("{:,.0f}".format(spend), "{:,.0f}".format(min_spend)))
    if trials < min_trials:
        shortfall.append("trials %d of %d" % (trials, min_trials))
    if out["minimums_met"] and clears_win:
        v, txt = "conclude_win", "Significant win: the 95% interval sits entirely on the winning side of the target, and minimums are met."
    elif out["minimums_met"] and clears_loss:
        v, txt = "conclude_loss", "Significant loss: the 95% interval sits entirely on the losing side of the target, and minimums are met."
    elif out["minimums_met"]:
        v, txt = "inconclusive_at_minimums", "Minimums met but the 95% interval still straddles the target; not significant."
    elif clears_win:
        v, txt = "trending_win_below_minimums", "Interval already clears the target, but below the benchmark minimums (%s); keep running." % ", ".join(shortfall)
    elif clears_loss:
        v, txt = "trending_loss_below_minimums", "Interval already misses the target, but below the benchmark minimums (%s); keep running or stop early on cost." % ", ".join(shortfall)
    else:
        v, txt = "keep_running", "Not enough data: %s, and the 95%% interval straddles the target." % ", ".join(shortfall or ["interval straddles the target"])
    out["verdict"], out["verdict_text"] = v, txt
    return out


def read_all():
    # type: () -> List[Dict[str, Any]]
    return [read_test(t) for t in store.get_state().get("tests", [])]
