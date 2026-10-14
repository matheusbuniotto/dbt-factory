"""Data testing & quality tools. Adapter-agnostic SQL, executed only through the dbt target (warehouse.show).
Statuses: pass | fail | warn | skip."""
import re
from .warehouse import show, rel_jinja, validate_select, QueryError
from . import analysis as A, dbt_tools as D

def Q(c): return f"{{{{ adapter.quote('{c}') }}}}"
def R(rel): return f"{{{{ {rel_jinja(rel)} }}}}"
def _f(v):
    try: return float(v)
    except (TypeError, ValueError): return None
def check(id, status, detail, **data): return {"id": id, "status": status, "detail": detail, **data}

def declared_grain(model, cwd=None):
    d = D.docs(model, cwd=cwd); meta = d.get("meta") or {}
    g = meta.get("grain")
    if g: return [g] if isinstance(g, str) else list(g)
    uniq = [c["name"] for c in d["columns"] if "unique" in c["tests"]]
    return uniq[:1] or None

# ---------- individual checks ----------
def grain_check(relation, grain, target=None, cwd=None):
    if not grain: return check("grain_unique", "fail", "no declared grain: add meta.grain or a unique test on the key column")
    cols = ", ".join(Q(c) for c in grain); nulls = " or ".join(f"{Q(c)} is null" for c in grain)
    r = show(f"""select (select count(*) from {R(relation)}) as row_count,
 (select count(*) from (select {cols} from {R(relation)} group by {cols} having count(*) > 1) d) as duplicate_keys,
 (select count(*) from {R(relation)} where {nulls}) as null_keys""", limit=1, target=target, cwd=cwd)["rows"][0]
    rc, dup, nk = r
    ok = dup == 0 and nk == 0
    return check("grain_unique", "pass" if ok else "fail", f"grain ({', '.join(grain)}): {rc} rows, {dup} duplicated keys, {nk} null keys",
                 grain=grain, row_count=rc, duplicate_keys=dup, null_keys=nk)

def fanout_check(model, grain=None, tolerance=0.001, cwd=None):
    """Join fan-out: duplicated grain, or additive measures inflated vs the same column upstream."""
    parents = [u.split(".")[-1] for u in (D.lineage(model, "upstream", depth=1, cwd=cwd).get("upstream") or [[]])[0] if u.startswith(("model.", "seed.", "snapshot."))]
    mcols = {c["name"]: c for c in A.columns(model, cwd=cwd)}
    findings, compared = [], []
    for p in parents:
        try: pcols = {c["name"]: c for c in A.columns(p, cwd=cwd)}
        except QueryError: continue
        shared_num = [c for c in mcols if c in pcols and mcols[c]["is_numeric"] and pcols[c]["is_numeric"] and not c.endswith("_id")]
        key = next((g for g in (grain or []) if g in pcols), None)
        parts = [f"(select count(*) from {R(model)}) as model_rows", f"(select count(*) from {R(p)}) as parent_rows"]
        if key: parts += [f"(select count(distinct {Q(key)}) from {R(p)}) as parent_keys", f"(select count(distinct {Q(key)}) from {R(model)}) as model_keys"]
        parts += [f"(select sum({Q(c)}) from {R(model)}) as m_{i}" for i, c in enumerate(shared_num)]
        parts += [f"(select sum({Q(c)}) from {R(p)}) as p_{i}" for i, c in enumerate(shared_num)]
        row = dict(zip(*[(lambda r: (r["columns"], r["rows"][0]))(show("select " + ", ".join(parts), limit=1, cwd=cwd))][0]))
        info = {"parent": p, "model_rows": row["model_rows"], "parent_rows": row["parent_rows"]}
        if key:
            info.update(key=key, parent_keys=row["parent_keys"], model_keys=row["model_keys"])
            if row["model_rows"] > row["model_keys"] and len(grain) == 1:
                findings.append(f"{model} has {row['model_rows']} rows for {row['model_keys']} distinct {key} (joined with {p}?)")
        for i, c in enumerate(shared_num):
            m, pv = _f(row[f"m_{i}"]), _f(row[f"p_{i}"])
            if m is not None and pv and m > pv * (1 + tolerance):
                findings.append(f"sum({c}) is {m:g} in {model} but {pv:g} in {p}: measure inflated x{m / pv:.2f}")
        compared.append(info)
    # count-measure inflation: number_of_orders / order_count summed over the model must not exceed the
    # row count of the matching parent (stg_orders / orders). Heuristic name match; catches count() after a join.
    for c in mcols:
        m = re.match(r"^(?:number_of_|n_|count_)(\w+)$|^(\w+?)_count$", c)
        if not m or not mcols[c]["is_numeric"]: continue
        ent = (m.group(1) or m.group(2)).lower()
        ent_forms = {ent, ent + "s", ent.rstrip("s")}
        for info in compared:
            pname = info["parent"].lower()
            if not any(pname == f or pname.endswith("_" + f) for f in ent_forms): continue
            r = show(f"select sum({Q(c)}) as v from {R(model)}", limit=1, cwd=cwd)["rows"]
            tot = _f(r[0][0]) if r else None
            if tot is not None and tot > info["parent_rows"] * (1 + tolerance):
                findings.append(f"sum({c}) = {tot:g} but {info['parent']} has only {info['parent_rows']} rows: "
                                f"count inflated by a join (use count(distinct ...) or aggregate before joining)")
    if not compared: return check("no_fanout", "skip", "no upstream relation to compare")
    return check("no_fanout", "fail" if findings else "pass", "; ".join(findings) or f"no duplication or measure inflation vs {', '.join(c['parent'] for c in compared)}", parents=compared)

