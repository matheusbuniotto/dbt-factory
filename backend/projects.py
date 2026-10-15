"""Project registry + detection: point dbt-factory at ANY local repo.

A *project* is a local git repo (or a sub-directory of one, for monorepos). Detection finds the dbt project
(dbt_project.yml anywhere in the tree), the dbt profile (project profiles.yml, $DBT_PROFILES_DIR, ~/.dbt),
the adapter (from the profile output `type`), targets, and checks the installed dbt version/adapter plugin.
Repos with .sql files but no dbt project run in *plain SQL* mode. Nothing here writes to the user's repo.

Per task, `render_task_profile` produces a profiles.yml for the task's worktree with exactly two outputs:
  dev  - a private dev location (duckdb: a file inside the worktree; others: the dev schema + `_factory_<task>` suffix)
  prod - the configured prod target, read-only (duckdb opened with access_mode READ_ONLY; only `dbt show` reads it)
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import time
from typing import Any

import yaml

SKIP_DIRS = {
    ".git",
    "node_modules",
    "target",
    "dbt_packages",
    "dbt_modules",
    "logs",
    ".venv",
    "venv",
    "__pycache__",
    ".factory",
    ".tox",
    ".mypy_cache",
}
# profile `type` -> sqlfluff dialect
DIALECTS = {
    "duckdb": "duckdb",
    "databricks": "databricks",
    "spark": "sparksql",
    "snowflake": "snowflake",
    "bigquery": "bigquery",
    "postgres": "postgres",
    "redshift": "redshift",
    "trino": "trino",
    "athena": "athena",
    "sqlserver": "tsql",
}
SCHEMA_KEY = {"bigquery": "dataset"}  # where the dev "schema" lives in a profile output
CONFIG_FILE = os.path.join(".factory", "config.yml")
CONFIG_KEYS = {
    "slim",  # slim builds: {depth: "" (all children) | int, favor_state: bool}
    "sql_style",  # SQL style: a path (file/dir) or {rules: path, guide: path}, relative to the repo
    "dbt_project_dir",  # sub-directory with dbt_project.yml (monorepos); auto-detected otherwise
    "profiles_dir",  # explicit profiles dir (relative to repo or absolute)
    "profile",  # override dbt_project.yml `profile:`
    "adapter",  # override adapter type (normally read from the profile)
    "targets",  # {dev: <output name>, prod: <output name>}
    "prod_target",  # shorthand for targets.prod
    "grain",  # grain conventions: {model_name: [cols]} or {"fct_*": [...]}
    "protected_paths",  # glob list the agent must not modify (gate fails if touched)
    "eval_cases_dir",  # repo-local eval cases
    "bootstrap",  # dev bootstrap: "none" (default: slim builds defer to prod) | "full" (seed+run)
    "layer_prefixes",  # naming convention for new models
    "sql",  # plain-SQL mode: {dialect: ansi, paths: [...]}
}


class ProjectError(Exception):
    pass


# ───────────────────────────── detection ─────────────────────────────


def _git(args, cwd):
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False, timeout=20)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(args, 127, "", "git unavailable")


def git_root(path: str) -> str | None:
    r = _git(["rev-parse", "--show-toplevel"], path)
    return os.path.realpath(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


def _walk(root, max_depth=6):
    root = os.path.abspath(root)
    base = root.count(os.sep)
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith("."))
        if d.count(os.sep) - base >= max_depth:
            dirs[:] = []
        yield d, files


def find_dbt_projects(root: str) -> list[str]:
    """Relative dirs (\".\" for root) containing dbt_project.yml, shallowest first."""
    out = [os.path.relpath(d, root) for d, files in _walk(root) if "dbt_project.yml" in files]
    return sorted(out, key=lambda p: (0 if p == "." else p.count(os.sep) + 1, p))


def count_sql(root: str, limit=5000) -> int:
    n = 0
    for _, files in _walk(root):
        n += sum(f.endswith(".sql") for f in files)
        if n >= limit:
            break
    return n


def load_config(repo_root: str, dbt_dir: str | None = None) -> dict:
    """.factory/config.yml from the dbt project dir, falling back to the repo root (project dir wins)."""
    cfg: dict = {}
    for d in [repo_root] + ([dbt_dir] if dbt_dir and dbt_dir != repo_root else []):
        p = os.path.join(d, CONFIG_FILE)
        if os.path.exists(p):
            with open(p) as f:
                data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                raise ProjectError(f"{p}: expected a mapping")
            cfg.update(data)
    unknown = sorted(set(cfg) - CONFIG_KEYS)
    if unknown:
        cfg["_unknown_keys"] = unknown
    return cfg


def read_dbt_project(dbt_dir: str) -> dict:
    with open(os.path.join(dbt_dir, "dbt_project.yml")) as f:
        return yaml.safe_load(f) or {}


def _profile_candidates(dbt_dir, repo_root, cfg):
    if cfg.get("profiles_dir"):
        p = cfg["profiles_dir"]
        yield "config", p if os.path.isabs(p) else os.path.join(repo_root, p)
    yield "project", dbt_dir
    if os.environ.get("DBT_PROFILES_DIR"):
        yield "DBT_PROFILES_DIR", os.environ["DBT_PROFILES_DIR"]
    yield "~/.dbt", os.path.expanduser("~/.dbt")


def discover_profile(dbt_dir: str, repo_root: str, profile_name: str, cfg: dict) -> dict:
    """First profiles.yml (in dbt's own precedence order) that defines `profile_name`."""
    tried = []
    for source, d in _profile_candidates(dbt_dir, repo_root, cfg):
        p = os.path.join(d, "profiles.yml")
        tried.append(p)
        if not os.path.exists(p):
            continue
        with open(p) as f:
            data = yaml.safe_load(f) or {}
        if profile_name in data and isinstance(data[profile_name], dict):
            return {"path": os.path.realpath(p), "source": source, "profile": data[profile_name], "tried": tried}
    return {"path": None, "source": None, "profile": None, "tried": tried}


def _dbt_version():
    try:
        from importlib.metadata import version

        return version("dbt-core")
    except Exception:
        return None


def _version_ok(required, installed):
    if not required or not installed:
        return True
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version

    reqs = required if isinstance(required, list) else [required]
    return all(Version(installed) in SpecifierSet(str(r).replace(" ", "")) for r in reqs)


def adapter_installed(adapter_type: str | None) -> bool:
    if not adapter_type:
        return False
    try:
        return importlib.util.find_spec(f"dbt.adapters.{adapter_type}") is not None
    except (ImportError, ValueError):
        return False


def _pick_targets(outputs: dict, default: str | None, cfg: dict) -> tuple[str | None, str | None]:
    targets = cfg.get("targets") or {}
    dev = targets.get("dev") or default or ("dev" if "dev" in outputs else next(iter(outputs), None))
    prod = targets.get("prod") or cfg.get("prod_target") or ("prod" if "prod" in outputs else None)
    return dev, prod


def _detect_git(det: dict, path: str) -> str | None:
    root = git_root(path)
    det["git"], det["git_root"] = bool(root), root
    if not root:
        det["errors"].append(
            "not a git repository: dbt-factory isolates every task in a git worktree and never edits your working "
            "tree. Run `git init && git add -A && git commit -m init` (or point at a git checkout)."
        )
        return None
    det["head"] = _git(["rev-parse", "--short", "HEAD"], root).stdout.strip() or None
    if not det["head"]:
        det["errors"].append("repository has no commits yet: commit once so tasks can branch from HEAD")
    det["subdir"] = os.path.relpath(path, root)
    return root


def _load_cfg(det: dict, root: str, dbt_dir: str | None) -> dict:
    try:
        cfg = load_config(root, dbt_dir)
    except ProjectError as ex:
        det["errors"].append(str(ex))
        return {}
    if cfg.get("_unknown_keys"):
        det["warnings"].append(f"unknown keys in .factory/config.yml: {cfg['_unknown_keys']}")
    return cfg


def _detect_sql(det: dict, path: str, cfg: dict) -> dict:
    n = count_sql(path)
    det["sql_files"], det["config"] = n, cfg
    if not n:
        det["mode"] = "unsupported"
        det["errors"].append("no dbt_project.yml and no .sql files found")
        return det
    det["mode"] = "sql"
    det["dialect"] = (cfg.get("sql") or {}).get("dialect", "ansi")
    det["warnings"].append(
        "no dbt_project.yml: plain SQL mode. The agent edits .sql files; gates are limited to sqlfluff/style "
        "checks and data gates are skipped (no dbt target to query through)."
    )
    return det


def _detect_version(det: dict, proj: dict) -> None:
    det["dbt_version_required"] = proj.get("require-dbt-version")
    det["dbt_version"] = _dbt_version()
    try:
        det["dbt_version_ok"] = _version_ok(det["dbt_version_required"], det["dbt_version"])
    except Exception as ex:  # unparsable specifier: report, don't block
        det["dbt_version_ok"] = None
        det["warnings"].append(f"could not parse require-dbt-version: {ex}")
    if det["dbt_version_ok"] is False:
        det["errors"].append(
            f"dbt-core {det['dbt_version']} does not satisfy require-dbt-version {det['dbt_version_required']}"
        )


def _detect_profile(det: dict, dbt_dir: str, root: str, cfg: dict) -> None:
    prof = discover_profile(dbt_dir, root, str(det["profile"]), cfg)
    det["profiles_path"], det["profiles_source"] = prof["path"], prof["source"]
    body = prof["profile"] or {}
    outputs = body.get("outputs") or {}
    det["targets"] = sorted(outputs)
    dev, prod = _pick_targets(outputs, body.get("target"), cfg)
    det["dev_target"], det["prod_target"] = dev, prod
    adapter = cfg.get("adapter") or (outputs.get(dev) or {}).get("type")
    det["adapter"], det["dialect"] = adapter, DIALECTS.get(adapter or "", "ansi")
    det["adapter_installed"] = adapter_installed(adapter)
    if not prof["profile"]:
        det["errors"].append(
            f"profile '{det['profile']}' not found (looked in: {', '.join(prof['tried'])}). Add a profiles.yml to the "
            "project, set DBT_PROFILES_DIR, or set profiles_dir in .factory/config.yml."
        )
    elif not adapter:
        det["errors"].append(f"profile '{det['profile']}' has no usable target '{dev}'")
    elif not det["adapter_installed"]:
        det["errors"].append(f"dbt adapter plugin for '{adapter}' is not installed: pip install dbt-{adapter}")
    if prof["profile"] and not prod:
        det["warnings"].append(
            f"no prod target: compare/baselines read '{dev}' read-only. Set targets.prod in .factory/config.yml."
        )
    if adapter and adapter not in DIALECTS:
        det["warnings"].append(f"adapter '{adapter}' is best-effort: dev isolation uses a schema suffix")
    det["bootstrap"] = cfg.get("bootstrap") or "none"  # slim builds defer unbuilt parents to prod


def detect(path: str) -> dict[str, Any]:
    """Inspect a local path. Never writes. Returns a JSON-able description incl. errors/warnings."""
    path = os.path.realpath(os.path.expanduser(path))
    det: dict[str, Any] = {"path": path, "name": os.path.basename(path), "errors": [], "warnings": []}
    if not os.path.isdir(path):
        det["errors"].append(f"not a directory: {path}")
        det["mode"] = "unsupported"
        return det
    root = _detect_git(det, path) or path
    cfg = _load_cfg(det, root, None)
    projects = find_dbt_projects(path)
    det["dbt_projects"] = projects
    rel = cfg.get("dbt_project_dir") or (projects[0] if projects else None)
    if len(projects) > 1 and not cfg.get("dbt_project_dir"):
        det["warnings"].append(
            f"{len(projects)} dbt projects found; using '{rel}'. Set dbt_project_dir in .factory/config.yml to choose."
        )
    if rel is None:
        return _detect_sql(det, path, cfg)
    dbt_dir = os.path.normpath(os.path.join(path, rel))
    det.update(mode="dbt", dbt_dir=dbt_dir, dbt_dir_rel=os.path.relpath(dbt_dir, root))
    cfg = _load_cfg(det, root, dbt_dir)
    det["config"] = cfg
    proj = read_dbt_project(dbt_dir)
    det["dbt_name"] = proj.get("name")
    det["model_paths"] = proj.get("model-paths") or proj.get("source-paths") or ["models"]
    det["profile"] = cfg.get("profile") or proj.get("profile") or proj.get("name")
    _detect_version(det, proj)
    _detect_profile(det, dbt_dir, root, cfg)
    return det


# ───────────────────────────── per-task profile ─────────────────────────────


def _abs_duckdb_path(p: str, dbt_dir: str) -> str:
    if not p or p == ":memory:" or "{{" in p or p.startswith(("md:", "s3:", "http")):
        return p
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(dbt_dir, p))


