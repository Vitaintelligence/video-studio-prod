"""OpenRouter provider against a mocked transport (contract per current OpenRouter docs), plus the
worker-side generative B-roll gate. Nothing here touches the network or spends money."""

from __future__ import annotations

import base64
import json
import shutil
import uuid

import httpx
import pytest
from pydantic import SecretStr

from server.core.config import Settings
from server.providers.openrouter import OpenRouterProvider, ProviderError
from tests.conftest import FIXTURE_VIDEO

KEY = "sk-or-v1-SECRETSECRETSECRET0123456789"
MODELS = {"data": [{
    "id": "vendor/video-x", "supported_durations": [4, 6, 8], "supported_resolutions": ["720p", "1080p"],
    "supported_aspect_ratios": ["16:9", "9:16"], "supported_sizes": ["1280x720"],
    "pricing_skus": {"per-video-second": "0.10"}, "allowed_passthrough_parameters": [],
}]}


def make_settings(**over) -> Settings:
    base = dict(_env_file=None, openrouter_api_key=SecretStr(KEY), openrouter_video_model="vendor/video-x",
                openrouter_reasoning_model="vendor/chat", openrouter_image_model="vendor/img",
                video_poll_interval_seconds=0.0, video_poll_timeout_seconds=5.0)
    base.update(over)
    return Settings(**base)


