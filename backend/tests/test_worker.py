from __future__ import annotations

import json
import shutil
import subprocess
import uuid

import pytest

from server.core.errors import ErrorCode
from server.db.models import Generation
from server.db.session import get_sessionmaker
from server.runtime.base import Abort, JobContext, RuntimeOrchestrator, RuntimeResult
from server.runtime.mock_runtime import MockRuntime, _write_checkpoint
from server.schemas.generation import GenerationCreate
from server.services import generation_service as svc
from server.services.output_validation import OutputInvalid, extract_thumbnail, validate_output
from server.services.storage import LocalStorage, StorageError
from server.worker import tasks
from server.worker.tasks import RetryableError, execute_generation

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg/ffprobe required")


def _new(env, **over) -> uuid.UUID:
    req = GenerationCreate(prompt="A calm documentary about tide pools at dawn", **over)
    with get_sessionmaker()() as s:
        gen, _ = svc.create_generation(s, req, user_id="dev", idempotency_key=None, settings=env["settings"])
        return gen.id


def _get(gid) -> Generation:
    with get_sessionmaker()() as s:
        return s.get(Generation, gid)


def _run(env, gid, runtime=None, **kw):
    kw.setdefault("shutdown_requested", lambda: False)
    return execute_generation(str(gid), settings=env["settings"], runtime=runtime or MockRuntime(0.0), **kw)


class ScriptedRuntime(RuntimeOrchestrator):
    name = "scripted"

    def __init__(self, fn):
        self.fn, self.calls = fn, 0

    def run_generation(self, ctx: JobContext) -> RuntimeResult:
        self.calls += 1
        return self.fn(ctx)


def _make_video(path, audio=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=1"]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=duration=1", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)


# -- success path --------------------------------------------------------------

def test_worker_success_uploads_validates_and_completes(env):
    gid = _new(env)
    assert _run(env, gid) == "completed"
    gen = _get(gid)
    assert gen.status == "completed" and gen.progress == 100 and gen.current_stage == "complete"
    assert gen.output_storage_key == f"generations/{gid}/final.mp4"
    assert gen.thumbnail_storage_key == f"generations/{gid}/thumbnail.jpg"
    assert gen.started_at and gen.completed_at and gen.actual_cost_usd is not None
    assert gen.meta["output"]["has_audio"] is True and gen.meta["output"]["duration_seconds"] > 0
    st = LocalStorage(env["settings"].local_storage_path)
    assert st.exists(gen.output_storage_key) and st.exists(gen.thumbnail_storage_key)
    validate_output(st.resolve(gen.output_storage_key), expect_audio=True)
    project = env["engine"] / "projects" / str(gid)
    assert not (project / "renders").exists()  # large media cleaned after upload
    assert (project / "checkpoint_compose.json").exists()  # debug JSON kept


def test_worker_persists_runtime_cut_ranges(env):
    gid = _new(env)

    def render_with_cut_map(ctx: JobContext) -> RuntimeResult:
        result = MockRuntime(0.0).run_generation(ctx)
        result.kept_ranges = [{"start": 0.0, "end": 0.6}]
        return result

    assert _run(env, gid, ScriptedRuntime(render_with_cut_map)) == "completed"
    assert _get(gid).meta["kept_ranges"] == [{"start": 0.0, "end": 0.6}]


def test_progress_persisted_from_checkpoints_during_run(env):
    gid = _new(env)
    seen = []

    class Watcher(MockRuntime):
        def _sleep(self, ctx, seconds):
            r = super()._sleep(ctx, seconds)
            with get_sessionmaker()() as s:
                g = s.get(Generation, gid)
                seen.append((g.status, g.progress, g.current_stage))
            return r

    _run(env, gid, Watcher(0.0))
    progresses = [p for _, p, _ in seen]
    assert progresses == sorted(progresses) and progresses[-1] > progresses[0]
    assert {"running"} == {s for s, _, _ in seen}
    assert "assets" in {stage for _, _, stage in seen}


def test_already_terminal_is_idempotent_and_skips_runtime(env):
    gid = _new(env)
    assert _run(env, gid) == "completed"
    rt = ScriptedRuntime(lambda ctx: pytest.fail("runtime must not run"))
    assert _run(env, gid, rt) == "already_terminal" and rt.calls == 0


def test_unknown_generation_is_a_noop(env):
    assert _run(env, uuid.uuid4()) == "not_found"


# -- failure / sanitization -----------------------------------------------------

def test_runtime_failure_marks_failed_with_sanitized_error(env):
    gid = _new(env)
    rt = ScriptedRuntime(lambda ctx: RuntimeResult("failed", error_code="GENERATION_FAILED",
                                                   detail="Traceback /app/openmontage/x.py sk-ant-api03-SECRETSECRET"))
    assert _run(env, gid, rt) == "failed"
    gen = _get(gid)
    assert gen.status == "failed" and gen.error_code == "GENERATION_FAILED"
    assert gen.error_message == "We couldn't finish this video."
    assert "SECRET" not in gen.error_message and "/app" not in gen.error_message
    assert gen.output_storage_key is None


