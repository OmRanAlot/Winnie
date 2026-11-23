"""User-confirmed role/deadline rules override historical and model suggestions."""

import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path

from app.schemas.pipeline import SemesterRoster
from app.schemas.planning import DraftContents, ProposedTask

ORDER_LEAD_DAYS = 21
POLICY_TEXT = """
Mandatory user-confirmed planning rules override historical precedents:
- The Secretary owns Highlander Hub event listings, posting and approval processes.
- The Treasurer must have all required physical event items ordered at least 21 days
  before the event. Classify ordering/purchasing tasks as kind order_items; assign
  Treasurer, phase before, and schedule no later than event_date minus 21 days.
- Do not confuse ordering with later receipt, packing, setup or reimbursement.
- If physical supplies/goodie bags/refreshments are needed but no ordering task exists,
  include an explicit ordering task. Never imply approval to spend or order anything.
- Budget approval and a required materials list must precede ordering by at least
  one calendar day. Move those prerequisite deadlines earlier as needed.
- Label Highlander Hub tasks kind highlander_hub, materials-list tasks materials_list,
  and budget approval tasks budget_approval. Other tasks are general.
"""


def task_kind(task: ProposedTask) -> str:
    title = re.sub(r"[^a-z0-9]+", " ", task.title.casefold()).strip()
    if "highlander hub" in title or "highlanderhub" in title:
        return "highlander_hub"
    if re.match(r"^(receiv\w*|pack\w*|unpack\w*|assembl\w*|distribut\w*|reimburs\w*|set up|setup|confirm receipt|track delivery)\b", title):
        return "general"
    physical = r"\b(items?|supplies|materials|food|refreshments?|catering|equipment|amazon|merchandise|swag)\b"
    if re.search(r"\b(order(?:ed|ing|s)?|purchas\w*|buy\w*|procur\w*)\b", title) and re.search(physical, title):
        # A purchase list is the specification, not the purchase itself.
        if re.search(r"\b(list|requirements)\b", title):
            return "materials_list"
        return "order_items"
    if (re.search(r"\b(materials|supplies|purchase)\b.*\b(list|requirements)\b", title)
            or re.search(r"\b(list|requirements)\b.*\b(materials|supplies)\b", title)):
        return "materials_list"
    if "budget" in title and re.search(r"\b(confirm\w*|approv\w*|finaliz\w*)\b", title):
        return "budget_approval"
    return task.kind


def apply_task_policies(plan: DraftContents) -> DraftContents:
    tasks = [task.model_copy(deep=True) for task in plan.tasks]
    for task in tasks:
        task.kind = task_kind(task)
        if task.kind == "highlander_hub":
            task.suggested_role = "Secretary"
            task.rationale = "User-confirmed responsibility: the Secretary manages Highlander Hub event postings and approvals."
        elif task.kind == "order_items":
            task.suggested_role = "Treasurer"
            task.phase = "before"
            task.rationale = "User-confirmed responsibility: the Treasurer orders all approved event items at least 21 days before the event."
    needs_items = any(re.search(r"\b(supplies|goodie bags?|refreshments?|catering|equipment|amazon|merchandise|swag)\b",
                               task.title.casefold()) and task.phase == "before" for task in tasks)
    if needs_items and not any(task.kind == "order_items" for task in tasks):
        existing_ids = {task.id for task in tasks}
        task_id = "POLICY-ORDER-ITEMS"
        while task_id in existing_ids:
            task_id += "-1"
        tasks.append(ProposedTask(
            id=task_id, title="Order all approved event items (if needed)", kind="order_items",
            suggested_role="Treasurer",
            rationale="User-confirmed 21-day ordering rule: physical supplies were mentioned but the draft omitted an ordering task. Confirm the item list and budget before purchasing.",
        ))
    if any(task.kind == "order_items" for task in tasks) and not any(task.kind == "materials_list" for task in tasks):
        task_id = "POLICY-MATERIALS-LIST"
        while task_id in {task.id for task in tasks}:
            task_id += "-1"
        tasks.append(ProposedTask(
            id=task_id, title="Finalize itemized list of required event purchases", kind="materials_list",
            suggested_role="Event Coordinator",
            rationale="Ordering prerequisite inferred from the user-confirmed rule: the Treasurer needs an itemized list before placing all orders 21 days before the event.",
        ))
    return DraftContents(tasks=tasks, questions=plan.questions)


