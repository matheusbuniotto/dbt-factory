"""SQL style API: project-level style persisted to <project>/.factory/ (see factory_tools/sql_style.py)."""

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from adapters import get_adapter
from factory_tools import sql_style as STYLE

router = APIRouter()
ORDER = [
    "$FACTORY_SQL_STYLE",
    ".factory/config.yml sql_style",
    "repo .sqlfluff",
    "repo .factory/.sqlfluff",
    "repo .factory/sql_style.md",
    "repo .claude/ style guide",
]


def _project():
    return os.environ.get("DBT_PROJECT")


def _dialect():
    return getattr(get_adapter(), "dialect", "duckdb")


def style_caps(cwd, project):
    st = STYLE.discover(cwd, project)
    return {
        "summary": st["summary"],
        "rules": (st["rules"] or {}).get("source"),
        "guide": (st["guide"] or {}).get("source"),
        "dialect": _dialect(),
    }


class StyleIn(BaseModel):
    sqlfluff: str | None = None  # sqlfluff ini text; "" removes the saved one
    guide: str | None = None  # markdown; "" removes


@router.get("/api/style")
def get_style():
    st = STYLE.discover(None, _project())
    return {
        "summary": st["summary"],
        "rules": st["rules"],
        "guide": st["guide"],
        "dialect": _dialect(),
        "order": ORDER,
        "env": os.environ.get("FACTORY_SQL_STYLE"),
    }


@router.put("/api/style")
def put_style(body: StyleIn):
    try:
        saved = STYLE.save(_project(), body.sqlfluff, body.guide)
    except ValueError as ex:
        raise HTTPException(400, str(ex)) from ex
    return {"saved": saved, **get_style()}
