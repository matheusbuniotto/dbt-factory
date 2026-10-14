"""Scoring for eval cases. All data checks run through the dbt target (factory_tools.warehouse)."""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
from factory_tools import dbt_tools as D
from factory_tools import quality as Q
from factory_tools import warehouse as W


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def close(a, b, tol=0.0):
    fa, fb = _num(a), _num(b)
    if fa is not None and fb is not None:
        return abs(fa - fb) <= tol * max(abs(fa), abs(fb), 1e-9) + 1e-9
    return str(a) == str(b)


def _scalar(sql, cwd):
    # trusted eval SQL may contain {{ ref() }}; go through show, not the ad-hoc validator
    r = W.show(sql, limit=1, cwd=cwd)
    return r["rows"][0][0] if r["rows"] else None


def _rows(sql, cwd, limit=500):
    r = W.show(sql, limit=limit, cwd=cwd)
    return r["columns"], r["rows"]


def code_assertions(case, model, cwd):
    out = []
    c = case.get("code") or {}

    def add(name, ok, detail=""):
        out.append({"kind": "code", "name": name, "passed": bool(ok), "detail": detail})

    # model exists + compiles
    try:
        D.compile_model(model, cwd=cwd)
        add("model compiles", True, model)
    except Exception as ex:
        add("model compiles", False, str(ex)[:200])
        return out
    cols = []
    try:
        cols = W.sample(model, 1, cwd=cwd)["columns"]
    except Exception as ex:
        add("model queryable", False, str(ex)[:200])
    for col in c.get("required_columns", []):
        add(f"has column {col}", col in cols, f"columns: {', '.join(cols)}")
    if c.get("grain"):
        try:
            g = Q.declared_grain(model, cwd=cwd) or []
        except Exception:
            g = []
        add("declares expected grain", sorted(g) == sorted(c["grain"]), f"declared={g} expected={c['grain']}")
    try:
        raw = D._find(D._manifest(cwd), model).get("raw_code") or ""
        add("no bare select *", not re.search(r"(?is)select\s+\*\s+from\s+(?!\{\{\s*(?:ref|source))", raw))
    except Exception:
        pass
    return out


def data_assertions(case, model, cwd):
    out = []
    for a in case.get("data") or []:
        name = a.get("name", "assertion")
        tol = float(a.get("tolerance", 0))
        try:
            if "row_count" in a:
                got = _scalar(f"select count(*) as v from {{{{ ref('{model}') }}}}", cwd)
                exp = a["row_count"]
            else:
                got = _scalar(a["query"].replace("{model}", model), cwd)
                exp = (
                    _scalar(a["expect_query"].replace("{model}", model), cwd)
                    if "expect_query" in a
                    else a.get("expect")
                )
            out.append(
                {"kind": "data", "name": name, "passed": close(got, exp, tol), "detail": f"got {got} expected {exp}"}
            )
        except Exception as ex:
            out.append(
                {"kind": "data", "name": name, "passed": False, "detail": f"{type(ex).__name__}: {str(ex)[:200]}"}
            )
    g = case.get("golden")
    if g:
        out.append(golden(model, g, cwd))
    return out


def golden(model, g, cwd):
    """Golden query equivalence: agent model vs reference SELECT, both through the adapter, keyed and tolerant."""
    cols = g["columns"]
    key = g["key"]
    tol = float(g.get("tolerance", 0))
    sel = ", ".join(cols)
    try:
        _, a = _rows(f"select {sel} from {{{{ ref('{model}') }}}}", cwd)
        # reference_sql is a full SELECT (may contain {{ ref }}); wrap as CTE
        _, b = _rows(f"with ref_q as ({g['reference_sql']}) select {sel} from ref_q", cwd)
    except Exception as ex:
        return {
            "kind": "golden",
            "name": "golden query equivalence",
            "passed": False,
            "detail": f"{type(ex).__name__}: {str(ex)[:200]}",
            "weight": 2,
        }
    ki = [cols.index(k) for k in key]

    def norm(r):
        return tuple(str(r[i]) for i in ki)

    A_, B_ = {norm(r): r for r in a}, {norm(r): r for r in b}
    missing, extra, diff = set(B_) - set(A_), set(A_) - set(B_), []
    for k in set(A_) & set(B_):
        for j, c in enumerate(cols):
            if j in ki:
                continue
            if not close(A_[k][j], B_[k][j], tol):
                diff.append({"key": k, "column": c, "got": A_[k][j], "expected": B_[k][j]})
    ok = not missing and not extra and not diff
    detail = f"{len(A_)} vs {len(B_)} rows; missing {len(missing)}, extra {len(extra)}, mismatched cells {len(diff)}"
    if diff:
        detail += f"; e.g. {diff[0]}"
    return {"kind": "golden", "name": "golden query equivalence", "passed": ok, "detail": detail, "weight": 2}


def gate_rate(gate):
    if not gate:
        return None
    cs = [c for c in gate.get("checks", []) if c["status"] != "skip"]
    if not cs:
        return None
    pts = sum(1.0 if c["status"] == "pass" else 0.5 if c["status"] in ("waived", "warn") else 0.0 for c in cs)
    return round(pts / len(cs), 3)


def frac(items):
    tot = sum(i.get("weight", 1) for i in items)
    return round(sum(i.get("weight", 1) for i in items if i["passed"]) / tot, 3) if tot else None


WEIGHTS = {"data": 0.5, "code": 0.25, "gates": 0.25}


def overall(code, data, gates, judge=None):
    parts = {"data": data, "code": code, "gates": gates}
    w = dict(WEIGHTS)
    if judge is not None:
        w = {k: v * 0.9 for k, v in w.items()}
        w["judge"] = 0.1
        parts["judge"] = judge
    present = {k: v for k, v in parts.items() if v is not None}
    tw = sum(w[k] for k in present)
    return round(sum(w[k] * present[k] for k in present) / tw, 3) if tw else 0.0