def null_check(relation, thresholds=None, default_max_pct=None, key_columns=(), target=None, cwd=None, profile=None):
    prof = profile or A.profile(relation, target, top_k=0, cwd=cwd)
    thresholds = thresholds or {}; bad, warn = [], []
    for c in prof["columns"]:
        lim = thresholds.get(c["name"], 0.0 if (c["name"] in key_columns or c["name"].endswith("_id")) else default_max_pct)
        if lim is None:
            if c["null_pct"] == 100 and prof["row_count"]: warn.append(f"{c['name']} is entirely null")
            continue
        if c["null_pct"] > lim: bad.append(f"{c['name']} {c['null_pct']}% null > {lim}%")
    st = "fail" if bad else "warn" if warn else "pass"
    return check("nulls_within_threshold", st, "; ".join(bad + warn) or "all columns within null thresholds",
                 nulls={c["name"]: c["null_pct"] for c in prof["columns"]})

def row_count_delta(relation, base_target="prod", max_delta_pct=5.0, cwd=None):
    n = show(f"select count(*) as n from {R(relation)}", limit=1, cwd=cwd)["rows"][0][0]
    try: b = show(f"select count(*) as n from {R(relation)}", limit=1, target=base_target, cwd=cwd)["rows"][0][0]
    except QueryError: return check("row_count_delta", "skip", f"{relation} is new (not in {base_target}): {n} rows", new=n, base=None)
    pct = 0.0 if b == n else (100.0 * (n - b) / b if b else 100.0)
    st = "pass" if abs(pct) <= max_delta_pct else "fail"
    return check("row_count_delta", st, f"{base_target} {b} → dev {n} rows ({pct:+.2f}%, limit ±{max_delta_pct}%)", base=b, new=n, delta_pct=round(pct, 3))

