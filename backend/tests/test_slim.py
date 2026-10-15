"""Slim builds on a many-model project: only modified models + their children are built; parents are deferred
to prod; follow-ups build only what changed since the last build; whole-project builds are refused."""

import os
import subprocess

import pytest

from conftest import ROOT, git_repo, task_worktree
from factory_tools import dbt_tools as D
from factory_tools import slim as S
from factory_tools.warehouse import QueryError

N = 60  # binary tree: m_i selects from m_{(i-1)//2}


def _children(i):
    out, frontier = set(), [i]
    while frontier:
        nxt = [c for p in frontier for c in (2 * p + 1, 2 * p + 2) if c < N]
        out.update(nxt)
        frontier = nxt
    return out


def _ids(ix):
    return {f"model.many.m_{i:03d}" for i in ix}


@pytest.fixture(scope="module")
def many(tmp_path_factory):
    src = tmp_path_factory.mktemp("src") / "many"
    (src / "models").mkdir(parents=True)
    (src / "dbt_project.yml").write_text("name: many\nversion: '1.0.0'\nprofile: many\nmodel-paths: ['models']\n")
    (src / "profiles.yml").write_text(
        "many:\n  target: dev\n  outputs:\n"
        "    dev: {type: duckdb, path: dev.duckdb, threads: 4}\n"
        "    prod: {type: duckdb, path: prod.duckdb, threads: 4}\n"
    )
    (src / ".gitignore").write_text("*.duckdb*\ntarget/\nlogs/\n.user.yml\n")
    (src / "models" / "m_000.sql").write_text("select 1 as id\n")
    for i in range(1, N):
        (src / "models" / f"m_{i:03d}.sql").write_text(f"select id from {{{{ ref('m_{(i - 1) // 2:03d}') }}}}\n")
    repo = git_repo(str(src), str(tmp_path_factory.mktemp("repos") / "many"))
    subprocess.run(
        [f"{ROOT}/.venv/bin/dbt", "build", "--target", "prod", "--quiet", "--profiles-dir", repo],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return task_worktree(repo, "slim", str(tmp_path_factory.mktemp("wt")))


def _built_models(res):
    return {u for u in res["built"] if u.startswith("model.")}


def test_slim_selection_and_followups(many):
    first = D.build(cwd=many)
    assert first["success"] and first["selection"]["models"] == 0 and first["selection"]["total_models"] == N

    with open(os.path.join(many, "models", "m_010.sql"), "a") as f:
        f.write("-- changed\n")
    r = D.build(cwd=many)
    assert r["success"], r["failed"]
    assert _built_models(r) == _ids({10} | _children(10))  # modified + children; parents deferred to prod
    assert r["selection"]["models"] == 1 + len(_children(10)) < N
    assert "--defer" in r["command"] and "state:modified+" in r["command"]

    with open(os.path.join(many, "models", "m_005.sql"), "a") as f:
        f.write("-- changed too\n")
    r2 = D.build(cwd=many)  # follow-up turn: only what changed since the last build
    assert r2["success"] and _built_models(r2) == _ids({5} | _children(5))
    assert "model.many.m_010" not in r2["built"]


def test_full_build_refused(many):
    for sel in ("*", "fqn:*"):
        with pytest.raises(QueryError, match="refusing a full-project build"):
            D.build(sel, cwd=many)
    with pytest.raises(QueryError, match="refusing"):
        D.build("*", cwd=many, full_build=True, confirm="yes")
    S.guard("m_001+", False, None)  # narrow selectors are fine


def test_depth_and_pending(many, monkeypatch):
    monkeypatch.setattr(S, "config", lambda cwd: {"depth": 1, "favor_state": False})
    man = D._manifest(many)
    sel, state = S.default_selection(many, man)
    assert sel.startswith("state:modified+1") and state == S.TURN_STATE
    assert S.pending(many, man) == []  # everything changed vs prod was built
