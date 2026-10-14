"""dbt project tools: manifest search, lineage, compile, build/test with structured results,
failing test rows, docs lookup, source freshness."""

import json
import os

from .warehouse import TOOLS_TARGET, QueryError, _err, project_dir, run_dbt, show


def _manifest(cwd=None, refresh=False):
    cwd = cwd or project_dir()
    path = os.path.join(cwd, TOOLS_TARGET, "manifest.json")
    if refresh or not os.path.exists(path) or _stale(cwd, path):
        p = run_dbt(["parse", "--quiet"], cwd=cwd)
        if p.returncode != 0:
            raise QueryError("dbt parse failed:\n" + _err(p))
    return json.load(open(path))


def _stale(cwd, path):
    mt = os.path.getmtime(path)
    for root, dirs, files in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in ("target", "logs", ".factory", ".git", "dbt_packages")]
        for f in files:
            if f.endswith((".sql", ".yml", ".yaml")) and os.path.getmtime(os.path.join(root, f)) > mt:
                return True
    return False


def _nodes(m):
    return {
        **m["nodes"],
        **m["sources"],
        **m.get("exposures", {}),
        **m.get("metrics", {}),
        **m.get("semantic_models", {}),
    }


def _find(m, name):
    nodes = _nodes(m)
    if name in nodes:
        return nodes[name]
    hits = [n for n in nodes.values() if n.get("name") == name or f'{n.get("source_name", "")}.{n.get("name")}' == name]
    if not hits:
        raise QueryError(f"no resource named {name!r}")
    hits.sort(key=lambda n: n["resource_type"] != "model")
    return hits[0]


def list_resources(
    resource_type: str | None = None, search: str | None = None, select: str | None = None, limit: int = 200, cwd=None
):
    m = _manifest(cwd)
    ids = None
    if select:
        p = run_dbt(["ls", "--select", select, "--output", "json", "--output-keys", "unique_id", "--quiet"], cwd=cwd)
        if p.returncode != 0:
            raise QueryError(_err(p))
        ids = {json.loads(l)["unique_id"] for l in p.stdout.splitlines() if l.startswith("{")}
    out = []
    for uid, n in _nodes(m).items():
        if ids is not None and uid not in ids:
            continue
        if resource_type and n["resource_type"] != resource_type:
            continue
        if search and search.lower() not in (n["name"] + " " + (n.get("description") or "")).lower():
            continue
        out.append(
            {
                "unique_id": uid,
                "name": n["name"],
                "resource_type": n["resource_type"],
                "path": n.get("original_file_path"),
                "materialized": n.get("config", {}).get("materialized"),
                "description": (n.get("description") or "")[:200],
                **({"source_name": n["source_name"]} if n["resource_type"] == "source" else {}),
            }
        )
    return {"count": len(out), "resources": out[:limit]}


def lineage(name: str, direction: str = "both", depth: int | None = None, include_tests: bool = False, cwd=None):
    m = _manifest(cwd)
    root = _find(m, name)["unique_id"]

    def walk(graph):
        seen, frontier, levels, d = {root}, [root], [], 0
        while frontier and (depth is None or d < depth):
            nxt = [
                c
                for u in frontier
                for c in graph.get(u, [])
                if c not in seen and (include_tests or not c.startswith("test."))
            ]
            nxt = list(dict.fromkeys(nxt))
            seen.update(nxt)
            if nxt:
                levels.append(nxt)
            frontier, d = nxt, d + 1
        return levels

    out = {"node": root}
    if direction in ("up", "upstream", "both"):
        out["upstream"] = walk(m["parent_map"])
    if direction in ("down", "downstream", "both"):
        out["downstream"] = walk(m["child_map"])
    return out


def compile_model(name: str, cwd=None):
    m = _manifest(cwd)
    n = _find(m, name)
    if n["resource_type"] not in ("model", "test", "snapshot", "analysis"):
        raise QueryError(f"{name} is a {n['resource_type']}, cannot compile")
    p = run_dbt(["compile", "--select", n["name"], "--quiet"], cwd=cwd)
    if p.returncode != 0:
        raise QueryError("dbt compile failed:\n" + _err(p))
    node = json.load(open(os.path.join(cwd or project_dir(), TOOLS_TARGET, "manifest.json")))["nodes"][n["unique_id"]]
    return {
        "unique_id": n["unique_id"],
        "path": n.get("original_file_path"),
        "raw_code": n.get("raw_code"),
        "compiled_code": node.get("compiled_code"),
    }