def reconcile(relation, measures, dimensions=None, base_target="prod", reference_sql=None, tolerance=0.001, cwd=None):
    """Aggregate totals per dimension: dev model vs prod model (or vs a reference SELECT), within relative tolerance."""
    if not measures: return check("reconciles", "skip", "no measures to reconcile")
    dims = dimensions or []
    dsel = ", ".join(f"cast({Q(d)} as {{{{ dbt.type_string() }}}}) as {Q(d)}" for d in dims)
    msel = ", ".join(f"sum(cast({Q(m)} as {{{{ dbt.type_float() }}}})) as {Q(m)}" for m in measures)
    grp = f" group by {', '.join(str(i + 1) for i in range(len(dims)))}" if dims else ""
    def agg(src, tgt=None):
        r = show(f"select {dsel + ', ' if dims else ''}{msel} from {src} as src{grp}", limit=500, target=tgt, cwd=cwd)
        return {tuple(row[:len(dims)]): dict(zip(measures, row[len(dims):])) for row in r["rows"]}
    new = agg(R(relation))
    if reference_sql:
        base, label = agg(f"({validate_select(reference_sql)})"), "reference query"
    else:
        try: base, label = agg(R(relation), base_target), f"{base_target}:{relation}"
        except QueryError:
            return check("reconciles", "skip", f"{relation} not in {base_target} and no reference_sql: reconcile vs a reference or waive")
    mism = []
    for k in sorted(set(base) | set(new), key=str):
        for m in measures:
            a, b = _f((base.get(k) or {}).get(m)), _f((new.get(k) or {}).get(m))
            if a is None and b is None: continue
            if a is None or b is None or abs(a - b) > tolerance * max(abs(a), abs(b), 1e-9):
                mism.append({"dims": dict(zip(dims, k)), "measure": m, "base": a, "new": b})
    st = "pass" if not mism else "fail"
    return check("reconciles", st, f"{len(mism)} of {len(set(base) | set(new)) * len(measures)} aggregate cells differ vs {label} (tol {tolerance:.3%})",
                 against=label, mismatches=mism[:10])

def preview_sanity(relation, cwd=None):
    s = show(f"select * from {R(relation)}", limit=20, cwd=cwd)
    if not s["rows"]: return check("preview_sanity", "fail", "relation is empty")
    allnull = [c for i, c in enumerate(s["columns"]) if all(r[i] is None for r in s["rows"])]
    return check("preview_sanity", "warn" if allnull else "pass", f"{s['row_count']} preview rows" + (f"; all-null in sample: {', '.join(allnull)}" if allnull else ""),
                 columns=s["columns"], sample=s["rows"][:3])

# ---------- the gate ----------
def data_quality_gate(model, grain=None, measures=None, dimensions=None, reference_sql=None, base_target="prod",
                      null_thresholds=None, default_null_pct=None, max_row_delta_pct=5.0, tolerance=0.001, cwd=None):
    checks = []
    def run(fn, *a, **kw):
        try: checks.append(fn(*a, **kw))
        except Exception as ex: checks.append(check(getattr(fn, "__name__", "check"), "fail", f"{type(ex).__name__}: {ex}"))
    grain = grain or declared_grain(model, cwd=cwd)
    prof = A.profile(model, top_k=0, cwd=cwd)
    if measures is None:
        measures = [c["name"] for c in prof["columns"] if c["is_numeric"] and not c["name"].endswith("_id") and c["name"] not in (grain or [])]
    run(grain_check, model, grain, cwd=cwd)
    run(fanout_check, model, grain, cwd=cwd)
    run(null_check, model, null_thresholds, default_null_pct, tuple(grain or ()), cwd=cwd, profile=prof)
    run(row_count_delta, model, base_target, max_row_delta_pct, cwd=cwd)
    run(reconcile, model, measures, dimensions, base_target, reference_sql, tolerance, cwd=cwd)
    run(preview_sanity, model, cwd=cwd)
    failed = [c["id"] for c in checks if c["status"] == "fail"]
    return {"model": model, "grain": grain, "measures": measures, "passed": not failed, "failed": failed,
            "summary": {s: sum(c["status"] == s for c in checks) for s in ("pass", "fail", "warn", "skip")}, "checks": checks}

