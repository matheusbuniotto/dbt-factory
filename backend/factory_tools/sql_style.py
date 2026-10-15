"""Configurable SQL style: machine rules (sqlfluff) + a human style guide (markdown).

Discovery order (first hit wins, per kind):
  1. $FACTORY_SQL_STYLE  - a file (.sqlfluff/.cfg/.toml/.ini -> rules, .md -> guide) or a directory holding either
  2. repo `.factory/config.yml` key `sql_style:` - a path (file/dir, relative to the repo) or {rules: path, guide: path}
  3. repo `.sqlfluff`                         (rules)
  4. repo `.factory/.sqlfluff`                (rules, committed)
  5. repo `.factory/sql_style.md`             (guide, committed)
  6. repo `.claude/sql_style.md`, `.claude/STYLE.md`, `.claude/style_guide.md`, `.claude/skills/*style*/SKILL.md` (guide)
  7. style saved from the UI for that project: <state>/style/<project id>/{.sqlfluff, sql_style.md} (never in the repo)
"Repo" = each task's own dirs, in order: the task dir (dbt sub-dir of the worktree), the worktree root, then that
task's project (dbt dir, repo root), read from <task>/.factory/project.json. Dialect follows the task's project."""

import configparser
import glob
import json
import os
import shutil
import subprocess
import sys

import yaml

from . import project_ctx as P

STATE = os.path.realpath(
    os.environ.get("FACTORY_STATE_DIR") or os.path.join(os.path.dirname(__file__), "..", "..", "state")
)

RULE_EXT = (".sqlfluff", ".cfg", ".ini", ".toml")
GUIDE_NAMES = (".factory/sql_style.md", ".claude/sql_style.md", ".claude/STYLE.md", ".claude/style_guide.md")
MAX_TEXT = 20000


def saved_dir(project_id):
    """Where the UI saves a project's style (factory state, so the user's repo is never written)."""
    return os.path.join(STATE, "style", project_id) if project_id else None


def task_dirs(cwd):
    """Lookup dirs for a task: task dir, worktree root, then its project's dbt dir and repo root."""
    ctx = P.load(cwd) if cwd else {}
    keys = ("worktree_root", "project_dir", "project_root")
    return [cwd, *(ctx.get(k) for k in keys)], ctx.get("project_id")


def _dirs(*dirs):
    out: list[str] = []
    for d in dirs:
        if d and os.path.isdir(d) and os.path.abspath(d) not in [os.path.abspath(x) for x in out]:
            out.append(d)
    return out


def _kind(path):
    if path.endswith(".md"):
        return "guide"
    if path.endswith(RULE_EXT) or os.path.basename(path) == ".sqlfluff":
        return "rules"
    return None


def _from_path(path, source, found):
    """Fill `found` (rules/guide) from a file or every file in a directory."""
    if not path or not os.path.exists(path):
        return
    cands = (
        [path]
        if os.path.isfile(path)
        else sorted(glob.glob(os.path.join(path, "*")) + glob.glob(os.path.join(path, ".*")))
    )
    for f in cands:
        k = _kind(f) if os.path.isfile(f) else None
        if k and not found.get(k):
            found[k] = {"path": f, "source": source}


def _from_config(d, found):
    cfg_p = os.path.join(d, ".factory", "config.yml")
    if not os.path.isfile(cfg_p):
        return
    try:
        with open(cfg_p) as fh:
            spec = (yaml.safe_load(fh) or {}).get("sql_style")
    except (OSError, yaml.YAMLError, AttributeError):
        return
    src = "repo .factory/config.yml"
    if isinstance(spec, str):
        _from_path(os.path.join(d, spec), src, found)
    elif isinstance(spec, dict):
        for k in ("rules", "guide"):
            p = os.path.join(d, spec[k]) if spec.get(k) else None
            if p and os.path.isfile(p) and not found.get(k):
                found[k] = {"path": p, "source": src}


def _from_repo(d, found):
    if not found.get("rules"):
        rel = next((r for r in (".sqlfluff", ".factory/.sqlfluff") if os.path.isfile(os.path.join(d, r))), None)
        if rel:
            found["rules"] = {"path": os.path.join(d, rel), "source": f"repo {rel}"}
    if not found.get("guide"):
        rel = next((r for r in GUIDE_NAMES if os.path.isfile(os.path.join(d, r))), None)
        sk = sorted(glob.glob(os.path.join(d, ".claude/skills/*style*/SKILL.md")))
        if rel:
            found["guide"] = {"path": os.path.join(d, rel), "source": f"repo {rel}"}
        elif sk:
            found["guide"] = {"path": sk[0], "source": "repo " + os.path.relpath(sk[0], d)}


def _with_text(item):
    if not item:
        return None
    try:
        with open(item["path"]) as fh:
            return {**item, "text": fh.read()[:MAX_TEXT]}
    except OSError:
        return None


def _from_saved(project_id, found):
    d = saved_dir(project_id)
    for kind, name in (("rules", ".sqlfluff"), ("guide", "sql_style.md")):
        p = os.path.join(d, name) if d else None
        if p and os.path.isfile(p) and not found.get(kind):
            found[kind] = {"path": p, "source": "factory settings"}


