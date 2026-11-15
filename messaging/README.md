# Winnie messaging sidecar

The service receives iMessage texts through Photon Spectrum Cloud, forwards their
text and sender metadata to FastAPI, and sends the backend's reply into the same chat.

```text
Your phone -> Photon Spectrum Cloud -> messaging/ -> FastAPI -> Supabase
Your phone <- Photon Spectrum Cloud <- messaging/ <- reply
```

Requires Node 22.12+ and npm. In PowerShell, from the repository root:

```powershell
Set-Location messaging
npm install
Copy-Item .env.example .env # First setup only; preserve existing credentials.
```

Fill in `PROJECT_SECRET` from your project's settings in the
[Photon dashboard](https://app.photon.codes). `PROJECT_ID` is already set to the
Winnie project. Keep both values in the local, gitignored `.env`; never commit secrets.
The old `PHOTON_API_KEY` placeholder belongs to a different SDK and is not used.

Set `MESSAGING_BRIDGE_SECRET` in this folder's `.env` to the same private value as
`WINNIE_MESSAGING_BRIDGE_SECRET` in the repository-root backend `.env`. Follow the
[personal messaging setup guide](../docs/MESSAGING_MEMBERS.md) for generating that
value, applying the member migration, and registering your sender identity/aliases.
The listener requires the secret at startup. No sender identity is read from text
the user typed; it comes from Photon message metadata.

```powershell
npm start
```

The command loads `.env`, runs TypeScript with `tsx`, and starts the incoming-message
loop. Leave it running, then text the iMessage line shown in your Photon dashboard
from a phone allowed in that project. `ping` checks the backend connection, `help`
shows the menu, `whoami` shows registration status, and `tasks` returns only the
linked member's verified assignments in the backend's active semester.
Shared lines only accept users added to the project. No public webhook or tunnel is
needed for this listener. Keep FastAPI running in a separate terminal.

If it fails, check project credentials, allowed users, and network access. Run only
one copy of the listener while testing. Stop it with Ctrl+C. Failure logs show the
stage and HTTP status without printing phone numbers, message text or credentials.
Personal commands are limited to direct messages; outbound/agent echoes are ignored.

Automatic reminder delivery is optional: follow [the reminder setup](../docs/REMINDERS.md)
before enabling `REMINDER_POLL_ENABLED=true`. The listener polls the backend's durable
outbox, sends authorized DMs, and acknowledges provider IDs without retrying a send
whose outcome is uncertain. Reminders remain off by default.

`npm run dev` restarts the process when source files change. `npm run typecheck`
checks TypeScript, `npm test` checks sender forwarding, and `npm run build` compiles to `dist/`.

The starter was generated with `create-spectrum-project@0.9.0` and adapted into this
existing service. Its Windows subprocess setup failed, so dependencies and credentials
were configured separately. The listener now uses the backend bridge instead of
the original echo reply.
