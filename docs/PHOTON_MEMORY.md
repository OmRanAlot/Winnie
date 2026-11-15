# Photon conversation memory

Winnie can remember task discussions in a direct message, including a follow-up such
as **“What about its deadline?”** after discussing a named task. Both the hosted Photon
webhook and the legacy bridge use the same memory layer.

## Enable on the deployed backend

1. Apply `supabase/migrations/20261115190000_photon_conversation_memory.sql` once,
   after the earlier migrations.
2. Deploy the updated backend. Memory is enabled by default; `WINNIE_MESSAGE_AI_ENABLED`
   and the Gemini key are still needed for natural-language replies.
3. These are optional regular Cloud Run environment variables, not secrets:

   ```dotenv
   WINNIE_MESSAGE_MEMORY_ENABLED=true
   WINNIE_MESSAGE_MEMORY_MAX_TURNS=6
   WINNIE_MESSAGE_MEMORY_TTL_SECONDS=7200
   ```

No new provider key, database password, or frontend configuration is needed. The
backend uses its existing server-side Supabase credentials. If memory storage is
unavailable, Winnie continues with a stateless reply and explicitly asks for a task
name/code next time. A failed memory operation does not undo an already saved task
change or claim that an unsaved task change succeeded.

## Scope and behavior

Each memory thread is keyed by verified member, platform, normalized sender identity,
DM space and active semester. The stored thread key is a hash; metadata does not store
the sender's phone/email. User-written message text may contain whatever the member
sent. History tables and functions are private to the server; browser users cannot
read them or pick another member's thread. Group chats do not load DM memory.

LangGraph appends backend-validated user/reply turns and checkpoints compact JSON into
Supabase. This survives a new service instance and uses no local SQLite files. Only
the latest checkpoint and last six turns are retained. Context expires after two hours
of inactivity; old expired rows are purged on later saves after a one-day safety window.

Before reuse, remembered task IDs are checked against current ownership and semester.
Old replies are dropped when their task version changes; a still-authorized task can
remain the referent while the model receives its current date/status. A task that is
reassigned away loses its referent and history. Ambiguous references prompt clarification.

Task completion still requires a current explicit completion assertion and the existing
ownership/version checks. Bare `yes`, `done` and `I completed it` remain insufficient.
Recipient consent and admin approval still require the explicit REQ action or frontend
button; dialogue history cannot authorize either. The model does not run the memory
checkpoint node or write to its database directly.

Text **`forget conversation`** (also `reset conversation` or `new conversation`) to clear
this DM's memory. This leaves actual task records and reassignment requests unchanged.
The clear writes a versioned empty checkpoint so an older in-flight request cannot
restore forgotten dialogue. Concurrent saves use optimistic version checks and fail
instead of overwriting a newer conversation. Duplicate message IDs cannot append twice
or be reused with different content within the retained history.

## Verify

From a linked member's DM:

1. Ask “When is [an exact task title] due?”
2. Ask “What about its deadline?” and verify Winnie refers to that task.
3. Change that task's deadline through the app; ask again and verify the current date.
4. Text `forget conversation`, then “What about its deadline?” — Winnie should ask which task.
5. Verify another member/DM cannot see or reuse this conversation.
6. Verify `yes` cannot complete a task or accept/approve a transfer.

Automated tests exercise the actual LangGraph checkpointer with synthetic durable
storage, the shared HTTP handler, expiration, task reauthorization, concurrent clears,
idempotency, and the complete SQL chain including RLS and server-only grants.
