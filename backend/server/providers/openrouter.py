"""OpenRouter provider (worker/backend only).

Thin, typed wrapper over the parts of OpenRouter we actually use, checked against the
current docs (2026-09): chat completions, image generation (`POST /images`), and asynchronous
video generation (`POST /videos`, poll `GET /videos/{id}`, download `GET /videos/{id}/content`,
capability discovery `GET /videos/models`). No model ids are hardcoded: they come from settings.
The API key is read from settings and only ever placed in the Authorization header - it is never
logged or returned.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx
import structlog

from server.core.config import Settings

log = structlog.get_logger(__name__)

VIDEO_PROFILES = ("standard", "premium", "ugc_broll", "fast")


class ProviderError(Exception):
    """Provider failure with a safe code (mapped to client-safe messages upstream)."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


@dataclass
class VideoModel:
    id: str
    supported_durations: list[int] = field(default_factory=list)
    supported_resolutions: list[str] = field(default_factory=list)
    supported_aspect_ratios: list[str] = field(default_factory=list)
    supported_sizes: list[str] = field(default_factory=list)
    price_per_second: float | None = None

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> "VideoModel":
        sku = d.get("pricing_skus") or {}
        try:
            raw = sku.get("per-video-second")
            price = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            price = None
        return cls(
            id=d["id"],
            supported_durations=[int(x) for x in d.get("supported_durations") or []],
            supported_resolutions=list(d.get("supported_resolutions") or []),
            supported_aspect_ratios=list(d.get("supported_aspect_ratios") or []),
            supported_sizes=list(d.get("supported_sizes") or []),
            price_per_second=price,
        )


@dataclass
class VideoJob:
    id: str
    status: str  # pending | in_progress | completed | failed
    polling_url: str | None = None
    cost_usd: float | None = None
    error: str | None = None
    urls: list[str] = field(default_factory=list)


@dataclass
class VideoRequestPlan:
    """A request already validated against the model's advertised capabilities."""

    model: str
    duration: int | None
    resolution: str | None
    aspect_ratio: str | None
    estimated_cost_usd: float | None


