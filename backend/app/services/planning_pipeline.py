"""Mandatory planner stages with validated handoffs; no storage or notification writes."""

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

from app.agents.stages import DeepStageRunner
from app.pipeline_schemas import (
    Classification,
    ClassifiedHistory,
    Dependencies,
    HistoricalClassification,
    PipelineDraft,
    PipelineRequest,
    Schedule,
    ScheduleItem,
)
from app.planning_schemas import DraftContents, PlanningRequest
from app.services.planning import PlanningUnavailable, validate_draft
from app.services.planning_context import normalize
from app.services.planning_history import (
    enrich_history,
    load_rosters,
    match_roles,
    timing_statistics,
)
from app.services.planning_policies import (
    ORDER_LEAD_DAYS,
    apply_task_policies,
    demo_secretary_roster,
    required_order_edges,
    validate_order_deadlines,
    validate_policy_dependencies,
)
from app.settings import REPO_ROOT


def exact_classification(name: str, taxonomy: dict) -> Classification:
    matches = [e for e in taxonomy["examples"] if normalize(e["event_name"]) == normalize(name)]
    if matches and len({e["category"] for e in matches}) == 1:
        return Classification(category=matches[0]["category"], confidence=1,
                              rationale="Exact labeled reference event.",
                              taxonomy_evidence_ids=[e["evidence_id"] for e in matches])
    return Classification(category="Unknown", confidence=0,
                          rationale="Offline mode only recognizes exact labeled examples.")


def validate_classification(result: Classification, taxonomy: dict):
    ids = {e["evidence_id"] for e in taxonomy["examples"]}
    if set(result.taxonomy_evidence_ids) - ids:
        raise ValueError("Classification fabricated taxonomy evidence.")
    if result.category != "Unknown" and not result.taxonomy_evidence_ids:
        raise ValueError("Inferred category requires reference evidence.")


def apply_dependencies(plan: DraftContents, dependencies: Dependencies, evidence: set):
    validate_policy_dependencies(plan, dependencies)
    tasks = {t.id: t.model_copy(deep=True) for t in plan.tasks}
    seen = set()
    for task in tasks.values():
        task.dependency_ids = []
    for edge in dependencies.edges:
        key = (edge.upstream_task_id, edge.downstream_task_id)
        if key in seen or key[0] not in tasks or key[1] not in tasks:
            raise ValueError("Duplicate edge or unknown dependency task ID.")
        if set(edge.evidence_ids) - evidence:
            raise ValueError("Dependency fabricated historical evidence.")
        if edge.basis == "explicit" and not edge.evidence_ids:
            raise ValueError("An explicit historical dependency requires evidence.")
        phases = {"before": 0, "during": 1, "after": 2}
        if phases[tasks[key[0]].phase] > phases[tasks[key[1]].phase]:
            raise ValueError("Dependency phases are in reverse order.")
        seen.add(key)
        tasks[key[1]].dependency_ids.append(key[0])
    return DraftContents(tasks=list(tasks.values()), questions=plan.questions)


def apply_schedule(plan, schedule, dependencies, request, examples):
    ids = {t.id for t in plan.tasks}
    if len(schedule.items) != len(ids) or {s.task_id for s in schedule.items} != ids:
        returned = [s.task_id for s in schedule.items]
        missing, extra = sorted(ids - set(returned)), sorted(set(returned) - ids)
        duplicates = sorted({task_id for task_id in returned if returned.count(task_id) > 1})
        raise ValueError(f"Schedule must cover every task exactly once. Missing: {missing}; "
                         f"unexpected: {extra}; duplicated: {duplicates}.")
    evidence = {t["evidence_id"] for e in examples for t in e["tasks"]}
    dates = {s.task_id: s.due_date for s in schedule.items}
    for item in schedule.items:
        if set(item.evidence_ids) - evidence:
            raise ValueError("Schedule fabricated historical evidence.")
    updated = DraftContents(tasks=[t.model_copy(update={"due_date": dates[t.id]}) for t in plan.tasks],
                            questions=plan.questions)
    # Reuse existing phase/evidence validation, without changing the legacy endpoint contract.
    validate_draft(updated, request, examples)
    validate_order_deadlines(updated, request.event_date)
    for edge in dependencies.edges:
        upstream, downstream = dates[edge.upstream_task_id], dates[edge.downstream_task_id]
        if upstream and downstream and (downstream - upstream).days < edge.minimum_gap_days:
            raise ValueError("Schedule violates a dependency buffer.")
    return updated


