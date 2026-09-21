"""Auth providers for development and anonymous device sessions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from fastapi import Request

from server.core.config import Settings
from server.core.errors import AppError, ErrorCode


@dataclass(frozen=True)
class Principal:
    user_id: str


class AuthProvider(ABC):
    @abstractmethod
    def authenticate(self, request: Request) -> Principal:  # raises AppError(UNAUTHORIZED)
        ...


def _unauthorized() -> AppError:
    return AppError(
        ErrorCode.UNAUTHORIZED,
        "Missing or invalid credentials.",
        401,
        headers={"WWW-Authenticate": "Bearer"},
    )


class DevTokenAuthProvider(AuthProvider):
    def __init__(self, token: str | None):
        self._token = token

    def authenticate(self, request: Request) -> Principal:
        if not self._token:
            raise _unauthorized()  # fail closed if misconfigured
        header = request.headers.get("authorization", "")
        scheme, _, supplied = header.partition(" ")
        if scheme.lower() != "bearer" or not supplied:
            raise _unauthorized()
        if not secrets.compare_digest(supplied.strip().encode(), self._token.encode()):
            raise _unauthorized()
        return Principal(user_id="dev")


def _device_signature(secret: str, payload: str) -> str:
    digest = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def issue_device_token(secret: str, install_id: uuid.UUID, ttl_seconds: int, *, now: int | None = None) -> tuple[str, int]:
    """Issue a compact server-signed token for one anonymous app installation."""
    issued_at = int(time.time()) if now is None else now
    expires_at = issued_at + ttl_seconds
    payload = f"v1.{install_id.hex}.{expires_at}"
    return f"{payload}.{_device_signature(secret, payload)}", expires_at


class DeviceSessionAuthProvider(AuthProvider):
    def __init__(self, secret: str | None):
        self._secret = secret

    def authenticate(self, request: Request) -> Principal:
        if not self._secret:
            raise _unauthorized()
        header = request.headers.get("authorization", "")
        scheme, _, supplied = header.partition(" ")
        if scheme.lower() != "bearer" or not supplied:
            raise _unauthorized()
        parts = supplied.strip().split(".")
        if len(parts) != 4 or parts[0] != "v1":
            raise _unauthorized()
        _, raw_install_id, raw_expiry, signature = parts
        try:
            install_id = uuid.UUID(hex=raw_install_id)
            expires_at = int(raw_expiry)
        except (ValueError, AttributeError):
            raise _unauthorized()
        if expires_at <= int(time.time()):
            raise _unauthorized()
        payload = f"v1.{install_id.hex}.{expires_at}"
        expected = _device_signature(self._secret, payload)
        if not secrets.compare_digest(signature.encode(), expected.encode()):
            raise _unauthorized()
        # Keep the install UUID out of storage keys and database rows.
        subject = hashlib.sha256(install_id.bytes).hexdigest()[:32]
        return Principal(user_id=f"device:{subject}")


def build_auth_provider(settings: Settings) -> AuthProvider:
    if settings.auth_mode == "dev_token":
        return DevTokenAuthProvider(settings.dev_token_value)
    if settings.auth_mode == "device_session":
        return DeviceSessionAuthProvider(settings.device_auth_secret_value)
    raise ValueError(f"Unsupported AUTH_MODE {settings.auth_mode!r}")