def _prod_attach(prod_path, existing):
    """duckdb: attach the prod file read-only to dev so --defer'd refs (prod_db.schema.table) resolve."""
    out = list(existing or [])
    if prod_path and os.path.isfile(prod_path):
        alias = os.path.splitext(os.path.basename(prod_path))[0]
        out.append({"path": prod_path, "alias": alias, "read_only": True})
    return out


def _suffix(task_id: str) -> str:
    return "_factory_" + re.sub(r"\W", "_", task_id)


def render_task_profile(det: dict, task_id: str, task_dir: str) -> str:
    """profiles.yml for a task: `dev` isolated per task, `prod` read-only. Raises ProjectError if unusable."""
    prof = discover_profile(
        det["dbt_dir"], det.get("git_root") or det["path"], str(det["profile"]), det.get("config") or {}
    )
    outputs = (prof["profile"] or {}).get("outputs") or {}
    if det["dev_target"] not in outputs:
        raise ProjectError(f"target '{det['dev_target']}' not in profile '{det['profile']}'")
    src_dev = dict(outputs[det["dev_target"]])
    src_prod = dict(outputs.get(det.get("prod_target") or det["dev_target"]) or src_dev)
    kind = src_dev.get("type")
    if kind == "duckdb":
        dev = {**src_dev, "path": os.path.join(task_dir, ".factory", "dev.duckdb")}
        dev.pop("config_options", None)
        prod = {**src_prod, "path": _abs_duckdb_path(src_prod.get("path", ""), det["dbt_dir"])}
        dev["attach"] = _prod_attach(prod["path"], src_dev.get("attach"))
        prod["config_options"] = {**(src_prod.get("config_options") or {}), "access_mode": "READ_ONLY"}
    else:
        key = SCHEMA_KEY.get(kind or "", "schema")
        dev = dict(src_dev)
        if dev.get(key):
            dev[key] = f"{dev[key]}{_suffix(task_id)}"
        else:
            dev[key] = f"dbt_factory{_suffix(task_id)}"
        prod = src_prod  # only ever read through `dbt show` (read-only SELECT, LIMIT enforced)
    return yaml.safe_dump(
        {det["profile"]: {"target": "dev", "outputs": {"dev": dev, "prod": prod}}},
        sort_keys=False,
        default_flow_style=False,
    )


