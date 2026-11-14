# Domain models

Add Pydantic request/response and domain schemas here. Begin with Member, Event, Task, Transcript, PlanProposal, Approval, Conversation, and Notification. See `CONTEXT.md` for fields and invariants.

These are just DATACLASSES ! They are not meant to be used for database persistence. Use the `db` module for that.