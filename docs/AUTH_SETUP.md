# Supabase login and profiles

## WiCS roster and consent

`members` is the existing roster used by messaging; `profiles` belongs to Auth
accounts. Apply `20261114140000_link_member_roster.sql` after the existing members
and profiles migrations to add role, GirlHacks title, major, graduation information,
contact fields, and a unique profile-to-member link. It preserves existing member codes.

The TSV reader understands the original unnamed name/contact columns and role/task
continuation lines. It treats only populated contact cells as authorized for import,
per the user's instructions. Blank emails/phones remain null; they are never inferred
from names or external sources. Roles remain usable for future delegation even when
a member has no contact details. Skills remain empty until supplied; a major or role
description is not treated as evidence of a person's skills. Admin status is not inferred.

From `backend/`, preview a TSV without writing to Supabase:

```powershell
uv run python -m app.import_roster "C:/path/to/roster.tsv"
```

Add `--prepare-sql` to write `backend/data/apply-roster.sql`, a private, gitignored
bundle containing the migration and roster import in one transaction. Run this bundle
once in the project's SQL Editor if CLI migration access is unavailable. Do not commit
or share this file; it contains the provided contact details. After the migration is
applied, subsequent imports use `--apply` to invoke the server-only transactional RPC.
Repeat imports update existing roster records without duplicating members. Exact
existing display names preserve legacy member codes; Auth matching never uses names.
Partial imports do not remove records absent from the source file.

Only a confirmed Auth email matching an active, consenting roster entry links the
profile. Importing after the Auth account already exists also fills its profile. An
unconfirmed account, a name match, or self-editable metadata cannot claim a role.
Linked login email addresses are fixed; changing them needs a separately implemented
administrator workflow. The import sends no invitations and does not create Auth
accounts, messaging identities, or member aliases. Invitation/password-setup UI is
still separate work. Role changes do not grant admin privileges.

The example export swapped the Technical Director and Membership Chair descriptions.
The user supplied corrected definitions on November 14, 2026. The importer uses those
verified definitions from `backend/app/services/role_definitions.py`: Membership Chair
owns recruitment, retention and community engagement (10 responsibilities); Technical
Director owns technical workshops and digital resources (5 responsibilities). Both are
marked `delegation_context_verified=true`. The original TSV is unchanged. These role
responsibilities do not establish individual skills. The spelling `Industry
Partnernships Chair` is normalized to `Industry Partnerships Chair`.

If a roster was already imported before this correction, preview and rerun the same
`app.import_roster PATH --apply` command to update these fields while preserving member
codes. If using prepared SQL, regenerate it from the corrected importer rather than
running an older bundle. Once the roster-link migration is applied, use the importer
with `--apply`, not a schema-plus-roster bundle that would rerun the migration.

Roster imports update the supplied name, role, contact, major, and graduation fields.
They preserve existing user-edited profile skills because this export has no skills.
For future exports, review changes in contact consent before applying a new snapshot.

Supabase Auth owns `auth.users` and password hashing. The application stores profile
data in `public.profiles`, keyed by the Auth user's UUID. There is no password column
in the profile table. Login continues to use `supabase.auth.signInWithPassword`.

## Apply the profile migration

The self-contained migration is
[`20261114120000_create_profiles.sql`](../supabase/migrations/20261114120000_create_profiles.sql).
In your project's Supabase dashboard, open **SQL Editor**, paste the whole file, and
run it once. It does not depend on the task migrations or modify task data.

Alternatively, after `npx supabase login`, use the CLI to inspect remote migration
history and pending migrations before pushing. Earlier task migrations might have
been applied manually; reconcile that history before pushing the entire directory.
Do not run `db reset` against the hosted project.

The migration creates a profile automatically for new Auth users and backfills
existing users. Auth email changes update `profiles.email`. User metadata supplies
only an initial name; metadata cannot grant a role or admin access.

| Column | Type | Who can change it |
|---|---|---|
| `id` | UUID referencing `auth.users.id` | Managed by Auth |
| `name` | Text, at most 200 characters | The profile owner or trusted backend |
| `email` | Nullable text mirrored from Auth | Supabase Auth |
| `phone_number` | Nullable contact number, at most 50 characters | The profile owner or trusted backend |
| `role` | Board position, defaults to `member` | Trusted backend/database access |
| `is_admin` | Boolean, defaults to `false` | Trusted backend/database access |
| `skills` | Text array, at most 50 nonempty skills | The profile owner or trusted backend |
| `created_at`, `updated_at` | Timestamps | Database triggers |

Members can read only their own profile. Anonymous clients have no profile access.
Members cannot insert/delete profiles or change `id`, `email`, `role`, or `is_admin`.
An `is_admin=true` profile does not itself grant broader database access. Later admin
features must verify identity and permissions in trusted backend code. A board position
is distinct from the `authenticated` role in Supabase's JWT.

The profile phone is contact information, not a verified phone login. Users change
their login email/password using Supabase Auth rather than updating this table.

## Create a sample login

The repository-root `.env` must contain `WINNIE_SUPABASE_URL` and
`WINNIE_SUPABASE_SECRET_KEY`. From `backend/`, run:

```powershell
uv run python -m app.create_demo_user --create
```

The command creates a confirmed regular Auth user, generates a random password, and
verifies email/password login. It sends no email. Credentials are saved in
`backend/data/demo-login.json` (gitignored), never in migrations or committed seed data.
Repeated runs reuse that login. If the profile migration is applied afterward, its
backfill creates the demo profile. Use this account only for development.

## Read/update the signed-in user's profile

Use the browser client configured with the project's publishable key. The Auth UUID
is available as `session.user.id` in `AuthProvider`:

```ts
const { data: profile, error } = await supabase
  .from('profiles')
  .select('*')
  .eq('id', session.user.id)
  .single();

const { error: updateError } = await supabase
  .from('profiles')
  .update({ name: 'Demo Member', skills: ['Python', 'Event planning'] })
  .eq('id', session.user.id);
```

Fetch profiles outside the `onAuthStateChange` callback, for example in a separate
React effect keyed by the session user ID. Clear cached profiles when the user changes
or signs out. Always display query errors in the UI.

This profile table does not secure FastAPI task/recording endpoints. Backend token
verification and board membership checks are separate work.

## Verify the migration locally

```powershell
npm run test:profiles
```

Tests run the real migration in PGlite PostgreSQL with stand-ins for Supabase's managed
Auth schema, roles, and `auth.uid()`. They verify backfill/signup, privilege escalation
rejection, owner-only access, anonymous denial, email sync, and deletion cascades.
They do not exercise the hosted Supabase Auth service or replace a hosted smoke test.
