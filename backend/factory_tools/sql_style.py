"""Configurable SQL style: machine rules (sqlfluff) + a human style guide (markdown).

Discovery order (first hit wins, per kind):
  1. $FACTORY_SQL_STYLE  - a file (.sqlfluff/.cfg/.toml/.ini -> rules, .md -> guide) or a directory holding either
  2. repo `.sqlfluff`                         (rules)
  3. repo `.factory/.sqlfluff`                (rules, written by the UI Settings panel)
  4. repo `.factory/sql_style.md`             (guide, also written by the UI)
  5. repo `.claude/sql_style.md`, `.claude/STYLE.md`, `.claude/style_guide.md`, `.claude/skills/*style*/SKILL.md` (guide)
"Repo" = the task worktree first, then the main project checkout (its .factory/ is git-excluded, so worktrees
don't inherit it). Dialect always follows the active dbt adapter (duckdb, databricks, ...)."""
import os, re, sys, json, glob, shutil, subprocess, configparser

RULE_EXT = (".sqlfluff", ".cfg", ".ini", ".toml")
GUIDE_NAMES = (".factory/sql_style.md", ".claude/sql_style.md", ".claude/STYLE.md", ".claude/style_guide.md")

def _dirs(cwd, project):
    out = []
    for d in (cwd, project):
        if d and os.path.isdir(d) and os.path.abspath(d) not in [os.path.abspath(x) for x in out]: out.append(d)
    return out

def discover(cwd=None, project=None):
    rules = guide = None
    env = os.environ.get("FACTORY_SQL_STYLE")
    if env and os.path.exists(env):
        cands = [env] if os.path.isfile(env) else sorted(glob.glob(os.path.join(env, "*"))) + sorted(glob.glob(os.path.join(env, ".*")))
        for f in cands:
            if not os.path.isfile(f): continue
            if f.endswith(".md") and not guide: guide = {"path": f, "source": "FACTORY_SQL_STYLE"}
            elif (f.endswith(RULE_EXT) or os.path.basename(f) == ".sqlfluff") and not rules: rules = {"path": f, "source": "FACTORY_SQL_STYLE"}
    for d in _dirs(cwd, project):
        if not rules:
            for rel in (".sqlfluff", ".factory/.sqlfluff"):
                if os.path.isfile(os.path.join(d, rel)): rules = {"path": os.path.join(d, rel), "source": f"repo {rel}"}; break
        if not guide:
            for rel in GUIDE_NAMES:
                if os.path.isfile(os.path.join(d, rel)): guide = {"path": os.path.join(d, rel), "source": f"repo {rel}"}; break
        if not guide:
            sk = sorted(glob.glob(os.path.join(d, ".claude/skills/*style*/SKILL.md")))
            if sk: guide = {"path": sk[0], "source": "repo " + os.path.relpath(sk[0], d)}
    if guide:
        try: guide["text"] = open(guide["path"]).read()[:20000]
        except OSError: guide = None
    if rules:
        try: rules["text"] = open(rules["path"]).read()[:20000]
        except OSError: rules = None
    return {"rules": rules, "guide": guide,
            "summary": " + ".join(dict.fromkeys(x["source"] for x in (rules, guide) if x)) or "default (sqlfluff defaults, no guide)"}

def prompt_block(style):
    g = (style or {}).get("guide")
    r = (style or {}).get("rules")
    if not (g or r): return ""
    out = ["\n\n## Team SQL style (from the repo; this wins over generic advice)"]
    if r: out.append(f"Machine rules: sqlfluff config at {r['source']} — the `sql_style` gate lints with it; fix every violation it reports.")
    if g: out.append(f"Style guide ({g['source']}):\n\n{g['text']}")
    return "\n".join(out)

def _sqlfluff_bin():
    return shutil.which("sqlfluff") or (os.path.join(os.path.dirname(sys.executable), "sqlfluff") if os.path.exists(os.path.join(os.path.dirname(sys.executable), "sqlfluff")) else None)

