"""Shared engine config (cli + sdk). Env:
FACTORY_ENGINE=auto|mock|cli|sdk   FACTORY_MODEL=<model>   FACTORY_MAX_TURNS=40
ANTHROPIC_BASE_URL (e.g. LiteLLM proxy http://localhost:4000), ANTHROPIC_AUTH_TOKEN / ANTHROPIC_API_KEY."""
import os
import sys
BACKEND = os.path.dirname(os.path.abspath(__file__))
MCP_NAME = "dbt-factory-tools"
ALLOWED_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Bash(dbt:*)", "Bash(ls:*)", "Skill", f"mcp__{MCP_NAME}"]
# HARD RULE: no local data access. Data files can't be read; only dbt (which uses the configured target) and the MCP tools touch data.
DATA_GLOBS = ["**/*.csv", "**/*.tsv", "**/*.parquet", "**/*.duckdb", "**/*.duckdb.wal", "**/*.db", "**/*.sqlite", "**/*.xlsx", "**/*.jsonl", "**/*.ndjson", "./seeds/**"]
DISALLOWED_TOOLS = [f"Read({g})" for g in DATA_GLOBS] + [f"Edit({g})" for g in DATA_GLOBS] + \
    ["Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(less:*)", "Bash(python:*)", "Bash(python3:*)", "Bash(duckdb:*)",
     "Bash(sqlite3:*)", "Bash(csvlook:*)", "Bash(awk:*)", "Bash(sed:*)", "Bash(cp:*)", "Bash(curl:*)", "WebFetch"]

def mcp_servers(worktree):
    py = os.path.join(os.path.dirname(BACKEND), ".venv", "bin", "python")
    return {MCP_NAME: {"type": "stdio", "command": py, "args": [os.path.join(BACKEND, "mcp_server.py")],
                       "env": {"DBT_PROJECT_DIR": worktree, "DBT_PROFILES_DIR": os.path.join(worktree, ".factory"),
                               "PATH": os.path.dirname(py) + ":/usr/bin:/bin", "DBT_FACTORY_ADAPTER": os.environ.get("DBT_FACTORY_ADAPTER", "duckdb")}}}

def write_mcp_config(worktree):
    import json
    path = os.path.join(worktree, ".factory", "mcp.json")
    json.dump({"mcpServers": mcp_servers(worktree)}, open(path, "w"), indent=2)
    return path

def project_skills(worktree):
    out, root = [], os.path.join(worktree, ".claude", "skills")
    if not os.path.isdir(root): return out
    for d in sorted(os.listdir(root)):
        f = os.path.join(root, d, "SKILL.md")
        if not os.path.exists(f): continue
        txt = open(f).read(); meta = {}
        if txt.startswith("---"):
            for line in txt.split("---", 2)[1].splitlines():
                if ":" in line: k, v = line.split(":", 1); meta[k.strip()] = v.strip()
        out.append({"name": meta.get("name", d), "description": meta.get("description", "")})
    return out

def mcp_tool_names():
    return [f"mcp__{MCP_NAME}__{n}" for n in ("dbt_list", "dbt_lineage", "dbt_compile", "dbt_build", "dbt_failing_test_rows", "dbt_docs",
            "dbt_source_freshness", "data_profile", "data_histogram", "data_compare", "data_sample", "data_query", "generate_dbt_tests", "data_quality_gate", "definition_of_done")]
MAX_TURNS = int(os.environ.get("FACTORY_MAX_TURNS", "40"))
ENGINES = ("mock", "cli", "sdk")

def model(): return os.environ.get("FACTORY_MODEL") or None

def claude_auth():
    if os.environ.get("ANTHROPIC_BASE_URL") and (os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
        return "gateway"
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"): return "api_key"
    if os.path.exists(os.path.expanduser("~/.claude/.credentials.json")): return "claude_login"
    return None

def default_engine():
    e = os.environ.get("FACTORY_ENGINE", "auto")
    if os.environ.get("FACTORY_MOCK") == "1": return "mock"
    if e in ENGINES: return e
    return "cli" if claude_auth() else "mock"
