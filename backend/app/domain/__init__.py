"""Domain objects: the nouns of Winnie, with no I/O and no business logic.

    models.py   Member, Role, RoleSeat, Skill, Meeting, Notification ... (dataclasses) and the
                task models ExtractedTask / Task / TaskDependency (Pydantic, mirroring the
                Supabase tables in supabase/migrations/).

API request/response shapes are separate: see schemas/. Business logic lives in services/.
"""
