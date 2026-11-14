# Schema notes

**Nothing here was verified against real data.** `SUPABASE_DB_URL` was not set when this was built
(`backend/.env` holds only a database password, and I did not construct a connection string from
it). The shape of `tasks` below comes from the repository's own migration
`supabase/migrations/20261114080000_create_tasks.sql`, which is the best available description of the
live table. Run `python scripts/discover.py` (read-only) against the real database to confirm.

## The codes question (`owner_code`, `stakeholder_codes`)

**Conclusion (inferred, UNVERIFIED): they are seat/role codes, possibly with a per-seat number
for two-seat roles (e.g. `PR1`, `PR2`). Treat as the assumption most likely to be wrong.**
`CODES_MEANING` was UNKNOWN, so this is inference. Evidence:

1. Format: both columns are constrained to `^[A-Z][A-Z0-9_-]{0,49}$`: uppercase abbreviations, not
   names. Person names ("Bob Newman") could not be stored; initials could, which is why it is not
   certain.
2. `CLAUDE.md` says a task or notification targets "a role (every holder) or one specific person,
   such as 'Sponsorship Chair #2'", and that several roles have two seats. A code scheme that
   addresses "Sponsorship Chair #2" is a seat scheme.
3. `stakeholder_codes` is used to notify roles ("sponsorship email sent notifies the President, the
   VP and Sponsorship Chair #2").
4. The repo's `seed.sql` says it is deliberately empty, so there were no sample values to inspect.

Counter-evidence: nothing in the repo ties codes to a fixed list, so mixed usage (seat codes plus a
few personal codes) cannot be ruled out.

### How the code handles it

`members.kind` (`'person'` | `'seat'`) lets one table hold either. `OWNER_CODE_KIND` (env,
default `seat`) decides what goes into `tasks.owner_code` for an extracted item:

| mode | owner_code |
|---|---|
| `seat` | the resolved seat's code; or, if only a person was named, the seat that person holds (`members.seat`) if it resolves; otherwise NULL + `needs_review` |
| `person` | the resolved person's code, else NULL + `needs_review` |
| `mixed` | the person's code if resolved, else the seat's code |

To switch, change `OWNER_CODE_KIND`; no schema change is needed. Populate `members` with codes
exactly as they appear in `tasks.owner_code` (`python -m app.cli members add --code ... --kind seat`).

## Conventions taken from the `tasks` migration

| thing | convention |
|---|---|
| `task_code` | `WIN-<YYYYMM>-<n>`, **assigned by a BEFORE INSERT trigger** from a global sequence (whatever is inserted is overwritten). The code generates the same shape (next number for the month, retry on collision) so it also works where the trigger is absent |
| `month_code` | `YYYY-MM`, immutable after insert. Derived from `held_at` in America/New_York |
| `status` | one of `todo` (default / initial), `in_progress`, `blocked`, `done` |
| `source` | one of `manual`, `meeting`, `sheet`, `doc`, `discord`. Extracted tasks use `meeting` |
| `source_reference` | `meeting:<meetings.id>` |
| `due_date` | `date`; the New York calendar date of the resolved deadline |
| `title` | 1-200 chars (longer titles are truncated) |

## New tables

`members`, `meetings`, `meeting_attendees`, `transcript_segments`, `task_meeting_links`,
`task_dependencies` (see `supabase/migrations/20261115*.sql`). RLS is enabled with no policies;
`anon`/`authenticated` are revoked where those roles exist. `tasks` and `tasks_placeholder` are never
altered; `tests/test_migrations.py` snapshots their columns, constraints, indexes, triggers, RLS flag
and row contents before and after applying the migrations (twice).

## Known conflict in the repo

`supabase/migrations/0001_init.sql` (older design) also creates `meetings`, with a different shape,
and a bigint `tasks`; it cannot coexist with the uuid `tasks` migration. The new `meetings`
migration refuses to run (clear error) if it finds that older `meetings` table instead of silently
skipping.
