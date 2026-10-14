"""Adapter-agnostic, read-only data access through dbt (`dbt show --inline`).
Never touches data files: every query runs on the configured dbt target."""

import contextlib
import datetime
import decimal
import json
import os
import re
import shutil
import subprocess
import sys
import threading

import sqlglot
from sqlglot import exp

MAX_LIMIT = int(os.environ.get("FACTORY_MAX_ROWS", "500"))
DEFAULT_TIMEOUT = int(os.environ.get("FACTORY_QUERY_TIMEOUT", "120"))
TOOLS_TARGET = ".factory/target-tools"  # keeps tool runs from clobbering the droid's target/


class QueryError(Exception):
    pass


class ReadOnlyViolation(QueryError):
    pass


def project_dir():
    return os.environ.get("DBT_PROJECT_DIR") or os.getcwd()


def dbt_bin():
    return shutil.which("dbt") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".venv/bin/dbt"
    )


def dialect():
    from adapters import get_adapter

    return get_adapter().dialect


def run_dbt(args, cwd=None, timeout=DEFAULT_TIMEOUT, tools_target=True):
    cwd = cwd or project_dir()
    env = dict(os.environ)
    if os.path.exists(os.path.join(cwd, ".factory", "profiles.yml")):
        env["DBT_PROFILES_DIR"] = os.path.join(cwd, ".factory")  # per-worktree profile always wins
    extra = ["--target-path", TOOLS_TARGET, "--log-path", ".factory/logs-tools"] if tools_target else []
    try:
        return subprocess.run(
            [dbt_bin(), *args, *extra], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise QueryError(f"dbt {args[0]} timed out after {timeout}s")


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _err(p):
    lines = [_ANSI.sub("", l) for l in (p.stdout + "\n" + p.stderr).splitlines() if l.strip()]
    for i, l in enumerate(lines):
        if "Encountered an error" in l or re.search(r"(Runtime|Compilation|Database|Parsing) Error", l):
            return "\n".join(x.strip() for x in lines[i : i + 8])
    keep = [l for l in lines if re.search(r"error|Error|ERROR|not found|does not exist", l)] or lines[-8:]
    return "\n".join(keep[-10:])


# ---------- relation specs ----------
_SPEC = re.compile(r"^(?:source:)?[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)?$")


def rel_jinja(spec: str) -> str:
    """'orders' -> ref('orders'); 'source:jaffle.raw_orders' or 'jaffle.raw_orders' -> source(...)."""
    spec = spec.strip()
    if not _SPEC.match(spec):
        raise QueryError(f"invalid relation spec {spec!r}: use a model name or source:<source>.<table>")
    if spec.startswith("source:") or "." in spec:
        s, t = spec.removeprefix("source:").split(".", 1)
        return f"source('{s}', '{t}')"
    return f"ref('{spec}')"


# ---------- read-only guard for ad-hoc SQL ----------
_JINJA_OK = re.compile(r"\{\{\s*(ref|source)\(\s*'[\w.]+'\s*(,\s*'[\w.]+'\s*)?\)\s*\}\}")
_FILE_FUNCS = {
    "read_csv",
    "read_csv_auto",
    "read_parquet",
    "read_json",
    "read_json_auto",
    "read_text",
    "read_blob",
    "parquet_scan",
    "csv_scan",
    "glob",
    "read_ndjson",
    "read_xlsx",
    "sqlite_scan",
    "postgres_scan",
    "read_files",
}
_FILE_FORMATS = {"csv", "parquet", "json", "delta", "text", "orc", "avro", "binaryfile"}
_WRITE_NODES = tuple(
    getattr(exp, n)
    for n in (
        "Insert",
        "Update",
        "Delete",
        "Create",
        "Drop",
        "Alter",
        "Merge",
        "Command",
        "Copy",
        "Use",
        "Set",
        "Transaction",
        "Commit",
        "Rollback",
        "TruncateTable",
        "Pragma",
        "Grant",
        "Attach",
        "Detach",
        "Install",
        "LoadData",
    )
    if hasattr(exp, n)
)


def validate_select(sql: str, read=None) -> str:
    """Allow exactly one SELECT/WITH/UNION query. Only {{ ref() }} / {{ source() }} jinja is allowed.
    Reject DML/DDL, multiple statements and anything that reads files directly."""
    if re.search(r"\{%|\{#", sql):
        raise ReadOnlyViolation("jinja blocks are not allowed; only {{ ref('x') }} / {{ source('s','t') }}")
    probe = _JINJA_OK.sub("__dbt_rel__", sql)
    if "{{" in probe or "}}" in probe:
        raise ReadOnlyViolation("only {{ ref(...) }} and {{ source(...) }} jinja is allowed")
    try:
        stmts = [s for s in sqlglot.parse(probe, read=read or dialect()) if s is not None]
    except Exception as ex:
        raise ReadOnlyViolation(f"could not parse SQL: {ex}")
    if len(stmts) != 1:
        raise ReadOnlyViolation("exactly one statement is allowed")
    st = stmts[0]
    if not isinstance(st, (exp.Select, exp.Union, exp.Intersect, exp.Except, exp.Subquery)):
        raise ReadOnlyViolation(f"only SELECT queries are allowed (got {type(st).__name__})")
    for node in st.walk():
        if isinstance(node, _WRITE_NODES):
            raise ReadOnlyViolation(f"{type(node).__name__} is not allowed")
        if isinstance(node, (exp.Anonymous, exp.Func)):
            name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if name in _FILE_FUNCS:
                raise ReadOnlyViolation(f"{name}() reads local files; query dbt relations instead")
        if isinstance(node, exp.Table):
            ident = node.this
            raw = ident.this if isinstance(ident, exp.Identifier) else str(ident)
            if isinstance(ident, exp.Literal) or re.search(r"[/\\]|\.(csv|parquet|json|duckdb|db)$", str(raw)):
                raise ReadOnlyViolation(f"table {raw!r} looks like a file path; query dbt relations instead")
            if (node.db or "").lower() in _FILE_FORMATS and not node.catalog:
                raise ReadOnlyViolation(f"{node.db}.`path` file reads are not allowed")
    return sql.strip().rstrip(";")


# ---------- execution ----------

_LOCK = threading.Lock()
_MANIFESTS: dict = {}
INPROC = os.environ.get("FACTORY_DBT_INPROC", "1") == "1"


def _jsonable(v):
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    return v


def _src_mtime(cwd):
    mt = 0
    for root, dirs, files in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in ("target", "logs", ".factory", ".git", "dbt_packages", "node_modules")]
        for f in files:
            if f.endswith((".sql", ".yml", ".yaml", ".csv")):
                mt = max(mt, os.path.getmtime(os.path.join(root, f)))
    return mt


