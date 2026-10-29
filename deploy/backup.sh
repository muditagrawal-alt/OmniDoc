#!/usr/bin/env bash
# Snapshot of the library (the omnidoc-data Docker volume: database, indexes, graph, uploads) into
# ~/omnidoc-backups, keeping the last 7. oracle-setup.sh runs it every night at 03:30.
# Restore: docker compose down; then
#   docker run --rm -v omnidoc_omnidoc-data:/data -v ~/omnidoc-backups:/b alpine sh -c "rm -rf /data/* && tar xzf /b/<file> -C /data"
set -euo pipefail
cd "$(dirname "$0")/.."
DEST="${OMNIDOC_BACKUP_DIR:-$HOME/omnidoc-backups}"
KEEP="${OMNIDOC_BACKUP_KEEP:-7}"
mkdir -p "$DEST"
DOCKER="docker"; docker info >/dev/null 2>&1 || DOCKER="sudo docker"
VOLUME=$($DOCKER volume ls -q | grep -E '(^|_)omnidoc-data$' | head -1)
[ -n "$VOLUME" ] || { echo "No omnidoc-data volume found" >&2; exit 1; }
# Fold the write-ahead log into the database files so the copy is consistent.
$DOCKER compose exec -T omnidoc python -c "import sqlite3; [sqlite3.connect(p).execute('PRAGMA wal_checkpoint(TRUNCATE)') for p in ('/data/omnidoc.db', '/data/tables.db')]" 2>/dev/null || true
STAMP=$(date +%Y-%m-%d_%H%M)
$DOCKER run --rm -v "$VOLUME":/data:ro -v "$DEST":/backup alpine tar czf "/backup/omnidoc-$STAMP.tgz" -C /data .
ls -1t "$DEST"/omnidoc-*.tgz | tail -n +"$((KEEP + 1))" | xargs -r rm --
echo "Backed up to $DEST/omnidoc-$STAMP.tgz"