def test_runtime_exception_marks_failed(env):
    gid = _new(env)

    def boom(ctx):
        raise RuntimeError("kaboom /etc/secret")

    assert _run(env, gid, ScriptedRuntime(boom)) == "failed"
    gen = _get(gid)
    assert gen.status == "failed" and "kaboom" not in (gen.error_message or "")


def test_mock_failure_prompt_flows_through(env):
    req = GenerationCreate(prompt="MOCK_FAIL please break this video now")
    with get_sessionmaker()() as s:
        gid = svc.create_generation(s, req, user_id="dev", idempotency_key=None, settings=env["settings"])[0].id
    assert _run(env, gid) == "failed" and _get(gid).status == "failed"


def test_budget_exceeded_aborts_and_fails(env):
    gid = _new(env)

    def overspend(ctx: JobContext):
        _write_checkpoint(ctx.project_dir, ctx.project_id, ctx.pipeline, "research", "in_progress", spent=99.0)
        abort = ctx.poll()
        assert abort and abort.code == "BUDGET_EXCEEDED"
        return RuntimeResult("aborted", abort=abort)

    assert _run(env, gid, ScriptedRuntime(overspend)) == "failed"
    assert _get(gid).error_code == "BUDGET_EXCEEDED"


def test_pipeline_stalled_on_human_gate_fails(env):
    gid = _new(env)

    def stall(ctx: JobContext):
        _write_checkpoint(ctx.project_dir, ctx.project_id, ctx.pipeline, "proposal", "awaiting_human")
        return RuntimeResult("aborted", abort=ctx.poll())

    assert _run(env, gid, ScriptedRuntime(stall)) == "failed"


# -- cancellation & shutdown ------------------------------------------------------

def test_cancel_mid_run_ends_cancelled_not_completed(env):
    gid = _new(env)

    def cancel_then_poll(ctx: JobContext):
        with get_sessionmaker()() as s:
            svc.request_cancel(s, gid, "dev")
        abort = ctx.poll()
        assert abort and abort.code == "CANCELLED"
        return RuntimeResult("aborted", abort=abort)

    assert _run(env, gid, ScriptedRuntime(cancel_then_poll)) == "cancelled"
    assert _get(gid).status == "cancelled"


def test_cancel_requested_before_start_is_honoured(env):
    gid = _new(env)
    with get_sessionmaker()() as s:
        svc.mark_starting(s, gid, "p", "mock")
        svc.request_cancel(s, gid, "dev")
    rt = ScriptedRuntime(lambda ctx: pytest.fail("must not run"))
    assert _run(env, gid, rt) == "cancelled"


def test_completed_output_wins_over_late_cancel_request(env):
    gid = _new(env)

    def finish_after_cancel(ctx: JobContext):
        import dataclasses

        result = MockRuntime(0.0).run_generation(dataclasses.replace(ctx, poll=lambda: None))
        with get_sessionmaker()() as s:  # cancel lands only after the render already finished
            svc.request_cancel(s, gid, "dev")
        return result

    assert _run(env, gid, ScriptedRuntime(finish_after_cancel)) == "completed"
    assert _get(gid).status == "completed"


def test_sigterm_requeues_instead_of_failing_or_completing(env):
    gid = _new(env)
    requeued = []
    rt = ScriptedRuntime(lambda ctx: RuntimeResult("aborted", abort=ctx.poll()))
    assert _run(env, gid, rt, shutdown_requested=lambda: True, requeue=requeued.append) == "requeued"
    gen = _get(gid)
    assert gen.status == "queued" and gen.meta["restarts"] == 1 and requeued == [gid]
    # ...and the redelivered task then completes normally
    assert _run(env, gid) == "completed"


# -- output validation -------------------------------------------------------------

def test_invalid_output_is_never_marked_completed(env):
    gid = _new(env)

    def garbage(ctx: JobContext):
        (ctx.project_dir / "renders").mkdir(parents=True, exist_ok=True)
        (ctx.project_dir / "renders" / "final.mp4").write_bytes(b"not a video")
        _write_checkpoint(ctx.project_dir, ctx.project_id, ctx.pipeline, "compose", "completed")
        return RuntimeResult("completed")

    assert _run(env, gid, ScriptedRuntime(garbage)) == "failed"
    gen = _get(gid)
    assert gen.status == "failed" and gen.error_code == "OUTPUT_INVALID" and gen.output_storage_key is None


