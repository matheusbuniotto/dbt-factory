"""Any-repo support: detection, profile discovery, per-task isolation, plain-SQL mode, registry, API end-to-end.
Uses the fixture repos (tests/fixtures), NOT the bundled demo."""

import os
import subprocess
import time

import pytest
import yaml
from conftest import task_worktree

import projects as PJ


def _status(repo):
    return subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout


# ---------- detection ----------
def test_detect_monorepo_dbt(mini_repo):
    d = PJ.detect(mini_repo)
    assert d["mode"] == "dbt" and not d["errors"], d["errors"]
    assert d["dbt_dir_rel"] == os.path.join("analytics", "dbt")
    assert d["profile"] == "mini" and d["profiles_source"] == "project"
    assert d["adapter"] == "duckdb" and d["dialect"] == "duckdb" and d["adapter_installed"]
    assert d["targets"] == ["dev", "prod"] and (d["dev_target"], d["prod_target"]) == ("dev", "prod")
    assert d["dbt_version_ok"] is True and d["bootstrap"] == "full"
    assert d["config"]["protected_paths"] == ["models/finance/*"]


def test_detect_plain_sql(sql_repo):
    d = PJ.detect(sql_repo)
    assert d["mode"] == "sql" and d["sql_files"] == 1 and d["dialect"] == "postgres" and not d["errors"]


def test_detect_refuses_non_git(tmp_path):
    (tmp_path / "q.sql").write_text("select 1\n")
    d = PJ.detect(str(tmp_path))
    assert d["git"] is False and any("not a git repository" in e for e in d["errors"])


def test_detect_unsupported(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    d = PJ.detect(str(tmp_path))
    assert d["mode"] == "unsupported" and any("no dbt_project.yml" in e for e in d["errors"])


def test_profile_discovery_env_and_missing(tmp_path, monkeypatch):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "dbt_project.yml").write_text("name: p\nprofile: snow\n")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # no ~/.dbt
    monkeypatch.delenv("DBT_PROFILES_DIR", raising=False)
    d = PJ.detect(str(proj))
    assert any("profile 'snow' not found" in e for e in d["errors"])
    pdir = tmp_path / "profiles"
    pdir.mkdir()
    (pdir / "profiles.yml").write_text(
        "snow:\n  target: dev\n  outputs:\n    dev: {type: snowflake, schema: analytics_dev, account: x}\n"
        "    prod: {type: snowflake, schema: analytics, account: x}\n"
    )
    monkeypatch.setenv("DBT_PROFILES_DIR", str(pdir))
    d = PJ.detect(str(proj))
    assert d["profiles_source"] == "DBT_PROFILES_DIR" and d["adapter"] == "snowflake" and d["dialect"] == "snowflake"
    assert d["prod_target"] == "prod"


@pytest.mark.parametrize(
    "kind,key,dev_val",
    [
        ("snowflake", "schema", "analytics_dev"),
        ("bigquery", "dataset", "analytics_dev"),
        ("postgres", "schema", "analytics_dev"),
    ],
)
def test_render_profile_isolates_dev_schema(tmp_path, kind, key, dev_val):
    det = {
        "dbt_dir": str(tmp_path),
        "path": str(tmp_path),
        "git_root": str(tmp_path),
        "profile": "p",
        "dev_target": "dev",
        "prod_target": "prod",
        "config": {"profiles_dir": str(tmp_path)},
    }
    (tmp_path / "profiles.yml").write_text(
        yaml.safe_dump(
            {
                "p": {
                    "target": "dev",
                    "outputs": {"dev": {"type": kind, key: dev_val}, "prod": {"type": kind, key: "analytics"}},
                }
            }
        )
    )
    out = yaml.safe_load(PJ.render_task_profile(det, "ab12", str(tmp_path / "wt")))["p"]["outputs"]
    assert out["dev"][key] == f"{dev_val}_factory_ab12"  # private per-task dev schema
    assert out["prod"][key] == "analytics"  # prod untouched (read via dbt show only)


def test_render_profile_duckdb_prod_read_only(mini_repo, tmp_path):
    d = PJ.detect(mini_repo)
    out = yaml.safe_load(PJ.render_task_profile(d, "t1", str(tmp_path)))["mini"]["outputs"]
    assert out["dev"]["path"] == str(tmp_path / ".factory" / "dev.duckdb")
    assert out["prod"]["path"] == os.path.join(d["dbt_dir"], "prod.duckdb")
    assert out["prod"]["config_options"]["access_mode"] == "READ_ONLY"


def test_registry_persists(tmp_path, mini_repo, sql_repo):
    reg = PJ.Registry(str(tmp_path / "projects.json"))
    a = reg.add(mini_repo)
    reg.add(sql_repo, name="queries")
    assert reg.add(mini_repo)["id"] == a["id"]  # idempotent
    again = PJ.Registry(str(tmp_path / "projects.json"))
    assert [p["name"] for p in again.list()] == ["mini", "queries"]
    assert again.remove(a["id"]) and len(PJ.Registry(str(tmp_path / "projects.json")).list()) == 1


