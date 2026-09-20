"""FastAPI application factory."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from server.api.routes import capabilities, generations, health, uploads
from server.core.config import Settings, get_settings
from server.core.errors import ErrorCode, error_body, install_error_handlers
from server.core.logging import configure_logging
from server.core.security import build_auth_provider
from server.services.queue import enqueue_generation
from server.services.ratelimit import get_rate_limiter, get_redis
from server.services.storage import UnsafeKeyError, get_storage

log = structlog.get_logger(__name__)

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"cache-control", b"no-store"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-resource-policy", b"same-site"),
]


class RequestContextMiddleware:
    """Request id, security headers, JSON content-type and body-size enforcement
    (pure ASGI so the body limit also applies to chunked uploads)."""

    def __init__(self, app: ASGIApp, max_body_bytes: int):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope["headers"]}
        request_id = headers.get(b"x-request-id", b"").decode("latin-1")[:64] or uuid.uuid4().hex
        if not request_id.replace("-", "").replace("_", "").isalnum():
            request_id = uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                hdrs = list(message.get("headers", []))
                hdrs.append((b"x-request-id", request_id.encode()))
                if not scope["path"].startswith("/media/"):
                    hdrs.extend(SECURITY_HEADERS)
                message["headers"] = hdrs
            await send(message)

        async def reject(status: int, code: ErrorCode, msg: str) -> None:
            body = json.dumps(error_body(code, msg)).encode()
            await send_wrapper(
                {"type": "http.response.start", "status": status,
                 "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]}
            )
            await send_wrapper({"type": "http.response.body", "body": body})

        try:
            method = scope["method"]
            if method in ("POST", "PUT", "PATCH"):
                declared = headers.get(b"content-length")
                if declared is not None and declared.isdigit() and int(declared) > self.max_body_bytes:
                    await reject(413, ErrorCode.PAYLOAD_TOO_LARGE, "Request body too large.")
                    return
                has_body = (declared not in (None, b"0")) or b"transfer-encoding" in headers
                ctype = headers.get(b"content-type", b"").decode("latin-1").lower()
                if has_body and scope["path"].startswith("/v1") and not ctype.startswith("application/json"):
                    await reject(415, ErrorCode.INVALID_REQUEST, "Content-Type must be application/json.")
                    return

                received = 0
                too_large = False

                async def limited_receive() -> Message:
                    nonlocal received, too_large
                    message = await receive()
                    if message["type"] == "http.request":
                        received += len(message.get("body", b""))
                        if received > self.max_body_bytes:
                            too_large = True
                            return {"type": "http.request", "body": b"", "more_body": False}
                    return message

                await self.app(scope, limited_receive, send_wrapper)
                if too_large:
                    log.warning("request_body_exceeded_limit")
                return

            await self.app(scope, receive, send_wrapper)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_logs=settings.is_production)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info(
            "api_boot",
            env=settings.app_env,
            auth_mode=settings.auth_mode,
            storage=settings.storage_backend,
            docs=settings.docs_enabled,
            runtime=settings.orchestrator_provider,
        )
        yield

    app = FastAPI(
        title="Video Generation API",
        version="1.0.0",
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.auth = build_auth_provider(settings)
    app.state.get_storage = get_storage
    app.state.get_redis = get_redis
    app.state.get_rate_limiter = get_rate_limiter
    app.state.enqueue = enqueue_generation

    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
            max_age=600,
        )
    app.add_middleware(RequestContextMiddleware, max_body_bytes=settings.max_body_bytes)
    install_error_handlers(app)

    app.include_router(health.router)
    app.include_router(capabilities.router)
    app.include_router(generations.router)
    app.include_router(uploads.router)

    if settings.storage_backend == "local" and not settings.is_production:
        _mount_dev_media(app)

    return app


def _mount_dev_media(app: FastAPI) -> None:
    """Development-only: serve locally stored outputs so a simulator can play them."""
    from fastapi import HTTPException

    @app.get("/media/{key:path}", include_in_schema=False)
    def dev_media(key: str):
        storage = app.state.get_storage()
        try:
            path = storage.resolve(key)
        except UnsafeKeyError:
            raise HTTPException(status_code=404, detail="Not found")
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(path)


def _build_default_app() -> FastAPI:
    return create_app()


app = _build_default_app()
