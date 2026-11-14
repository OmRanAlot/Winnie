# Personal tasks over iMessage

The Photon listener forwards the actual sender ID, platform and conversation type
to FastAPI. FastAPI uses an admin-managed member mapping and verified spreadsheet
aliases to return only that member's unfinished tasks. It does not accept a name
typed into a message as proof of identity.

The website's Supabase Auth login is separate. Logging into the website does not
automatically link an iMessage account, and no frontend login files are changed by
this feature. A later onboarding flow can connect both identities to the same person.

## 1. Create the member tables

After both task migrations, run the contents of
`supabase/migrations/20261114120000_add_messaging_members.sql` once in Supabase's
SQL Editor. This creates:

| Table | Purpose |
|---|---|
| `members` | A stable member code, display name and active flag |
| `member_identities` | Which platform sender ID belongs to each member |
| `member_aliases` | Which full names/emails in a semester tracker identify each member |

These tables are server-only. They do not allow anonymous or ordinary frontend
clients to enroll identities. Configure records using the Supabase dashboard as a
project admin. If a table already exists, stop and inspect it instead of deleting it.

## 2. Authenticate the listener's requests to Python

A sender field in an HTTP request is trustworthy only when it comes from the
configured listener. A shared private secret authenticates that bridge. The code
requires it for personal commands, including whoami; there is no development bypass.
The secret is not the Photon project secret or the Supabase key.

Generate one new random value locally, from `backend/`:

```powershell
& ".\.venv\Scripts\python.exe" -c "import secrets; print(secrets.token_urlsafe(32))"
```

Paste the same generated value into two existing local environment files, preserving
their other settings. Do not paste the actual value into chat or source control.

Repository-root `.env`:

```dotenv
WINNIE_MESSAGING_BRIDGE_SECRET=YOUR_GENERATED_VALUE
WINNIE_ACTIVE_SEMESTER=fall-2026
```

`messaging/.env`:

```dotenv
MESSAGING_BRIDGE_SECRET=YOUR_GENERATED_VALUE
```

Restart both programs after saving. Backend, from `backend/`:

```powershell
& ".\.venv\Scripts\python.exe" -m fastapi dev app/main.py
```

Messaging, from `messaging/` in another terminal:

```powershell
npm start
```

Keep the backend bound to localhost for local development. A deployed bridge
requires private networking or HTTPS and secret management. Do not put the bridge
secret in `VITE_`/`NEXT_PUBLIC_` variables or browser requests.

## 3. Discover your sender identity

Text `whoami` to Winnie in a **direct conversation**. Before registration, the reply
shows the platform and exact canonical sender ID. It may be a phone number or an
email address. Use that exact value; don't guess phone prefixes or formatting.
For email handles, use lowercase when inserting the identity.

If the reply says data could not be loaded, check that the migration was applied and
the backend can access Supabase. If the listener reports HTTP 401, its bridge secret
does not match. HTTP 503 for personal commands means the backend secret is missing.

## 4. Register yourself as an admin

In Supabase Table Editor, insert these records in order:

1. In `members`, set a stable uppercase code such as `MEMBER1`, your display name,
   and `active = true`. Codes identify people, not role seats that change each semester.
2. In `member_identities`, set `platform = imessage`, the exact sender ID from whoami,
   and `member_code = MEMBER1`.
3. In `member_aliases`, add `semester_code = fall-2026`, your exact full name as it
   appears in the tracker, and `member_code = MEMBER1`. If some cells use your email,
   add another row for that full email, linked to the same member code.

Repeat for other members as needed. One member may have several aliases and sender
identities. An alias cannot belong to two different people in the same semester.
Use verified full names/emails rather than ambiguous nicknames or first names.
Do not use the member's name as an unverified self-registration command.

The code retains raw `assignee_text` in tasks. It resolves complete aliases when
reading personal tasks, so you do not have to reimport the CSV just to add a member.
A shared cell such as `Avery Chen morgan@example.test` is recognized only when all
names/emails in it have verified alias mappings. Unrecognized text is excluded from
personal results and produces a warning that the list may be incomplete. Add mappings
for both assignees before expecting a shared task to appear. No fuzzy matching or
splitting full names on spaces is used.

## 5. Test personal commands

- `ping`: connection check; no task data is returned.
- `help`: numbered menu.
- `whoami` or `2`: check the linked member.
- `tasks`, `my tasks`, or `1`: up to five earliest-due unfinished tasks for that member
  in `WINNIE_ACTIVE_SEMESTER`.

The query includes todo, in-progress and blocked tasks; completed tasks are excluded.
Earlier deadlines come first, including overdue dates. Tasks without a fixed date
come last. This is deadline ordering, not a priority/urgency scoring algorithm.
Response task numbers are display labels, not commands to complete a task.

Unknown/deactivated members receive no task list. Group and unknown conversation
types receive no personal identity or task data. The backend trusts sender metadata
only from a listener possessing the bridge secret; anyone with that secret has bridge
privileges, so treat it as a private credential.

When the semester changes, update `WINNIE_ACTIVE_SEMESTER`, import the new tracker,
and add verified alias mappings for that semester. Identity links remain stable.
Reminders and automatic Google Sheets sync are separate future features.

## Where the code lives

- `messaging/src/bridge.ts`: request payload and authentication header.
- `messaging/src/index.ts`: receives Photon messages and calls FastAPI.
- `backend/app/routes/messages.py`: validates requests and bridge credentials.
- `backend/app/services/members.py`: sender lookup and verified assignment matching.
- `backend/app/services/message_replies.py`: personal commands and reply formatting.
- `backend/app/services/tasks.py`: unfinished-task queries.
