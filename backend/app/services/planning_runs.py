"""Durable, resumable planning and human review. Approval is not task activation."""

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from app.agents.planning_workflow import build_planning_workflow, draft_revision
from app.agents.prompts import STAGE_NAMES, stage_prompt
from app.agents.stages import DeepStageRunner
from app.core.settings import REPO_ROOT, Settings
from app.integrations.planning_runs import PlanningRunStore, RunConflict
from app.schemas.pipeline import PipelineDraft, PipelineRequest
from app.schemas.planning_runs import PlanningReview
from app.services.planning_pipeline import run_pipeline

logger = logging.getLogger(__name__)


class RunContextChanged(RunConflict):
    pass


class RunSetupError(Exception):
    pass


def resolved(path):
    return path if path is None or path.is_absolute() else REPO_ROOT / path


def signature(context: dict) -> str:
    """Pin source snapshots, prompt rules and validation code; never store API keys."""
    paths = [context["knowledge_path"], context["taxonomy_path"], context["roster_path"],
             str(REPO_ROOT / "backend/data/eboardMembers.json")]
    files = {str(path): hashlib.sha256(Path(path).read_bytes()).hexdigest()
             if Path(path).exists() else "missing" for path in paths if path}
    for name in ("services/planning_pipeline.py", "services/planning_policies.py",
                 "services/planning_history.py", "schemas/pipeline.py", "schemas/planning.py",
                 "agents/planning_workflow.py"):
        path = REPO_ROOT / "backend/app" / name
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    value = {"files": files, "prompts": {name: stage_prompt(name) for name in STAGE_NAMES},
             "mode": context["mode"], "model": context["model"],
             "history_semester": context["history_semester"], "workflow_version": 1}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class DurableStageRunner:
    def __init__(self, store, run_id, runner):
        self.store, self.run_id, self.runner = store, run_id, runner
        self.last_key = None

    def reject_last(self):
        if self.last_key:
            self.store.discard(self.run_id, self.last_key)

    async def run(self, stage, schema, payload):
        if "validation_feedback" in payload:
            self.reject_last()
        key = hashlib.sha256(json.dumps(
            [stage, schema.model_json_schema(), payload], sort_keys=True, default=str,
        ).encode()).hexdigest()
        self.last_key = key
        cached = self.store.cached(self.run_id, key)
        if cached:
            result = schema.model_validate_json(cached)
            self.store.event(self.run_id, stage, "reused")
            return result
        self.store.event(self.run_id, stage, "started")
        result = schema.model_validate(await self.runner.run(stage, schema, payload))
        self.store.cache(self.run_id, key, stage, result.model_dump_json())
        self.store.event(self.run_id, stage, "completed")
        return result


