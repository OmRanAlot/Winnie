"""Durable generation/status/review endpoints mounted under /api/planning/runs."""

import logging
from secrets import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException

from app.core.settings import Settings
from app.integrations.planning_runs import RunConflict, RunNotFound
from app.routes.tasks import envelope
from app.schemas.pipeline import PipelineRequest
from app.schemas.planning_runs import PlanningReview
from app.services.planning_runs import PlanningRuns, RunSetupError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/runs")


def get_planning_runs():
    return PlanningRuns(Settings())


Runs = Annotated[PlanningRuns, Depends(get_planning_runs)]


def authorize_review(x_winnie_planning_review_key: str = Header(default="")):
    expected = Settings().planning_review_api_key.get_secret_value()
    if not expected:
        raise HTTPException(503, "Configure WINNIE_PLANNING_REVIEW_API_KEY to enable review.")
    if not compare_digest(expected.encode(), x_winnie_planning_review_key.encode()):
        raise HTTPException(401, "Invalid planning review key.")


def operation(call):
    try:
        return envelope(call(), {"activated": False, "storage": "local_checkpoint"})
    except RunNotFound:
        raise HTTPException(404, "Planning run not found.")
    except RunConflict as exc:
        raise HTTPException(409, str(exc))
    except RunSetupError:
        raise HTTPException(503, "Planning context is unavailable. Check configured source files.")


async def execute_in_background(runs, run_id):
    try:
        await runs.execute(run_id)
    except (RunConflict, RunNotFound):
        logger.info("Planning run %s was already claimed or removed", run_id)


@router.post("", status_code=202)
def create_run(request: PipelineRequest, background: BackgroundTasks, runs: Runs):
    response = operation(lambda: runs.create(request))
    background.add_task(execute_in_background, runs, response["data"]["id"])
    return response


@router.get("/{run_id}")
def get_run(run_id: UUID, runs: Runs):
    return operation(lambda: runs.get(str(run_id)))


@router.post("/{run_id}/resume", status_code=202)
def resume_run(run_id: UUID, background: BackgroundTasks, runs: Runs):
    response = operation(lambda: runs.resumable(str(run_id)))
    if response["data"]["status"] in ("queued", "running", "failed"):
        background.add_task(execute_in_background, runs, str(run_id))
    return response


@router.post("/{run_id}/review", dependencies=[Depends(authorize_review)])
async def review_run(run_id: UUID, review: PlanningReview, runs: Runs):
    try:
        result = await runs.review(str(run_id), review)
    except RunNotFound:
        raise HTTPException(404, "Planning run not found.")
    except RunConflict as exc:
        raise HTTPException(409, str(exc))
    return envelope(result, {"activated": False, "storage": "local_checkpoint"})
