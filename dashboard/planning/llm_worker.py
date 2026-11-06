"""Out-of-process Claude call. The dashboard server never imports `anthropic` or holds the key.

stdin:  {"system": str, "messages": [...], "max_tokens": int}
stdout: {"ok": bool, "text": str, "stop_reason": str, "usage": {...}, "model": str, "seconds": float,
         "error": str (when ok is false)}

Run as `python -m planning.llm_worker` with ANTHROPIC_API_KEY in the environment (on the Studio
the key is injected by the owner vault wrapper for this process only).
"""

import json
import sys
import time

MODEL = "claude-opus-5-5"
EFFORT = "medium"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _usage(msg):
    u = getattr(msg, "usage", None)
    if u is None:
        return {}
    out = {}
    for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        v = getattr(u, k, None)
        if v is not None:
            out[k] = v
    return out


def _text(msg):
    parts = []
    for block in getattr(msg, "content", None) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts)


def run(req):
    import anthropic  # imported only here, inside the worker process

    client = anthropic.Anthropic()  # key from env ANTHROPIC_API_KEY
    kwargs = dict(model=MODEL, max_tokens=int(req.get("max_tokens") or 32000),
                  betas=[FALLBACK_BETA], system=req["system"], messages=req["messages"])
    t0 = time.time()
    try:
        stream_cm = client.beta.messages.stream(fallbacks="default", output_config={"effort": EFFORT}, **kwargs)
    except TypeError:
        # older SDK without the typed kwargs: send them in the raw body
        stream_cm = client.beta.messages.stream(
            extra_body={"fallbacks": "default", "output_config": {"effort": EFFORT}}, **kwargs)
    with stream_cm as stream:
        msg = stream.get_final_message()
    seconds = round(time.time() - t0, 2)
    stop = getattr(msg, "stop_reason", None)
    out = {"ok": True, "text": "", "stop_reason": stop, "usage": _usage(msg),
           "model": getattr(msg, "model", MODEL), "seconds": seconds}
    if stop == "refusal":
        details = getattr(msg, "stop_details", None)
        cat = getattr(details, "category", None) if details is not None else None
        out.update(ok=False, error="Opus 5.5 declined the request (refusal%s)" % (", " + cat if cat else ""))
        return out
    if stop == "max_tokens":
        out.update(ok=False, error="Opus 5.5 hit max_tokens before finishing; output truncated")
        return out
    out["text"] = _text(msg)
    return out


def main():
    try:
        req = json.loads(sys.stdin.read())
        out = run(req)
    except Exception as exc:  # report every failure as JSON so the caller can show it
        out = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc), "text": "",
               "stop_reason": None, "usage": {}, "model": MODEL, "seconds": 0}
    sys.stdout.write(json.dumps(out))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
