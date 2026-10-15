"""Definition-of-Done gates: code + data. Pure code checks don't touch the warehouse.
Data checks go through the dbt target. Status: pass | fail | warn | skip | waived."""

import os
import re

from . import dbt_tools as D
from . import quality as Q
from .warehouse import _release_duckdb

LAYER = re.compile(r"^(stg_|int_|fct_|dim_|mart_|rpt_|customers|orders|payments)")
SELECT_STAR = re.compile(r"(?is)\bselect\s+\*")
HARD_SCHEMA = re.compile(r"(?is)\b(?:from|join)\s+(?:[\w\"`]+\.){1,2}[\w\"`]+")  # schema.table (not {{)
REF_OR_SOURCE = re.compile(r"\{\{\s*(ref|source)\s*\(")


def _file(cwd, path):
    p = os.path.join(cwd, path)
    return open(p).read() if os.path.exists(p) else None


def code_gates(model, cwd=None, lint=True):
    cwd = cwd or os.getcwd()
    checks = []

    def add(id, status, detail, **extra):
        checks.append({"id": id, "status": status, "detail": detail, "group": "code", **extra})

    # compile + build for the model and its tests
    try:
        D.compile_model(model, cwd=cwd)
        add("dbt_compile", "pass", f"{model} compiles")
    except Exception as ex:
        add("dbt_compile", "fail", str(ex)[:300])
        return _pack(model, checks)
    try:
        b = D.build(f"{model}+", cwd=cwd)
        add(
            "dbt_build",
            "pass" if b["success"] else "fail",
            f"{b['summary']} in {b['elapsed']}s"
            + (f"; failed: {[f['unique_id'] for f in b['failed'][:5]]}" if b["failed"] else ""),
            summary=b["summary"],
            failed=b.get("failed"),
        )
    except Exception as ex:
        add("dbt_build", "fail", str(ex)[:300])
    # docs + tests
    try:
        docs = D.docs(model, cwd=cwd)
        cols = docs.get("columns") or []
        tests = docs.get("tests") or []
        undoc = [c["name"] for c in cols if not (c.get("description") or "").strip()]
        if not docs.get("description"):
            add("docs_and_tests", "fail", "model has no description")
        elif not cols:
            add("docs_and_tests", "fail", "model has no column docs in yml")
        elif not tests:
            add("docs_and_tests", "fail", "no tests on the model or its columns")
        elif undoc:
            add("docs_and_tests", "warn", f"{len(undoc)} columns without description: {', '.join(undoc[:6])}")
        else:
            add("docs_and_tests", "pass", f"{len(cols)} columns documented, {len(tests)} tests")
        # grain declared
        g = Q.declared_grain(model, cwd=cwd)
        add(
            "grain_declared",
            "pass" if g else "fail",
            f"grain={g}" if g else "declare meta.grain or put unique+not_null on the key",
        )
    except Exception as ex:
        add("docs_and_tests", "fail", str(ex)[:200])
        g = None
    # naming / layer
    add(
        "naming_layer",
        "pass" if LAYER.match(model) else "fail",
        f"{model} matches stg_/int_/fct_/dim_/mart_ (or known mart)"
        if LAYER.match(model)
        else f"{model}: rename to stg_/int_/fct_/dim_/mart_*",
    )
    # SQL style
    try:
        node = D._find(D._manifest(cwd), model)
        raw = node.get("raw_code") or ""
        # allow `select * from {{ ref/source }}` in CTEs; flag other SELECT *
        bad_star = [m.group(0) for m in re.finditer(r"(?is)select\s+\*\s+from\s+(?!\{\{\s*(?:ref|source)\b)", raw)]
        if bad_star:
            add("no_select_star", "fail", "SELECT * of a non-ref/source: list columns explicitly")
        else:
            add("no_select_star", "pass", "no bare SELECT * (ref/source * in CTEs is OK)")
        # hardcoded schemas: from/join of identifier.identifier outside jinja
        cleaned = re.sub(r"\{\{.*?\}\}", " REF ", raw, flags=re.S)
        HARD_SCHEMA.findall(cleaned)
        # ignore CTEs (with x as) and simple table refs without dots after strip
        hard = [
            h
            for h in re.finditer(r"(?is)\b(?:from|join)\s+((?:[\w\"`]+\.){1,2}[\w\"`]+)", cleaned)
            if not h.group(1).lower().startswith(("information_schema.", "pg_catalog."))
        ]
        if hard:
            add(
                "ref_source_only",
                "fail",
                f"hardcoded relation(s): {', '.join(h.group(1) for h in hard[:4])}; use ref()/source()",
            )
        elif not REF_OR_SOURCE.search(raw) and "seed" not in (D.docs(model, cwd=cwd).get("depends_on") or [""])[0]:
            # models that only select from CTEs of literals are fine for unit tests; otherwise expect refs
            add("ref_source_only", "warn", "no ref()/source() found (is this intentional?)")
        else:
            add("ref_source_only", "pass", "uses ref()/source()")
    except Exception as ex:
        add("no_select_star", "skip", str(ex)[:120])
        add("ref_source_only", "skip", str(ex)[:120])
    if lint:
        _style_check(model, cwd, add)
    return _pack(model, checks)


