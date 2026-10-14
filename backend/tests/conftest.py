"""Shared fixtures: a real dbt worktree of the demo project (duckdb dev target + read-only prod)."""

import os
import subprocess
import sys

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
os.environ["PATH"] = f"{ROOT}/.venv/bin:" + os.environ["PATH"]
WT = f"{ROOT}/worktrees/_pytest"


@pytest.fixture(scope="session")
def wt():
    from adapters import get_adapter
    from factory_tools import dbt_tools as D

    if not os.path.isdir(WT):
        subprocess.run(
            ["git", "worktree", "add", "-f", "-B", "factory/_pytest", WT, "HEAD"],
            cwd=f"{ROOT}/projects/jaffle_shop",
            check=True,
            capture_output=True,
        )
    os.makedirs(f"{WT}/.factory", exist_ok=True)
    open(f"{WT}/.factory/profiles.yml", "w").write(
        get_adapter().profiles_yml("jaffle_shop", WT, f"{ROOT}/projects/jaffle_shop")
    )
    if not os.path.exists(f"{WT}/warehouse.duckdb"):
        D.build(cwd=WT)
    return WT
