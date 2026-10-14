#!/usr/bin/env bash
# One-time setup: python venv, frontend deps, demo dbt project (jaffle_shop_duckdb) with prod warehouse + skills.
set -euo pipefail; cd "$(dirname "$0")/.."; ROOT=$(pwd)
command -v uv >/dev/null || { echo "install uv: https://docs.astral.sh/uv/"; exit 1; }
[ -d .venv ] || uv venv .venv --python "${PYTHON_VERSION:-3.12}"
uv pip install --python .venv/bin/python -r requirements.txt
if [ "${SKIP_FRONTEND:-0}" != "1" ]; then (cd frontend && npm ci); fi
if [ ! -d projects/jaffle_shop ]; then
  git clone https://github.com/dbt-labs/jaffle_shop_duckdb projects/jaffle_shop
  mkdir -p projects/jaffle_shop/.claude/skills && cp -r examples/jaffle_shop_skills/* projects/jaffle_shop/.claude/skills/
  (cd projects/jaffle_shop && git add .claude && git -c user.email=factory@local -c user.name=factory commit -qm "Add Claude skills")
  # build the "prod" warehouse once (read-only target for tasks)
  (cd projects/jaffle_shop && DBT_PROFILES_DIR=. "$ROOT/.venv/bin/dbt" build --quiet)
fi
command -v claude >/dev/null || echo "optional: npm i -g @anthropic-ai/claude-code && claude login  (for cli/sdk engines)"
echo "setup done -> ./run.sh"
