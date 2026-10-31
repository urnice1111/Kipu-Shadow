#!/usr/bin/env bash
# Serve Kipu Shadow publicly during evaluations: API on :9000, ngrok HTTPS tunnel, and
# caffeinate so the Mac does not sleep. Prints the URL to paste in Frontier (/v1 root).
# Optional: NGROK_DOMAIN=<your-static-domain>.ngrok-free.app for a stable URL.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
mkdir -p logs

cleanup() {
  kill "${api_pid:-}" "${ngrok_pid:-}" "${caf_pid:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if lsof -tiTCP:9000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "El puerto 9000 ya está en uso; detén ese proceso primero (lsof -iTCP:9000)." >&2
  exit 1
fi

caffeinate -dimsu &
caf_pid=$!

./run.sh >> logs/server.log 2>&1 &
api_pid=$!
for _ in $(seq 1 120); do
  curl -fsS http://localhost:9000/v1/health >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fsS http://localhost:9000/v1/health >/dev/null || { echo "La API no arrancó; revisa logs/server.log" >&2; exit 1; }

if [[ -n "${NGROK_DOMAIN:-}" ]]; then
  ngrok http 9000 --url "https://${NGROK_DOMAIN}" --log stdout > logs/ngrok.log 2>&1 &
else
  ngrok http 9000 --log stdout > logs/ngrok.log 2>&1 &
fi
ngrok_pid=$!

url=""
for _ in $(seq 1 60); do
  url="$(curl -fsS http://127.0.0.1:4040/api/tunnels 2>/dev/null | python3 -c 'import sys,json; t=json.load(sys.stdin)["tunnels"]; print(next((x["public_url"] for x in t if x["public_url"].startswith("https")), ""))' 2>/dev/null || true)"
  [[ -n "$url" ]] && break
  sleep 0.5
done
[[ -n "$url" ]] || { echo "ngrok no dio URL; revisa logs/ngrok.log" >&2; exit 1; }

echo
echo "URL para Frontier:  ${url}/v1"
echo "Prueba:             curl ${url}/v1/health"
echo "Logs:               logs/server.log, logs/ngrok.log"
echo "Ctrl+C para detener todo."
wait "$api_pid"
