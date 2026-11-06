"""LLM front door for the planning layer. Never imports `anthropic`.

call() runs planning.llm_worker in a subprocess (or returns stub fixtures when
ATLAS_LLM_MODE=stub). The LLM only reads documents and writes proposals; it has no
path to an ad account. Publishing is planning.executor, triggered by a human.
"""

import json
import os
import shlex
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

MODEL = "claude-opus-5-5"
EFFORT = "medium"
MAX_TOKENS = 32000
TIMEOUT_S = 300
STUB_DELAY_S = 2.5

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class LLMError(RuntimeError):
    pass


class LLMNotConfigured(LLMError):
    pass


def mode():
    # type: () -> str
    """stub | cmd | key | none"""
    if os.environ.get("ATLAS_LLM_MODE", "").strip().lower() == "stub":
        return "stub"
    if os.environ.get("ATLAS_LLM_CMD", "").strip():
        return "cmd"
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return "key"
    return "none"


def configured():
    # type: () -> bool
    return mode() != "none"


def _command():
    # type: () -> List[str]
    m = mode()
    if m == "cmd":
        return shlex.split(os.environ["ATLAS_LLM_CMD"])
    if m == "key":
        return [sys.executable, "-m", "planning.llm_worker"]
    raise LLMNotConfigured("LLM not configured: set ATLAS_LLM_CMD or ANTHROPIC_API_KEY (or ATLAS_LLM_MODE=stub for fixtures)")


def call(system, messages, max_tokens=MAX_TOKENS, stub=None):
    # type: (str, List[Dict[str, Any]], int, Optional[Callable[[], str]]) -> Dict[str, Any]
    """One model call. Returns {ok, text, stop_reason, usage, model, seconds}; raises LLMError."""
    if mode() == "stub":
        t0 = time.time()
        time.sleep(STUB_DELAY_S)
        if stub is None:
            raise LLMError("no stub fixture for this call")
        return {"ok": True, "text": stub(), "stop_reason": "end_turn", "usage": {}, "model": MODEL + " (stub)",
                "seconds": round(time.time() - t0, 2)}
    cmd = _command()
    payload = json.dumps({"system": system, "messages": messages, "max_tokens": max_tokens})
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, input=payload, capture_output=True, text=True, timeout=TIMEOUT_S, cwd=BASE_DIR)
    except subprocess.TimeoutExpired:
        raise LLMError("Opus 5.5 call timed out after %d s" % TIMEOUT_S)
    except OSError as exc:
        raise LLMError("could not start the LLM worker: %s" % exc)
    out = None
    try:
        out = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else None
    except (ValueError, IndexError):
        out = None
    if not isinstance(out, dict):
        tail = (proc.stderr or "").strip().splitlines()[-1:] or ["no output"]
        raise LLMError("LLM worker failed (exit %s): %s" % (proc.returncode, tail[0][:300]))
    if not out.get("ok"):
        raise LLMError(out.get("error") or "LLM call failed (stop_reason %s)" % out.get("stop_reason"))
    out.setdefault("seconds", round(time.time() - t0, 2))
    return out


def parse_json(text):
    # type: (str) -> Optional[Dict[str, Any]]
    """First JSON object in text (tolerates ```json fences and surrounding prose)."""
    if not text:
        return None
    dec = json.JSONDecoder()
    i = text.find("{")
    while i != -1:
        try:
            obj, _ = dec.raw_decode(text, i)
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
        i = text.find("{", i + 1)
    return None


def ask_json(system, messages, stub=None, before_call=None, max_tokens=MAX_TOKENS):
    # type: (str, List[Dict[str, Any]], Optional[Callable[[], str]], Optional[Callable[[], None]], int) -> Tuple[Dict[str, Any], Dict[str, Any]]
    """Call, parse the first JSON object; on parse failure retry once. Returns (obj, call_meta).

    before_call() runs before every model call (used for the daily call cap / counter).
    """
    if before_call:
        before_call()
    res = call(system, messages, max_tokens=max_tokens, stub=stub)
    obj = parse_json(res.get("text", ""))
    if obj is None:
        if before_call:
            before_call()
        retry = list(messages) + [
            {"role": "assistant", "content": res.get("text") or "(empty)"},
            {"role": "user", "content": "That was not a valid JSON object. Reply with only the JSON object in the required shape."},
        ]
        res2 = call(system, retry, max_tokens=max_tokens, stub=stub)
        res2["seconds"] = round(float(res.get("seconds") or 0) + float(res2.get("seconds") or 0), 2)
        res = res2
        obj = parse_json(res.get("text", ""))
        if obj is None:
            raise LLMError("Opus 5.5 did not return a JSON object (after one retry)")
    return obj, res
