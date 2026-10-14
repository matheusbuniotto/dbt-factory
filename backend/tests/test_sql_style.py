"""SQL style discovery, lint with line numbers, gate + review findings, API."""
import os, sys, shutil, pytest
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from factory_tools import sql_style as ST

BAD = "SELECT Order_ID, customer_id\nFROM {{ ref('orders') }}\n"

def mk(tmp_path, files):
    for k, v in files.items():
        p = tmp_path / k; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(v)
    return str(tmp_path)

def test_discovery_order(tmp_path, monkeypatch):
    monkeypatch.delenv("FACTORY_SQL_STYLE", raising=False)
    d = mk(tmp_path / "repo", {".factory/sql_style.md": "# g1", ".claude/sql_style.md": "# g2", ".factory/.sqlfluff": "[sqlfluff]\n"})
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
    path, templ = ST.effective_config({"rules": {"path": "x", "text": "[sqlfluff]\ndialect = postgres\ntemplater = jinja\n"}}, d, "databricks")
    txt = open(path).read()
    assert "dialect = databricks" in txt and templ == "jinja" and "apply_dbt_builtins" in txt

def test_lint_reports_lines(tmp_path):
    if not ST._sqlfluff_bin(): pytest.skip("sqlfluff missing")
    d = mk(tmp_path, {"models/m.sql": BAD, ".sqlfluff": open(os.path.join(ROOT, "examples", ".sqlfluff")).read()})
    r = ST.lint("models/m.sql", d, dialect="duckdb", style=ST.discover(d))
    assert r["status"] == "fail" and r["violations"]
    assert any(v["code"] == "CP01" and v["line"] == 1 for v in r["violations"]), r["violations"]
    good = mk(tmp_path / "g", {"models/m.sql": "select\n    order_id,\n    customer_id\nfrom {{ ref('orders') }}\n",
                                ".sqlfluff": open(os.path.join(ROOT, "examples", ".sqlfluff")).read()})
    assert ST.lint("models/m.sql", good, style=ST.discover(good))["status"] == "pass"

def test_save_validates(tmp_path):
    with pytest.raises(ValueError): ST.save(str(tmp_path), rules_text="not = ini without section")
    saved = ST.save(str(tmp_path), rules_text="[sqlfluff]\n", guide_text="# g")
    assert len(saved) == 2 and ST.discover(str(tmp_path))["guide"]["text"] == "# g"
    ST.save(str(tmp_path), rules_text="", guide_text="")
    assert ST.discover(str(tmp_path))["rules"] is None

def test_review_findings_inline(tmp_path):
    from factory_tools import review as R
    d = mk(tmp_path, {"models/m.sql": BAD})
    gate = {"checks": [{"id": "sql_style", "status": "fail", "group": "code", "detail": "x", "path": "models/m.sql", "source": "repo .sqlfluff",
                        "violations": [{"line": 1, "col": 1, "code": "CP01", "description": "Keywords must be lower case."}]}]}
    f = R.gate_findings(gate, "models/m.sql", d)
    assert f[0]["line"] == 1 and f[0]["line_hint"].startswith("SELECT") and "CP01" in f[0]["message"]

def test_style_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setattr(main, "PROJECT", str(tmp_path)); monkeypatch.delenv("FACTORY_SQL_STYLE", raising=False)
    c = TestClient(main.app)
    assert c.get("/api/style").json()["rules"] is None
    r = c.put("/api/style", json={"sqlfluff": "[sqlfluff]\nmax_line_length = 90\n", "guide": "# mine"}).json()
    assert r["rules"]["source"] == "repo .factory/.sqlfluff" and r["guide"]["text"] == "# mine"
    assert c.put("/api/style", json={"sqlfluff": "garbage"}).status_code == 400