def build(
    select: str | None = None,
    command: str = "build",
    exclude: str | None = None,
    full_refresh: bool = False,
    cwd=None,
    timeout=900,
):
    if command not in ("build", "test", "run", "seed", "snapshot"):
        raise QueryError("command must be build|test|run|seed|snapshot")
    args = (
        [command]
        + (["--select", select] if select else [])
        + (["--exclude", exclude] if exclude else [])
        + (["--full-refresh"] if full_refresh else [])
    )
    p = run_dbt(args, cwd=cwd, timeout=timeout, tools_target=False)  # real target/: the droid's own artifacts
    rr_path = os.path.join(cwd or project_dir(), "target", "run_results.json")
    if not os.path.exists(rr_path):
        raise QueryError(_err(p))
    rr = json.load(open(rr_path))
    results = []
    summary: dict[str, int] = {}
    for r in rr["results"]:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
        results.append(
            {
                "unique_id": r["unique_id"],
                "status": r["status"],
                "failures": r.get("failures"),
                "execution_time": round(r.get("execution_time") or 0, 3),
                "message": (r.get("message") or "")[:300],
                "rows_affected": (r.get("adapter_response") or {}).get("rows_affected"),
            }
        )
    failed = [r for r in results if r["status"] in ("error", "fail", "warn")]
    return {
        "command": " ".join(["dbt", *args]),
        "success": p.returncode == 0,
        "summary": summary,
        "elapsed": round(rr.get("elapsed_time", 0), 2),
        "failed": failed,
        "results": results if len(results) <= 60 else results[:60],
    }


def failing_test_rows(test: str, limit: int = 20, cwd=None):
    """Re-run a test's compiled SQL through the adapter and return the failing rows."""
    m = _manifest(cwd)
    n = _find(m, test)
    if n["resource_type"] != "test":
        raise QueryError(f"{test} is not a test")
    p = run_dbt(["compile", "--select", n["name"], "--quiet"], cwd=cwd)
    if p.returncode != 0:
        raise QueryError(_err(p))
    code = json.load(open(os.path.join(cwd or project_dir(), TOOLS_TARGET, "manifest.json")))["nodes"][
        n["unique_id"]
    ].get("compiled_code")
    rows = show(code, limit=limit, cwd=cwd)
    return {
        "test": n["unique_id"],
        "column": n.get("column_name"),
        "attached_to": n.get("attached_node"),
        "failing_rows": rows["rows"],
        "columns": rows["columns"],
        "truncated": rows["truncated"],
        "passed": rows["row_count"] == 0,
    }


def docs(name: str, cwd=None):
    m = _manifest(cwd)
    n = _find(m, name)
    uid = n["unique_id"]
    tests = []
    for c in m["child_map"].get(uid, []):
        if c.startswith("test."):
            t = m["nodes"][c]
            meta = t.get("test_metadata") or {}
            tests.append(
                {
                    "name": t["name"],
                    "test": meta.get("name", "singular"),
                    "column": t.get("column_name"),
                    "kwargs": {
                        k: v for k, v in (meta.get("kwargs") or {}).items() if k not in ("model", "column_name")
                    },
                }
            )
    return {
        "unique_id": uid,
        "resource_type": n["resource_type"],
        "description": n.get("description"),
        "path": n.get("original_file_path"),
        "materialized": n.get("config", {}).get("materialized"),
        "depends_on": (n.get("depends_on") or {}).get("nodes", []),
        "columns": [
            {
                "name": k,
                "description": v.get("description"),
                "data_type": v.get("data_type"),
                "tests": [t["test"] for t in tests if t["column"] == k],
            }
            for k, v in (n.get("columns") or {}).items()
        ],
        "tests": tests,
        "meta": {**(n.get("config", {}).get("meta") or {}), **(n.get("meta") or {})},
        "raw_code": n.get("raw_code"),
        "patch_path": n.get("patch_path"),
        "freshness": n.get("freshness") if n["resource_type"] == "source" else None,
    }


def freshness(select: str | None = None, cwd=None):
    m = _manifest(cwd)
    srcs = [
        s
        for s in m["sources"].values()
        if (s.get("freshness") or {}).get("warn_after", {}).get("count")
        or (s.get("freshness") or {}).get("error_after", {}).get("count")
    ]
    if not srcs:
        return {
            "sources_with_freshness": 0,
            "message": "no sources declare a freshness policy (loaded_at_field + warn_after/error_after)",
            "results": [],
        }
    p = run_dbt(
        ["source", "freshness"]
        + (["--select", select] if select else [])
        + ["--output", os.path.join(TOOLS_TARGET, "sources.json")],
        cwd=cwd,
    )
    path = os.path.join(cwd or project_dir(), TOOLS_TARGET, "sources.json")
    if not os.path.exists(path):
        raise QueryError(_err(p))
    res = json.load(open(path))["results"]
    return {
        "sources_with_freshness": len(srcs),
        "results": [
            {
                "unique_id": r["unique_id"],
                "status": r["status"],
                "max_loaded_at": r.get("max_loaded_at"),
                "age_seconds": r.get("max_loaded_at_time_ago_in_s"),
            }
            for r in res
        ],
    }
