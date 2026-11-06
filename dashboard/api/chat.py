"""Quick Chat API (/api/chat). Stateless: the browser owns the history."""

from typing import Any, Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

import quickchat
from planning import llm

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str
    content: str


class SendBody(BaseModel):
    messages: List[ChatMessage]


def _ip(request):
    # Cloudflare Tunnel sets CF-Connecting-IP; fall back to the socket peer.
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")


@router.get("/")
def info():
    # type: () -> Dict[str, Any]
    _, meta = quickchat.build_context()
    return {"ok": True, "model": quickchat.MODEL, "effort": quickchat.EFFORT, "llm_configured": llm.configured(),
            "llm_mode": llm.mode(), "context": meta,
            "limits": {"max_history": quickchat.MAX_HISTORY, "max_chars": quickchat.MAX_USER_CHARS,
                       "per_hour": quickchat.PER_IP_PER_HOUR}}


@router.get("/context", response_class=PlainTextResponse)
def context():
    doc, _ = quickchat.build_context()
    return PlainTextResponse(doc, media_type="text/markdown; charset=utf-8")


@router.post("/send")
def send(body: SendBody, request: Request):
    try:
        out = quickchat.send([m.dict() for m in body.messages], ip=_ip(request))
    except quickchat.ChatError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except quickchat.RateLimited as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=429)
    except llm.LLMError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    out["ok"] = True
    return out
