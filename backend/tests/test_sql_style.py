"""SQL style discovery, lint with line numbers, gate + review findings, API."""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from factory_tools import sql_style as ST

BAD = "SELECT Order_ID, customer_id\nFROM {{ ref('orders') }}\n"


def mk(tmp_path, files):
    for k, v in files.items():
        p = tmp_path / k
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(v)
    return str(tmp_path)


def test_discovery_order(tmp_path, monkeypatch):
    monkeypatch.delenv("FACTORY_SQL_STYLE", raising=False)
    d = mk(
        tmp_path / "repo",
        {".factory/sql_style.md": "# g1", ".claude/sql_style.md": "# g2", ".factory/.sqlfluff": "[sqlfluff]\n"},
    )
    s = ST.discover(d)
    assert s["rules"]["source"] == "repo .factory/.sqlfluff" and s["guide"]["source"] == "repo .factory/sql_style.md"
    (tmp_path / "repo" / ".sqlfluff").write_text("[sqlfluff]\nmax_line_length = 80\n")
    assert ST.discover(d)["rules"]["source"] == "repo .sqlfluff"
    env = mk(tmp_path / "env", {"team.md": "# env guide", "team.sqlfluff": "[sqlfluff]\n"})
    monkeypatch.setenv("FACTORY_SQL_STYLE", env)
    s = ST.discover(d)
    assert s["rules"]["source"] == s["guide"]["source"] == "FACTORY_SQL_STYLE" and "env guide" in s["guide"]["text"]


def test_claude_dir_and_project_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("FACTORY_SQL_STYLE", raising=False)
    wt = mk(tmp_path / "wt", {"x.sql": "select 1"})
    proj = mk(tmp_path / "proj", {".claude/skills/sql-style/SKILL.md": "# skill guide"})
    s = ST.discover(wt, proj)
    assert s["rules"] is None and "skill guide" in s["guide"]["text"]


def test_prompt_block():
    assert ST.prompt_block({"rules": None, "guide": None}) == ""
    b = ST.prompt_block({"rules": {"source": "repo .sqlfluff"}, "guide": {"source": "g", "text": "lowercase all"}})
    assert "lowercase all" in b and "sql_style" in b


def test_effective_config_forces_dialect(tmp_path):
    d = mk(tmp_path, {})
    path, templ = ST.effective_config(
        {"rules": {"path": "x", "text": "[sqlfluff]\ndialect = postgres\ntemplater = jinja\n"}}, d, "databricks"
    )
    txt = open(path).read()
    assert "dialect = databricks" in txt and templ == "jinja" and "apply_dbt_builtins" in txt


def test_lint_reports_lines(tmp_path):
    if not ST._sqlfluff_bin():
        pytest.skip("sqlfluff missing")
    d = mk(tmp_path, {"models/m.sql": BAD, ".sqlfluff": open(os.path.join(ROOT, "examples", ".sqlfluff")).read()})
    r = ST.lint("models/m.sql", d, dialect="duckdb", style=ST.discover(d))
    assert r["status"] == "fail" and r["violations"]
    assert any(v["code"] == "CP01" and v["line"] == 1 for v in r["violations"]), r["violations"]
    good = mk(
        tmp_path / "g",
        {
            "models/m.sql": "select\n    order_id,\n    customer_id\nfrom {{ ref('orders') }}\n",
            ".sqlfluff": open(os.path.join(ROOT, "examples", ".sqlfluff")).read(),
        },
    )
    assert ST.lint("models/m.sql", good, style=ST.discover(good))["status"] == "pass"