class PlanningRuns:
    def __init__(self, settings: Settings, *, runner_factory=DeepStageRunner):
        self.settings = settings
        self.store = PlanningRunStore(resolved(settings.planning_runs_path))
        self.runner_factory = runner_factory

    def create(self, request: PipelineRequest) -> dict:
        settings = self.settings
        context = {
            "knowledge_path": str(resolved(settings.planning_knowledge_path)),
            "taxonomy_path": str(resolved(settings.planning_taxonomy_path)),
            "roster_path": str(resolved(settings.planning_roster_path)) if settings.planning_roster_path else None,
            "history_semester": settings.planning_history_semester,
            "mode": settings.planning_mode, "model": settings.planning_model,
            "timeout": settings.planning_pipeline_timeout_seconds,
        }
        try:
            for name in ("knowledge_path", "taxonomy_path", "roster_path"):
                if context[name] and not Path(context[name]).is_file():
                    raise RunSetupError("Planning context is missing.")
            context["signature"] = signature(context)
        except OSError as exc:
            raise RunSetupError("Planning context could not be read.") from exc
        run_id = self.store.create(request.model_dump(mode="json"), context)
        return self.get(run_id)

    def get(self, run_id: str) -> dict:
        record = self.store.get(run_id)
        return {
            "id": run_id, "status": record["status"], "request": record["request"],
            "draft": record["draft"], "revision": record["revision"],
            "decision": record["decision"], "error_code": record["error_code"],
            "current_stage": record["current_stage"], "progress": self.store.events(run_id),
            "created_at": datetime.fromtimestamp(record["created_at"], UTC).isoformat(),
            "updated_at": datetime.fromtimestamp(record["updated_at"], UTC).isoformat(),
            "activated": False,
        }

    def check_context(self, record):
        try:
            matches = signature(record["context"]) == record["context"]["signature"]
        except OSError:
            matches = False
        if not matches:
            raise RunContextChanged("Planning references or rules changed. Start a new run.")

    async def execute(self, run_id: str) -> dict:
        record = self.store.get(run_id)
        if record["status"] in ("waiting_for_review", "approved", "rejected"):
            return self.get(run_id)
        self.check_context(record)
        return await self._invoke(run_id, record)

    def resumable(self, run_id: str) -> dict:
        record = self.store.get(run_id)
        if record["status"] not in ("waiting_for_review", "approved", "rejected"):
            self.check_context(record)
        return self.get(run_id)

    async def review(self, run_id: str, review: PlanningReview) -> dict:
        record = self.store.get(run_id)
        if review.expected_revision != record["revision"]:
            raise RunConflict("Review revision is stale or no draft is ready.")
        if record["status"] in ("approved", "rejected"):
            existing = record["decision"] or {}
            if existing.get("decision") == review.decision:
                return self.get(run_id)
            raise RunConflict("This draft has already received a different decision.")
        if record["status"] != "waiting_for_review":
            raise RunConflict("This run is not waiting for review.")
        self.check_context(record)
        return await self._invoke(run_id, record, review=review)

    async def _invoke(self, run_id, record, review=None):
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from langgraph.types import Command

        owner = self.store.claim(run_id)
        context = record["context"]
        runner = DurableStageRunner(self.store, run_id, self.runner_factory(context["model"]))

        async def generate(request):
            draft = await run_pipeline(
                PipelineRequest.model_validate(request),
                knowledge_path=Path(context["knowledge_path"]),
                taxonomy_path=Path(context["taxonomy_path"]),
                roster_path=Path(context["roster_path"]) if context["roster_path"] else None,
                history_semester=context["history_semester"], mode=context["mode"],
                model=context["model"], timeout=context["timeout"], runner=runner,
            )
            self.check_context(record)
            return draft.model_dump(mode="json")

        try:
            # Separate files avoid a synchronous progress write blocking the event loop
            # while the async checkpointer waits to commit its own transaction.
            checkpoint_path = self.store.path.with_suffix(".checkpoints.sqlite3")
            async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
                graph = build_planning_workflow(saver, generate)
                config = {"configurable": {"thread_id": run_id}}
                snapshot = await graph.aget_state(config)
                if review:
                    if (not snapshot.values.get("draft") or
                            draft_revision(snapshot.values["draft"]) != review.expected_revision):
                        raise RunConflict("Checkpoint does not match the reviewed revision.")
                    value = Command(resume=review.model_dump(mode="json"))
                else:
                    value = None if snapshot.values else {"request": record["request"]}
                await graph.ainvoke(value, config=config)
                snapshot = await graph.aget_state(config)
                draft = PipelineDraft.model_validate(snapshot.values["draft"]).model_dump(mode="json")
                decision = snapshot.values.get("decision")
                if decision:
                    status = "approved" if decision["decision"] == "approve" else "rejected"
                    decision = {**decision, "authorization": "planning_review_key",
                                "reviewed_at": datetime.now(UTC).isoformat()}
                elif snapshot.next:
                    status = "waiting_for_review"
                else:
                    raise ValueError("Workflow completed without a review decision.")
                self.store.event(run_id, "review", "requested" if status == "waiting_for_review" else status)
                self.store.finish(run_id, owner, status=status, draft=draft,
                                  revision=draft_revision(draft), decision=decision)
        except (Exception, asyncio.CancelledError) as exc:
            runner.reject_last()
            logger.warning("planning run %s stopped: %s", run_id, type(exc).__name__)
            self.store.finish(run_id, owner, status="failed", error_code="planning_interrupted")
            if isinstance(exc, (asyncio.CancelledError, RunConflict)):
                raise
        return self.get(run_id)