def required_order_edges(plan: DraftContents) -> list[tuple[str, str]]:
    return [(prerequisite.id, order.id) for order in plan.tasks if order.kind == "order_items"
            for prerequisite in plan.tasks
            if prerequisite.id != order.id and prerequisite.kind in ("materials_list", "budget_approval")]


def schedule_order_policies(plan: DraftContents, event_date: date) -> DraftContents:
    """Apply confirmed purchase timing to a single-shot draft, including added tasks.

    Only ordering and its prerequisites receive policy-derived deadlines. The
    pipeline has a separate timeline specialist and continues to validate its dates.
    """
    tasks = {task.id: task.model_copy(deep=True) for task in plan.tasks}
    policy_edges = set(required_order_edges(plan))
    for upstream, downstream in policy_edges:
        if upstream not in tasks[downstream].dependency_ids:
            tasks[downstream].dependency_ids.append(upstream)

    # Check the expanded graph for cycles before changing its schedule. New
    # policy edges may require dates to move; the input graph was already validated.
    DraftContents(tasks=[task.model_copy(update={"due_date": None})
                         for task in tasks.values()], questions=plan.questions)
    cutoff = event_date - timedelta(days=ORDER_LEAD_DAYS)
    scheduled = {}

    def schedule(task_id):
        task = tasks[task_id]
        if task_id in scheduled and scheduled[task_id] <= task.due_date:
            return
        scheduled[task_id] = task.due_date
        for upstream_id in task.dependency_ids:
            upstream = tasks[upstream_id]
            if upstream.phase != "before":
                raise ValueError("Ordering prerequisites must be preparation tasks.")
            gap = 1 if (upstream_id, task_id) in policy_edges else 0
            latest = task.due_date - timedelta(days=gap)
            if upstream.due_date is None or upstream.due_date > latest:
                upstream.due_date = latest
                upstream.rationale += " Deadline inferred from the required purchasing prerequisite."
            schedule(upstream_id)

    for task in tasks.values():
        if task.kind == "order_items":
            if task.due_date is None or task.due_date > cutoff:
                task.due_date = cutoff
                task.rationale += " Deadline set by the confirmed 21-day ordering rule."
            schedule(task.id)
    return DraftContents(tasks=list(tasks.values()), questions=plan.questions)


def validate_policy_dependencies(plan: DraftContents, dependencies):
    edges = {(edge.upstream_task_id, edge.downstream_task_id): edge for edge in dependencies.edges}
    for pair in required_order_edges(plan):
        if pair not in edges or edges[pair].minimum_gap_days < 1:
            raise ValueError(f"Ordering policy requires dependency {pair[0]} -> {pair[1]} with at least a 1-day gap.")


def validate_order_deadlines(plan: DraftContents, event_date: date):
    cutoff = event_date - timedelta(days=ORDER_LEAD_DAYS)
    for task in plan.tasks:
        if task_kind(task) == "order_items" and (task.due_date is None or task.due_date > cutoff):
            raise ValueError(f"Ordering task {task.id} must have a deadline on or before {cutoff.isoformat()} (21 days before the event).")


def demo_secretary_roster(path: Path, semester: str) -> SemesterRoster | None:
    """Use the existing current-demo Secretary; never treat it as historical evidence."""
    if not path.exists():
        return None
    entry = json.loads(path.read_text(encoding="utf-8")).get("Secretary", {})
    name = entry.get("name", "").strip()
    if not name:
        return None
    code = "WICS_" + hashlib.sha256(name.casefold().encode()).hexdigest()[:12].upper()
    return SemesterRoster.model_validate({
        "semester_code": semester, "verified_by": "Current demo roster; Secretary confirmed by user",
        "members": [{"member_code": code, "display_name": name, "roles": ["Secretary"]}],
    })