def discover(cwd=None, project=None, project_id=None):
    """Style for a task (cwd = its task dir) or, with cwd=None, for a project (`project` = its repo root)."""
    found: dict = {}
    dirs, ctx_pid = task_dirs(cwd)
    _from_path(os.environ.get("FACTORY_SQL_STYLE"), "FACTORY_SQL_STYLE", found)
    for d in _dirs(*dirs, project):
        _from_config(d, found)
        _from_repo(d, found)
    _from_saved(project_id or ctx_pid, found)
    rules, guide = _with_text(found.get("rules")), _with_text(found.get("guide"))
    summary = " + ".join(dict.fromkeys(x["source"] for x in (rules, guide) if x))
    return {"rules": rules, "guide": guide, "summary": summary or "default (sqlfluff defaults, no guide)"}


def prompt_block(style):
    g = (style or {}).get("guide")
    r = (style or {}).get("rules")
    if not (g or r):
        return ""
    out = ["\n\n## Team SQL style (from the repo; this wins over generic advice)"]
    if r:
        out.append(
            f"Machine rules: sqlfluff config at {r['source']} — the `sql_style` gate lints with it; fix every violation it reports."
        )
    if g:
        out.append(f"Style guide ({g['source']}):\n\n{g['text']}")
    return "\n".join(out)


def _sqlfluff_bin():
    local = os.path.join(os.path.dirname(sys.executable), "sqlfluff")
    return shutil.which("sqlfluff") or (local if os.path.exists(local) else None)


def _new_parser():
    cp = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=("#", ";"))
    cp.optionxform = str  # type: ignore[assignment,method-assign]
    return cp


def _section(cp, name):
    if not cp.has_section(name):
        cp.add_section(name)
    return name


def _templater(cp):
    templater = cp.get("sqlfluff", "templater", fallback="jinja")
    if templater == "dbt":
        try:
            import sqlfluff_templater_dbt  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            templater = "jinja"
    return templater


def effective_config(style, cwd, dialect):
    """Write <cwd>/.factory/sqlfluff.cfg: the user's rules + dialect forced to the adapter + templater paths."""
    cp = _new_parser()
    r = (style or {}).get("rules")
    if r and not r["path"].endswith(".toml"):
        try:
            cp.read_string(r["text"])
        except configparser.Error as ex:
            raise ValueError(f"invalid sqlfluff config {r['source']}: {ex}") from ex
    _section(cp, "sqlfluff")
    cp.set("sqlfluff", "dialect", dialect)
    templater = _templater(cp)
    cp.set("sqlfluff", "templater", templater)
    if templater == "dbt":
        sec = _section(cp, "sqlfluff:templater:dbt")
        cp.set(sec, "project_dir", cwd)
        prof = os.path.join(cwd, ".factory")
        if os.path.exists(os.path.join(prof, "profiles.yml")):
            cp.set(sec, "profiles_dir", prof)
    else:
        cp.set(_section(cp, "sqlfluff:templater:jinja"), "apply_dbt_builtins", "True")
    os.makedirs(os.path.join(cwd, ".factory"), exist_ok=True)
    path = os.path.join(cwd, ".factory", "sqlfluff.cfg")
    with open(path, "w") as f:
        cp.write(f)
    return path, templater


def _violations(data):
    vs = []
    for f in data:
        for v in f.get("violations", []):
            vs.append(
                {
                    "line": v.get("start_line_no") or v.get("line_no"),
                    "col": v.get("start_line_pos") or v.get("line_pos"),
                    "code": v.get("code"),
                    "name": v.get("name"),
                    "description": v.get("description"),
                }
            )
    return vs


def lint(sql_path, cwd, dialect="duckdb", style=None, timeout=120):
    """Return {status, violations:[{line, col, code, name, description}], templater, source}."""
    exe = _sqlfluff_bin()
    style = style if style is not None else discover(cwd)
    if not exe:
        return {"status": "skip", "violations": [], "detail": "sqlfluff not installed", "source": style["summary"]}
    cfg, templater = effective_config(style, cwd, dialect)
    argv = [exe, "lint", sql_path, "--config", cfg, "--format", "json", "--nofail", "--disable-progress-bar"]
    r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    base = {"templater": templater, "source": style["summary"]}
    try:
        data = json.loads(r.stdout[r.stdout.find("[") :] or "[]")
    except json.JSONDecodeError:
        return {"status": "warn", "violations": [], "detail": (r.stderr or r.stdout)[-400:], **base}
    vs = _violations(data)
    parse_errs = [v for v in vs if v["code"] in ("PRS", "TMP")]
    status = "pass" if not vs else ("warn" if len(parse_errs) == len(vs) else "fail")
    return {"status": status, "violations": vs, **base}


def _write_or_remove(path, text):
    if text.strip():
        with open(path, "w") as fh:
            fh.write(text)
        return [path]
    if os.path.exists(path):
        os.remove(path)
    return []


def save(project_id, rules_text=None, guide_text=None):
    d = saved_dir(project_id)
    os.makedirs(d, exist_ok=True)
    saved = []
    if rules_text is not None:
        try:
            _new_parser().read_string(rules_text)
        except configparser.Error as ex:
            raise ValueError(f"not a valid sqlfluff config: {ex}") from ex
        saved += _write_or_remove(os.path.join(d, ".sqlfluff"), rules_text)
    if guide_text is not None:
        saved += _write_or_remove(os.path.join(d, "sql_style.md"), guide_text)
    return saved
