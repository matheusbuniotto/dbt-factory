"""Analyst-facing review: risk flags, lineage impact, findings from gates + heuristics, data compare.
Comments are stored by the API; this module only builds the review report."""

import logging
import os
import re
import shlex
import subprocess

from . import analysis as A
from . import dbt_tools as D
from . import gates as G
from .warehouse import QueryError

log = logging.getLogger(__name__)

LAYER_RISK = {
    "stg_": "low",
    "int_": "med",
    "fct_": "high",
    "dim_": "high",
    "mart_": "high",
    "rpt_": "high",
    "monthly_": "high",
}


def _sh(cmd, cwd):
    argv = shlex.split(cmd) if isinstance(cmd, str) else cmd  # never shell=True
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)


def changed_models(cwd, base="HEAD"):
    """sql/yml under models/ that differ from base (uncommitted + committed since base)."""
    r = _sh(["git", "diff", "--name-only", base], cwd)
    files = [l for l in r.stdout.splitlines() if l.startswith("models/") and l.endswith((".sql", ".yml", ".yaml"))]
    # also untracked
    r2 = _sh(["git", "ls-files", "--others", "--exclude-standard", "models"], cwd)
    files += [l for l in r2.stdout.splitlines() if l.endswith((".sql", ".yml", ".yaml"))]
    models = sorted(
        {os.path.splitext(os.path.basename(f))[0] for f in files if not os.path.basename(f).startswith("_")}
    )
    # drop schema.yml-only names that aren't models
    real = []
    for m in models:
        if os.path.exists(os.path.join(cwd, "models", f"{m}.sql")) or any(
            os.path.exists(os.path.join(cwd, "models", d, f"{m}.sql"))
            for d in os.listdir(os.path.join(cwd, "models"))
            if os.path.isdir(os.path.join(cwd, "models", d))
        ):
            real.append(m)
        else:
            # search
            for _root, _, fs in os.walk(os.path.join(cwd, "models")):
                if f"{m}.sql" in fs:
                    real.append(m)
                    break
    return sorted(set(real)), sorted(set(files))


def file_diff(cwd, path, base="HEAD"):
    r = _sh(["git", "diff", "-U3", base, "--", path], cwd)
    if not r.stdout:
        r = _sh(["git", "diff", "--no-index", "/dev/null", path], cwd) if os.path.exists(os.path.join(cwd, path)) else r
    return r.stdout


def _risk_for_model(model, cwd, gate=None, compare=None):
    reasons, score = [], 0
    layer = next((p for p in LAYER_RISK if model.startswith(p)), None)
    if layer:
        r = LAYER_RISK[layer]
        reasons.append(f"touches {layer}* layer")
        score += {"low": 1, "med": 2, "high": 3}[r]
    else:
        reasons.append("non-standard model name")
        score += 2
    # materialization / grain / columns from gate + compare
    try:
        docs = D.docs(model, cwd=cwd)
        mat = docs.get("materialized") or "view"
        if mat in ("incremental", "table"):
            reasons.append(f"materialized as {mat}")
            score += 1 if mat == "table" else 2
    except Exception:
        docs = {}
    if gate:
        for c in gate.get("checks", []):
            if c["status"] != "fail":
                continue
            if c["id"] == "grain_unique":
                reasons.append("grain/key uniqueness failing")
                score += 3
            elif c["id"] == "docs_and_tests":
                reasons.append("docs or tests missing")
                score += 2
            elif c["id"] == "no_fanout":
                reasons.append("join fan-out detected")
                score += 3
            elif c["id"] == "reconciles":
                reasons.append("does not reconcile with prod")
                score += 2
            elif c["id"] == "dbt_build":
                reasons.append("dbt build failing")
                score += 3
            else:
                reasons.append(f"gate fail: {c['id']}")
                score += 1
    if compare:
        if compare.get("status") == "new_relation":
            reasons.append("new model (not in prod)")
            score += 1
        else:
            if compare.get("columns_removed"):
                reasons.append(f"removed columns: {', '.join(compare['columns_removed'][:4])}")
                score += 3
            if compare.get("type_changes"):
                reasons.append(f"type changes on {len(compare['type_changes'])} cols")
                score += 2
            kd = compare.get("key_diff") or {}
            if kd.get("changed_rows") or kd.get("only_in_new") or kd.get("only_in_base"):
                reasons.append(f"row-level diff vs prod ({kd.get('changed_rows', 0)} changed)")
                score += 2
            if (compare.get("row_count") or {}).get("delta"):
                reasons.append(f"row count Δ {(compare['row_count']['delta'])}")
                score += 1
    level = "high" if score >= 5 else "med" if score >= 2 else "low"
    return {"level": level, "score": score, "reasons": reasons}


def impact(model, cwd):
    try:
        lin = D.lineage(model, "downstream", cwd=cwd)
        downs = [u for level in lin.get("downstream", []) for u in level]
    except Exception:
        downs = []
    models = [u for u in downs if u.startswith("model.")]
    exposures = [u for u in downs if u.startswith("exposure.")]
    return {"downstream_models": models, "exposures": exposures, "count": len(models) + len(exposures)}