class Fake:
    """Records requests and plays back scripted responses keyed by (method, path)."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        handler = self.routes.get((request.method, request.url.path))
        if handler is None:
            return httpx.Response(404, json={"error": "unexpected"})
        return handler(request) if callable(handler) else handler


def provider(routes, **settings_over) -> tuple[OpenRouterProvider, Fake]:
    fake = Fake(routes)
    s = make_settings(**settings_over)
    client = httpx.Client(base_url=s.openrouter_base_url, transport=httpx.MockTransport(fake))
    return OpenRouterProvider(s, client=client), fake


def test_requires_key():
    with pytest.raises(ProviderError) as e:
        OpenRouterProvider(Settings(_env_file=None))
    assert e.value.code == "PROVIDER_UNAVAILABLE"


def test_verify_key_uses_free_endpoint_and_returns_no_secrets():
    p, fake = provider({("GET", "/api/v1/key"): httpx.Response(200, json={"data": {"label": "sk-or-v1-abc...xyz", "limit_remaining": 4.2, "is_free_tier": False}})})
    out = p.verify_key()
    assert out == {"authenticated": True, "is_free_tier": False, "limit_remaining": 4.2}
    assert fake.calls[0].headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in json.dumps(out)


def test_auth_and_provider_errors_are_mapped_without_leaking_bodies():
    for status, code in ((401, "PROVIDER_UNAVAILABLE"), (402, "PROVIDER_UNAVAILABLE"), (429, "PROVIDER_UNAVAILABLE"),
                         (503, "PROVIDER_UNAVAILABLE"), (400, "INVALID_PROVIDER_REQUEST")):
        p, _ = provider({("GET", "/api/v1/key"): httpx.Response(status, json={"error": f"secret detail {KEY}"})})
        with pytest.raises(ProviderError) as e:
            p.verify_key()
        assert e.value.code == code and KEY not in str(e.value)


def test_chat_and_image():
    img = base64.b64encode(b"\x89PNGfake").decode()
    p, fake = provider({
        ("POST", "/api/v1/chat/completions"): httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]}),
        ("POST", "/api/v1/images"): httpx.Response(200, json={"data": [{"b64_json": img, "media_type": "image/png"}], "usage": {"cost": 0.04}}),
    })
    assert p.chat([{"role": "user", "content": "yo"}]) == "hi"
    assert json.loads(fake.calls[0].content)["model"] == "vendor/chat"
    raw, mt, cost = p.generate_image("a vase", aspect_ratio="9:16")
    assert raw == b"\x89PNGfake" and mt == "image/png" and cost == 0.04
    body = json.loads(fake.calls[1].content)
    assert body["model"] == "vendor/img" and body["aspect_ratio"] == "9:16"


def test_no_model_configured_is_a_controlled_error():
    p, _ = provider({}, openrouter_reasoning_model=None)
    with pytest.raises(ProviderError) as e:
        p.chat([{"role": "user", "content": "x"}])
    assert e.value.code == "PROVIDER_UNAVAILABLE"


def test_video_capability_validation_happens_before_any_spend():
    p, fake = provider({("GET", "/api/v1/videos/models"): httpx.Response(200, json=MODELS)})
    plan = p.plan_video_request(profile=None, duration=5, aspect_ratio="9:16")
    assert plan.duration == 6 and plan.resolution == "720p" and plan.estimated_cost_usd == pytest.approx(0.6)
    assert p.plan_video_request(profile=None, duration=30, aspect_ratio="16:9").duration == 8  # capped to the model's max
    with pytest.raises(ProviderError) as e:
        p.plan_video_request(profile=None, duration=4, aspect_ratio="1:1")
    assert e.value.code == "INVALID_PROVIDER_REQUEST"
    assert all(c.method == "GET" for c in fake.calls)  # nothing was submitted
    assert len([c for c in fake.calls if c.url.path.endswith("/videos/models")]) == 1  # cached


def test_unknown_or_unconfigured_video_model():
    p, _ = provider({("GET", "/api/v1/videos/models"): httpx.Response(200, json=MODELS)}, openrouter_video_model="vendor/other")
    with pytest.raises(ProviderError):
        p.plan_video_request(profile=None, duration=4, aspect_ratio="9:16")
    p2, _ = provider({}, openrouter_video_model=None)
    with pytest.raises(ProviderError):
        p2.plan_video_request(profile="ugc_broll", duration=4, aspect_ratio="9:16")


def test_profiles_map_to_env_configured_models():
    p, _ = provider({}, openrouter_video_profiles={"ugc_broll": "vendor/cheap", "premium": "vendor/best"})
    assert p.resolve_video_model("ugc_broll") == "vendor/cheap" and p.resolve_video_model("premium") == "vendor/best"
    assert p.resolve_video_model("fast") == "vendor/video-x"  # falls back to the default video model


def test_video_generation_submit_poll_download(tmp_path):
    states = iter(["pending", "in_progress", "completed"])
    payload = FIXTURE_VIDEO.read_bytes()

    def poll(_req):
        st = next(states)
        body = {"id": "job1", "status": st}
        if st == "completed":
            body.update(unsigned_urls=["https://x/content?index=0"], usage={"cost": 0.42})
        return httpx.Response(200, json=body)

    p, fake = provider({
        ("GET", "/api/v1/videos/models"): httpx.Response(200, json=MODELS),
        ("POST", "/api/v1/videos"): httpx.Response(202, json={"id": "job1", "polling_url": "https://openrouter.ai/api/v1/videos/job1", "status": "pending"}),
        ("GET", "/api/v1/videos/job1"): poll,
        ("GET", "/api/v1/videos/job1/content"): httpx.Response(200, content=payload),
    })
    dest = tmp_path / "broll.mp4"
    cost, plan = p.generate_video_clip("a serum bottle on marble", dest, profile=None, duration=4, aspect_ratio="9:16",
                                       sleep=lambda _s: None)
    assert cost == 0.42 and plan.model == "vendor/video-x" and dest.read_bytes() == payload
    submit = next(c for c in fake.calls if c.method == "POST")
    body = json.loads(submit.content)
    assert body == {"model": "vendor/video-x", "prompt": "a serum bottle on marble", "generate_audio": False,
                    "duration": 4, "resolution": "720p", "aspect_ratio": "9:16"}
    assert all(c.headers["authorization"] == f"Bearer {KEY}" for c in fake.calls)


def test_video_generation_failure_timeout_and_cancel(tmp_path):
    base = {("GET", "/api/v1/videos/models"): httpx.Response(200, json=MODELS),
            ("POST", "/api/v1/videos"): httpx.Response(202, json={"id": "j", "status": "pending"})}
    p, _ = provider({**base, ("GET", "/api/v1/videos/j"): httpx.Response(200, json={"id": "j", "status": "failed", "error": f"boom {KEY}"})})
    with pytest.raises(ProviderError) as e:
        p.generate_video_clip("x", tmp_path / "a.mp4", profile=None, duration=4, aspect_ratio="9:16", sleep=lambda _s: None)
    assert e.value.code == "GENERATION_FAILED" and KEY not in str(e.value)

    p, _ = provider({**base, ("GET", "/api/v1/videos/j"): httpx.Response(200, json={"id": "j", "status": "in_progress"})},
                    video_poll_timeout_seconds=0.0)
    with pytest.raises(ProviderError) as e:
        p.generate_video_clip("x", tmp_path / "b.mp4", profile=None, duration=4, aspect_ratio="9:16", sleep=lambda _s: None)
    assert e.value.code == "TIMEOUT"

    p, _ = provider({**base, ("GET", "/api/v1/videos/j"): httpx.Response(200, json={"id": "j", "status": "in_progress"})})
    with pytest.raises(ProviderError) as e:
        p.generate_video_clip("x", tmp_path / "c.mp4", profile=None, duration=4, aspect_ratio="9:16",
                              should_cancel=lambda: True, sleep=lambda _s: None)
    assert e.value.code == "CANCELLED"


def test_empty_download_is_an_error(tmp_path):
    p, _ = provider({("GET", "/api/v1/videos/j/content"): httpx.Response(200, content=b"")})
    with pytest.raises(ProviderError):
        p.download_video("j", tmp_path / "x.mp4")


def test_key_never_in_logs_or_repr(capsys):
    p, _ = provider({("GET", "/api/v1/key"): httpx.Response(401, json={})})
    with pytest.raises(ProviderError):
        p.verify_key()
    assert KEY not in capsys.readouterr().out
    assert KEY not in repr(p.settings) and KEY not in str(p.settings.model_dump())


def test_worker_source_and_client_code_never_reference_the_key_outside_settings():
    """The key is a backend-only secret: not in any schema returned to clients, not in the mobile tree."""
    from pathlib import Path

    from server.schemas import edit, generation, misc

    for mod in (edit, generation, misc):
        assert "openrouter" not in Path(mod.__file__).read_text(encoding="utf-8").lower()
    mobile = Path(__file__).resolve().parents[2] / "mobile" / "lib"
    if mobile.exists():
        for f in mobile.rglob("*.dart"):
            text = f.read_text(encoding="utf-8").lower()
            # secrets, not words: a comment warning about keys is fine; key material or key env names are not
            assert "sk-or-" not in text and "sk-ant-" not in text and "openrouter_api_key" not in text and "anthropic_api_key" not in text, f


# ------------------------------------------------------------------ worker-side generative B-roll gate
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")
def test_enabled_broll_generates_downloads_and_is_capped_and_budgeted(client, upload_asset, real_engine, tmp_path, monkeypatch):
    from server.runtime.local_edit_runtime import LocalEditRuntime
    from server.runtime.router_runtime import EditRouterRuntime
    from server.worker.tasks import execute_generation

    settings = real_engine["settings"].model_copy(update={
        "enable_generative_broll": True, "openrouter_api_key": SecretStr(KEY), "openrouter_video_model": "vendor/video-x",
        "max_broll_clips_per_edit": 1, "video_poll_interval_seconds": 0.0})
    generated: list[str] = []

    class StubProvider:
        def generate_video_clip(self, prompt, dest, **kw):
            generated.append(prompt)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(FIXTURE_VIDEO, dest)
            return 0.30, None

    rt = EditRouterRuntime(settings, LocalEditRuntime(settings, provider_factory=lambda: StubProvider()), None)
    a = upload_asset()
    body = {"asset_ids": [a["id"]], "instruction": ("Tighten the pacing. Generate a new shot of the bottle on a marble vanity. "
                                                    "Generate another clip of hands applying serum.")}
    eid = client.post("/v1/edits", json=body, headers={"Idempotency-Key": uuid.uuid4().hex}).json()["id"]
    assert execute_generation(eid, settings=settings, runtime=rt, shutdown_requested=lambda: False) == "completed"
    assert len(generated) == 1  # capped at max_broll_clips_per_edit even though two were requested
    from server.db.models import Generation
    from server.db.session import get_sessionmaker

    with get_sessionmaker()() as s:
        g = s.get(Generation, uuid.UUID(eid))
        assert g.actual_cost_usd == pytest.approx(0.30) and g.meta["warnings"] == []
    assert client.get(f"/v1/edits/{eid}").json()["warnings"] == []
