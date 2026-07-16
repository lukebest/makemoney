#!/usr/bin/env bash
# One-command local dev: FastAPI backend + Vite frontend.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  trap - EXIT INT TERM
  if [[ -n "${FRONTEND_PID}" ]] && kill -0 "${FRONTEND_PID}" 2>/dev/null; then
    kill "${FRONTEND_PID}" 2>/dev/null || true
    wait "${FRONTEND_PID}" 2>/dev/null || true
  fi
  if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    kill "${BACKEND_PID}" 2>/dev/null || true
    wait "${BACKEND_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [[ ! -d .venv ]]; then
  echo ">> creating .venv"
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

if ! python -c "import fastapi, uvicorn" 2>/dev/null; then
  echo ">> installing Python dependencies"
  pip install -r requirements.txt
fi

if [[ ! -d frontend/node_modules ]]; then
  echo ">> installing frontend dependencies"
  (cd frontend && npm install)
fi

port_in_use() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :${port}" 2>/dev/null | grep -q ":${port}"
  elif command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
  else
    return 1
  fi
}

if port_in_use "${BACKEND_PORT}"; then
  echo "!! port ${BACKEND_PORT} already in use (backend). Stop the other process or set BACKEND_PORT."
  exit 1
fi
if port_in_use "${FRONTEND_PORT}"; then
  echo "!! port ${FRONTEND_PORT} already in use (frontend). Stop the other process or set FRONTEND_PORT."
  exit 1
fi

echo ">> starting backend  http://127.0.0.1:${BACKEND_PORT}"
PYTHONPATH=. uvicorn backend.main:app --reload --host 127.0.0.1 --port "${BACKEND_PORT}" &
BACKEND_PID=$!

# Wait until health responds (or backend exits).
for _ in $(seq 1 40); do
  if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
    echo "!! backend exited early"
    exit 1
  fi
  if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

echo ">> starting frontend http://127.0.0.1:${FRONTEND_PORT}"
(
  cd frontend
  npm run dev -- --host 127.0.0.1 --port "${FRONTEND_PORT}"
) &
FRONTEND_PID=$!

echo
echo "知止已启动"
echo "  Web UI : http://127.0.0.1:${FRONTEND_PORT}"
echo "  API    : http://127.0.0.1:${BACKEND_PORT}/docs"
echo "按 Ctrl+C 同时停止前后端"
echo

wait "${FRONTEND_PID}" "${BACKEND_PID}"
