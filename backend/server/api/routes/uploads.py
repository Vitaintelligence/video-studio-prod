from __future__ import annotations

import hashlib
import hmac
import time
import uuid

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from server.api.dependencies import get_db, get_principal, get_rate_limiter_dep, get_settings_dep, get_storage_dep
from server.core.errors import AppError, ErrorCode
from server.core.security import Principal
from server.db.models import Asset
from server.schemas.edit import AssetOut
from server.schemas.misc import ALLOWED_UPLOAD_TYPES, PURPOSE_KINDS, PresignRequest, PresignResponse
from server.services.edit_service import asset_out
from server.services.storage import LocalStorage, StorageError, sanitize_filename, validate_key

router = APIRouter(prefix="/v1/uploads", tags=["uploads"])
log = structlog.get_logger(__name__)


def _sign(secret: str, asset_id: str, exp: int) -> str:
    return hmac.new(secret.encode(), f"{asset_id}:{exp}".encode(), hashlib.sha256).hexdigest()


def _secret(settings) -> str:
    return settings.dev_token_value or "dev-local-upload-secret"


@router.post("/presign", response_model=PresignResponse)
def presign_upload(
    body: PresignRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
    settings=Depends(get_settings_dep),
    storage=Depends(get_storage_dep),
    limiter=Depends(get_rate_limiter_dep),
    session=Depends(get_db),
):
    limiter.hit("uploads", principal.user_id, settings.rate_limit_uploads_per_minute)

    local_dev = isinstance(storage, LocalStorage) and not settings.is_production
    if not storage.supports_presign and not local_dev:
        raise AppError(ErrorCode.UPLOADS_UNAVAILABLE, "Uploads are not available in this environment.", 501)

    content_type = body.content_type.lower().split(";")[0].strip()
    kind = ALLOWED_UPLOAD_TYPES.get(content_type)
    if kind is None:
        raise AppError(ErrorCode.INVALID_REQUEST, "Unsupported content type.", 422)
    if kind not in PURPOSE_KINDS[body.purpose]:
        raise AppError(ErrorCode.INVALID_REQUEST, "This file type is not allowed for that purpose.", 422)
    max_bytes = settings.max_upload_bytes_video if kind == "video" else settings.max_upload_bytes_image
    if body.size_bytes is not None and body.size_bytes > max_bytes:
        raise AppError(ErrorCode.PAYLOAD_TOO_LARGE, f"File exceeds the {max_bytes // (1024 * 1024)} MB limit.", 413)

    asset_id = uuid.uuid4()
    filename = sanitize_filename(body.filename)
    key = validate_key(f"uploads/{principal.user_id}/{asset_id.hex}/{filename}")
    session.add(Asset(id=asset_id, user_id=principal.user_id, project_id=body.project_id, filename=filename,
                      content_type=content_type, purpose=body.purpose, storage_key=key, status="pending"))
    session.commit()

    if storage.supports_presign:
        try:
            p = storage.presign_upload(key, content_type, settings.presign_ttl_seconds)
        except StorageError:
            log.error("presign_failed", exc_info=True)
            raise AppError(ErrorCode.STORAGE_FAILED, "Could not prepare the upload.", 503)
        method, url, headers, expires = p.method, p.url, p.headers, p.expires_in
    else:  # development: signed PUT straight to this API, streamed to disk
        exp = int(time.time()) + settings.presign_ttl_seconds
        sig = _sign(_secret(settings), asset_id.hex, exp)
        base = str(request.base_url).rstrip("/")
        method, url, headers, expires = "PUT", f"{base}/v1/uploads/{asset_id}/content?exp={exp}&sig={sig}", \
            {"Content-Type": content_type}, settings.presign_ttl_seconds

    return PresignResponse(upload_id=asset_id.hex, asset_id=str(asset_id), method=method, url=url, headers=headers, key=key,
                           expires_in=expires, max_bytes=max_bytes)


@router.put("/{asset_id}/content", include_in_schema=False)
async def upload_local_content(asset_id: uuid.UUID, request: Request, exp: int = Query(...), sig: str = Query(...)):
    """Development-only stand-in for an R2 presigned PUT. Streams the body to disk in chunks."""
    settings = request.app.state.settings
    storage = request.app.state.get_storage()
    if settings.is_production or not isinstance(storage, LocalStorage):
        raise AppError(ErrorCode.NOT_FOUND, "Not found.", 404)
    if exp < time.time() or not hmac.compare_digest(sig, _sign(_secret(settings), asset_id.hex, exp)):
        raise AppError(ErrorCode.UNAUTHORIZED, "Upload link is invalid or expired.", 401)

    from server.db.session import get_sessionmaker

    with get_sessionmaker()() as session:
        asset = session.get(Asset, asset_id)
        if asset is None or asset.status != "pending":
            raise AppError(ErrorCode.NOT_FOUND, "Not found.", 404)
        kind = ALLOWED_UPLOAD_TYPES.get(asset.content_type, "video")
        limit = settings.max_upload_bytes_video if kind == "video" else settings.max_upload_bytes_image
        key = asset.storage_key

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise AppError(ErrorCode.PAYLOAD_TOO_LARGE, "File is too large.", 413)
    dest = storage.resolve(key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    written = 0
    with tmp.open("wb") as fh:
        async for chunk in request.stream():
            written += len(chunk)
            if written > limit:
                fh.close()
                tmp.unlink(missing_ok=True)
                raise AppError(ErrorCode.PAYLOAD_TOO_LARGE, "File is too large.", 413)
            fh.write(chunk)
    tmp.replace(dest)
    return Response(status_code=200)


@router.post("/{asset_id}/complete", response_model=AssetOut)
def complete_upload(asset_id: uuid.UUID, principal: Principal = Depends(get_principal), session=Depends(get_db),
                    storage=Depends(get_storage_dep), settings=Depends(get_settings_dep)):
    """Client calls this after the direct upload succeeded; we verify the object really exists."""
    asset = session.get(Asset, asset_id)
    if asset is None or asset.user_id != principal.user_id:
        raise AppError(ErrorCode.NOT_FOUND, "Upload not found.", 404)
    if asset.status == "uploaded":
        return asset_out(asset)
    size = storage.size(asset.storage_key)
    if size is None or size <= 0:
        raise AppError(ErrorCode.INVALID_REQUEST, "The file has not finished uploading.", 409)
    kind = ALLOWED_UPLOAD_TYPES.get(asset.content_type, "video")
    limit = settings.max_upload_bytes_video if kind == "video" else settings.max_upload_bytes_image
    if size > limit:
        storage.delete(asset.storage_key)
        raise AppError(ErrorCode.PAYLOAD_TOO_LARGE, "File is too large.", 413)
    asset.status, asset.size_bytes = "uploaded", size
    session.commit()
    return asset_out(asset)
