"""Shared fixtures.

* `wt`: a real dbt worktree of the demo project (duckdb dev target + read-only prod), built once per session.
* `mini_repo` / `sql_repo`: the fixture repos in tests/fixtures copied to a temp dir and `git init`-ed, so tests
  exercise detection and task isolation against a project that is NOT the demo.
State and worktrees of API tests are redirected to a temp dir so tests never touch the developer's state/.
"""

import os
import shutil
import subprocess
import sys
import tempfile

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(BACKEND)
FIXTURES = os.path.join(BACKEND, "tests", "fixtures")
sys.path.insert(0, BACKEND)
os.environ["PATH"] = f"{ROOT}/.venv/bin:" + os.environ["PATH"]
WT = f"{ROOT}/worktrees/_pytest"
DEMO = f"{ROOT}/projects/jaffle_shop"

_TMP = tempfile.mkdtemp(prefix="factory-pytest-")
os.environ.setdefault("FACTORY_STATE_DIR", os.path.join(_TMP, "state"))
os.environ.setdefault("FACTORY_WORKTREES_DIR", os.path.join(_TMP, "worktrees"))
os.environ.setdefault("FACTORY_PROJECT", DEMO)
os.environ.setdefault("FACTORY_MOCK_DELAY", "0")


def git_repo(src: str, dst: str) -> str:
    shutil.copytree(src, dst)
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(
            ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
            cwd=dst,
            check=True,
            capture_output=True,
        )
    return dst


def task_worktree(project_path: str, name: str, base_dir: str) -> str:
    """Worktree + per-task profile exactly like the API does (projects.render_task_profile)."""
    import json

    import projects as PJ

    det = PJ.detect(project_path)
    assert not det["errors"], det["errors"]
    wt = os.path.join(base_dir, name)
    if not os.path.isdir(wt):
        subprocess.run(
            ["git", "worktree", "add", "-f", "-B", f"factory/{name}", wt, "HEAD"],
            cwd=det["git_root"],
            check=True,
            capture_output=True,
        )
    task_dir = os.path.normpath(os.path.join(wt, os.path.relpath(det.get("dbt_dir") or det["path"], det["git_root"])))
    os.makedirs(f"{task_dir}/.factory", exist_ok=True)
    with open(f"{task_dir}/.factory/.gitignore", "w") as f:
        f.write("*\n")
    with open(f"{task_dir}/.factory/project.json", "w") as f:
        json.dump(PJ.task_context(det), f)
    if det["mode"] == "dbt":
        with open(f"{task_dir}/.factory/profiles.yml", "w") as f:
            f.write(PJ.render_task_profile(det, name, task_dir))
    return task_dir


@pytest.fixture(scope="session")
def wt():
    from factory_tools import dbt_tools as D

    d = task_worktree(DEMO, "_pytest", f"{ROOT}/worktrees")
    if not os.path.exists(f"{d}/.factory/dev.duckdb"):
        D.build(cwd=d)
    return d


@pytest.fixture(scope="session")
def mini_repo(tmp_path_factory):
    """Monorepo fixture; its 'prod' warehouse is built once (as the user's own prod would be)."""
    repo = git_repo(os.path.join(FIXTURES, "mini_dbt"), str(tmp_path_factory.mktemp("repos") / "mini"))
    dbt_dir = os.path.join(repo, "analytics", "dbt")
    subprocess.run(
        [f"{ROOT}/.venv/bin/dbt", "build", "--target", "prod", "--quiet", "--profiles-dir", dbt_dir],
        cwd=dbt_dir,
        check=True,
        capture_output=True,
    )
    return repo


@pytest.fixture(scope="session")
def sql_repo(tmp_path_factory):
    return git_repo(os.path.join(FIXTURES, "plain_sql"), str(tmp_path_factory.mktemp("repos") / "plainsql"))
