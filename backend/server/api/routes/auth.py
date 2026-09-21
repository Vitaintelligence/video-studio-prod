from __future__ import annotations

import hashlib
import time

from fastapi import APIRouter, Depends, Request

from server.api.dependencies import get_rate_limiter_dep, get_settings_dep
from server.core.errors import AppError, ErrorCode
from server.core.security import issue_device_token
from server.schemas.misc import DeviceSessionRequest, DeviceSessionResponse

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/device-session", response_model=DeviceSessionResponse)
def create_device_session(
    body: DeviceSessionRequest,
    request: Request,
    settings=Depends(get_settings_dep),
    limiter=Depends(get_rate_limiter_dep),
):
    """Create a signed anonymous session for one app installation.

    This identifies an installation; it is deliberately not an account login.
    """
    if settings.auth_mode != "device_session" or not settings.device_auth_secret_value:
        raise AppError(ErrorCode.NOT_FOUND, "Not found.", 404)
    subject = hashlib.sha256(body.install_id.bytes).hexdigest()[:32]
    limiter.hit("device_sessions", subject, 10)
    token, expires_at = issue_device_token(
        settings.device_auth_secret_value,
        body.install_id,
        settings.device_session_ttl_seconds,
    )
    return DeviceSessionResponse(access_token=token, expires_in=max(0, expires_at - int(time.time())))
