"""Media library API (prefix /api/media). Thin HTTP layer over the ``media`` module.

GET  /                      ?status=&kind=  -> {ok, assets, counts, statuses, kinds, campaigns}
GET  /{id}                  -> {ok, asset}
POST /requests              {title, description, kind, brief, due, platforms, placements} -> {ok, asset}  (requested)
POST /{id}/upload           multipart `file` (png/jpeg/webp/gif, mp4/mov, html/zip; <= 50 MB) -> {ok, asset}  (in_review)
POST /{id}/approve          {note?} -> {ok, asset}  (approved)
POST /{id}/reject           {note} (required) -> {ok, asset}  (back to requested)
POST /{id}                  {title, description, brief, tags, due, platforms, placements} -> {ok, asset}
Every mutation is logged through store.log_activity by the media module.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, File, UploadFile

import media
import store

router = APIRouter(prefix="/api/media", tags=["media"])

CHUNK = 1024 * 1024


def _campaigns():
    return [{"id": c["id"], "name": c["name"], "platform": c["platform"]} for c in store.get_state().get("campaigns", [])]


@router.get("/")
def list_media(status: Optional[str] = None, kind: Optional[str] = None):
    # type: (Optional[str], Optional[str]) -> Dict[str, Any]
    assets = media.list_assets(status=status or None, kind=kind or None)
    return {"ok": True, "assets": assets, "counts": media.counts(), "statuses": list(media.STATUSES),
            "status_labels": media.STATUS_LABELS, "kinds": list(media.KINDS), "campaigns": _campaigns(),
            "max_upload_bytes": media.MAX_UPLOAD_BYTES, "mimes": sorted(media.MIME_KIND)}


@router.post("/requests")
def create_request(body: Dict[str, Any] = Body(...)):
    if not isinstance(body, dict):
        raise store.BadInput("body must be an object")
    asset = media.create_request(
        title=body.get("title"), description=body.get("description", ""), kind=body.get("kind", "image"),
        brief=body.get("brief", ""), due=body.get("due"), platforms=body.get("platforms"),
        placements=body.get("placements"))
    return {"ok": True, "asset": asset}


@router.get("/{asset_id}")
def get_media(asset_id: str):
    return {"ok": True, "asset": media.get_asset(asset_id)}


@router.post("/{asset_id}/upload")
async def upload(asset_id: str, file: UploadFile = File(...)):
    media.get_asset(asset_id)  # 404 before reading the body
    if media.normalize_mime(file.content_type, file.filename or "") is None:
        raise store.BadInput("unsupported file type %r: use PNG, JPEG, WEBP, GIF, MP4, MOV, HTML or ZIP"
                             % (file.content_type or file.filename))
    buf = bytearray()
    while True:
        chunk = await file.read(CHUNK)
        if not chunk:
            break
        buf += chunk
        if len(buf) > media.MAX_UPLOAD_BYTES:
            raise store.BadInput("file is larger than 50 MB")
    asset = media.attach_file(asset_id, file.filename or "", file.content_type, bytes(buf))
    return {"ok": True, "asset": asset}


@router.post("/{asset_id}/approve")
def approve(asset_id: str, body: Optional[Dict[str, Any]] = Body(None)):
    note = (body or {}).get("note", "") if isinstance(body, dict) else ""
    return {"ok": True, "asset": media.approve(asset_id, note)}


@router.post("/{asset_id}/reject")
def reject(asset_id: str, body: Optional[Dict[str, Any]] = Body(None)):
    note = body.get("note") if isinstance(body, dict) else None
    media.get_asset(asset_id)
    return {"ok": True, "asset": media.reject(asset_id, note)}


@router.post("/{asset_id}")
def edit(asset_id: str, body: Dict[str, Any] = Body(...)):
    media.get_asset(asset_id)
    return {"ok": True, "asset": media.update(asset_id, body)}
