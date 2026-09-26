#!/usr/bin/env bash
# One-command start: sets up Python, checks the keys in backend/.env,
# and serves the app at http://localhost:8000 (PORT=xxxx to change).
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || { echo "Python 3.10+ is required: https://www.python.org/downloads/"; exit 1; }

if [ ! -x backend/.venv/bin/python ]; then
  echo "Creating backend/.venv with $PY"
  "$PY" -m venv backend/.venv
  backend/.venv/bin/python -m pip install -q --upgrade pip
fi
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  echo "Created backend/.env from the template. Add your keys there to run Jev and the LLM live."
fi

echo "Installing Python packages"
backend/.venv/bin/python -m pip install -q -r backend/requirements.txt

# The zip ships a prebuilt frontend; Node is only needed if it is missing.
if [ ! -f frontend/dist/index.html ]; then
  command -v npm >/dev/null 2>&1 || { echo "Node 18+ is needed to build the frontend: https://nodejs.org"; exit 1; }
  (cd frontend && npm install && npm run build)
fi

echo "Checking API keys"
(cd backend && .venv/bin/python check_keys.py) ||
  echo "A key failed (details above). The app still starts: a rejected Jev key falls back to the local stand-in."

echo
echo "Jeva is running at http://localhost:$PORT  (Ctrl+C to stop)"
cd backend && exec .venv/bin/uvicorn api:app --port "$PORT"