def task_context(det: dict) -> dict:
    """What tools inside a worktree need to know (written to <task>/.factory/project.json)."""
    cfg = det.get("config") or {}
    return {
        "mode": det.get("mode"),
        "adapter": det.get("adapter"),
        "dialect": det.get("dialect", "ansi"),
        "model_paths": det.get("model_paths") or ["models"],
        "protected_paths": cfg.get("protected_paths") or [],
        "grain": cfg.get("grain") or {},
        "layer_prefixes": cfg.get("layer_prefixes"),
        "sql_paths": (cfg.get("sql") or {}).get("paths"),
        "bootstrap": det.get("bootstrap", "none"),
        "slim": cfg.get("slim") or {},
        "single_writer": det.get("adapter") == "duckdb",
    }


# ───────────────────────────── registry ─────────────────────────────


def project_id(path: str) -> str:
    return hashlib.sha1(os.path.realpath(path).encode()).hexdigest()[:10]


class Registry:
    """state/projects.json: [{id, name, path, added}]. The env/CLI default project is always present."""

    def __init__(self, path: str):
        self.path = path
        self.items: dict[str, dict] = {}
        if os.path.exists(path):
            with open(path) as f:
                for p in json.load(f):
                    self.items[p["id"]] = p

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(list(self.items.values()), f, indent=2)
        os.replace(tmp, self.path)

    def add(self, path: str, name: str | None = None) -> dict:
        path = os.path.realpath(os.path.expanduser(path))
        pid = project_id(path)
        if pid not in self.items:
            self.items[pid] = {"id": pid, "name": name or os.path.basename(path), "path": path, "added": time.time()}
            self._save()
        elif name and self.items[pid]["name"] != name:
            self.items[pid]["name"] = name
            self._save()
        return self.items[pid]

    def remove(self, pid: str) -> bool:
        if self.items.pop(pid, None) is None:
            return False
        self._save()
        return True

    def get(self, pid: str) -> dict | None:
        return self.items.get(pid)

    def by_path(self, path: str) -> dict | None:
        return self.items.get(project_id(path))

    def list(self) -> list[dict]:
        return sorted(self.items.values(), key=lambda p: p["added"])
