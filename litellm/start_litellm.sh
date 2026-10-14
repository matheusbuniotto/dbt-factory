#!/usr/bin/env bash
# Start a LiteLLM proxy on :4000 using litellm/litellm_config.yaml (installs litellm into .litellm-venv on first run).
set -euo pipefail; cd "$(dirname "$0")"; ROOT=$(cd .. && pwd)
[ -x "$ROOT/.litellm-venv/bin/litellm" ] || { uv venv -q "$ROOT/.litellm-venv"; uv pip install -q --python "$ROOT/.litellm-venv/bin/python" 'litellm[proxy]'; }
export LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-sk-factory-local}"
: "${OPENAI_API_KEY:?set OPENAI_API_KEY (or edit litellm_config.yaml for another provider)}"
pkill -f "litellm --config $PWD/litellm_config.yaml" 2>/dev/null || true
nohup "$ROOT/.litellm-venv/bin/litellm" --config "$PWD/litellm_config.yaml" --port "${LITELLM_PORT:-4000}" > "$ROOT/litellm.log" 2>&1 &
echo "LiteLLM on http://localhost:${LITELLM_PORT:-4000} (log: litellm.log). Now start the factory with:"
echo "  FACTORY_ENGINE=sdk FACTORY_MODEL=gpt-4o ANTHROPIC_BASE_URL=http://localhost:${LITELLM_PORT:-4000} ANTHROPIC_AUTH_TOKEN=$LITELLM_MASTER_KEY \\"
echo "  ANTHROPIC_SMALL_FAST_MODEL=gpt-4o-mini ANTHROPIC_DEFAULT_HAIKU_MODEL=gpt-4o-mini ./run.sh"
