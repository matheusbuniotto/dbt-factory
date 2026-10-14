"""Tool tests: pure SQL guard tests + integration tests against a real dbt worktree (duckdb target)."""
import json, os, subprocess, sys, asyncio
import pytest
BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
os.environ["PATH"] = f"{ROOT}/.venv/bin:" + os.environ["PATH"]
from factory_tools import warehouse as W, analysis as A, dbt_tools as D
from adapters import get_adapter

# ---------- read-only guard (no warehouse) ----------
@pytest.mark.parametrize("sql", [
    "select * from {{ ref('orders') }}", "with x as (select 1 as a) select * from x",
    "select a from {{ source('jaffle', 'raw_orders') }} union all select 1"])
def test_guard_allows_selects(sql): assert W.validate_select(sql, read="duckdb")

@pytest.mark.parametrize("sql,why", [
    ("delete from {{ ref('orders') }}", "Delete"), ("drop table orders", "Drop"),
    ("select 1; select 2", "exactly one"), ("insert into t select 1", "Insert"),
    ("select * from read_csv_auto('seeds/raw_orders.csv')", ""),
    ("select * from 'seeds/raw_orders.csv'", "file path"),
    ("select * from read_parquet('x.parquet')", ""),
    ("{% do run_query('drop table x') %} select 1", "jinja"),
    ("select {{ adapter.get_relation('a','b','c') }}", "jinja"),
    ("attach 'other.duckdb'", ""), ("copy orders to 'out.csv'", "")])
def test_guard_rejects(sql, why):
    with pytest.raises(W.ReadOnlyViolation) as e: W.validate_select(sql, read="duckdb")
    assert why.lower() in str(e.value).lower()

def test_guard_databricks_file_read():
    with pytest.raises(W.ReadOnlyViolation): W.validate_select("select * from parquet.`/mnt/raw/x`", read="databricks")

def test_rel_spec():
    assert W.rel_jinja("orders") == "ref('orders')"
    assert W.rel_jinja("source:jaffle.raw") == "source('jaffle', 'raw')"
    with pytest.raises(W.QueryError): W.rel_jinja("orders; drop table x")

def test_no_direct_file_access_in_code():
    """HARD RULE: nothing in the backend opens warehouse/data files itself."""
    import re
    for root, _, files in os.walk(BACKEND):
        if "tests" in root or "__pycache__" in root: continue
        for f in files:
            if f.endswith(".py"):
                src = open(os.path.join(root, f)).read()
                assert not re.search(r"^\s*import duckdb|duckdb\.connect|import pandas|pd\.read_", src, re.M), f

# ---------- integration ----------
WT = f"{ROOT}/worktrees/_pytest"

@pytest.fixture(scope="session")
def wt():
    if not os.path.isdir(WT):
        subprocess.run(["git", "worktree", "add", "-f", "-B", "factory/_pytest", WT, "HEAD"], cwd=f"{ROOT}/projects/jaffle_shop", check=True, capture_output=True)
    os.makedirs(f"{WT}/.factory", exist_ok=True)
    open(f"{WT}/.factory/profiles.yml", "w").write(get_adapter().profiles_yml("jaffle_shop", WT, f"{ROOT}/projects/jaffle_shop"))
    if not os.path.exists(f"{WT}/warehouse.duckdb"):
        D.build(cwd=WT)
    return WT

def test_list_and_docs(wt):
    r = D.list_resources("model", cwd=wt); names = {x["name"] for x in r["resources"]}
    assert {"orders", "customers", "stg_orders"} <= names
    d = D.docs("orders", cwd=wt)
    assert any(c["name"] == "order_id" and "unique" in c["tests"] for c in d["columns"])
    assert D.list_resources(select="+orders", cwd=wt)["count"] >= 3

def test_lineage(wt):
    l = D.lineage("orders", "upstream", cwd=wt)
    assert "model.jaffle_shop.stg_orders" in l["upstream"][0]
    assert D.lineage("stg_orders", "downstream", depth=1, cwd=wt)["downstream"][0]

def test_compile(wt):
    c = D.compile_model("orders", cwd=wt)
    assert "{{" in c["raw_code"] and "{{" not in c["compiled_code"] and "stg_orders" in c["compiled_code"]

def test_build_structured(wt):
    b = D.build("stg_orders", command="test", cwd=wt)
    assert b["success"] and b["summary"].get("pass", 0) >= 1 and not b["failed"]

def test_failing_test_rows(wt):
    t = next(x for x in D.list_resources("test", cwd=wt)["resources"] if x["name"].startswith("unique_orders_order_id"))
    r = D.failing_test_rows(t["name"], cwd=wt)
    assert r["passed"] and r["failing_rows"] == []

def test_freshness_no_policy(wt):
    assert D.freshness(cwd=wt)["sources_with_freshness"] == 0

def test_sample_query_limit(wt):
    s = W.sample("orders", 5, cwd=wt); assert s["row_count"] == 5 and "order_id" in s["columns"]
    q = W.query("select order_id from {{ ref('orders') }}", limit=100000, cwd=wt)
    assert q["limit"] == W.MAX_LIMIT and q["row_count"] == 99
    with pytest.raises(W.ReadOnlyViolation): W.query("delete from {{ ref('orders') }}", cwd=wt)

def test_profile(wt):
    p = A.profile("orders", cwd=wt)
    assert p["row_count"] == 99
    oid = next(c for c in p["columns"] if c["name"] == "order_id"); assert oid["distinct"] == 99 and oid["nulls"] == 0
    st = next(c for c in p["columns"] if c["name"] == "status"); assert st["top_values"][0]["value"] == "completed"

def test_histogram(wt):
    h = A.histogram("orders", "amount", 5, cwd=wt); assert h["kind"] == "numeric" and sum(b["count"] for b in h["buckets"]) == 99
    assert A.histogram("orders", "status", cwd=wt)["kind"] == "categorical"

def test_compare_prod_vs_dev(wt):
    c = A.compare("customers", key="customer_id", cwd=wt)
    assert c["status"] == "compared" and c["identical"] and c["key_diff"]["compared_rows"] == 100
    n = A.compare("does_not_exist_anywhere", cwd=wt) if False else None

def test_compare_detects_changes(wt):
    # compare two different relations on the same target: stg_customers vs customers share customer_id
    c = A.compare("customers", key="customer_id", base_target="dev", base_relation="stg_customers", cwd=wt)
    assert "number_of_orders" in c["columns_added"] and not c["identical"]

def test_mcp_server_stdio(wt):
    sys.path.insert(0, os.path.dirname(__file__))
    from mcp_smoke import main
    names, lin, blocked = asyncio.run(main(wt))
    assert "data_compare" in names and "dbt_build" in names and len(names) == 15
    assert lin["upstream"] and blocked["error"] == "read_only_violation"
