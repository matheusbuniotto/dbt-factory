# syntax=docker/dockerfile:1.7
# Multi-stage image: build the UI, resolve Python deps in a builder, ship a slim non-root runtime.

FROM node:22-bookworm-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS deps
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /opt/venv && VIRTUAL_ENV=/opt/venv uv pip install -r requirements.txt

FROM python:3.12-slim-bookworm AS runtime
LABEL org.opencontainers.image.title="dbt-factory" org.opencontainers.image.source="https://github.com/matheusbuniotto/dbt-factory"
# git: the factory isolates every run in a git worktree
RUN apt-get update \
    && apt-get install -y --no-install-recommends git=1:2.39.* \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 factory \
    && useradd --system --uid 10001 --gid factory --create-home factory
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 FACTORY_MOCK=1
WORKDIR /app
COPY --from=deps /opt/venv /opt/venv
COPY --chown=factory:factory backend/ backend/
COPY --chown=factory:factory evals/ evals/
COPY --chown=factory:factory examples/ examples/
COPY --chown=factory:factory docs/ docs/
COPY --chown=factory:factory scripts/ scripts/
COPY --from=ui --chown=factory:factory /ui/dist frontend/dist
# runtime dirs the app writes to (worktrees, state, projects) must be owned by the non-root user
RUN install -d -o factory -g factory /app/worktrees /app/state /app/projects
USER factory
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=4).status == 200 else 1)"]
WORKDIR /app/backend
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8787"]
