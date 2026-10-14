"""Tests: quality tools, DoD gates, eval scoring, review risk/impact, comments + verdict API.
All data access goes through dbt (adapter) in the worktrees/_pytest worktree."""

import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, ROOT)
import evals.scoring as S
from factory_tools import gates as G
from factory_tools import quality as Q
from factory_tools import review as R
from factory_tools import warehouse as W

WT = os.path.join(ROOT, "worktrees", "_pytest")  # demo worktree (see conftest.wt)
FAN = os.path.join(WT, "models", "fct_pytest_fanout.sql")
FAN_SQL = """-- intentionally fans out: one order can have many payments, grain claimed as order_id
select o.order_id, o.customer_id, p.payment_id, p.amount
from {{ ref('orders') }} o
join {{ ref('stg_payments') }} p on o.order_id = p.order_id
"""
FAN_YML = """version: 2
models:
  - name: fct_pytest_fanout
    description: test fan-out model (duplicated order_id after payments join)
    meta: {grain: [order_id]}
    columns:
      - name: order_id
        description: claimed grain (not unique after join)
        data_tests: [not_null]
"""


@pytest.fixture(scope="module")
def cwd(wt):
    return wt


@pytest.fixture(scope="module")
def fanout(cwd):
    open(FAN, "w").write(FAN_SQL)
    open(FAN.replace(".sql", ".yml"), "w").write(FAN_YML)
    p = W.run_dbt(["run", "--select", "fct_pytest_fanout", "--quiet"], cwd=cwd, timeout=300)
    assert p.returncode == 0, p.stdout + p.stderr
    yield "fct_pytest_fanout"
    for f in (FAN, FAN.replace(".sql", ".yml")):
        if os.path.exists(f):
            os.remove(f)


# ---------- pure ----------
def test_parse_waivers():
    w = G.parse_waivers(
        'x <waiver id="reconciles">new model, no prod</waiver> y <waiver id="row_count_delta">ok</waiver>'
    )
    assert set(w) == {"reconciles", "row_count_delta"} and "new model" in w["reconciles"]


def test_layer_and_star_regex():
    from factory_tools import project_ctx as P

    layer = P.layer_re("/nonexistent")  # no project.json -> default convention
    assert layer.match("fct_monthly_revenue") and layer.match("dim_customer_ltv")
    assert not layer.match("monthly_rev") and not layer.match("orders")
    star = r"(?is)select\s+\*\s+from\s+(?!\{\{\s*(?:ref|source)\b)"
    assert re.search(star, "select * from foo") and not re.search(star, "select * from {{ ref('orders') }}")


def test_scoring_math():
    assert S.close(100, 100.05, 0.001) and not S.close(100, 110, 0.001) and S.close("a", "a")
    assert S.gate_rate({"checks": [{"status": "pass"}, {"status": "skip"}]}) == 1.0
    assert S.gate_rate({"checks": [{"status": "pass"}, {"status": "fail"}]}) == 0.5
    assert S.gate_rate({"checks": [{"status": "waived"}, {"status": "warn"}]}) == 0.5
    assert S.frac([{"passed": True}, {"passed": False, "weight": 2}]) == pytest.approx(0.333, abs=1e-3)
    assert S.overall(1, 1, 1) == 1.0
    assert S.overall(0.0, 1.0, None) == pytest.approx(0.667, abs=1e-3)  # data-only weight renormalises
    assert S.overall(1, 1, 1, judge=0.0) == pytest.approx(0.9)


# ---------- adapter-backed ----------
def test_grain_and_nulls_on_orders(cwd):
    assert Q.grain_check("orders", ["order_id"], cwd=cwd)["status"] == "pass"
    assert Q.grain_check("orders", ["customer_id"], cwd=cwd)["status"] == "fail"
    assert Q.null_check("orders", key_columns=["order_id"], cwd=cwd)["status"] in ("pass", "warn")


def test_fanout_detected(cwd, fanout):
    r = Q.fanout_check(fanout, grain=["customer_id"], cwd=cwd)
    assert r["status"] == "fail", r


def test_reconcile_reference_sql(cwd):
    ok = Q.reconcile("orders", ["amount"], reference_sql="select order_id, amount from {{ ref('orders') }}", cwd=cwd)
    assert ok["status"] == "pass", ok


def test_generate_tests(cwd):
    out = Q.generate_tests("orders", cwd=cwd)
    assert "order_id" in str(out)


def test_run_gates_and_golden(cwd, fanout):
    g = G.run_gates(fanout, cwd=cwd)
    ids = {c["id"]: c["status"] for c in g["checks"]}
    assert ids["dbt_compile"] == "pass" and ids["naming_layer"] == "pass"
    assert ids.get("no_fanout") == "fail" and g["passed"] is False
    # golden: fan-out model has more rows than distinct orders
    gold = S.golden(
        fanout,
        {
            "columns": ["order_id", "amount"],
            "key": ["order_id"],
            "reference_sql": "select order_id, amount from {{ ref('orders') }}",
        },
        cwd,
    )
    assert gold["passed"] is False


def test_review_risk_and_impact(cwd, fanout):
    rev = R.build_review(cwd, model=fanout, run_data=True)
    m = next(x for x in rev["models"] if x["model"] == fanout)
    assert m["risk"]["level"] in ("med", "high") and m["risk"]["reasons"]
    assert rev["summary"] and rev["risk"] in ("low", "med", "high")
    imp = R.impact("stg_orders", cwd)
    assert any("orders" in u for u in imp["downstream_models"])


# ---------- API: comments + verdict (no GitHub) ----------
def test_comments_and_verdict_api(cwd):
    import main
    from fastapi.testclient import TestClient

    tid = "pytestrv"
    main.TASKS[tid] = {
        "id": tid,
        "prompt": "t",
        "status": "succeeded",
        "worktree": cwd,
        "branch": "factory/_pytest",
        "events": [],
        "turns": [{"prompt": "t", "status": "succeeded"}],
        "engine": "mock",
        "comments": [],
    }
    try:
        c = TestClient(main.app)
        a = c.post(
            f"/api/tasks/{tid}/comments", json={"body": "use count distinct", "path": "models/x.sql", "line": 3}
        ).json()
        c.post(f"/api/tasks/{tid}/comments", json={"body": "general note"})
        assert len(c.get(f"/api/tasks/{tid}/comments").json()) == 2
        assert c.post(f"/api/tasks/{tid}/comments/{a['id']}/resolve?resolved=true").json()["resolved"] is True
        v = c.post(
            f"/api/tasks/{tid}/verdict", json={"verdict": "request_changes", "body": "fix", "post_to_github": False}
        ).json()
        assert v["verdict"] == "request_changes" and v["gh"] is None
        assert c.post(f"/api/tasks/{tid}/verdict", json={"verdict": "nope"}).status_code == 400
    finally:
        main.TASKS.pop(tid, None)
        p = os.path.join(main.STATE, f"{tid}.json")
        if os.path.exists(p):
            os.remove(p)
