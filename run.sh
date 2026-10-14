#!/usr/bin/env bash
# Start dbt-factory (kills previous instances first). FACTORY_MOCK=auto|1|0
# usage: ./run.sh [--project PATH]   (or FACTORY_PROJECT=PATH ./run.sh); default: the bundled demo (projects/jaffle_shop)
set -u
while [ $# -gt 0 ]; do
  case "$1" in
    --project) [ $# -ge 2 ] || { echo "--project needs a path" >&2; exit 2; }; FACTORY_PROJECT=$(cd "$2" && pwd) || exit 2; export FACTORY_PROJECT; shift 2 ;;
    --project=*) FACTORY_PROJECT=$(cd "${1#*=}" && pwd) || exit 2; export FACTORY_PROJECT; shift ;;
    -h|--help) sed -n 2,3p "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
cd "$(dirname "$0")" || exit 1; ROOT=$(pwd); export PATH="$HOME/.local/bin:$PATH"
stop() {
  pkill -f "$ROOT/.venv/bin/uvicorn main:app" ; pkill -f "uvicorn main:app --host 0.0.0.0 --port 8787"
  pkill -f "$ROOT/frontend/node_modules/.bin/vite"; pkill -f "npm exec vite"
  for port in 8787 5173 5174 5175; do
    pids=$(ss -ltnpH "sport = :$port" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u)
    # shellcheck disable=SC2086  # $pids is a whitespace-separated list on purpose
    [ -n "$pids" ] && kill $pids 2>/dev/null
  done
  for _ in $(seq 20); do ss -ltnH '( sport = :8787 or sport = :5173 )' | grep -q . || return 0; sleep 0.5; done
  echo "ports still busy; force killing"; ss -ltnpH '( sport = :8787 or sport = :5173 )' | grep -o 'pid=[0-9]*' | cut -d= -f2 | xargs -r kill -9
}
stop
(cd backend && nohup "$ROOT/.venv/bin/uvicorn" main:app --host 0.0.0.0 --port 8787 > "$ROOT/backend.log" 2>&1 &)
(cd frontend && nohup npx vite --port 5173 --strictPort > "$ROOT/frontend.log" 2>&1 &)
for _ in $(seq 30); do curl -sf localhost:8787/api/health >/dev/null && curl -sf localhost:5173 >/dev/null && break; sleep 0.5; done
echo "UI http://localhost:5173  API http://localhost:8787"
