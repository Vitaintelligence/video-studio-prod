"""FastAPI dependencies. Everything stateful hangs off ``app.state`` so tests can
swap components without monkeypatching modules."""

from __future__ import annotations

from typing import Callable

from fastapi import Request
from sqlalchemy.orm import Session

from server.core.config import Settings
from server.core.security import Principal
from server.db.session import get_session
from server.services.ratelimit import RateLimiter
from server.services.storage import StorageService


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_principal(request: Request) -> Principal:
    principal = request.app.state.auth.authenticate(request)
    request.state.user_id = principal.user_id
    return principal


def get_db():
    yield from get_session()


def get_storage_dep(request: Request) -> StorageService:
    return request.app.state.get_storage()


def get_redis_dep(request: Request):
    return request.app.state.get_redis()


def get_rate_limiter_dep(request: Request) -> RateLimiter:
    return request.app.state.get_rate_limiter()


def get_enqueue(request: Request) -> Callable:
    return request.app.state.enqueue


__all__ = [
    "Session",
    "get_settings_dep",
    "get_principal",
    "get_db",
    "get_storage_dep",
    "get_redis_dep",
    "get_rate_limiter_dep",
    "get_enqueue",
]
