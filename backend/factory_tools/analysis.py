"""Data analysis utilities. All SQL is generated portable (dbt cross-db macros + adapter.get_columns_in_relation)
and executed through the dbt target via warehouse.show()."""

from typing import Any

from .warehouse import QueryError, rel_jinja, show


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def columns(relation, target=None, cwd=None):
    sql = f"""{{%- set cols = adapter.get_columns_in_relation({rel_jinja(relation)}) -%}}
{{% for c in cols %}}select {{{{ loop.index }}}} as ord, '{{{{ c.name }}}}' as column_name, '{{{{ c.data_type }}}}' as data_type,
 {{{{ 'true' if (c.is_numeric() or c.is_float() or c.is_integer()) else 'false' }}}} as is_numeric
{{% if not loop.last %}}union all {{% endif %}}{{% endfor %}}"""
    r = show(sql, limit=500, target=target, cwd=cwd)
    rows = sorted(r["rows"], key=lambda x: x[0])
    return [{"name": x[1], "data_type": x[2], "is_numeric": bool(x[3])} for x in rows]


def _profile_sql(rel, cols, top_k):
    parts, tops = [], []
    for i, c in enumerate(cols):
        q = f"{{{{ adapter.quote('{c['name']}') }}}}"
        num = f"sum(cast({q} as {{{{ dbt.type_float() }}}}))" if c["is_numeric"] else "null"
        parts.append(f"""select {i} as ord, count(*) as row_count, count({q}) as non_null, count(distinct {q}) as distinct_count,
 cast(min({q}) as {{{{ dbt.type_string() }}}}) as min_value, cast(max({q}) as {{{{ dbt.type_string() }}}}) as max_value, {num} as sum_value
 from {{{{ {rel} }}}}""")
        if top_k:
            tops.append(f"""select * from (select {i} as ord, cast({q} as {{{{ dbt.type_string() }}}}) as value, count(*) as n,
 row_number() over (order by count(*) desc) as rk from {{{{ {rel} }}}} group by 2) t{i} where rk <= {int(top_k)}""")
    return " union all ".join(parts), " union all ".join(tops)


def profile(relation: str, target: str | None = None, top_k: int = 5, cwd=None) -> dict:
    """Row count, nulls, distinct, min/max (and sum for numerics) + top values per column."""
    cols = columns(relation, target, cwd)
    if not cols:
        raise QueryError(f"relation {relation!r} has no columns or does not exist in target {target or 'dev'}")
    rel = rel_jinja(relation)
    stats_sql, top_sql = _profile_sql(rel, cols, top_k)
    stats = {r[0]: r for r in show(stats_sql, limit=500, target=target, cwd=cwd)["rows"]}
    tops: dict[Any, Any] = {}
    if top_sql:
        for r in show(top_sql, limit=500, target=target, cwd=cwd)["rows"]:
            tops.setdefault(r[0], []).append({"value": r[1], "count": r[2]})
    out = []
    for i, c in enumerate(cols):
        s = stats.get(i)
        rc, nn = (s[1], s[2]) if s else (0, 0)
        out.append(
            {
                **c,
                "non_null": nn,
                "nulls": rc - nn,
                "null_pct": round(100 * (rc - nn) / rc, 2) if rc else 0,
                "distinct": s[3] if s else 0,
                "min": s[4] if s else None,
                "max": s[5] if s else None,
                "sum": s[6] if s else None,
                "top_values": sorted(tops.get(i, []), key=lambda x: -x["count"]),
            }
        )
    return {
        "relation": relation,
        "target": target or "dev",
        "row_count": out[0]["non_null"] + out[0]["nulls"] if out else 0,
        "columns": out,
    }


def histogram(relation: str, column: str, bins: int = 10, target: str | None = None, cwd=None) -> dict:
    cols = {c["name"]: c for c in columns(relation, target, cwd)}
    if column not in cols:
        raise QueryError(f"column {column!r} not in {relation} ({', '.join(cols)})")
    rel, q, n = rel_jinja(relation), f"{{{{ adapter.quote('{column}') }}}}", max(1, min(int(bins), 50))
    if not cols[column]["is_numeric"]:
        r = show(
            f"""select cast({q} as {{{{ dbt.type_string() }}}}) as value, count(*) as n from {{{{ {rel} }}}} group by 1 order by 2 desc""",
            limit=n,
            target=target,
            cwd=cwd,
        )
        return {
            "relation": relation,
            "column": column,
            "kind": "categorical",
            "buckets": [{"value": v, "count": c} for v, c in r["rows"]],
        }
    f = "{{ dbt.type_float() }}"
    sql = f"""with s as (select cast({q} as {f}) as v from {{{{ {rel} }}}} where {q} is not null),
b as (select min(v) as lo, max(v) as hi from s)
select case when b.hi = b.lo then 0 else least(cast(floor((s.v - b.lo) / ((b.hi - b.lo) / {n})) as integer), {n - 1}) end as bucket,
 min(b.lo) as lo, min(b.hi) as hi, count(*) as n from s cross join b group by 1 order by 1"""
    rows = show(sql, limit=n, target=target, cwd=cwd)["rows"]
    if not rows:
        return {"relation": relation, "column": column, "kind": "numeric", "buckets": []}
    lo, hi = _num(rows[0][1]), _num(rows[0][2])
    w = (hi - lo) / n if hi != lo else 0
    return {
        "relation": relation,
        "column": column,
        "kind": "numeric",
        "min": lo,
        "max": hi,
        "buckets": [
            {"bucket": int(b), "from": round(lo + b * w, 4), "to": round(lo + (b + 1) * w, 4), "count": c}
            for b, _, _, c in rows
        ],
    }