def _show_inproc(sql, limit, target, timeout, cwd):
    """dbt show via dbtRunner in-process with a cached manifest (~3x faster than a subprocess). Same adapter path."""
    from dbt.cli.main import dbtRunner

    cwd = cwd or project_dir()
    common = [
        "--project-dir",
        cwd,
        "--target-path",
        os.path.join(cwd, TOOLS_TARGET),
        "--log-path",
        os.path.join(cwd, ".factory/logs-tools"),
        "--quiet",
    ]
    if os.path.exists(os.path.join(cwd, ".factory", "profiles.yml")):
        common += ["--profiles-dir", os.path.join(cwd, ".factory")]
    if target:
        common += ["--target", target]
    key, mt = (cwd, target), _src_mtime(cwd)
    with _LOCK, contextlib.redirect_stdout(sys.stderr):  # never write to stdout (MCP stdio safety)
        cached = _MANIFESTS.get(key)
        if not cached or cached[0] < mt:
            r = dbtRunner().invoke(["parse", *common])
            if not r.success:
                raise QueryError(f"dbt parse failed: {r.exception}")
            _MANIFESTS[key] = cached = (mt, r.result)
        r = dbtRunner(manifest=cached[1]).invoke(["show", "--inline", sql, "--limit", str(limit), *common])
        # release the duckdb handle so other processes (eval scorer, another worktree) can open the file
        _release_duckdb()
        # dbt adds the inline sql_operation to the shared manifest; drop it so the next call doesn't collide
        try:
            m = cached[1]
            for uid in [u for u in m.nodes if u.startswith("sql_operation.")]:
                m.nodes.pop(uid, None)
        except Exception:
            pass
    if not r.success:
        msg = str(r.exception or "") or (
            str(r.result.results[0].message) if r.result and r.result.results else "dbt show failed"
        )
        raise QueryError(msg.strip()[:1500])
    t = r.result.results[0].agate_table
    return list(t.column_names), [[_jsonable(v) for v in row] for row in t.rows]


def _release_duckdb():
    """Close every dbt-duckdb LocalEnvironment connection held by this process."""
    try:
        from dbt.adapters.duckdb import environments as env

        for attr in ("_ENVIRONMENTS", "ENVIRONMENTS", "_environments"):
            store = getattr(env, attr, None)
            if isinstance(store, dict):
                for e in list(store.values()):
                    try:
                        e.close()
                    except Exception:
                        pass
                store.clear()
                return
        # fall back: walk modules for LocalEnvironment instances with .conn
        import gc

        from dbt.adapters.duckdb.environments.local import LocalEnvironment

        for o in gc.get_objects():
            if isinstance(o, LocalEnvironment):
                try:
                    o.close()
                except Exception:
                    pass
    except Exception:
        pass


def show(sql: str, limit: int = 50, target: str | None = None, timeout: int = DEFAULT_TIMEOUT, cwd=None) -> dict:
    """Run trusted SQL (may contain jinja) via `dbt show --inline`, LIMIT enforced by dbt."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    if INPROC:
        cols, rows = _show_inproc(sql, limit, target, timeout, cwd)
        return {
            "columns": cols,
            "rows": rows,
            "row_count": len(rows),
            "limit": limit,
            "truncated": len(rows) >= limit,
            "target": target or "dev",
        }
    args = ["show", "--inline", sql, "--limit", str(limit), "--output", "json", "--quiet"]
    if target:
        args += ["--target", target]
    p = run_dbt(args, cwd=cwd, timeout=timeout)
    if p.returncode != 0:
        raise QueryError(_err(p) or "dbt show failed")
    out = p.stdout[p.stdout.find("{") :]
    try:
        rows = json.loads(out)["show"]
    except Exception:
        raise QueryError("could not parse dbt show output: " + p.stdout[-500:])
    cols = list(rows[0].keys()) if rows else []
    return {
        "columns": cols,
        "rows": [[r.get(c) for c in cols] for r in rows],
        "row_count": len(rows),
        "limit": limit,
        "truncated": len(rows) >= limit,
        "target": target or "dev",
    }


def query(sql: str, limit: int = 50, target: str | None = None, timeout: int = 60, cwd=None) -> dict:
    """Ad-hoc read-only SELECT (validated) with enforced LIMIT and timeout."""
    return show(validate_select(sql), limit=limit, target=target, timeout=min(int(timeout), DEFAULT_TIMEOUT), cwd=cwd)


def sample(relation: str, limit: int = 20, target: str | None = None, cwd=None) -> dict:
    return {
        "relation": relation,
        **show(f"select * from {{{{ {rel_jinja(relation)} }}}}", limit=limit, target=target, cwd=cwd),
    }
