# Gemini task conversations

Winnie can interpret a member's text using Gemini, answer questions about their
verified unfinished assignments, and mark a clearly identified task done. Gemini
interprets the user's report; it does not independently verify real-world work.

```text
Photon message + sender + message ID
  -> verify bridge and member
  -> retrieve only that member's assigned tasks
  -> Gemini returns structured intent and candidate task IDs
  -> Python validates the decision and rechecks ownership
  -> Supabase completes one task and saves a receipt atomically
  -> Photon sends the database's confirmation
```

## Enable locally

1. Apply `supabase/migrations/20261114160000_message_task_completions.sql` once in
   Supabase SQL Editor, after the existing task/member migrations. It adds a private
   completion-receipt table and a server-only function. It does not complete tasks
   during installation. No existing task or member rows are deleted.
2. Keep the existing backend `GEMINI_API_KEY` and `GEMINI_MODEL` settings. Add
   `WINNIE_MESSAGE_AI_ENABLED=true` to the backend environment file. Settings reads
   repository-root `.env`, then `backend/.env`; if both define a setting, the backend
   file wins. `WINNIE_MESSAGE_AI_MODEL` optionally selects a separate messaging model;
   otherwise the existing Gemini model is used. No LangChain key is required: this
   small interpreter uses the installed Google GenAI SDK; Deep Agents remains the
   separate planning integration.
3. Preserve the matching bridge secrets and restart both programs. From `backend/`:

   ```powershell
   & ".\.venv\Scripts\python.exe" -m fastapi dev app/main.py
   ```

   From `messaging/` in a second terminal:

   ```powershell
   npm start
   ```

The updated listener must be running: it forwards `message_id` from Photon's message
metadata, not from user text. Personal commands require a verified member identity
and aliases as described in [member setup](MESSAGING_MEMBERS.md).

## Try it

- `tasks` lists up to five earliest-due unfinished assignments and their unique WIN codes.
- `What do I have coming up?` asks Gemini about the supplied unfinished task context.
- `I finished booking the workshop room.` can complete one unambiguous assigned task.
- `done WIN-202610-42` explicitly completes the assigned task with that canonical code,
  without making a model call. Use an actual code from your list.
- `I'm almost done booking the room` or `I haven't finished the room booking` must
  not complete anything.
- `done`, `yes`, an unclear pronoun, multiple possible tasks, or multiple reported
  completions asks for a task name/event/code. Display numbers are not task identities.

For a live write test, choose a task you really finished, or create a clearly labeled
fictional task assigned to your test member. Confirm its status in Supabase after
Winnie replies. This slice does not notify dependent owners or update Google Sheets.

## How interpretation works

`MessageDecision` requires an intent (`complete_task`, `clarify`, or `answer`), selected
task IDs, an explicit-completion flag, an exact evidence quote, confidence, and reply
text. Gemini receives the current message and only allowlisted fields of that member's
verified unfinished tasks: IDs/codes, title, event, deadline and status. Raw assignment
cells, roster contacts and task notes are not included as context. User message text
itself is sent to Gemini. There are no database, filesystem or messaging tools on the model.

Python rejects unknown/duplicate task IDs, unsupported evidence, low confidence,
multiple candidate tasks, and negative/future/uncertain completion language. Duplicate
task titles require an exact code. It rereads the selected task and alias mapping
after interpretation. Only the database's committed reply can confirm completion;
the model's suggested wording is never used as a save confirmation.

Unknown senders and group/unknown conversation types receive no personal task context
and cannot change tasks. Exact commands still work without an AI call. The default
AI flag is false; direct `done WIN-code` commands remain available after applying
the migration and updating the listener.

There is no multi-turn chat history in this version. Each interpretation uses the
current message and current tasks; a bare `yes` cannot approve an implied prior action.
If more than `WINNIE_MESSAGE_AI_MAX_TASKS` (default 60) tasks are assigned, use an exact
task code instead of sending a truncated context to the model. Messages longer than
3,000 characters also ask for a specific task.

## Completion receipts and retries

`message_task_completions` stores provider/message identity, member, a request hash,
task ID, committed reply, whether it changed status, and creation time. It does not
store the full incoming text. A receipt and status change commit in the same transaction.
Repeated or simultaneous delivery of the same provider message replays its first
result. It cannot select and complete a second task on retry. The transaction verifies
the sender is still linked to an active member and checks the original task version
and assignee cell. Only the trusted backend service role can call it.

Gemini timeout/invalid output produces a clear failure or clarification without a
status change. `WINNIE_MESSAGE_AI_TIMEOUT_SECONDS` defaults to 10; the listener's
overall backend deadline is 30 seconds. A lost database response can have an uncertain
outcome: Winnie asks you to check `tasks`, rather than claiming nothing was saved.
Replayed provider events can recover the stored confirmation without a new write.

The CSV importer still lets a reviewed sheet import update sheet-owned status fields.
Inspect status changes before applying an older export so it does not reopen work
completed through messaging. Automatic sheet synchronization and conflict resolution
remain separate work.

## Verification

```powershell
# backend/
& ".\.venv\Scripts\python.exe" -m pytest tests/test_conversation.py tests/test_message_members.py -q

# repository root: actual SQL transaction in local PostgreSQL/PGlite, synthetic data
node --test supabase/tests/message-completions.test.mjs

# messaging/
npm run typecheck
npm test
```

Python tests mock Gemini and storage. SQL tests execute the migrations locally and
verify commit/rollback, inactive identities, stale tasks, permission denial and replay.
Hosted migration deployment and a real member's completion require a separate smoke test.