def compare(
    relation: str,
    key: str | None = None,
    base_target: str = "prod",
    new_target: str | None = None,
    base_relation: str | None = None,
    max_rows: int = 500,
    cwd=None,
) -> dict:
    """Compare a relation between two dbt targets (default prod vs dev): row counts, schema changes,
    column-level stat deltas, and (with key) a key-based row diff over up to max_rows rows."""
    base_rel = base_relation or relation
    res: dict[str, Any] = {
        "relation": relation,
        "base": f"{base_target}:{base_rel}",
        "new": f"{new_target or 'dev'}:{relation}",
    }
    try:
        new = profile(relation, new_target, top_k=0, cwd=cwd)
    except QueryError as ex:
        raise QueryError(f"new side failed: {ex}")
    try:
        base = profile(base_rel, base_target, top_k=0, cwd=cwd)
    except QueryError:
        return {
            **res,
            "status": "new_relation",
            "message": f"{base_rel} not found in {base_target}: it is new in this change",
            "row_count": {"base": None, "new": new["row_count"]},
            "columns_added": [c["name"] for c in new["columns"]],
        }
    bc, nc = {c["name"]: c for c in base["columns"]}, {c["name"]: c for c in new["columns"]}
    res.update(
        status="compared",
        row_count={"base": base["row_count"], "new": new["row_count"], "delta": new["row_count"] - base["row_count"]},
        columns_added=[c for c in nc if c not in bc],
        columns_removed=[c for c in bc if c not in nc],
        type_changes=[
            {"column": c, "base": bc[c]["data_type"], "new": nc[c]["data_type"]}
            for c in nc
            if c in bc and bc[c]["data_type"] != nc[c]["data_type"]
        ],
    )
    col_diffs = []
    for c in nc:
        if c not in bc:
            continue
        d = {
            k: (bc[c][k], nc[c][k])
            for k in ("nulls", "distinct", "min", "max", "sum")
            if str(bc[c][k]) != str(nc[c][k])
        }
        if d:
            col_diffs.append({"column": c, **{k: {"base": a, "new": b} for k, (a, b) in d.items()}})
    res["column_stat_changes"] = col_diffs
    if key:
        if key not in nc or key not in bc:
            raise QueryError(f"key {key!r} must exist on both sides")
        shared = [c for c in nc if c in bc]

        def Q(c):
            return f"{{{{ adapter.quote('{c}') }}}}"

        sel = ", ".join(f"cast({Q(c)} as {{{{ dbt.type_string() }}}}) as {Q(c)}" for c in shared)

        def pull(rel, tgt):
            r = show(
                f'select {sel} from {{{{ {rel_jinja(rel)} }}}} order by {Q(key)}', limit=max_rows, target=tgt, cwd=cwd
            )
            ki = r["columns"].index(key)
            return {row[ki]: dict(zip(r["columns"], row, strict=False)) for row in r["rows"]}, r["truncated"]

        (b, bt), (n, nt) = pull(base_rel, base_target), pull(relation, new_target)
        only_b, only_n = sorted(set(b) - set(n)), sorted(set(n) - set(b))
        changed: list[dict[str, Any]] = []
        per_col: dict[str, Any] = {}
        for k in sorted(set(b) & set(n)):
            diff = {c: {"base": b[k][c], "new": n[k][c]} for c in shared if b[k][c] != n[k][c]}
            if diff:
                changed.append({"key": k, "changes": diff})
                for c in diff:
                    per_col[c] = per_col.get(c, 0) + 1
        res["key_diff"] = {
            "key": key,
            "compared_rows": len(set(b) & set(n)),
            "sample_truncated": bt or nt,
            "only_in_base": len(only_b),
            "only_in_new": len(only_n),
            "changed_rows": len(changed),
            "changed_by_column": per_col,
            "examples": {"only_in_base": only_b[:5], "only_in_new": only_n[:5], "changed": changed[:5]},
        }
    res["identical"] = not (
        res["columns_added"]
        or res["columns_removed"]
        or res["type_changes"]
        or col_diffs
        or res["row_count"]["delta"]
        or (
            key
            and (res["key_diff"]["changed_rows"] or res["key_diff"]["only_in_base"] or res["key_diff"]["only_in_new"])
        )
    )
    return res