# ---------- test generation ----------
def generate_tests(model, cwd=None, unit_test=True):
    """Suggest dbt tests from the data (via the adapter): grain unique/not_null, not_null, accepted_values,
    relationships to upstream keys, non-negative range checks (singular tests) and a dbt>=1.8 unit-test scaffold."""
    prof = A.profile(model, top_k=10, cwd=cwd); docs = D.docs(model, cwd=cwd); rc = prof["row_count"]
    m = D._manifest(cwd); uid = docs["unique_id"]
    parent_keys = {}
    for pid in m["parent_map"].get(uid, []):
        for t in m["child_map"].get(pid, []):
            tn = m["nodes"].get(t, {})
            if (tn.get("test_metadata") or {}).get("name") == "unique" and tn.get("column_name"):
                parent_keys[tn["column_name"]] = pid.split(".")[-1]
    grain = declared_grain(model, cwd=cwd) or [next((c["name"] for c in prof["columns"] if c["distinct"] == rc and c["nulls"] == 0), None)]
    grain = [g for g in grain if g]
    cols, singular = [], {}
    for c in prof["columns"]:
        tests = []
        if c["name"] in grain and len(grain) == 1: tests += ["unique", "not_null"]
        elif c["nulls"] == 0 and (c["name"].endswith("_id") or c["is_numeric"]): tests.append("not_null")
        if c["name"] in parent_keys and parent_keys[c["name"]] != model and c["name"] not in grain:
            tests.append({"relationships": {"to": f"ref('{parent_keys[c['name']]}')", "field": c["name"]}})
        if not c["is_numeric"] and 1 < c["distinct"] <= 8 and c["nulls"] == 0 and rc > c["distinct"] * 2 and "date" not in c["data_type"].lower() and "time" not in c["data_type"].lower():
            tests.append({"accepted_values": {"values": sorted(str(v["value"]) for v in c["top_values"])}})
        if c["is_numeric"] and _f(c["min"]) is not None and _f(c["min"]) >= 0 and not c["name"].endswith("_id"):
            singular[f"tests/assert_{model}_{c['name']}_non_negative.sql"] = f"-- {c['name']} must never be negative\nselect *\nfrom {{{{ ref('{model}') }}}}\nwhere {c['name']} < 0\n"
        if tests: cols.append((c["name"], tests))
    def y(v, ind):
        if isinstance(v, dict):
            return "".join(f"\n{' ' * ind}{k}: {y(x, ind + 2) if isinstance(x, (dict, list)) else (repr(x) if isinstance(x, str) and k == 'to' else x)}" for k, x in v.items())
        if isinstance(v, list): return "[" + ", ".join(f"'{x}'" for x in v) + "]"
        return str(v)
    lines = ["version: 2", "models:", f"  - name: {model}"]
    if len(grain) > 1: lines += ["    config:", "      meta:", f"        grain: [{', '.join(grain)}]"]
    lines.append("    columns:")
    for name, tests in cols:
        lines += [f"      - name: {name}", "        data_tests:"]
        for t in tests:
            if isinstance(t, str): lines.append(f"          - {t}")
            else:
                k, v = next(iter(t.items())); lines.append(f"          - {k}:")
                for kk, vv in v.items(): lines.append(f"              {kk}: {y(vv, 0) if isinstance(vv, list) else (repr(vv) if kk == 'to' else vv)}")
    out = {"model": model, "grain": grain, "schema_yml": "\n".join(lines) + "\n", "singular_tests": singular}
    if len(grain) > 1:
        out["grain_test_sql"] = f"select {', '.join(grain)}, count(*) as n\nfrom {{{{ ref('{model}') }}}}\ngroup by {', '.join(grain)}\nhaving count(*) > 1\n"
    if unit_test:
        parents = [p.split(".")[-1] for p in m["parent_map"].get(uid, []) if p.startswith(("model.", "seed."))]
        given = []
        for p in parents:
            try:
                smp = show(f"select * from {R(p)}", limit=3, cwd=cwd)
                rows = [dict(zip(smp["columns"], r)) for r in smp["rows"]]
            except QueryError: rows = []
            given.append({"input": f"ref('{p}')", "rows": rows})
        ut = [f"unit_tests:", f"  - name: test_{model}_logic", f"    model: {model}", "    given:"]
        for g in given:
            ut += [f"      - input: {g['input']}", "        rows:"] + [f"          - {{{', '.join(f'{k}: {v!r}' for k, v in r.items())}}}" for r in g["rows"]]
        ut += ["    expect:", "      rows:", "        # TODO: fill the expected output for the given rows (dbt >= 1.8)", "        - {}"]
        out["unit_test_yml"] = "\n".join(ut) + "\n"
        out["note"] = "unit test is a scaffold: inputs are real sampled rows (via adapter); expected rows must be filled in"
    return out

def run_unit_tests(select=None, cwd=None):
    sel = f"{select},test_type:unit" if select else "test_type:unit"
    return D.build(sel, command="test", cwd=cwd)
