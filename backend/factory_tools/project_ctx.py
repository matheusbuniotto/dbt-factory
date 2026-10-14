"""Per-worktree project context written by the factory at task creation (<task dir>/.factory/project.json).
Tools read it to avoid assuming a specific demo project, dialect or layout."""

import fnmatch
import json
import os
import re

import yaml

DEFAULT_LAYERS = ("stg_", "int_", "fct_", "dim_", "mart_", "rpt_")


def load(cwd=None) -> dict:
    p = os.path.join(cwd or os.getcwd(), ".factory", "project.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {}


def dialect(cwd=None) -> str:
    d = load(cwd).get("dialect")
    if d:
        return d
    from adapters import get_adapter  # legacy: env-selected adapter

    return get_adapter().dialect


def mode(cwd=None) -> str:
    return load(cwd).get("mode") or "dbt"


def model_paths(cwd=None) -> list[str]:
    ctx = load(cwd)
    if ctx.get("model_paths"):
        return list(ctx["model_paths"])
    p = os.path.join(cwd or os.getcwd(), "dbt_project.yml")
    if os.path.exists(p):
        with open(p) as f:
            proj = yaml.safe_load(f) or {}
        return list(proj.get("model-paths") or ["models"])
    return ["models"]


def is_model_file(path: str, cwd=None) -> bool:
    return any(path == mp or path.startswith(mp.rstrip("/") + "/") for mp in model_paths(cwd))


def find_model_file(model: str, cwd=None) -> str | None:
    """Relative path of <model>.sql under the model paths, or None."""
    cwd = cwd or os.getcwd()
    for mp in model_paths(cwd):
        for root, dirs, files in os.walk(os.path.join(cwd, mp)):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            if f"{model}.sql" in files:
                return os.path.relpath(os.path.join(root, f"{model}.sql"), cwd)
    return None


def layer_re(cwd=None):
    prefixes = load(cwd).get("layer_prefixes") or DEFAULT_LAYERS
    return re.compile("^(" + "|".join(re.escape(p) for p in prefixes) + ")")


def protected_hits(paths, cwd=None) -> list[str]:
    pats = load(cwd).get("protected_paths") or []
    return sorted({p for p in paths for pat in pats if fnmatch.fnmatch(p, pat) or p.startswith(pat.rstrip("*/") + "/")})


def grain_for(model: str, cwd=None):
    g = load(cwd).get("grain") or {}
    if model in g:
        return g[model]
    for pat, cols in g.items():
        if fnmatch.fnmatch(model, pat):
            return cols
    return None
