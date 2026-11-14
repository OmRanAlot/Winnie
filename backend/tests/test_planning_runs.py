"""Real SQLite/LangGraph checkpoint tests with synthetic context and fake specialists."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.settings import Settings
from app.integrations.planning_runs import RunConflict
from app.main import app
from app.routes.planning_runs import get_planning_runs
from app.routes.tasks import authorize_tasks
from app.schemas.planning_runs import PlanningReview
from app.services.planning_runs import PlanningRuns, RunContextChanged
from tests.test_planning_pipeline import (
    FakeRunner,
    request,
    sources,  # noqa: F401
)


@pytest.fixture
def configured(sources, tmp_path):  # noqa: F811
    return Settings(_env_file=None, planning_mode="deepagents", planning_model="test:fake",
                    planning_runs_path=tmp_path / "runs.sqlite3",
                    planning_knowledge_path=sources["knowledge_path"],
                    planning_taxonomy_path=sources["taxonomy_path"],
                    planning_roster_path=sources["roster_path"])


@pytest.mark.asyncio
async def test_pauses_for_review_and_resumes_from_checkpoint_without_model_calls(configured):
    first_runner = FakeRunner()
    service = PlanningRuns(configured, runner_factory=lambda model: first_runner)
    run = service.create(request())
    result = await service.execute(run["id"])
    assert result["status"] == "waiting_for_review"
    assert len(result["revision"]) == 64
    assert result["activated"] is False
    assert first_runner.calls == ["classify", "classify_history", "tasks", "dependencies", "timeline"]
    assert result["draft"]["status"] == "draft"

    second_runner = FakeRunner()
    reopened = PlanningRuns(configured, runner_factory=lambda model: second_runner)
    review = PlanningReview(decision="approve", expected_revision=result["revision"])
    approved = await reopened.review(run["id"], review)
    assert approved["status"] == "approved"
    assert approved["activated"] is False
    assert second_runner.calls == []
    assert (await reopened.review(run["id"], review))["decision"] == approved["decision"]
    with pytest.raises(RunConflict):
        await reopened.review(run["id"], review.model_copy(update={"decision": "reject"}))


@pytest.mark.asyncio
async def test_retry_reuses_completed_specialists_after_failure(configured):
    class Interrupted(FakeRunner):
        async def run(self, stage, schema, payload):
            if stage == "timeline":
                raise RuntimeError("PRIVATE PROVIDER ERROR")
            return await super().run(stage, schema, payload)

    service = PlanningRuns(configured, runner_factory=lambda model: Interrupted())
    run = service.create(request())
    failed = await service.execute(run["id"])
    assert failed["status"] == "failed"
    assert "PRIVATE" not in json.dumps(failed)
    replacement = FakeRunner()
    reopened = PlanningRuns(configured, runner_factory=lambda model: replacement)
    resumed = await reopened.execute(run["id"])
    assert resumed["status"] == "waiting_for_review"
    assert replacement.calls == ["timeline"]
    assert sum(event["action"] == "reused" for event in resumed["progress"]) == 4


@pytest.mark.asyncio
async def test_retry_in_a_new_python_process_reuses_saved_stages(configured):
    class Interrupted(FakeRunner):
        async def run(self, stage, schema, payload):
            if stage == "timeline":
                raise RuntimeError("Interrupted")
            return await super().run(stage, schema, payload)

    service = PlanningRuns(configured, runner_factory=lambda model: Interrupted())
    run = service.create(request())
    assert (await service.execute(run["id"]))["status"] == "failed"
    code = """
import asyncio, json, sys
from pathlib import Path
from app.core.settings import Settings
from app.services.planning_runs import PlanningRuns
from tests.test_planning_pipeline import FakeRunner
runner = FakeRunner()
service = PlanningRuns(Settings(_env_file=None, planning_runs_path=Path(sys.argv[1])), runner_factory=lambda model: runner)
result = asyncio.run(service.execute(sys.argv[2]))
print(json.dumps({'status': result['status'], 'calls': runner.calls}))
"""
    # An actual new interpreter proves that no in-process agent state is needed to resume.
    child = await asyncio.to_thread(subprocess.run,
        [sys.executable, "-c", code, str(configured.planning_runs_path), run["id"]],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, child.stderr
    assert json.loads(child.stdout.strip().splitlines()[-1]) == {
        "status": "waiting_for_review", "calls": ["timeline"],
    }


@pytest.mark.asyncio
async def test_review_interrupt_survives_a_new_python_process(configured):
    service = PlanningRuns(configured, runner_factory=lambda model: FakeRunner())
    run = service.create(request())
    ready = await service.execute(run["id"])
    code = """
