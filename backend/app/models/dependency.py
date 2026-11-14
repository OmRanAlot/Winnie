# TaskDependency — directed edge "task A depends on task B".
# Core feature: when B finishes or gets blocked, owners of dependents are notified.
# Cycles must be rejected.


from dataclasses import dataclass
from typing import List

@dataclass
class TaskDependency:
    task_id: int  # ID of the dependent task (task A)
    depends_on_task_id: int  # ID of the task it depends on (task B)

    def __post_init__(self):
        if self.task_id == self.depends_on_task_id:
            raise ValueError("A task cannot depend on itself.")
