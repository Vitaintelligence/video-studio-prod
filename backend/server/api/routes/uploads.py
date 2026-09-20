from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends

from server.api.dependencies import get_principal, get_rate_limiter_dep, get_settings_dep, get_storage_dep
from server.core.errors import AppError, ErrorCode
from server.core.security import Principal
from server.schemas.misc import ALLOWED_UPLOAD_TYPES, PURPOSE_KINDS, PresignRequest, PresignResponse
from server.services.storage import StorageError, sanitize_filename, validate_key

router = APIRouter(prefix="/v1/uploads", tags=["uploads"])
log = structlog.get_logger(__name__)


@router.post("/presign", response_model=PresignResponse)
def presign_upload(
    body: PresignRequest,
    principal: Principal = Depends(get_principal),
    settings=Depends(get_settings_dep),
    storage=Depends(get_storage_dep),
    limiter=Depends(get_rate_limiter_dep),
):
    limiter.hit("uploads", principal.user_id, settings.rate_limit_uploads_per_minute)

    if not storage.supports_presign:
        raise AppError(
            ErrorCode.UPLOADS_UNAVAILABLE,
            "Uploads are not available in this environment.",
            501,
        )

    content_type = body.content_type.lower().split(";")[0].strip()
    kind = ALLOWED_UPLOAD_TYPES.get(content_type)
    if kind is None:
        raise AppError(ErrorCode.INVALID_REQUEST, "Unsupported content type.", 422)
    if kind not in PURPOSE_KINDS[body.purpose]:
        raise AppError(ErrorCode.INVALID_REQUEST, "This file type is not allowed for that purpose.", 422)

    max_bytes = settings.max_upload_bytes_video if kind == "video" else settings.max_upload_bytes_image
    if body.size_bytes is not None and body.size_bytes > max_bytes:
        raise AppError(ErrorCode.PAYLOAD_TOO_LARGE, f"File exceeds the {max_bytes // (1024 * 1024)} MB limit.", 413)

    upload_id = uuid.uuid4().hex
    key = validate_key(f"uploads/{principal.user_id}/{upload_id}/{sanitize_filename(body.filename)}")
    try:
        presigned = storage.presign_upload(key, content_type, settings.presign_ttl_seconds)
    except StorageError:
        log.error("presign_failed", exc_info=True)
        raise AppError(ErrorCode.STORAGE_FAILED, "Could not prepare the upload.", 503)

    return PresignResponse(
        upload_id=upload_id,
        method=presigned.method,
        url=presigned.url,
        headers=presigned.headers,
        key=presigned.key,
        expires_in=presigned.expires_in,
        max_bytes=max_bytes,
    )
