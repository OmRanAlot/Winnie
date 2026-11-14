"""Run a draft pipeline and save a private review artifact; never activates tasks."""

import argparse
import asyncio
import json
from pathlib import Path

from app.core.settings import REPO_ROOT, Settings
from app.schemas.pipeline import PipelineRequest
from app.services.planning_pipeline import run_pipeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True)
    parser.add_argument("--idea", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--semester", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new output filename; existing drafts are never overwritten.")
    settings = Settings()

    def resolved(path):
        return path if path is None or path.is_absolute() else REPO_ROOT / path

    draft = asyncio.run(run_pipeline(
        PipelineRequest(event_name=args.event, idea=args.idea, event_date=args.date,
                        semester_code=args.semester),
        knowledge_path=resolved(settings.planning_knowledge_path),
        taxonomy_path=resolved(settings.planning_taxonomy_path),
        roster_path=resolved(settings.planning_roster_path),
        history_semester=settings.planning_history_semester, mode=settings.planning_mode,
        model=settings.planning_model, timeout=settings.planning_pipeline_timeout_seconds,
    ))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(draft.model_dump_json(indent=2))
    print(json.dumps({"mode": draft.mode, "category": draft.classification.category,
                      "tasks": len(draft.plan.tasks), "stages": len(draft.completed_stages),
                      "persisted_to_task_store": False}))


if __name__ == "__main__":
    main()
