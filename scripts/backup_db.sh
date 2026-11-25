#!/usr/bin/env bash
# Logical backup of the database to a timestamped, compressed file.
# Render's paid Postgres plans also take automatic daily backups; this is an extra copy.
set -euo pipefail
: "${DATABASE_URL:?set DATABASE_URL}"
out="${1:-backups}/viralpilot-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
mkdir -p "$(dirname "$out")"
pg_dump --no-owner --format=plain "$DATABASE_URL" | gzip -9 > "$out"
echo "wrote $out"
