#!/usr/bin/env bash
# Copy the pseudonym registry, its secret and the live state to data/backup/<timestamp>/.
# Losing these means losing every pseudonym already published. Never commit them.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
dest="data/backup/$(date +%Y%m%d-%H%M%S)${1:+-$1}"
mkdir -p "$dest"

if [[ -f data/pseudonyms.db ]]; then
  .venv/bin/python -c "
import sqlite3, sys
src = sqlite3.connect('data/pseudonyms.db')
dst = sqlite3.connect(sys.argv[1])
src.backup(dst)
dst.close(); src.close()
" "$dest/pseudonyms.db"
fi
for f in data/secret.key data/state.pkl data/registry.db output/entities.json; do
  [[ -f "$f" ]] && cp "$f" "$dest/"
done
echo "Respaldo en $dest:"
ls -la "$dest"
