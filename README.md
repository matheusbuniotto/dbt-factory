# dbt factory

[![CI](https://github.com/matheusbuniotto/dbt-factory/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/matheusbuniotto/dbt-factory/actions/workflows/ci.yml)
[![CodeQL](https://github.com/matheusbuniotto/dbt-factory/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/matheusbuniotto/dbt-factory/actions/workflows/codeql.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/matheusbuniotto/dbt-factory/badge)](https://scorecard.dev/viewer/?uri=github.com/matheusbuniotto/dbt-factory)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-fe5196.svg)](https://conventionalcommits.org)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://pre-commit.com)

Droid-style "software factory" for analytics engineers: describe a dbt change, an agent works in its own git worktree, runs `dbt build`, and the UI streams plan / tool calls / diff / SQL / data preview.

## Setup

Requirements: Python 3.12 + [uv](https://docs.astral.sh/uv/), Node 20+, git. Optional: `gh` (PRs / review verdicts) and the `claude` CLI (live engines).

```bash
./scripts/setup.sh       # .venv, frontend deps, clones jaffle_shop_duckdb into projects/ and builds its prod warehouse
./run.sh                 # kills old instances, starts API :8787 and UI :5173
open http://localhost:5173
```

Without credentials everything runs on the `mock` engine (real dbt work, canned agent stream).

## Use with your repo

dbt-factory works on any local git repo. The bundled `jaffle_shop` demo (set up by `scripts/setup.sh`) is only the default.

```bash
./run.sh --project ~/code/analytics            # or: FACTORY_PROJECT=~/code/analytics ./run.sh
```

You can also register more repos in the UI: on the new-session screen, use the project picker and click **Add repo**. Registered repos are
saved in `state/projects.json` (paths must be under `$HOME`, the folder containing dbt-factory, or `FACTORY_ALLOWED_ROOTS`), the sidebar groups sessions by project, and each task records which project it ran against.

**What gets detected** (`GET /api/projects` shows the result, including errors and warnings):

| | |
|---|---|
| dbt project | `dbt_project.yml` anywhere in the tree, so monorepos work (e.g. `analytics/dbt`). If there are several, set `dbt_project_dir`. |
| profile | Searched in this order: `profiles_dir` from config, then the project's `profiles.yml`, then `$DBT_PROFILES_DIR`, then `~/.dbt/profiles.yml`. |
| adapter | Taken from the profile output `type`: duckdb, databricks, snowflake, bigquery, postgres (others best effort). The SQL dialect follows. |
| targets | `dev` is the profile default target. `prod` is the `prod` output if it exists, or `targets.prod` from config. |
| dbt version | Checks `require-dbt-version` and that the adapter plugin is installed. |
| plain SQL | A repo with `.sql` files but no dbt project. The agent edits the SQL, and gates are limited to sqlfluff and style checks. Data gates are skipped, and the UI says so. |

### Safety model

- **Your working tree is never touched.** Every task runs in a `git worktree` of your repo, on branch `factory/<id>`. The repo must be a git repo with at least one commit; a folder that isn't one is refused with a clear message.
- **Isolated dev target.** Each task gets its own profile in `<worktree>/.factory/profiles.yml`:
  - `dev` is private: on duckdb, a file inside the worktree; on warehouses, your dev schema or dataset plus `_factory_<task>`.
  - `prod` is your prod output, read-only: duckdb opens it with `access_mode: READ_ONLY`, and elsewhere it is only read through `dbt show` (read-only SELECT with a LIMIT).
  - Profiles keep `env_var()` references, so no secrets are copied out of your environment.
- **Bootstrap.** On duckdb the task runs `dbt seed` + `dbt run` into its private dev file, so new models have their parents. Warehouses default to `bootstrap: none`, so nothing is built until the agent builds its own models.
- **Factory scratch files are never committed or shown in the diff.** `.factory/`, `target/`, `logs/` and `*.duckdb` stay out of commits and diffs.

**Repo-local config** (`.factory/config.yml`, in the dbt project dir or the repo root; all keys optional):

```yaml
dbt_project_dir: analytics/dbt     # monorepo: which dbt project to use
profiles_dir: .ci/profiles         # explicit profiles dir
targets: { dev: dev, prod: prod }  # output names in your profile
grain:                             # grain conventions (exact name or glob)
  fct_orders: [order_id]
  "fct_daily_*": [date_day]
protected_paths: [models/finance/*] # editing these fails the protected_paths gate
layer_prefixes: [stg_, int_, fct_, dim_, mart_]
eval_cases_dir: .factory/evals     # repo-local eval cases: python -m evals run --project <repo>
bootstrap: none                    # full = seed+run the base project into dev
sql: { dialect: postgres, paths: [queries] } # plain-SQL repos
```

The agent also loads `.claude/skills/*` and your SQL style config from the repo. Eval cases can name their target repo with
`project: <path>` (the bundled cases use `projects/jaffle_shop`).

## Engines (`FACTORY_ENGINE=auto|mock|cli|sdk`)

| engine | what runs | notes |
|---|---|---|
| `mock` | `backend/mock.py` | Replays a canned Claude-Code stream but really edits models and runs dbt. Default when no credentials. |
| `cli`  | `claude -p ... --output-format stream-json --verbose` | Follow-ups use `--resume <session_id>`. |
| `sdk`  | `backend/sdk_runner.py` (claude-agent-sdk `query()`) | Converts SDK messages to the same stream-json lines; `resume=` for follow-ups. |

`auto` = `cli` if credentials exist, else `mock`. The new-session composer has an engine selector, so each task can pick its own engine (it stays fixed for that task's follow-ups).
Both live engines use the same system prompt (`backend/prompts.py`), tools `Read, Write, Edit, Glob, Grep, Bash(dbt:*), Bash(ls:*), Bash(cat:*)`, `acceptEdits`, cwd = task worktree, `FACTORY_MAX_TURNS` (40). Cancel kills the engine's process group.

Credentials (picked up by both live engines; `/api/health` reports `auth`):

- `claude login` (subscription) → `~/.claude/.credentials.json`
- `ANTHROPIC_API_KEY`
- gateway: `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` (e.g. LiteLLM)

Other env: `FACTORY_MODEL` (passed as `--model` / `model=`), `CLAUDE_CODE_MAX_RETRIES` (default 2 so bad credentials fail fast), `DBT_FACTORY_ADAPTER=duckdb|databricks`.

## External gateway (LiteLLM or any Anthropic-compatible proxy)

The factory does not ship or run a proxy. Point it at the gateway your platform provides:

```bash
FACTORY_ENGINE=sdk FACTORY_MODEL=<model-name-on-gateway> \
ANTHROPIC_BASE_URL=https://your-gateway ANTHROPIC_AUTH_TOKEN=<token> \
./run.sh
```

The gateway must expose the Anthropic Messages API (`/v1/messages`). Non-Claude models must be good at tool calling; quality varies.

## Tests

`.venv/bin/python -m pytest -q backend/tests` (SDK message → UI event normalization).

## API

`POST /api/tasks {prompt, engine?}` · `GET /api/tasks[/{id}]` · `GET /api/tasks/{id}/events?since=N` (SSE) · `POST /api/tasks/{id}/messages {content}` · `POST /api/tasks/{id}/cancel` · `GET /api/tasks/{id}/diff` · `GET /api/tasks/{id}/preview` · `POST /api/tasks/{id}/pr` · `POST /api/tasks/{id}/cleanup[?delete_branch=true]` · `GET /api/health`

## Agent tooling: `dbt-factory-tools` MCP server (`backend/mcp_server.py`)

Local stdio MCP server, registered per task: the CLI gets `--mcp-config .factory/mcp.json`, the SDK gets `mcp_servers=`. Allowed as `mcp__dbt-factory-tools`.

- dbt: `dbt_list` (manifest search + selectors), `dbt_lineage` (up/downstream by level), `dbt_compile`, `dbt_build` (build/test/run with selectors, structured `run_results.json`), `dbt_failing_test_rows`, `dbt_docs`, `dbt_source_freshness`
- data: `data_profile`, `data_histogram`, `data_compare` (prod vs dev target: row delta, schema, column stats, key-based diff), `data_sample`, `data_query` (read-only SELECT, LIMIT ≤ 500, timeout)

### No local data (hard rule)

All data goes through the configured dbt target via `dbt show --inline` (`backend/factory_tools/warehouse.py`). SQL is built from dbt macros (`adapter.get_columns_in_relation`, `adapter.quote`, `dbt.type_string()`), so it stays adapter-agnostic. Each task profile has `dev` (the task's schema/db) and `prod` (baseline) targets. Ad-hoc SQL is parsed with sqlglot: one SELECT only; no DML/DDL, no jinja beyond `ref`/`source`, no file readers (`read_csv`, `'x.parquet'`, `parquet.\`path\``). The agent can't`Read`/`Edit` data files (csv/parquet/duckdb/seeds/…), and `cat/head/python/duckdb/…` are disallowed in Bash. The UI preview also uses `dbt show`.

### Project skills

Both engines load project settings and skills (`--setting-sources project` / `setting_sources=["project"]`, plus the `Skill` tool). The demo repo has `.claude/skills/dbt-model-conventions`. The UI composer chip "N skills · M mcp tools" lists the skills and MCP tools, taken from the engine's init event (or a static scan in mock mode).

Tests: `.venv/bin/python -m pytest -q backend/tests` (~45 tests, ~3 min: SQL guard, every tool against a real worktree, MCP over stdio, SDK normalization).

## Definition of Done (gates)

After every succeeded turn the backend runs code + data gates on the preview model and emits a `gate` event. The UI shows a **Done n/m** chip and a **Done** scorecard tab (plain-language check names). Agents must call `definition_of_done` and iterate (or emit `<waiver id="CHECK">reason</waiver>` — never for `dbt_compile`, `dbt_build`, or `grain_unique`).

Code: compile, build, docs+tests, grain declared, naming (`stg_`/`int_`/`fct_`/`dim_`), no bare `SELECT *`, `ref`/`source` only, sqlfluff.
Data (via dbt target only): grain unique, no fan-out (incl. inflated `number_of_orders`-style counts), nulls, row-count vs prod, reconcile, preview sanity.

`GET /api/tasks/{id}/gate?refresh=true` re-runs.

## Review (analyst view)

Per-task **Review** mode (no keyboard nav): overall risk badge + look-first list, models ordered by risk with plain-language reasons and downstream impact, code diff beside data-vs-prod compare, inline findings, comments (line + general) with resolve, **Send to droid** (packages open comments as a follow-up turn), and Approve / Request changes. Optional "post to GitHub PR" is only executed when the user ticks it and clicks Submit (`gh pr review`).

`GET /api/tasks/{id}/review`, `POST .../comments`, `POST .../comments/send-to-agent`, `POST .../verdict`.

## Evals

```bash
.venv/bin/python -m evals list
.venv/bin/python -m evals run --engine mock                 # all cases
.venv/bin/python -m evals run --engine mock --case monthly_revenue
```

Six jaffle cases under `evals/cases/`. Scores: data 50% · code 25% · gates 25% (optional LLM judge 10% when `FACTORY_JUDGE=claude`). A case **passes** when every data assertion (incl. golden-query equivalence through the adapter) holds and code ≥ 75%. Results in `evals/results/<run_id>.json`. UI: sidebar **Evals** (runs list, per-case scorecards, compare two runs, "Run mock evals").

## Best practices

`docs/BEST_PRACTICES.md` is appended to the system prompt and shipped as a skill template in `docs/skills-template/`. Project skills under `.claude/skills/` win on conflicts.

## Screenshots

`screenshots/` — `gate-scorecard.png`, `review-analyst.png`, `review-verdict.png`, `evals-compare.png`, `tools-profile-compare.png`, … Sample eval result: `evals/results/mock-final.json`.

## CI

A multi-stage GitHub Actions pipeline covers hygiene, static analysis, complexity, security, tests, data/evals, frontend and container. See [docs/CI.md](docs/CI.md).
