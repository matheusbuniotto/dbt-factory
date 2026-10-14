#!/usr/bin/env python3
"""Gate an eval run against evals/expected.yml and render a markdown scorecard.

usage: eval_gate.py RESULTS_JSON [--expected evals/expected.yml] [--out scorecard.md]
Exit 1 if any case's pass/fail differs from the expectation or pass rate < min_pass_rate.
"""

import argparse
import json
import sys

import yaml


def pct(x):
    return "—" if x is None else f"{round(x * 100)}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--expected", default="evals/expected.yml")
    ap.add_argument("--out", default="eval-scorecard.md")
    a = ap.parse_args()
    run = json.load(open(a.results))
    exp = yaml.safe_load(open(a.expected))
    cases = {c["id"]: c for c in run.get("cases", [])}
    agg = run.get("aggregate", {})
    rows, errors = [], []
    for cid, want in exp["cases"].items():
        c = cases.get(cid)
        if not c:
            errors.append(f"{cid}: missing from run")
            rows.append((cid, want, "missing", {}, "❌"))
            continue
        got = "pass" if c.get("passed") else "fail"
        ok = got == want
        if not ok:
            errors.append(f"{cid}: expected {want}, got {got} ({c.get('error') or ''})".strip())
        rows.append((cid, want, got, c.get("scores") or {}, "✅" if ok else "❌"))
    if (agg.get("pass_rate") or 0) < exp.get("min_pass_rate", 0):
        errors.append(f"pass rate {agg.get('pass_rate')} < {exp['min_pass_rate']}")
    md = [
        "## Eval scorecard (mock engine)",
        "",
        f"Run `{run.get('run_id')}` · pass rate **{pct(agg.get('pass_rate'))}** · overall **{pct(agg.get('overall'))}** · "
        f"data **{pct(agg.get('data'))}** · code **{pct(agg.get('code'))}** · gates **{pct(agg.get('gates'))}** · "
        f"avg {agg.get('avg_seconds')}s/case",
        "",
        "| case | expected | actual | data | code | gates | overall | match |",
        "|---|:-:|:-:|---:|---:|---:|---:|:-:|",
    ]
    for cid, want, got, s, mark in rows:
        md.append(
            f"| `{cid}` | {want} | {got} | {pct(s.get('data'))} | {pct(s.get('code'))} | {pct(s.get('gates'))} | {pct(s.get('overall'))} | {mark} |"
        )
    md += ["", f"**Result: {'❌ ' + '; '.join(errors) if errors else '✅ all seeded cases behave as expected'}**", ""]
    out = "\n".join(md)
    open(a.out, "w").write(out)
    print(out)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