def effective_config(style, cwd, dialect):
    """Write <cwd>/.factory/sqlfluff.cfg: the user's rules + dialect forced to the adapter + templater paths."""
    cp = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=('#', ';')); cp.optionxform = str
    r = (style or {}).get("rules")
    if r and not r["path"].endswith(".toml"):
        try: cp.read_string(r["text"])
        except configparser.Error as ex: raise ValueError(f"invalid sqlfluff config {r['source']}: {ex}")
    if not cp.has_section("sqlfluff"): cp.add_section("sqlfluff")
    cp.set("sqlfluff", "dialect", dialect)
    templater = cp.get("sqlfluff", "templater", fallback="jinja")
    if templater == "dbt":
        try:
            import sqlfluff_templater_dbt  # noqa: F401
        except ImportError:
            templater = "jinja"
    cp.set("sqlfluff", "templater", templater)
    if templater == "dbt":
        sec = "sqlfluff:templater:dbt"
        if not cp.has_section(sec): cp.add_section(sec)
        cp.set(sec, "project_dir", cwd)
        prof = os.path.join(cwd, ".factory")
        if os.path.exists(os.path.join(prof, "profiles.yml")): cp.set(sec, "profiles_dir", prof)
    else:
        sec = "sqlfluff:templater:jinja"
        if not cp.has_section(sec): cp.add_section(sec)
        cp.set(sec, "apply_dbt_builtins", "True")
    os.makedirs(os.path.join(cwd, ".factory"), exist_ok=True)
    path = os.path.join(cwd, ".factory", "sqlfluff.cfg")
    with open(path, "w") as f: cp.write(f)
    return path, templater

def lint(sql_path, cwd, dialect="duckdb", style=None, timeout=120):
    """Return {status, violations:[{line, col, code, name, description}], templater, source}."""
    exe = _sqlfluff_bin()
    style = style if style is not None else discover(cwd)
    if not exe: return {"status": "skip", "violations": [], "detail": "sqlfluff not installed", "source": style["summary"]}
    cfg, templater = effective_config(style, cwd, dialect)
    r = subprocess.run([exe, "lint", sql_path, "--config", cfg, "--format", "json", "--nofail", "--disable-progress-bar"],
                       cwd=cwd, capture_output=True, text=True, timeout=timeout)
    try: data = json.loads(r.stdout[r.stdout.find("["):] or "[]")
    except json.JSONDecodeError:
        return {"status": "warn", "violations": [], "detail": (r.stderr or r.stdout)[-400:], "templater": templater, "source": style["summary"]}
    vs = []
    for f in data:
        for v in f.get("violations", []):
            line = v.get("start_line_no") or v.get("line_no"); col = v.get("start_line_pos") or v.get("line_pos")
            vs.append({"line": line, "col": col, "code": v.get("code"), "name": v.get("name"), "description": v.get("description")})
    parse_errs = [v for v in vs if v["code"] in ("PRS", "TMP")]
    status = "pass" if not vs else ("warn" if parse_errs and len(parse_errs) == len(vs) else "fail")
    return {"status": status, "violations": vs, "templater": templater, "source": style["summary"]}

def save(project, rules_text=None, guide_text=None):
    d = os.path.join(project, ".factory"); os.makedirs(d, exist_ok=True); saved = []
    if rules_text is not None:
        cp = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=('#', ';'))
        try: cp.read_string(rules_text)
        except configparser.Error as ex: raise ValueError(f"not a valid sqlfluff config: {ex}")
        p = os.path.join(d, ".sqlfluff")
        if rules_text.strip(): open(p, "w").write(rules_text); saved.append(p)
        elif os.path.exists(p): os.remove(p)
    if guide_text is not None:
        p = os.path.join(d, "sql_style.md")
        if guide_text.strip(): open(p, "w").write(guide_text); saved.append(p)
        elif os.path.exists(p): os.remove(p)
    return saved
