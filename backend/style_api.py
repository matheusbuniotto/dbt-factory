"""SQL style API: per-project style; UI edits are saved in factory state, never in the repo (see factory_tools/sql_style.py)."""

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from factory_tools import project_ctx as P
from factory_tools import sql_style as STYLE

router = APIRouter()
ORDER = [
    "$FACTORY_SQL_STYLE",
    "repo .factory/config.yml sql_style",
    "repo .sqlfluff / .factory/.sqlfluff",
    "repo .factory/sql_style.md / .claude/ style guide",
    "factory settings (saved here)",
]


def _project(project_id):
    """(id, repo root, dialect) of a registered project; default project when no id."""
    import project_api as PAPI  # lazy: project_api mounts this router

    entry = PAPI.REGISTRY.get(project_id or PAPI.default_project_id() or "")
    if not entry:
        raise HTTPException(404, "unknown project")
    pid = entry["id"]  # the registry's own id, not the request string
    det = PAPI.detect_project(pid)
    return pid, det.get("git_root") or det["path"], det.get("dialect") or "ansi"


def style_caps(cwd, project_id=None):
    """Capabilities line for a task (cwd = task dir; its project comes from .factory/project.json)."""
    st = STYLE.discover(cwd, project_id=project_id)
    return {
        "summary": st["summary"],
        "rules": (st["rules"] or {}).get("source"),
        "guide": (st["guide"] or {}).get("source"),
        "dialect": P.dialect(cwd) if cwd else None,
    }


class StyleIn(BaseModel):
    sqlfluff: str | None = None  # sqlfluff ini text; "" removes the saved one
    guide: str | None = None  # markdown; "" removes


@router.get("/api/style")
def get_style(project_id: str | None = None):
    pid, root, dialect = _project(project_id)
    st = STYLE.discover(None, root, project_id=pid)
    return {
        "project_id": pid,
        "summary": st["summary"],
        "rules": st["rules"],
        "guide": st["guide"],
        "dialect": dialect,
        "order": ORDER,
        "env": os.environ.get("FACTORY_SQL_STYLE"),
    }


@router.put("/api/style")
def put_style(body: StyleIn, project_id: str | None = None):
    pid, _root, _d = _project(project_id)
    try:
        saved = STYLE.save(pid, body.sqlfluff, body.guide)
    except ValueError as ex:
        raise HTTPException(400, str(ex)) from ex
    return {"saved": [os.path.basename(p) for p in saved], **get_style(pid)}