def test_save_validates(tmp_path, monkeypatch):
    """UI-saved style lives in factory state per project id, never in the repo; repo files win over it."""
    monkeypatch.setattr(ST, "STATE", str(tmp_path / "state"))
    monkeypatch.delenv("FACTORY_SQL_STYLE", raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(ValueError):
        ST.save("p1", rules_text="not = ini without section")
    saved = ST.save("p1", rules_text="[sqlfluff]\n", guide_text="# g")
    assert len(saved) == 2 and all(str(tmp_path / "state") in p for p in saved)
    st = ST.discover(None, str(repo), project_id="p1")
    assert st["guide"]["text"] == "# g" and st["rules"]["source"] == "factory settings"
    assert not (repo / ".factory").exists()
    (repo / ".sqlfluff").write_text("[sqlfluff]\n")
    assert ST.discover(None, str(repo), project_id="p1")["rules"]["source"] == "repo .sqlfluff"
    ST.save("p1", rules_text="", guide_text="")
    assert ST.discover(None, str(tmp_path / "nothing"), project_id="p1")["rules"] is None


def test_task_dirs_from_project_json(tmp_path, monkeypatch):
    """A task finds style in its dbt sub-dir, its worktree root, then its own project's root/.factory/config.yml."""
    import json

    monkeypatch.delenv("FACTORY_SQL_STYLE", raising=False)
    proj, wt = tmp_path / "proj", tmp_path / "wt"
    (proj / ".factory").mkdir(parents=True)
    (proj / ".factory" / "config.yml").write_text("sql_style:\n  guide: docs/sql.md\n")
    (proj / "docs").mkdir()
    (proj / "docs" / "sql.md").write_text("# project guide\n")
    task = wt / "analytics" / "dbt"
    (task / ".factory").mkdir(parents=True)
    (wt / ".sqlfluff").write_text("[sqlfluff]\n")
    ctx = {
        "worktree_root": str(wt),
        "project_root": str(proj),
        "project_dir": str(proj / "analytics/dbt"),
        "project_id": "x",
    }
    (task / ".factory" / "project.json").write_text(json.dumps(ctx))
    st = ST.discover(str(task))
    assert st["rules"]["path"] == str(wt / ".sqlfluff")
    assert st["guide"]["text"] == "# project guide\n" and st["guide"]["source"] == "repo .factory/config.yml"


def test_review_findings_inline(tmp_path):
    from factory_tools import review as R

    d = mk(tmp_path, {"models/m.sql": BAD})
    gate = {
        "checks": [
            {
                "id": "sql_style",
                "status": "fail",
                "group": "code",
                "detail": "x",
                "path": "models/m.sql",
                "source": "repo .sqlfluff",
                "violations": [{"line": 1, "col": 1, "code": "CP01", "description": "Keywords must be lower case."}],
            }
        ]
    }
    f = R.gate_findings(gate, "models/m.sql", d)
    assert f[0]["line"] == 1 and f[0]["line_hint"].startswith("SELECT") and "CP01" in f[0]["message"]


def test_style_api(mini_repo, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import main

    monkeypatch.setattr(ST, "STATE", str(tmp_path / "state"))
    monkeypatch.delenv("FACTORY_SQL_STYLE", raising=False)
    c = TestClient(main.app)
    pid = c.post("/api/projects", json={"path": mini_repo}).json()["id"]
    assert c.get(f"/api/style?project_id={pid}").json()["project_id"] == pid
    r = c.put(
        f"/api/style?project_id={pid}", json={"sqlfluff": "[sqlfluff]\nmax_line_length = 90\n", "guide": "# mine"}
    ).json()
    assert r["guide"]["text"] == "# mine" and r["saved"] == [".sqlfluff", "sql_style.md"]
    assert c.put(f"/api/style?project_id={pid}", json={"sqlfluff": "garbage"}).status_code == 400
    assert c.get("/api/style?project_id=nope").status_code == 404


def test_factory_config_sql_style(tmp_path, monkeypatch):
    """`.factory/config.yml` `sql_style:` points discovery at repo files (path or {rules, guide})."""
    from factory_tools import sql_style as ST

    monkeypatch.delenv("FACTORY_SQL_STYLE", raising=False)
    (tmp_path / "style").mkdir()
    (tmp_path / "style" / "team.sqlfluff").write_text("[sqlfluff]\nmax_line_length = 90\n")
    (tmp_path / "style" / "guide.md").write_text("# lower-case keywords\n")
    (tmp_path / ".factory").mkdir()
    (tmp_path / ".factory" / "config.yml").write_text("sql_style: style\n")
    st = ST.discover(str(tmp_path))
    assert st["rules"]["path"].endswith("team.sqlfluff") and st["guide"]["text"].startswith("# lower")
    assert st["summary"] == "repo .factory/config.yml"
    (tmp_path / ".factory" / "config.yml").write_text("sql_style:\n  guide: style/guide.md\n")
    (tmp_path / ".sqlfluff").write_text("[sqlfluff]\n")
    st = ST.discover(str(tmp_path))
    assert st["rules"]["source"] == "repo .sqlfluff" and st["guide"]["source"] == "repo .factory/config.yml"
