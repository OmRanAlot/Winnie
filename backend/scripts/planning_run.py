"""Create, resume or inspect a local durable event-planning run."""

import argparse
import asyncio
import json
from uuid import UUID

from app.core.settings import Settings
from app.schemas.pipeline import PipelineRequest
from app.services.planning_runs import PlanningRuns


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--event", required=True)
    create.add_argument("--idea", required=True)
    create.add_argument("--date", required=True)
    create.add_argument("--semester", required=True)
    create.add_argument("--run", action="store_true", help="Generate immediately, pausing at review.")
    for name in ("show", "resume"):
        command = commands.add_parser(name)
        command.add_argument("run_id", type=UUID)
    args = parser.parse_args()
    runs = PlanningRuns(Settings())
    if args.command == "create":
        result = runs.create(PipelineRequest(event_name=args.event, idea=args.idea,
                                            event_date=args.date, semester_code=args.semester))
        if args.run:
            print(json.dumps({"id": result["id"], "status": "queued"}), flush=True)
            result = asyncio.run(runs.execute(result["id"]))
    elif args.command == "resume":
        result = asyncio.run(runs.execute(str(args.run_id)))
    else:
        result = runs.get(str(args.run_id))
    # Full output includes the persisted proposal and exact revision needed for HTTP review.
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
