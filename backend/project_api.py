"""Project registry API: register local repos, detect their setup, and prepare per-task worktrees.
Mounted by main.py. The user's working tree is never modified: tasks use git worktrees of their repo."""

import json
import os
import subprocess
import tempfile

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import projects as PJ

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.realpath(os.environ.get("FACTORY_STATE_DIR") or f"{ROOT}/state")
os.makedirs(STATE, exist_ok=True)
router = APIRouter()


def has_running_tasks(pid: str) -> bool:  # replaced by main.py
    return False


def allowed_roots() -> list[str]:
    """Where repos may be registered from (FACTORY_ALLOWED_ROOTS, os.pathsep-separated). Default: $HOME, the folder
    containing dbt-factory, and the temp dir. Keeps the API from being pointed at arbitrary system paths."""
    env = os.environ.get("FACTORY_ALLOWED_ROOTS")
    roots = env.split(os.pathsep) if env else [os.path.expanduser("~"), os.path.dirname(ROOT), tempfile.gettempdir()]
    return [os.path.realpath(r) for r in roots if r]


def safe_path(raw: str) -> str:
    """Normalise a user-supplied path and require it to live under an allowed root."""
    path = os.path.normpath(os.path.realpath(os.path.expanduser(raw.strip())))
    root = next((r for r in allowed_roots() if path == r or path.startswith(r.rstrip(os.sep) + os.sep)), None)
    if root is None or not path.startswith(root):
        raise HTTPException(
            400,
            {
                "message": "path outside allowed roots",
                "errors": [f"{path} is not under {allowed_roots()} (set FACTORY_ALLOWED_ROOTS)"],
            },
        )
    return path


def _sh(argv, cwd):
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)


# The default project comes from FACTORY_PROJECT (or `./run.sh --project PATH`); the bundled demo is only a fallback.
DEMO_PROJECT = f"{ROOT}/projects/jaffle_shop"
DEFAULT_PROJECT = os.path.realpath(
    os.path.expanduser(os.environ.get("FACTORY_PROJECT") or os.environ.get("DBT_PROJECT") or DEMO_PROJECT)
)
PROJECTS_FILE = f"{STATE}/projects.json"
REGISTRY = PJ.Registry(PROJECTS_FILE)
if os.path.isdir(DEFAULT_PROJECT):
    REGISTRY.add(DEFAULT_PROJECT)
DETECT_CACHE: dict = {}
# never committed / diffed from a task worktree
EXCLUDE_PATHSPEC = [
    ":(exclude).factory",
    ":(exclude)target",
    ":(exclude)logs",
    ":(exclude)dbt_packages",
    ":(exclude)*.duckdb*",
]


def detect_project(pid, refresh=False):
    p = REGISTRY.get(pid)
    if not p:
        raise HTTPException(404, "unknown project")
    if refresh or pid not in DETECT_CACHE:
        DETECT_CACHE[pid] = {**PJ.detect(p["path"]), "id": pid, "name": p["name"]}
    return DETECT_CACHE[pid]


def default_project_id():
    p = REGISTRY.by_path(DEFAULT_PROJECT)
    return p["id"] if p else (REGISTRY.list()[0]["id"] if REGISTRY.list() else None)


class ProjectIn(BaseModel):
    path: str
    name: str | None = None


def _project_public(p):
    d = detect_project(p["id"])
    keys = (
        "mode",
        "git",
        "git_root",
        "subdir",
        "head",
        "dbt_dir_rel",
        "dbt_projects",
        "dbt_name",
        "profile",
        "profiles_path",
        "profiles_source",
        "adapter",
        "adapter_installed",
        "dialect",
        "targets",
        "dev_target",
        "prod_target",
        "dbt_version",
        "dbt_version_required",
        "dbt_version_ok",
        "sql_files",
        "bootstrap",
        "errors",
        "warnings",
    )
    cfg = {k: v for k, v in (d.get("config") or {}).items() if not k.startswith("_")}
    return {
        **p,
        **{k: d.get(k) for k in keys},
        "config": cfg,
        "default": p["path"] == DEFAULT_PROJECT,
        "ready": not d["errors"],
    }


@router.get("/api/projects")
def list_projects(refresh: bool = False):
    if refresh:
        DETECT_CACHE.clear()
    return [_project_public(p) for p in REGISTRY.list()]


@router.post("/api/projects")
def add_project(body: ProjectIn):
    path = safe_path(body.path)
    det = PJ.detect(path)
    if det["mode"] == "unsupported" or not det.get("git"):
        raise HTTPException(400, {"message": "cannot use this path", "errors": det["errors"]})
    p = REGISTRY.add(path, body.name)
    DETECT_CACHE.pop(p["id"], None)
    return _project_public(p)


@router.get("/api/projects/{pid}")
def get_project(pid: str, refresh: bool = False):
    detect_project(pid, refresh=refresh)
    return _project_public(REGISTRY.get(pid))


@router.delete("/api/projects/{pid}")
def remove_project(pid: str):
    p = REGISTRY.get(pid)
    if not p:
        raise HTTPException(404)
    if has_running_tasks(pid):
        raise HTTPException(409, "project has running tasks")
    REGISTRY.remove(pid)  # only forgets it; never touches the repo or its tasks' branches
    DETECT_CACHE.pop(pid, None)
    return {"removed": pid}


def resolve_project(project: str | None, project_id: str | None) -> dict:
    """Project for a new task: an explicit path (registered on the fly), a registered id, or the default."""
    if project:
        path = safe_path(project if os.path.isabs(project) else os.path.join(ROOT, project))
        det = PJ.detect(path)
        if det["mode"] == "unsupported" or not det.get("git"):
            raise HTTPException(400, {"message": "project not usable", "errors": det["errors"]})
        pid = REGISTRY.add(det["path"])["id"]
    else:
        pid = project_id or default_project_id()
    if not pid:
        raise HTTPException(400, "no project configured: set FACTORY_PROJECT or add one in the UI")
    det = detect_project(pid, refresh=True)
    if det["errors"]:
        raise HTTPException(400, {"message": f"project '{det['name']}' is not ready", "errors": det["errors"]})
    return det


def prepare_worktree(det, tid, branch, wt_root):
    """git worktree of the user's repo (their working tree is never modified); returns (wt_root, task_dir)."""
    root = det["git_root"]
    wt = f"{wt_root}/{tid}"
    r = _sh(["git", "worktree", "add", "-b", branch, wt, "HEAD"], root)
    if r.returncode:
        raise HTTPException(500, r.stderr)
    rel = os.path.relpath(det["dbt_dir"] if det["mode"] == "dbt" else det["path"], root)
    task_dir = os.path.normpath(os.path.join(wt, rel))
    os.makedirs(f"{task_dir}/.factory", exist_ok=True)
    with open(f"{task_dir}/.factory/.gitignore", "w") as f:
        f.write("# dbt-factory scratch (profiles, dev warehouse, logs): never committed\n*\n")
    with open(f"{task_dir}/.factory/project.json", "w") as f:
        json.dump(PJ.task_context(det), f, indent=2)
    if det["mode"] == "dbt":
        try:
            prof = PJ.render_task_profile(det, tid, task_dir)
        except PJ.ProjectError as ex:
            _sh(["git", "worktree", "remove", "--force", wt], root)
            raise HTTPException(400, str(ex))
        with open(f"{task_dir}/.factory/profiles.yml", "w") as f:
            f.write(prof)
    return wt, task_dir
