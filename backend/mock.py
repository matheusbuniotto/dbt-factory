"""Mock engine: emits Claude-Code-shaped stream-json events but does real work
(writes a model, builds it, runs MCP tools + Definition of Done) so diff/preview/gates are genuine.
Solutions come from mock_solutions.pick(prompt); some are intentionally flawed (fan-out, nulls, month boundary)."""

import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mock_solutions
from engine_config import ALLOWED_TOOLS, MCP_NAME, mcp_tool_names, project_skills
from factory_tools import analysis as A
from factory_tools import dbt_tools as D
from factory_tools import gates as G
from factory_tools import project_ctx as P

DELAY = float(os.environ.get("FACTORY_MOCK_DELAY", "0.4"))


def M(n):
    return f"mcp__{MCP_NAME}__{n}"


def call(fn, *a, **kw):
    try:
        return json.dumps(fn(*a, **kw), default=str)
    except Exception as ex:
        return json.dumps({"error": type(ex).__name__, "message": str(ex)})


def _init(cwd):
    return {
        "type": "system",
        "subtype": "init",
        "session_id": "mock",
        "model": "mock-replay",
        "cwd": cwd,
        "tools": [t for t in ALLOWED_TOOLS if not t.startswith("mcp__")] + mcp_tool_names(),
        "mcp_servers": [{"name": MCP_NAME, "status": "connected"}],
        "skills": [s["name"] for s in project_skills(cwd)],
    }


class Turn:
    def __init__(self):
        self.n = 0

    def ev(self, o):
        time.sleep(DELAY)
        return json.dumps(o)

    def text(self, t):
        return self.ev({"type": "assistant", "message": {"content": [{"type": "text", "text": t}]}})

    def tool(self, name, inp):
        self.n += 1
        i = f"t{self.n}"
        return i, self.ev(
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": i, "name": name, "input": inp}]}}
        )

    def res(self, i, text):
        return json.dumps(
            {
                "type": "user",
                "message": {"content": [{"type": "tool_result", "tool_use_id": i, "content": text[:12000]}]},
            }
        )


def _waivers_text(w):
    return "\n".join(f'<waiver id="{k}">{v}</waiver>' for k, v in w.items())


def run_mock(prompt, cwd, env, followup=False):
    T = Turn()
    yield T.ev(_init(cwd))
    if followup:
        yield from _followup(T, prompt, cwd)
        return
    if P.mode(cwd) == "sql":
        yield from _sql_mode(T, prompt, cwd)
        return
    try:
        models = [r["name"] for r in D.list_resources("model", cwd=cwd)["resources"]]
    except Exception:
        models = None
    sol = mock_solutions.pick(prompt, models)
    if not sol:
        yield T.text("[MOCK MODE] This project has no models to build on.")
        yield json.dumps(
            {"type": "result", "subtype": "success", "is_error": False, "num_turns": 1, "result": "nothing to do"}
        )
        return
    model = sol["model"]
    anchor = sol.get("base") or "orders"
    mdir = P.model_paths(cwd)[0]
    yield T.text(f"[MOCK MODE] Request: {prompt}\nI'll inspect the project and load the team's skills first.")
    for sk in ("dbt-data-agent", "dbt-model-conventions"):
        p = os.path.join(cwd, f".claude/skills/{sk}/SKILL.md")
        if os.path.exists(p):
            i, e = T.tool("Skill", {"skill": sk})
            yield e
            yield T.res(i, open(p).read()[:3000])
    i, e = T.tool(M("dbt_list"), {"resource_type": "model"})
    yield e
    yield T.res(i, call(D.list_resources, "model", cwd=cwd))
    i, e = T.tool(M("dbt_lineage"), {"name": anchor, "direction": "both"})
    yield e
    yield T.res(i, call(D.lineage, anchor, "both", cwd=cwd))
    yield T.text(f"<plan>\n{sol['plan']}\n</plan>")
    for path, body in ((f"{mdir}/{model}.sql", sol["sql"]), (f"{mdir}/{model}.yml", sol["yml"])):
        i, e = T.tool("Write", {"file_path": path, "content": body})
        yield e
        os.makedirs(os.path.dirname(os.path.join(cwd, path)), exist_ok=True)
        with open(os.path.join(cwd, path), "w") as fh:
            fh.write(body)
        yield T.res(i, "File created")
    i, e = T.tool(M("dbt_build"), {"select": f"{model}+"})
    yield e
    yield T.res(i, call(D.build, f"{model}+", cwd=cwd))
    i, e = T.tool(M("data_profile"), {"relation": model})
    yield e
    yield T.res(i, call(A.profile, model, cwd=cwd))
    i, e = T.tool(M("definition_of_done"), {"model": model})
    yield e
    dod = call(G.run_gates, model, waivers=sol["waivers"], cwd=cwd)
    yield T.res(i, dod)
    d = json.loads(dod)
    failed = d.get("failed") or []
    msg = f"Definition of Done: {'green' if d.get('passed') else 'red on ' + ', '.join(failed)}."
    if sol["waivers"]:
        msg += "\n" + _waivers_text(sol["waivers"])
    yield T.text(f"{msg}\n<preview_model>{model}</preview_model>\n{sol['summary']}")
    yield json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "num_turns": T.n + 3,
            "total_cost_usd": 0.0,
            "result": sol["summary"] + " (mock)",
        }
    )


