"""Consistent error model.

Clients only ever see ``{"error": {"code": ..., "message": ...}}``. Detailed
exceptions are logged server-side; nothing here forwards raw exception text.
"""

from __future__ import annotations

import re
from enum import Enum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

import structlog

log = structlog.get_logger(__name__)


class ErrorCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    GENERATION_NOT_FOUND = "GENERATION_NOT_FOUND"
    GENERATION_FAILED = "GENERATION_FAILED"
    PIPELINE_UNAVAILABLE = "PIPELINE_UNAVAILABLE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    STORAGE_FAILED = "STORAGE_FAILED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    CANCELLED = "CANCELLED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    UPLOADS_UNAVAILABLE = "UPLOADS_UNAVAILABLE"
    QUEUE_UNAVAILABLE = "QUEUE_UNAVAILABLE"
    OUTPUT_INVALID = "OUTPUT_INVALID"
    TIMEOUT = "TIMEOUT"
    NOT_FOUND = "NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# The only messages a mobile client ever gets for terminal generation failures.
CLIENT_MESSAGES: dict[str, str] = {
    ErrorCode.GENERATION_FAILED: "We couldn't finish this video.",
    ErrorCode.PIPELINE_UNAVAILABLE: "Video creation is temporarily unavailable.",
    ErrorCode.PROVIDER_UNAVAILABLE: "A creative service is temporarily unavailable. Please try again.",
    ErrorCode.STORAGE_FAILED: "We couldn't save your video. Please try again.",
    ErrorCode.BUDGET_EXCEEDED: "This video was too complex to create. Try a shorter or simpler idea.",
    ErrorCode.CANCELLED: "This video was cancelled.",
    ErrorCode.OUTPUT_INVALID: "We couldn't finish this video.",
    ErrorCode.TIMEOUT: "This video took too long to create. Please try again.",
    ErrorCode.INTERNAL_ERROR: "Something went wrong.",
}


def client_message(code: str) -> str:
    return CLIENT_MESSAGES.get(code, CLIENT_MESSAGES[ErrorCode.GENERATION_FAILED])


class AppError(Exception):
    def __init__(self, code: ErrorCode, message: str, status_code: int = 400, headers: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.headers = headers or {}


def error_body(code: ErrorCode | str, message: str) -> dict:
    code_value = code.value if isinstance(code, ErrorCode) else code
    return {"error": {"code": code_value, "message": message}}


_PATH_RE = re.compile(r"([A-Za-z]:\\|/)(?:[\w.\-]+[\\/])+[\w.\-]*")
_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|Bearer\s+\S+|(?i:key|token|secret|password)=\S+)")


def sanitize_text(text: str, limit: int = 300) -> str:
    """Strip paths and credential-looking substrings from a string."""
    text = _SECRET_RE.sub("[redacted]", text)
    text = _PATH_RE.sub("[path]", text)
    return text[:limit]


_STATUS_CODES = {
    400: ErrorCode.INVALID_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.INVALID_REQUEST,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
    415: ErrorCode.INVALID_REQUEST,
    422: ErrorCode.INVALID_REQUEST,
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(error_body(exc.code, exc.message), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        problems = []
        for err in exc.errors()[:5]:
            loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
            problems.append(f"{loc}: {err.get('msg', 'invalid')}" if loc else str(err.get("msg", "invalid")))
        return JSONResponse(
            error_body(ErrorCode.INVALID_REQUEST, "; ".join(problems) or "Invalid request."),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = _STATUS_CODES.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        msg = exc.detail if isinstance(exc.detail, str) and exc.status_code < 500 else "Request failed."
        return JSONResponse(error_body(code, msg), status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.error("unhandled_exception", path=request.url.path, exc_info=exc)
        return JSONResponse(
            error_body(ErrorCode.INTERNAL_ERROR, CLIENT_MESSAGES[ErrorCode.INTERNAL_ERROR]),
            status_code=500,
        )
