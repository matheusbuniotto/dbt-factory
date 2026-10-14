"""dbt-factory-tools: local stdio MCP server exposing dbt + data-analysis tools to the droid.
All data access goes through the configured dbt target (read-only, LIMIT enforced).
Env: DBT_PROJECT_DIR (defaults to cwd), DBT_PROFILES_DIR."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp.server.fastmcp import FastMCP

from factory_tools import analysis as A
from factory_tools import dbt_tools as D
from factory_tools import gates as G
from factory_tools import quality as Q
from factory_tools import warehouse as W

mcp = FastMCP("dbt-factory-tools")


def _run(fn, *a, **kw):
    try:
        return json.dumps(fn(*a, **kw), default=str)
    except W.ReadOnlyViolation as ex:
        return json.dumps({"error": "read_only_violation", "message": str(ex)})
    except Exception as ex:
        return json.dumps({"error": type(ex).__name__, "message": str(ex)})


@mcp.tool()
def dbt_list(resource_type: str | None = None, search: str | None = None, select: str | None = None) -> str:
    """List/search dbt resources from the manifest. resource_type: model|source|seed|test|snapshot|exposure; search: substring of name/description; select: dbt selector (e.g. 'tag:finance', '+orders')."""
    return _run(D.list_resources, resource_type, search, select)


@mcp.tool()
def dbt_lineage(name: str, direction: str = "both", depth: int | None = None, include_tests: bool = False) -> str:
    """Upstream/downstream lineage of a model/source by level. direction: upstream|downstream|both; depth: max levels."""
    return _run(D.lineage, name, direction, depth, include_tests)


@mcp.tool()
def dbt_compile(name: str) -> str:
    """Compile a model (or test) and return raw and compiled SQL."""
    return _run(D.compile_model, name)


@mcp.tool()
def dbt_build(
    select: str | None = None, command: str = "build", exclude: str | None = None, full_refresh: bool = False
) -> str:
    """Run dbt build|test|run|seed|snapshot with selectors; returns structured run_results (status per node, failures, timings)."""
    return _run(D.build, select, command, exclude, full_refresh)


@mcp.tool()
def dbt_failing_test_rows(test: str, limit: int = 20) -> str:
    """Return the rows that make a dbt test fail (re-runs its compiled SQL on the warehouse)."""
    return _run(D.failing_test_rows, test, limit)


@mcp.tool()
def dbt_docs(name: str) -> str:
    """Docs for a model/source: description, columns (descriptions, tests), depends_on, materialization, freshness policy."""
    return _run(D.docs, name)


@mcp.tool()
def dbt_source_freshness(select: str | None = None) -> str:
    """Run dbt source freshness for sources that declare a policy."""
    return _run(D.freshness, select)


@mcp.tool()
def data_profile(relation: str, target: str | None = None, top_k: int = 5) -> str:
    """Profile a relation: row count, nulls, distinct, min/max/sum, top values per column. relation: model name or source:<src>.<table>; target: dbt target (default dev)."""
    return _run(A.profile, relation, target, top_k)


@mcp.tool()
def data_histogram(relation: str, column: str, bins: int = 10, target: str | None = None) -> str:
    """Distribution of one column: numeric histogram buckets or categorical top values."""
    return _run(A.histogram, relation, column, bins, target)


@mcp.tool()
def data_compare(
    relation: str,
    key: str | None = None,
    base_target: str = "prod",
    new_target: str | None = None,
    base_relation: str | None = None,
    max_rows: int = 500,
) -> str:
    """Compare a relation between targets (default prod vs dev): row count delta, schema changes, column stat changes and, with key, a key-based row diff."""
    return _run(A.compare, relation, key, base_target, new_target, base_relation, max_rows)


@mcp.tool()
def data_sample(relation: str, limit: int = 20, target: str | None = None) -> str:
    """Sample rows from a relation (LIMIT enforced, max 500)."""
    return _run(W.sample, relation, limit, target)


@mcp.tool()
def data_query(sql: str, limit: int = 50, target: str | None = None, timeout: int = 60) -> str:
    """Ad-hoc READ-ONLY SELECT through the dbt target. Use {{ ref('model') }} / {{ source('s','t') }} for relations. LIMIT and timeout enforced; DML/DDL/file reads rejected."""
    return _run(W.query, sql, limit, target, timeout)


@mcp.tool()
def generate_dbt_tests(model: str, unit_test: bool = True) -> str:
    """Generate dbt tests for a model from live data: unique/not_null on grain, relationships, accepted_values, non-negative singulars, and a dbt>=1.8 unit-test scaffold. Returns YAML/SQL to write."""
    return _run(Q.generate_tests, model, unit_test=unit_test)


@mcp.tool()
def data_quality_gate(
    model: str,
    grain: list[str] | None = None,
    measures: list[str] | None = None,
    dimensions: list[str] | None = None,
    reference_sql: str | None = None,
    base_target: str = "prod",
    max_row_delta_pct: float = 5.0,
    tolerance: float = 0.001,
) -> str:
    """Run the data quality gate: grain unique, no fan-out, nulls, row-count vs prod, reconcile aggregates, preview sanity. Returns structured pass/fail."""
    return _run(
        Q.data_quality_gate,
        model,
        grain=grain,
        measures=measures,
        dimensions=dimensions,
        reference_sql=reference_sql,
        base_target=base_target,
        max_row_delta_pct=max_row_delta_pct,
        tolerance=tolerance,
    )


@mcp.tool()
def definition_of_done(
    model: str,
    grain: list[str] | None = None,
    measures: list[str] | None = None,
    dimensions: list[str] | None = None,
    reference_sql: str | None = None,
) -> str:
    """Full Definition of Done: code gates (compile/build, docs+tests, naming, no select *, ref/source, sqlfluff) + data gates. Iterate until passed=true or emit <waiver id="...">reason</waiver>."""
    return _run(G.run_gates, model, grain=grain, measures=measures, dimensions=dimensions, reference_sql=reference_sql)


TOOL_NAMES = [
    "dbt_list",
    "dbt_lineage",
    "dbt_compile",
    "dbt_build",
    "dbt_failing_test_rows",
    "dbt_docs",
    "dbt_source_freshness",
    "data_profile",
    "data_histogram",
    "data_compare",
    "data_sample",
    "data_query",
    "generate_dbt_tests",
    "data_quality_gate",
    "definition_of_done",
]

if __name__ == "__main__":
    if os.environ.get("DBT_PROJECT_DIR"):
        os.chdir(os.environ["DBT_PROJECT_DIR"])
    mcp.run()
