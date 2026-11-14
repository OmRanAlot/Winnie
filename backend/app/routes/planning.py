"""Read-only draft generation, protected using the existing task API access policy."""

from fastapi import APIRouter, Depends, HTTPException

from app.core.settings import REPO_ROOT, Settings
from app.routes.planning_runs import router as runs_router
from app.routes.tasks import authorize_tasks, envelope
from app.schemas.pipeline import PipelineRequest
from app.schemas.planning import PlanningDraft, PlanningRequest
from app.services.planning import PlanningUnavailable, create_draft
from app.services.planning_pipeline import run_pipeline

router = APIRouter(prefix="/api/planning", tags=["planning"],
                   dependencies=[Depends(authorize_tasks)])
router.include_router(runs_router)


@router.post("/drafts")
async def draft_plan(request: PlanningRequest):
    settings = Settings()
    path = settings.planning_knowledge_path
    if not path.is_absolute():
        path = REPO_ROOT / path
    try:
        draft: PlanningDraft = await create_draft(
            request, knowledge_path=path, mode=settings.planning_mode,
            model=settings.planning_model, timeout=settings.planning_timeout_seconds,
        )
    except PlanningUnavailable:
        raise HTTPException(503, "Planning unavailable. Check local context, model and credentials.")
    return envelope(draft.model_dump(mode="json"), {"persisted": False, "activated": False})


@router.post("/pipeline-drafts")
async def pipeline_draft(request: PipelineRequest):
    settings = Settings()

    def resolved(path):
        return path if path is None or path.is_absolute() else REPO_ROOT / path

    try:
        draft = await run_pipeline(
            request, knowledge_path=resolved(settings.planning_knowledge_path),
            taxonomy_path=resolved(settings.planning_taxonomy_path),
            roster_path=resolved(settings.planning_roster_path),
            history_semester=settings.planning_history_semester, mode=settings.planning_mode,
            model=settings.planning_model, timeout=settings.planning_pipeline_timeout_seconds,
        )
    except PlanningUnavailable:
        raise HTTPException(503, "Staged planning unavailable. Check context, roster and model setup.")
    return envelope(draft.model_dump(mode="json"), {"persisted": False, "activated": False})
