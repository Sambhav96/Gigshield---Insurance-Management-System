#!/usr/bin/env bash
# apply_migrations.sh — Apply all SQL migrations to the target database.
# Usage: DATABASE_URL=postgresql://... bash apply_migrations.sh
# Or:    bash apply_migrations.sh postgresql://user:pass@host:5432/db
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATIONS_DIR="$SCRIPT_DIR/../supabase/migrations"

# Accept DATABASE_URL from env or first argument
DB_URL="${1:-${DATABASE_URL:-}}"
if [[ -z "$DB_URL" ]]; then
  echo "❌ ERROR: DATABASE_URL not set and no argument provided."
  echo "   Usage: DATABASE_URL=postgresql://... bash apply_migrations.sh"
  exit 1
fi

echo "🗄️  Applying GigShield database migrations"
echo "   Target: ${DB_URL%%@*}@..."   # hide password in log

# Create tracking table
psql "$DB_URL" -q -c "
  CREATE TABLE IF NOT EXISTS _migrations (
    id         SERIAL PRIMARY KEY,
    filename   TEXT UNIQUE NOT NULL,
    applied_at TIMESTAMPTZ DEFAULT NOW()
  );
"

for SQL_FILE in $(ls "$MIGRATIONS_DIR"/*.sql 2>/dev/null | sort); do
  FNAME="$(basename "$SQL_FILE")"

  # Check if already applied
  APPLIED=$(psql "$DB_URL" -tAq -c "SELECT COUNT(*) FROM _migrations WHERE filename = '$FNAME';")
  if [[ "$APPLIED" -gt 0 ]]; then
    echo "   ⏭  Already applied: $FNAME"
    continue
  fi

  echo "   ▶  Applying: $FNAME"
  if psql "$DB_URL" -q -f "$SQL_FILE"; then
    psql "$DB_URL" -q -c "INSERT INTO _migrations (filename) VALUES ('$FNAME') ON CONFLICT DO NOTHING;"
    echo "   ✅ Applied: $FNAME"
  else
    echo "   ❌ FAILED: $FNAME — stopping."
    exit 1
  fi
done

echo ""
echo "✅ All migrations applied."
echo ""
# Quick sanity check
echo "📊 Table count:"
psql "$DB_URL" -tAq -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';"