def test_missing_audio_fails_when_voice_expected(env):
    def silent(ctx: JobContext):
        _make_video(ctx.project_dir / "renders" / "final.mp4", audio=False)
        _write_checkpoint(ctx.project_dir, ctx.project_id, ctx.pipeline, "compose", "completed")
        return RuntimeResult("completed")

    gid = _new(env, voice_enabled=True)
    assert _run(env, gid, ScriptedRuntime(silent)) == "failed" and _get(gid).error_code == "OUTPUT_INVALID"
    gid2 = _new(env, voice_enabled=False)
    assert _run(env, gid2, ScriptedRuntime(silent)) == "completed"


def test_validate_output_rules(tmp_path):
    good = tmp_path / "a.mp4"
    _make_video(good)
    probe = validate_output(good, expect_audio=True)
    assert probe.duration_seconds > 0 and probe.video_codec == "h264" and probe.has_audio and probe.size_bytes > 0
    with pytest.raises(OutputInvalid):
        validate_output(tmp_path / "missing.mp4", expect_audio=False)
    empty = tmp_path / "e.mp4"
    empty.write_bytes(b"")
    with pytest.raises(OutputInvalid):
        validate_output(empty, expect_audio=False)
    audio_only = tmp_path / "a.m4a"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=duration=1", str(audio_only)], check=True)
    with pytest.raises(OutputInvalid, match="video stream"):
        validate_output(audio_only, expect_audio=False)
    thumb = tmp_path / "t.jpg"
    assert extract_thumbnail(good, thumb, 0.3) and thumb.stat().st_size > 0
    assert extract_thumbnail(empty, tmp_path / "x.jpg", 0.3) is False


# -- upload retry semantics ----------------------------------------------------------

class FlakyStorage(LocalStorage):
    def __init__(self, root, failures):
        super().__init__(root)
        self.failures = failures

    def put_file(self, key, path, content_type=None):
        if self.failures > 0:
            self.failures -= 1
            raise StorageError("boom https://u:pw@r2/x")
        super().put_file(key, path, content_type)


def test_upload_failure_retries_then_reuses_render_without_rerunning_agent(env, tmp_path):
    gid = _new(env)
    storage = FlakyStorage(tmp_path / "s", failures=1)
    rt = ScriptedRuntime(lambda ctx: MockRuntime(0.0).run_generation(ctx))
    with pytest.raises(RetryableError):
        _run(env, gid, rt, storage=storage, attempt=0, max_retries=2)
    assert _get(gid).status == "running" and rt.calls == 1  # not failed, not completed

    # Celery retry: the finished render is reused; the (paid) agent does not run again.
    assert _run(env, gid, rt, storage=storage, attempt=1, max_retries=2) == "completed"
    assert rt.calls == 1 and _get(gid).status == "completed"


def test_upload_failure_on_last_attempt_fails_with_storage_error(env, tmp_path):
    gid = _new(env)
    storage = FlakyStorage(tmp_path / "s", failures=99)
    assert _run(env, gid, storage=storage, attempt=2, max_retries=2) == "failed"
    gen = _get(gid)
    assert gen.status == "failed" and gen.error_code == ErrorCode.STORAGE_FAILED.value and gen.output_storage_key is None


# -- celery wiring -------------------------------------------------------------------

def test_celery_configuration(env):
    from server.services.queue import TASK_NAME
    from server.worker.celery_app import celery_app

    conf = celery_app.conf
    assert TASK_NAME in celery_app.tasks
    assert conf.task_acks_late and conf.task_reject_on_worker_lost and conf.worker_prefetch_multiplier == 1
    assert conf.task_soft_time_limit < conf.task_time_limit < conf.broker_transport_options["visibility_timeout"]
    task = celery_app.tasks[TASK_NAME]
    assert task.max_retries >= 1 and RetryableError in task.autoretry_for


def test_workspace_id_is_uuid_only():
    from server.runtime.openmontage_runtime import WorkspaceError, safe_project_id

    assert safe_project_id(uuid.UUID(int=5)) == str(uuid.UUID(int=5))
    for bad in ("../x", "my prompt text", "", "a" * 36):
        with pytest.raises(WorkspaceError):
            safe_project_id(bad)


def test_old_workspaces_are_purged(env):
    import os
    import time

    from server.runtime.openmontage_runtime import prepare_workspace, purge_old_workspaces

    old, fresh = str(uuid.uuid4()), str(uuid.uuid4())
    for pid in (old, fresh):
        prepare_workspace(env["engine"], pid)
    past = time.time() - 48 * 3600
    os.utime(env["engine"] / "projects" / old, (past, past))
    assert purge_old_workspaces(env["engine"], 24) == 1
    assert not (env["engine"] / "projects" / old).exists() and (env["engine"] / "projects" / fresh).exists()


_ = (json, tasks, Abort)
