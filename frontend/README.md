# Ask Winnie! – frontend

Requires Node.js 22.12 or newer. The current build/test tools were updated together.

## Run locally
    npm install
    npm run dev
Opens at http://localhost:5173

## Authentication
Create `.env.local` from `.env.example` and fill in the Supabase URL and publishable
key before starting. Use a manually invited account linked to the approved roster.
See [authentication finalization](../docs/AUTH_FINALIZATION.md) for the hosted SQL
migration, redirect URLs, SMTP, invitations, and administrator assignment.

`src/auth/` handles login, invitation/password recovery, private profile loading and
logout. Admin status comes from a server-verified profile. The frontend passes the
Supabase access token to FastAPI; shared backend keys never belong in the browser.

Run `npm run typecheck`, `npm test`, `npm run test:ui`, and `npm run build` to verify changes.
The frontend mixes JavaScript and TypeScript. TypeScript checks the TS/TSX files with
React 18 types; existing JavaScript files are included for module resolution without
enabling strict JavaScript checking. Both authentication and Supabase have one
implementation, imported explicitly from their `.jsx`/`.js` files.

## Backend hookup
Tasks, members, meetings and dashboard forms load from the backend after authentication.
Board information is read-only. See [dashboard connections](../docs/FRONTEND_BACKEND.md)
for migration and verification steps. Production hosting must serve index.html for
`/auth/set-password` as well as `/`.
