#!/usr/bin/env bash
# Downloads the official sample and public tests. Credentials come only from
# the environment (or a local .env that git ignores). The token is never printed.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ -z "${SOURCES_URL:-}" || -z "${SOURCES_TOKEN:-}" ]]; then
  echo "Faltan SOURCES_URL y SOURCES_TOKEN." >&2
  echo "Exportalos en el entorno o copialos a .env (esta en .gitignore)." >&2
  echo "Salen de /evento/reto en Frontier. No los pegues en el repo." >&2
  exit 1
fi

if [[ "$SOURCES_TOKEN" == "replace-me" || "$SOURCES_URL" == *"example.invalid"* ]]; then
  echo "SOURCES_URL o SOURCES_TOKEN siguen siendo el placeholder de .env.example." >&2
  exit 1
fi

base="${SOURCES_URL%/}"
mkdir -p sample fuentes

echo "Descargando sample.zip, record_index y tests/public (token no se imprime)..."
curl -fSL --retry 3 --retry-delay 1 \
  -H "Authorization: Bearer ${SOURCES_TOKEN}" \
  -H "Accept: application/zip" \
  -o sample.zip \
  "${base}/sample.zip"

curl -fSL --retry 3 --retry-delay 1 \
  -H "Authorization: Bearer ${SOURCES_TOKEN}" \
  -H "Accept: application/json" \
  -o fuentes/record_index.json \
  "${base}/record_index"

curl -fSL --retry 3 --retry-delay 1 \
  -H "Authorization: Bearer ${SOURCES_TOKEN}" \
  -H "Accept: application/json" \
  -o fuentes/tests_public.json \
  "${base}/tests/public"

rm -rf sample/unpacked
mkdir -p sample/unpacked
unzip -qo sample.zip -d sample/unpacked
rm -f sample.zip

expected="$(find sample/unpacked -type d -name expected_output | head -n 1 || true)"
public_dir="$(find sample/unpacked -name record_index.json -print | head -n 1 || true)"
if [[ -z "$expected" || -z "$public_dir" ]]; then
  echo "El zip no trajo expected_output/ o record_index.json. Contenido:" >&2
  find sample/unpacked -maxdepth 3 -print >&2
  exit 1
fi
public_dir="$(dirname "$public_dir")"

echo "Validador sobre la salida ideal de la muestra..."
node validar.mjs "$expected" --public "$public_dir"

echo "Listo."
echo "  muestra:    $expected"
echo "  indice:     $public_dir/record_index.json"
echo "  corpus:     fuentes/record_index.json"
echo "  tests:      fuentes/tests_public.json"
