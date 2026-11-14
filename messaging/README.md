# Winnie messaging sidecar

The first integration milestone is a real iMessage echo through Photon Spectrum Cloud.
The service receives a text and replies in the same conversation with `echo: <text>`.
It does not call the FastAPI backend yet.

```text
Your phone -> Photon Spectrum Cloud -> messaging/ -> Photon -> your phone
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

```powershell
npm start
```

The command loads `.env`, runs TypeScript with `tsx`, and starts the incoming-message
loop. Leave it running, then text the iMessage line shown in your Photon dashboard
from a phone allowed in that project. For example, `hello` should receive `echo: hello`.
Shared lines only accept users added to the project. No public webhook or tunnel is
needed for this echo starter.

If it fails, check project credentials, allowed users, and network access. Run only
one copy of the listener while testing. Stop it with Ctrl+C. Logs report successful
replies without printing phone numbers or message text.

`npm run dev` restarts the process when source files change. `npm run typecheck`
checks TypeScript, and `npm run build` compiles to `dist/`.

The starter was generated with `create-spectrum-project@0.9.0` and adapted into this
existing service. Its Windows subprocess setup failed, so dependencies and credentials
were configured separately. The inbound/outbound/config/type placeholder files are
reserved for the later backend bridge; they do not participate in the echo loop.
