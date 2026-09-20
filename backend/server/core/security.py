"""Auth provider abstraction (Phase 1: static dev token).

The mobile app's real identity system replaces ``DevTokenAuthProvider`` later
without touching the routes: they depend only on ``Principal``.
"""

from __future__ import annotations

import secrets
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


def build_auth_provider(settings: Settings) -> AuthProvider:
    if settings.auth_mode == "dev_token":
        return DevTokenAuthProvider(settings.dev_token_value)
    raise ValueError(f"Unsupported AUTH_MODE {settings.auth_mode!r}")
