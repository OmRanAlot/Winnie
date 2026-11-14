#!/usr/bin/env bash
# Apply the ADDITIVE meeting-ingest migrations (supabase/migrations/20261115*.sql) to the database
# in SUPABASE_DB_URL. Run this yourself; the autonomous build never touched that database.
#
#   export SUPABASE_DB_URL='postgresql://...'      # or put it in ingest/.env
#   ./scripts/apply_migrations.sh            # asks for confirmation
#   ./scripts/apply_migrations.sh --yes      # no prompt
#
# Each file runs in its own transaction (psql --single-transaction, stop on first error) and is
# recorded in public.ingest_migrations, so re-running skips what is already applied. The SQL is
# also written to be re-runnable. Requires psql. It never ALTERs/DROPs public.tasks or
# public.tasks_placeholder.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATIONS_DIR="$HERE/../../supabase/migrations"

if [[ -z "${SUPABASE_DB_URL:-}" && -f "$HERE/../.env" ]]; then
  # shellcheck disable=SC1091
  set -a; source "$HERE/../.env"; set +a
fi
: "${SUPABASE_DB_URL:?SUPABASE_DB_URL is not set}"
command -v psql >/dev/null || { echo "psql not found (install the PostgreSQL client)" >&2; exit 1; }
# The URL goes through -d: some psql builds ignore options placed after a positional connection string.
run_psql() { psql -d "$SUPABASE_DB_URL" "$@"; }

# Show where we are about to write, with credentials masked.
masked="$(printf '%s' "$SUPABASE_DB_URL" | sed -E 's#(://)[^@/]*@#\1***@#')"
echo "Target database: $masked"
shopt -s nullglob
files=("$MIGRATIONS_DIR"/20261115*.sql)
((${#files[@]})) || { echo "no migrations found in $MIGRATIONS_DIR" >&2; exit 1; }
echo "Migrations:"; printf '  %s\n' "${files[@]##*/}"

if [[ "${1:-}" != "--yes" ]]; then
  read -r -p "Apply to the database above? Type 'yes' to continue: " answer
  [[ "$answer" == "yes" ]] || { echo "aborted"; exit 1; }
fi

run_psql -v ON_ERROR_STOP=1 -q <<'SQL'
create table if not exists public.ingest_migrations (
  name text primary key, applied_at timestamptz not null default now());
alter table public.ingest_migrations enable row level security;
SQL

for f in "${files[@]}"; do
  name="$(basename "$f")"
  done_already="$(run_psql -At -v ON_ERROR_STOP=1 \
    -c "select 1 from public.ingest_migrations where name = '$name'")"
  if [[ "$done_already" == "1" ]]; then echo "skip  $name (already applied)"; continue; fi
  echo "apply $name"
  run_psql -v ON_ERROR_STOP=1 --single-transaction -q -f "$f" \
    -c "insert into public.ingest_migrations (name) values ('$name')"
done
# Fail loudly if anything was silently not applied.
recorded="$(run_psql -At -v ON_ERROR_STOP=1 -c "select count(*) from public.ingest_migrations")"
((recorded >= ${#files[@]})) || { echo "ERROR: only $recorded of ${#files[@]} migrations recorded" >&2; exit 1; }
echo "done ($recorded migrations recorded)"