# ---------- tools against a non-demo project ----------
def test_tools_on_fixture_dbt_project(mini_repo, tmp_path):
    from factory_tools import analysis as A
    from factory_tools import dbt_tools as D
    from factory_tools import gates as G
    from factory_tools import project_ctx as P

    cwd = task_worktree(mini_repo, "mini-tools", str(tmp_path))
    assert cwd.endswith(os.path.join("analytics", "dbt"))
    b = D.build(cwd=cwd)
    assert b["success"], b
    assert os.path.exists(os.path.join(cwd, ".factory", "dev.duckdb"))
    names = {r["name"] for r in D.list_resources("model", cwd=cwd)["resources"]}
    assert {"stg_items", "items", "fin_revenue"} <= names
    c = A.compare("items", key="item_id", cwd=cwd)  # dev vs read-only prod
    assert c.get("identical") is True, c
    assert P.grain_for("items", cwd) == ["item_id"] and P.dialect(cwd) == "duckdb"
    # pre-existing model without a layer prefix is exempt from naming; protected path edits fail the gate
    g = G.run_gates("items", skip_data=True, cwd=cwd)
    naming = next(x for x in g["checks"] if x["id"] == "naming_layer")
    assert naming["status"] == "pass" and "pre-existing" in naming["detail"]
    assert next(x for x in g["checks"] if x["id"] == "protected_paths")["status"] == "pass"
    with open(os.path.join(cwd, "models", "finance", "fin_revenue.sql"), "a") as f:
        f.write("-- edited\n")
    g = G.run_gates("items", skip_data=True, cwd=cwd)
    assert "protected_paths" in g["failed"]
    assert _status(mini_repo) == ""  # the user's working tree is untouched


def test_sql_gates_plain_repo(sql_repo, tmp_path):
    from factory_tools import gates as G

    cwd = task_worktree(sql_repo, "sql-gates", str(tmp_path))
    with open(os.path.join(cwd, "queries", "bad.sql"), "w") as f:
        f.write("SELECT * FROM t\n")
    g = G.sql_gates(cwd)
    ids = {c["id"]: c["status"] for c in g["checks"]}
    assert ids["select_star:queries/bad.sql"] == "fail" and ids["data_gates"] == "skip"
    assert "sqlfluff" in ids
    assert _status(sql_repo) == ""


# ---------- API end-to-end (mock engine) ----------
def _wait(c, tid, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        t = c.get(f"/api/tasks/{tid}").json()
        if t["status"] != "running" and t.get("phase") is None:
            return t
        time.sleep(0.5)
    raise AssertionError("task timeout")


def test_api_projects_and_tasks(mini_repo, sql_repo, tmp_path):
    import main
    from fastapi.testclient import TestClient

    c = TestClient(main.app)
    r = c.post("/api/projects", json={"path": str(tmp_path)})  # not a git repo
    assert r.status_code == 400 and "not a git repository" in str(r.json())
    mini = c.post("/api/projects", json={"path": mini_repo, "name": "mini"}).json()
    plain = c.post("/api/projects", json={"path": sql_repo}).json()
    assert mini["ready"] and mini["mode"] == "dbt" and mini["dbt_dir_rel"] == "analytics/dbt"
    assert plain["ready"] and plain["mode"] == "sql"
    listed = {p["id"]: p for p in c.get("/api/projects").json()}
    assert {mini["id"], plain["id"]} <= set(listed)

    tid = c.post("/api/tasks", json={"prompt": "items mart", "engine": "mock", "project_id": mini["id"]}).json()["id"]
    t = _wait(c, tid)
    assert t["project_id"] == mini["id"] and t["mode"] == "dbt" and t["status"] == "succeeded", t
    assert t["worktree"].endswith("analytics/dbt") and t["git_root"] == os.path.realpath(mini_repo)
    diff = c.get(f"/api/tasks/{tid}/diff").json()["diff"]
    assert "fct_factory_items" in diff and ".factory" not in diff and "dev.duckdb" not in diff
    logs = [e for e in c.get(f"/api/tasks/{tid}/events").text.splitlines() if '"log"' in e or "gate" in e]
    assert t.get("gate"), [x[-250:] for x in logs if "gate" in x or "error" in x][-6:]
    assert any(x["id"] == "dbt_build" and x["status"] == "pass" for x in t["gate"]["checks"])

    sid = c.post("/api/tasks", json={"prompt": "daily revenue", "engine": "mock", "project_id": plain["id"]}).json()[
        "id"
    ]
    s = _wait(c, sid)
    assert s["mode"] == "sql" and s["status"] == "succeeded", s
    ids = {x["id"]: x["status"] for x in s["gate"]["checks"]}
    assert ids["data_gates"] == "skip" and ids["sqlfluff"] in ("pass", "fail")
    assert c.get(f"/api/tasks/{sid}/preview").status_code == 409

    tasks = {x["id"]: x for x in c.get("/api/tasks").json()}
    assert tasks[tid]["project_name"] == "mini" and tasks[sid]["project_id"] == plain["id"]
    for x in (tid, sid):
        assert c.post(f"/api/tasks/{x}/cleanup?delete_branch=true").json()["worktree_removed"]
    assert _status(mini_repo) == "" and _status(sql_repo) == ""  # never mutated the user's working trees