async def run_pipeline(request: PipelineRequest, *, knowledge_path: Path, taxonomy_path: Path,
                       roster_path: Path | None = None, history_semester: str = "fall-2026",
                       mode: str = "mock", model: str = "", timeout: float = 60,
                       runner=None) -> PipelineDraft:
    """One timeout bounds the entire staged run, not each provider request separately."""
    try:
        return await asyncio.wait_for(_pipeline(
            request, knowledge_path, taxonomy_path, roster_path, history_semester,
            mode, model, runner,
        ), timeout)
    except Exception as exc:
        raise PlanningUnavailable("Staged planning unavailable; check context and provider setup.") from exc


async def _pipeline(request, knowledge_path, taxonomy_path, roster_path, history_semester,
                    mode, model, runner):
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    if taxonomy.get("schema_version") != 1:
        raise ValueError("Unsupported taxonomy version.")
    knowledge = json.loads(knowledge_path.read_text(encoding="utf-8"))
    if knowledge.get("schema_version") != 1:
        raise ValueError("Unsupported knowledge version.")
    rosters = load_rosters(roster_path)
    events = enrich_history(knowledge, rosters, history_semester)
    if mode not in ("mock", "deepagents"):
        raise ValueError("Unknown planning mode.")
    if mode == "deepagents" and runner is None:
        if not model:
            raise ValueError("An explicit model is required.")
        runner = DeepStageRunner(model)
    stages, warnings = [], [
        "Historical deadlines measure scheduled lead time, not actual effort or completion time.",
        "Historical role labels require verified historical owners; inferred roles remain proposals.",
        "Historical examples are incomplete; task counts are tailored to the idea, not fixed by category.",
        "Draft only: no tasks are saved to member pages, activated or messaged.",
    ]

    async def stage(name, schema, payload):
        value = await runner.run(name, schema, payload)
        return schema.model_validate(value)

    async def validated_stage(name, schema, payload, validate):
        """Give the specialist actionable validation feedback, with bounded retries."""
        current_payload = payload
        for attempt in range(3):
            result = await stage(name, schema, current_payload)
            try:
                return result, validate(result)
            except ValueError as exc:
                if attempt == 2:
                    raise
                current_payload = {**payload, "validation_feedback": str(exc),
                                   "previous_attempt": result.model_dump(mode="json")}
        raise ValueError("Specialist repair attempts exhausted.")

    if request.category is not None:
        classification = Classification(category=request.category, confidence=1,
                                        rationale="Category explicitly provided in the request.")
    elif mode == "mock":
        classification = exact_classification(request.event_name, taxonomy)
    else:
        classification = await stage("classify", Classification, {
            "request": request.model_dump(mode="json"), "taxonomy": taxonomy,
        })
        validate_classification(classification, taxonomy)
    stages.append("event_classification")
    if mode == "mock":
        classified = ClassifiedHistory(events=[HistoricalClassification(
            event_id=e["event_id"], **exact_classification(e["name"], taxonomy).model_dump(),
        ) for e in events])
        warnings.append("MOCK: exact-name classification only; no idea reasoning or inferred dependencies.")
    else:
        classified = await stage("classify_history", ClassifiedHistory, {
            "taxonomy": taxonomy, "events": [
                {"event_id": e["event_id"], "name": e["name"], "legacy_type": e["event_type"]}
                for e in events],
        })
    expected_ids = {e["event_id"] for e in events}
    if len(classified.events) != len(expected_ids) or {e.event_id for e in classified.events} != expected_ids:
        raise ValueError("Historical classification must cover every event exactly once.")
    for item in classified.events:
        validate_classification(item, taxonomy)
    stages.append("historical_event_classification")
    accepted = {e.event_id for e in classified.events
                if e.category == classification.category and e.confidence >= .65
                and e.category != "Unknown" and classification.confidence >= .65}
    examples = [e for e in events if e["event_id"] in accepted and e["tasks"]]
    stats = timing_statistics(examples)
    stages.append("historical_task_role_and_lead_time_retrieval")
    if not examples:
        warnings.append("No confident matching Fall task history; new tasks require inference and review.")
    if any(s["sample_count"] < 3 for s in stats):
        warnings.append("Some timing patterns have fewer than three samples; treat them as weak precedents.")
    if any(not t["role_mapping_verified"] for e in examples for t in e["tasks"]):
        warnings.append("Some historical owners lack verified role mappings; their roles are unknown.")
    payload = {"request": request.model_dump(mode="json"),
               "classification": classification.model_dump(), "historical_examples": examples}
    if mode == "mock":
        from app.agents.planner import mock_plan

        # The legacy mock needs only name/idea/date; its old event_type does not classify here.
        plan = mock_plan(PlanningRequest(event_name=request.event_name, idea=request.idea,
                                        event_date=request.event_date, event_type="WiCS"), examples)
    else:
        plan = await stage("tasks", DraftContents, payload)
        if any(t.due_date is not None or t.dependency_ids for t in plan.tasks):
            raise ValueError("Task extraction cannot bypass scheduling or dependency stages.")
    validate_draft(plan, request, examples)
    plan = apply_task_policies(plan)
    stages.append("task_and_role_planning")
    evidence = {t["evidence_id"] for e in examples for t in e["tasks"]}
    payload["ordering_deadline"] = (request.event_date - timedelta(days=ORDER_LEAD_DAYS)).isoformat()
    payload["required_ordering_dependencies"] = required_order_edges(plan)
    if any(task.kind == "order_items" for task in plan.tasks) and request.event_date - timedelta(days=ORDER_LEAD_DAYS) < date.today():
        warnings.append("The mandatory 21-day ordering cutoff has already passed; review event timing and whether orders were already placed.")
    if mode == "mock":
        dependencies = Dependencies.model_validate({"edges": [
            {"upstream_task_id": upstream, "downstream_task_id": downstream,
             "minimum_gap_days": 1, "rationale": "User policy: requirements and budget precede ordering."}
            for upstream, downstream in required_order_edges(plan)]})
        plan = apply_dependencies(plan, dependencies, evidence)
    else:
        dependencies, plan = await validated_stage("dependencies", Dependencies, {
            **payload, "draft": plan.model_dump(mode="json"),
        }, lambda result: apply_dependencies(plan, result, evidence))
    stages.append("dependency_planning")
    if mode == "mock":
        schedule = Schedule(items=[ScheduleItem(task_id=t.id,
                                                due_date=(request.event_date - timedelta(days=ORDER_LEAD_DAYS)) if t.kind == "order_items" else None,
                                                rationale="Offline mode does not infer schedules.")
                                    for t in plan.tasks])
        plan = apply_schedule(plan, schedule, dependencies, request, examples)
    else:
        schedule, plan = await validated_stage("timeline", Schedule, {
            **payload, "draft": plan.model_dump(mode="json"),
            "required_task_ids": [task.id for task in plan.tasks],
            "dependencies": dependencies.model_dump(), "timing_statistics": stats,
            "planning_date": date.today().isoformat(),
        }, lambda result: apply_schedule(plan, result, dependencies, request, examples))
    warnings.extend(schedule.warnings)
    if any(item.due_date is None for item in schedule.items):
        warnings.append("Some deadlines remain unknown; dependency readiness is not guaranteed.")
    stages.append("timeline_planning")
    assignment_rosters = list(rosters)
    if not any(roster.semester_code == request.semester_code for roster in assignment_rosters):
        demo_roster = demo_secretary_roster(REPO_ROOT / "backend/data/eboardMembers.json", request.semester_code)
        if demo_roster:
            assignment_rosters.append(demo_roster)
            warnings.append("Secretary matching uses the current demo roster, not a confirmed semester-wide roster.")
    assignments = match_roles(plan.tasks, assignment_rosters, request.semester_code)
    stages.append("verified_role_to_member_matching")
    if any(a["proposed_member_code"] is None for a in assignments):
        warnings.append("Some owners need a verified role holder or a choice between multiple holders.")
    lookup = {a["task_id"]: a for a in assignments}
    handoffs = [{"upstream": lookup[edge.upstream_task_id],
                 "downstream": lookup[edge.downstream_task_id],
                 "minimum_gap_days": edge.minimum_gap_days, "rationale": edge.rationale}
                for edge in dependencies.edges
                if lookup[edge.upstream_task_id]["role"] != lookup[edge.downstream_task_id]["role"]
                or lookup[edge.upstream_task_id]["proposed_member_code"] != lookup[edge.downstream_task_id]["proposed_member_code"]]
    return PipelineDraft(mode=mode, request=request, classification=classification,
                         historical_classifications=classified.events, plan=plan,
                         dependencies=dependencies, schedule=schedule, assignments=assignments,
                         handoffs=handoffs, timing_statistics=stats, historical_examples=examples,
                         warnings=warnings, completed_stages=stages)