def _style_check(model, cwd, add):
    """SQL style: the repo/task style config (sqlfluff rules) linted with the active adapter's dialect."""
    from adapters import get_adapter

    from . import sql_style as ST

    try:
        try:
            sql_path = D._find(D._manifest(cwd), model).get("original_file_path") or f"models/{model}.sql"
        except Exception:
            sql_path = f"models/{model}.sql"
        dialect = getattr(get_adapter(), "dialect", "duckdb")
        res = ST.lint(sql_path, cwd, dialect=dialect, style=ST.discover(cwd, os.environ.get("DBT_PROJECT")))
        vs = res["violations"]
        tag = f"[{res['source']}, templater={res.get('templater')}]"
        if vs:
            detail = f"{len(vs)} violation(s) {tag}: " + "; ".join(
                f"L{v['line']} {v['code']} {v['description']}" for v in vs[:8]
            )
        else:
            detail = res.get("detail") or f"clean {tag}"
        add("sql_style", res["status"], detail, violations=vs, path=sql_path, source=res["source"])
    except Exception as ex:
        add("sql_style", "skip", str(ex)[:160])


def data_gates(model, grain=None, measures=None, dimensions=None, reference_sql=None, waivers=None, cwd=None, **kw):
    waivers = waivers or {}
    gate = Q.data_quality_gate(
        model, grain=grain, measures=measures, dimensions=dimensions, reference_sql=reference_sql, cwd=cwd, **kw
    )
    checks = []
    for c in gate["checks"]:
        c = dict(c, group="data")
        if c["id"] in waivers and c["status"] == "fail":
            c["status"] = "waived"
            c["detail"] = f"WAIVED: {waivers[c['id']]} · was: {c['detail']}"
        checks.append(c)
    return _pack(model, checks, grain=gate.get("grain"), measures=gate.get("measures"))


def run_gates(model, waivers=None, skip_data=False, cwd=None, **data_kw):
    code = code_gates(model, cwd=cwd)
    data = (
        {"checks": [], "passed": True, "summary": {}}
        if skip_data
        else data_gates(model, waivers=waivers, cwd=cwd, **data_kw)
    )
    checks = code["checks"] + data["checks"]
    try:
        _release_duckdb()
    except Exception:
        pass
    return _pack(model, checks, grain=data.get("grain") or code.get("grain"), measures=data.get("measures"))


def _pack(model, checks, **extra):
    failed = [c["id"] for c in checks if c["status"] == "fail"]
    summary = {s: sum(c["status"] == s for c in checks) for s in ("pass", "fail", "warn", "skip", "waived")}
    return {"model": model, "passed": not failed, "failed": failed, "summary": summary, "checks": checks, **extra}


# extract waivers from agent text: <waiver id="row_count_delta">reason</waiver>
WAIVER_RE = re.compile(r'<waiver\s+id=["\']([\w]+)["\']\s*>(.*?)</waiver>', re.S | re.I)


def parse_waivers(events_text: str) -> dict:
    return {m.group(1): m.group(2).strip() for m in WAIVER_RE.finditer(events_text or "")}