def _factory_model(cwd):
    """The model the first turn created (fct_/dim_/int_ prefix) in this worktree."""
    for mp in P.model_paths(cwd):
        for _r, _d, fs in os.walk(os.path.join(cwd, mp)):
            for f in sorted(fs):
                if f.endswith(".sql") and f.startswith(("fct_", "dim_", "int_", "monthly_")):
                    return f[:-4]
    return "fct_monthly_revenue"


def _style_fix(T, rel, cwd, p, sql, fixed):
    """Style follow-up (upper-case SQL): `sqlfluff fix` with the repo/task style config. Returns (sql, fixed)."""
    if not re.search(r"\b(SELECT|FROM|GROUP BY)\b", sql):
        return sql, fixed
    from factory_tools import sql_style as ST

    cfg, _ = ST.effective_config(ST.discover(cwd), cwd, P.dialect(cwd))
    i, e = T.tool("Bash", {"command": f"sqlfluff fix {rel} --config .factory/sqlfluff.cfg"})
    yield e
    exe = ST._sqlfluff_bin() or "sqlfluff"
    argv = [exe, "fix", rel, "--config", cfg, "--disable-progress-bar"]
    r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)
    yield T.res(i, (r.stdout or r.stderr)[-600:])
    with open(p) as fh:
        sql = fh.read()
    return sql, sql.replace(") total_amount", ") as total_amount") if " as total_amount" not in sql else sql


def _followup(T, prompt, cwd):
    # find the factory model in this worktree
    if P.mode(cwd) == "sql":
        yield from _sql_mode(T, prompt, cwd)
        return
    model = _factory_model(cwd)
    yield T.text(
        f"[MOCK MODE] Follow-up: {prompt}\n<plan>\n- Address review comments on `{model}`\n- Fix nulls / fan-out if flagged\n- Re-run Definition of Done\n</plan>"
    )
    rel = P.find_model_file(model, cwd) or f"models/{model}.sql"
    p = os.path.join(cwd, rel)
    sql = open(p).read()
    fixed = sql
    # fix known flaws when asked
    if "lifetime_value" in sql and "coalesce" not in sql:
        fixed = sql.replace("ltv.lifetime_value", "coalesce(ltv.lifetime_value, 0) as lifetime_value")
    if "left join payments on orders.order_id = payments.order_id" in sql:
        fixed = sql.replace(
            "count(orders.order_id) as number_of_orders", "count(distinct orders.order_id) as number_of_orders"
        )
    if "order_date < '2018-03-31'" in sql:
        fixed = sql.replace("order_date < '2018-03-31'", "order_date < '2018-04-01'")
    if fixed == sql and "revenue_per_customer" not in sql and "sum(amount) as revenue" in sql:
        fixed = sql.replace(
            "    round(sum(amount) / count(distinct order_id), 2) as avg_order_value\n",
            "    round(sum(amount) / count(distinct order_id), 2) as avg_order_value,\n    round(sum(amount) / count(distinct customer_id), 2) as revenue_per_customer\n",
        )
    sql, fixed = yield from _style_fix(T, rel, cwd, p, sql, fixed)
    i, e = T.tool("Edit", {"file_path": rel, "old_string": "...", "new_string": fixed[-400:]})
    yield e
    open(p, "w").write(fixed)
    yield T.res(i, "Edited" if fixed != sql else "No change needed")
    i, e = T.tool(M("dbt_build"), {"select": f"{model}+"})
    yield e
    yield T.res(i, call(D.build, f"{model}+", cwd=cwd))
    i, e = T.tool(M("definition_of_done"), {"model": model})
    yield e
    dod = call(G.run_gates, model, waivers={"reconciles": "new model"}, cwd=cwd)
    yield T.res(i, dod)
    d = json.loads(dod)
    yield T.text(
        f"Definition of Done: {'green' if d.get('passed') else 'red on ' + ', '.join(d.get('failed') or [])}.\n"
        f'<waiver id="reconciles">new model</waiver>\n<preview_model>{model}</preview_model>\nAddressed follow-up on {model}.'
    )
    yield json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "num_turns": T.n + 2,
            "total_cost_usd": 0.0,
            "result": f"Follow-up applied to {model} (mock).",
        }
    )


def _sql_mode(T, prompt, cwd):
    """Plain-SQL repo: write one clean query file, then lint/style gates (no data access possible)."""
    ctx = P.load(cwd)
    folder = (ctx.get("sql_paths") or [""])[0]
    slug = "_".join(re.findall(r"[a-z0-9]+", (prompt or "query").lower())[:5]) or "query"
    path = os.path.join(folder, f"factory_{slug}.sql")
    body = f"-- {prompt[:100]}\nselect\n    1 as id,\n    'mock' as source\n"
    yield T.text(f"[MOCK MODE] Plain SQL repo. Request: {prompt}\n<plan>\n- Add `{path}`\n- Lint it\n</plan>")
    i, e = T.tool("Write", {"file_path": path, "content": body})
    yield e
    os.makedirs(os.path.dirname(os.path.join(cwd, path)) or cwd, exist_ok=True)
    with open(os.path.join(cwd, path), "w") as fh:
        fh.write(body)
    yield T.res(i, "File created")
    g = G.sql_gates(cwd, files=[path])
    yield T.text(
        f"SQL gates: {'green' if g['passed'] else 'red on ' + ', '.join(g['failed'])}. Data gates skipped (plain SQL mode)."
    )
    yield json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "num_turns": T.n + 2,
            "total_cost_usd": 0.0,
            "result": f"wrote {path} (mock)",
        }
    )


if __name__ == "__main__":
    for line in run_mock(sys.argv[2], os.getcwd(), dict(os.environ), followup=sys.argv[1] == "followup"):
        print(line, flush=True)
