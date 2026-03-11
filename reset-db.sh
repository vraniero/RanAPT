#!/usr/bin/env bash
#
# reset-db.sh — Wipe the RanAPT database and start fresh.
#
set -euo pipefail

DB_PATH="$HOME/.ranapt/ranapt.db"

if [ ! -f "$DB_PATH" ]; then
  echo "No database found at $DB_PATH — nothing to do."
  exit 0
fi

read -rp "This will permanently delete $DB_PATH. Continue? [y/N] " answer
if [[ "$answer" != [yY] ]]; then
  echo "Aborted."
  exit 0
fi

rm "$DB_PATH"
echo "Database deleted. A fresh one will be created on next app launch."