def heuristic_findings(cwd, files, base="HEAD"):
    """Quick, model-free findings on the diff (secrets, select *, dropped tests, etc.)."""
    out = []
    for path in files:
        diff = file_diff(cwd, path, base)
        for _i, line in enumerate(diff.splitlines()):
            if not line.startswith("+") or line.startswith("+++"):
                continue
            body = line[1:]
            if re.search(r"(?i)(api[_-]?key|secret|password)\s*=\s*['\"][^'\"]+['\"]", body):
                out.append(
                    {
                        "path": path,
                        "line_hint": body.strip()[:80],
                        "kind": "possible_secret",
                        "severity": "high",
                        "message": "Possible secret in added line",
                    }
                )
            if re.search(r"(?i)\bTODO\b|\bFIXME\b", body):
                out.append(
                    {
                        "path": path,
                        "line_hint": body.strip()[:80],
                        "kind": "todo",
                        "severity": "low",
                        "message": "TODO/FIXME added",
                    }
                )
            if re.search(r"(?is)select\s+\*\s+from\s+(?!\{\{\s*(?:ref|source))", body):
                out.append(
                    {
                        "path": path,
                        "line_hint": body.strip()[:80],
                        "kind": "select_star",
                        "severity": "med",
                        "message": "Bare SELECT * added",
                    }
                )
        # removed tests
        if path.endswith((".yml", ".yaml")):
            removed = [
                l[1:].strip()
                for l in diff.splitlines()
                if l.startswith("-") and not l.startswith("---") and "test" in l.lower()
            ]
            if removed:
                out.append(
                    {
                        "path": path,
                        "line_hint": removed[0][:80],
                        "kind": "tests_removed",
                        "severity": "high",
                        "message": f"Tests removed ({len(removed)} lines)",
                    }
                )
    return out


# anchor a failed check to the SQL line most likely responsible, so analysts see it inline
_ANCHORS = {
    "no_fanout": r"(?i)\bcount\((?!\s*distinct)|\bjoin\b",
    "no_select_star": r"(?i)select\s+\*",
    "ref_source_only": r"(?i)\b(from|join)\s+\w+\.\w+",
    "nulls_within_threshold": r"(?i)\bleft\s+join\b|\bsum\(",
    "reconciles": r"(?i)\bwhere\b|\bsum\(",
    "row_count_delta": r"(?i)\bwhere\b|\bjoin\b",
}


def _anchor(cwd, path, check_id):
    import re as _re

    pat = _ANCHORS.get(check_id)
    if not (pat and cwd and path):
        return None
    try:
        lines = open(os.path.join(cwd, path)).read().splitlines()
    except OSError:
        return None
    for l in lines:
        if _re.search(pat, l):
            return l.strip()[:80]
    return None


def gate_findings(gate, path_for_model, cwd=None):
    out = []
    for c in gate.get("checks", []):
        if c["status"] not in ("fail", "warn"):
            continue
        out.append(
            {
                "path": path_for_model,
                "line_hint": _anchor(cwd, path_for_model, c["id"]),
                "kind": c["id"],
                "severity": "high" if c["status"] == "fail" else "med",
                "message": f"[{c['group']}/{c['id']}] {c['detail'][:200]}",
                "status": c["status"],
            }
        )
    return out


def build_review(cwd, model=None, base="HEAD", run_data=True):
    models, files = changed_models(cwd, base)
    if model and model not in models:
        models = [model] + models
    primary = model or (models[0] if models else None)
    per_model, findings = [], []
    for m in models:
        path = next((f for f in files if f.endswith(f"{m}.sql")), f"models/{m}.sql")
        gate = compare = None
        if run_data:
            try:
                gate = G.run_gates(m, cwd=cwd)
            except Exception:
                # full traceback stays in the server log; the client gets a non-sensitive summary
                log.exception("gates failed for %s", m)
                gate = {
                    "passed": False,
                    "checks": [
                        {
                            "id": "gate_error",
                            "status": "fail",
                            "detail": "gate run failed (see server log)",
                            "group": "code",
                        }
                    ],
                    "failed": ["gate_error"],
                    "summary": {},
                }
            try:
                compare = A.compare(m, cwd=cwd)
            except QueryError as ex:
                log.warning("compare failed for %s: %s", m, ex)
                compare = {"status": "error", "message": "query against the warehouse failed (see server log)"}
            except Exception:
                log.exception("compare failed for %s", m)
                compare = {"status": "error", "message": "comparison failed (see server log)"}
        risk = _risk_for_model(
            m, cwd, gate, compare if isinstance(compare, dict) and compare.get("status") != "error" else None
        )
        imp = impact(m, cwd)
        per_model.append(
            {
                "model": m,
                "path": path,
                "risk": risk,
                "impact": imp,
                "gate": gate,
                "compare": compare,
                "diff": file_diff(cwd, path, base)[:20000],
            }
        )
        if gate:
            findings.extend(gate_findings(gate, path, cwd))
    findings.extend(heuristic_findings(cwd, files, base))
    # overall risk = max of models
    order = {"high": 3, "med": 2, "low": 1}
    overall = max((m["risk"]["level"] for m in per_model), key=lambda x: order[x], default="low")
    return {
        "primary": primary,
        "models": per_model,
        "files": files,
        "findings": findings,
        "risk": overall,
        "summary": _summary(per_model, findings),
        "look_first": _look_first(per_model, findings),
    }


def _summary(models, findings):
    if not models:
        return "No model changes detected."
    bits = [f"{len(models)} model(s) changed ({', '.join(m['model'] for m in models)})"]
    highs = [m for m in models if m["risk"]["level"] == "high"]
    if highs:
        bits.append(f"high risk: {', '.join(m['model'] for m in highs)}")
    fails = [f for f in findings if f["severity"] == "high"]
    if fails:
        bits.append(f"{len(fails)} high-severity findings")
    return ". ".join(bits) + "."


def _look_first(models, findings):
    out = []
    for m in sorted(models, key=lambda x: -x["risk"]["score"])[:3]:
        out.append({"model": m["model"], "why": "; ".join(m["risk"]["reasons"][:2]) or m["risk"]["level"]})
    for f in findings:
        if f["severity"] == "high" and len(out) < 5:
            out.append({"model": f["path"], "why": f["message"][:120]})
    return out