import asyncio, json, sys
from pathlib import Path
from app.core.settings import Settings
from app.schemas.planning_runs import PlanningReview
from app.services.planning_runs import PlanningRuns
from tests.test_planning_pipeline import FakeRunner
runner = FakeRunner()
service = PlanningRuns(Settings(_env_file=None, planning_runs_path=Path(sys.argv[1])), runner_factory=lambda model: runner)
result = asyncio.run(service.review(sys.argv[2], PlanningReview(decision='reject', expected_revision=sys.argv[3])))
print(json.dumps({'status': result['status'], 'calls': runner.calls, 'activated': result['activated']}))
"""
    child = await asyncio.to_thread(subprocess.run,
        [sys.executable, "-c", code, str(configured.planning_runs_path), run["id"], ready["revision"]],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, child.stderr
    assert json.loads(child.stdout.strip().splitlines()[-1]) == {
        "status": "rejected", "calls": [], "activated": False,
    }
    assert service.get(run["id"])["status"] == "rejected"


@pytest.mark.asyncio
async def test_stale_revision_and_changed_context_cannot_be_reviewed(configured):
    service = PlanningRuns(configured, runner_factory=lambda model: FakeRunner())
    run = service.create(request())
    ready = await service.execute(run["id"])
    with pytest.raises(RunConflict):
        await service.review(run["id"], PlanningReview(decision="approve", expected_revision="0" * 64))
    with configured.planning_taxonomy_path.open("a", encoding="utf-8") as file:
        file.write("\n")
    with pytest.raises(RunContextChanged):
        await service.review(run["id"], PlanningReview(decision="approve", expected_revision=ready["revision"]))


@pytest.mark.asyncio
async def test_changed_context_prevents_retry(configured):
    service = PlanningRuns(configured)
    run = service.create(request())
    configured.planning_knowledge_path.write_text("{}", encoding="utf-8")
    with pytest.raises(RunContextChanged):
        await service.execute(run["id"])


@pytest.mark.asyncio
async def test_concurrent_execution_is_not_duplicated(configured):
    entered = asyncio.Event()

    class Stalled:
        async def run(self, *args):
            entered.set()
            await asyncio.Event().wait()

    service = PlanningRuns(configured, runner_factory=lambda model: Stalled())
    run = service.create(request())
    worker = asyncio.create_task(service.execute(run["id"]))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        with pytest.raises(RunConflict):
            await service.execute(run["id"])
    finally:
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker


def test_api_generation_progress_and_protected_review(configured, monkeypatch, signed_in_member):
    service = PlanningRuns(configured, runner_factory=lambda model: FakeRunner())
    app.dependency_overrides[get_planning_runs] = lambda: service
    app.dependency_overrides[authorize_tasks] = lambda: signed_in_member
    monkeypatch.setenv("WINNIE_PLANNING_REVIEW_API_KEY", "")
    try:
        with TestClient(app) as client:
            created = client.post("/api/planning/runs", json=request().model_dump(mode="json"))
            assert created.status_code == 202
            run_id = created.json()["data"]["id"]
            ready = client.get(f"/api/planning/runs/{run_id}").json()["data"]
            assert ready["status"] == "waiting_for_review"
            body = {"decision": "approve", "expected_revision": ready["revision"]}
            url = f"/api/planning/runs/{run_id}/review"
            # Review uses the same verified administrator identity as the dashboard.
            headers = {}
            stale = {**body, "expected_revision": "0" * 64}
            assert client.post(url, json=stale, headers=headers).status_code == 409
            approved = client.post(url, json=body, headers=headers)
            assert approved.status_code == 200
            assert approved.json()["data"]["status"] == "approved"
            assert approved.json()["data"]["activated"] is False
            assert "context" not in ready
            assert client.get("/api/planning/runs/00000000-0000-0000-0000-000000000000").status_code == 404
    finally:
        app.dependency_overrides.pop(get_planning_runs, None)
        app.dependency_overrides.pop(authorize_tasks, None)