class OpenRouterProvider:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        if not settings.openrouter_api_key:
            raise ProviderError("PROVIDER_UNAVAILABLE", "OPENROUTER_API_KEY is not configured")
        self.settings = settings
        self._key = settings.openrouter_api_key.get_secret_value()
        self.client = client or httpx.Client(
            base_url=settings.openrouter_base_url.rstrip("/"), timeout=settings.openrouter_timeout_seconds
        )
        self._models_cache: tuple[float, list[VideoModel]] | None = None

    # -- plumbing -----------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        try:
            resp = self.client.request(method, path, headers=self._headers(), **kw)
        except httpx.HTTPError as exc:
            log.warning("openrouter_transport_error", path=path, error=type(exc).__name__)
            raise ProviderError("PROVIDER_UNAVAILABLE", "transport error") from exc
        if resp.status_code in (401, 403):
            raise ProviderError("PROVIDER_UNAVAILABLE", "authentication failed")
        if resp.status_code == 402:
            raise ProviderError("PROVIDER_UNAVAILABLE", "insufficient provider credit")
        if resp.status_code == 429 or resp.status_code >= 500:
            raise ProviderError("PROVIDER_UNAVAILABLE", f"provider status {resp.status_code}")
        if resp.status_code >= 400:
            log.warning("openrouter_rejected_request", path=path, status=resp.status_code, body=resp.text[:300])
            raise ProviderError("INVALID_PROVIDER_REQUEST", f"provider rejected request ({resp.status_code})")
        return resp

    @staticmethod
    def _model(override: str | None, configured: str | None, what: str) -> str:
        model = override or configured
        if not model:
            raise ProviderError("PROVIDER_UNAVAILABLE", f"no {what} model configured")
        return model

    # -- account / health -------------------------------------------------------------
    def verify_key(self) -> dict[str, Any]:
        """Free authenticated call (no generation). Returns only non-sensitive fields."""
        data = self._request("GET", "/key").json().get("data", {})
        return {
            "authenticated": True,
            "is_free_tier": data.get("is_free_tier"),
            "limit_remaining": data.get("limit_remaining"),
        }

    # -- chat / reasoning / vision -----------------------------------------------------
    def chat(self, messages: list[dict[str, Any]], *, model: str | None = None, vision: bool = False,
             max_tokens: int = 800, temperature: float = 0.2, thinking: bool = True) -> str:
        """`thinking=False` asks reasoning-capable models not to spend the token budget on hidden reasoning
        (otherwise a long deliberation can exhaust `max_tokens` and leave the visible answer empty)."""
        configured = self.settings.openrouter_vision_model if vision else self.settings.openrouter_reasoning_model
        chosen = self._model(model, configured, "vision" if vision else "reasoning")
        body: dict[str, Any] = {"model": chosen, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        if not thinking:
            body["reasoning"] = {"enabled": False}
        data = self._request("POST", "/chat/completions", json=body).json()
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("PROVIDER_UNAVAILABLE", "unexpected chat response") from exc

    # -- images -----------------------------------------------------------------------
    def generate_image(self, prompt: str, *, aspect_ratio: str = "9:16",
                       model: str | None = None) -> tuple[bytes, str, float | None]:
        body = {"model": self._model(model, self.settings.openrouter_image_model, "image"), "prompt": prompt,
                "aspect_ratio": aspect_ratio, "n": 1}
        data = self._request("POST", "/images", json=body).json()
        try:
            item = data["data"][0]
            raw = base64.b64decode(item["b64_json"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError("PROVIDER_UNAVAILABLE", "unexpected image response") from exc
        cost = (data.get("usage") or {}).get("cost")
        return raw, item.get("media_type", "image/png"), float(cost) if cost is not None else None

    # -- video ------------------------------------------------------------------------
    def list_video_models(self, *, force: bool = False, ttl: float = 600.0) -> list[VideoModel]:
        if not force and self._models_cache and time.monotonic() - self._models_cache[0] < ttl:
            return self._models_cache[1]
        data = self._request("GET", "/videos/models").json().get("data", [])
        models = [VideoModel.from_api(d) for d in data if isinstance(d, dict) and d.get("id")]
        self._models_cache = (time.monotonic(), models)
        return models

    def resolve_video_model(self, profile: str | None = None) -> str:
        s = self.settings
        model = (s.openrouter_video_profiles.get(profile) if profile else None) or s.openrouter_video_model
        if not model:
            raise ProviderError("PROVIDER_UNAVAILABLE", "no video model configured")
        return model

    def plan_video_request(self, *, profile: str | None, duration: int, aspect_ratio: str,
                           resolution: str | None = None) -> VideoRequestPlan:
        """Validate against the model's advertised capabilities BEFORE spending anything."""
        model_id = self.resolve_video_model(profile)
        model = next((m for m in self.list_video_models() if m.id == model_id), None)
        if model is None:
            raise ProviderError("PROVIDER_UNAVAILABLE", "configured video model is not offered by the provider")
        if model.supported_aspect_ratios and aspect_ratio not in model.supported_aspect_ratios:
            raise ProviderError("INVALID_PROVIDER_REQUEST", f"aspect ratio {aspect_ratio} unsupported by model")
        if model.supported_durations:
            longer = [d for d in sorted(model.supported_durations) if d >= duration]
            duration = longer[0] if longer else max(model.supported_durations)
        if model.supported_resolutions and (resolution is None or resolution not in model.supported_resolutions):
            resolution = model.supported_resolutions[0]
        est = model.price_per_second * duration if model.price_per_second is not None else None
        return VideoRequestPlan(model.id, duration, resolution, aspect_ratio, est)

    def submit_video_generation(self, prompt: str, plan: VideoRequestPlan, *, generate_audio: bool = False) -> VideoJob:
        body: dict[str, Any] = {"model": plan.model, "prompt": prompt, "generate_audio": generate_audio}
        if plan.duration:
            body["duration"] = plan.duration
        if plan.resolution:
            body["resolution"] = plan.resolution
        if plan.aspect_ratio:
            body["aspect_ratio"] = plan.aspect_ratio
        data = self._request("POST", "/videos", json=body).json()
        return VideoJob(id=data["id"], status=data.get("status", "pending"), polling_url=data.get("polling_url"))

    def get_video_generation(self, job_id: str) -> VideoJob:
        d = self._request("GET", f"/videos/{job_id}").json()
        cost = (d.get("usage") or {}).get("cost")
        return VideoJob(id=d.get("id", job_id), status=d.get("status", "pending"), polling_url=d.get("polling_url"),
                        cost_usd=float(cost) if cost is not None else None, error=d.get("error"),
                        urls=list(d.get("unsigned_urls") or []))

    def download_video(self, job_id: str, dest: Path, index: int = 0) -> int:
        """Stream the finished video to disk. Returns bytes written."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        try:
            with self.client.stream("GET", f"/videos/{job_id}/content", params={"index": index},
                                    headers={"Authorization": f"Bearer {self._key}"}) as r:
                if r.status_code >= 400:
                    raise ProviderError("PROVIDER_UNAVAILABLE", f"download failed ({r.status_code})")
                with dest.open("wb") as fh:
                    for chunk in r.iter_bytes(1024 * 256):
                        fh.write(chunk)
                        written += len(chunk)
        except httpx.HTTPError as exc:
            raise ProviderError("PROVIDER_UNAVAILABLE", "download transport error") from exc
        if written == 0:
            raise ProviderError("PROVIDER_UNAVAILABLE", "empty video download")
        return written

    def generate_video_clip(self, prompt: str, dest: Path, *, profile: str | None, duration: int, aspect_ratio: str,
                            should_cancel: Callable[[], bool] = lambda: False,
                            sleep: Callable[[float], None] = time.sleep) -> tuple[float | None, VideoRequestPlan]:
        """Submit -> poll -> download. Runs on the worker only (never inside a web request)."""
        plan = self.plan_video_request(profile=profile, duration=duration, aspect_ratio=aspect_ratio)
        job = self.submit_video_generation(prompt, plan)
        log.info("openrouter_video_submitted", job_id=job.id, model=plan.model, duration=plan.duration)
        deadline = time.monotonic() + self.settings.video_poll_timeout_seconds
        while True:
            if should_cancel():
                raise ProviderError("CANCELLED", "cancelled while generating")
            job = self.get_video_generation(job.id)
            if job.status == "completed":
                break
            if job.status == "failed":
                log.warning("openrouter_video_failed", job_id=job.id, error=(job.error or "")[:200])
                raise ProviderError("GENERATION_FAILED", "provider reported failure")
            if time.monotonic() > deadline:
                raise ProviderError("TIMEOUT", "video generation timed out")
            sleep(self.settings.video_poll_interval_seconds)
        self.download_video(job.id, dest)
        return (job.cost_usd if job.cost_usd is not None else plan.estimated_cost_usd), plan
