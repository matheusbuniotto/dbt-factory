#!/usr/bin/env python3
"""Complexity ratchet for Python (radon) and TypeScript (lizard).

Rules (see docs/CI.md):
  * new/unknown function  : cyclomatic complexity <= CC_MAX (rank C, 15)
  * baselined function    : may not get more complex than its recorded CC
  * module maintainability: radon MI rank >= B (MI >= 10) unless baselined; baselined may not drop > MI_SLACK
  * any source file       : <= FILE_MAX_LINES lines unless baselined (and may not grow past baseline + 10%)
  * any function          : <= FUNC_MAX_LINES lines unless baselined
The baseline (.ci/complexity-baseline.json) records today's debt so the gate is green now and can only ratchet down.
`--update` rewrites the baseline (do this only when debt is paid down).
"""

import argparse
import csv
import io
import json
import os
import subprocess
import sys

CC_MAX, MI_MIN, MI_SLACK, FILE_MAX_LINES, FUNC_MAX_LINES = 15, 10.0, 5.0, 600, 120
PY_PATHS = ["backend", "evals", "scripts"]
PY_EXCLUDE = "backend/tests/*"
TS_PATH = "frontend/src"
BASELINE = ".ci/complexity-baseline.json"


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def rank(cc):
    return "ABCDEF"[min(5, max(0, (cc - 1) // 5))] if cc <= 40 else "F"


def collect():
    funcs, mods, files = {}, {}, {}
    cc = json.loads(run(["radon", "cc", "-j", "-e", PY_EXCLUDE, *PY_PATHS]))
    for path, blocks in cc.items():
        for b in blocks if isinstance(blocks, list) else []:
            name = f"{path}::{b.get('classname') + '.' if b.get('classname') else ''}{b['name']}"
            funcs[name] = {"cc": b["complexity"], "lines": b["endline"] - b["lineno"] + 1}
    mi = json.loads(run(["radon", "mi", "-j", "-e", PY_EXCLUDE, *PY_PATHS]))
    for path, v in mi.items():
        if isinstance(v, dict) and "mi" in v:
            mods[path] = round(v["mi"], 2)
    out = run(["lizard", "--csv", TS_PATH])
    for row in csv.reader(io.StringIO(out)):
        # nloc, ccn, tokens, params, length, location, file, function, long_name, start, end
        if len(row) < 11:
            continue
        name = f"{row[6]}::{row[7]}@{row[9]}"
        funcs[name.split("@")[0]] = {"cc": int(row[1]), "lines": int(row[4])}
    for root in [*PY_PATHS, TS_PATH]:
        for dp, _, fs in os.walk(root):
            if "/tests" in dp or "node_modules" in dp:
                continue
            for f in fs:
                if f.endswith((".py", ".ts", ".tsx")):
                    p = os.path.join(dp, f)
                    with open(p, encoding="utf-8") as fh:
                        files[p] = sum(1 for _ in fh)
    return {"functions": funcs, "modules_mi": mods, "files": files}


def gate(cur, base):
    errs, rows = [], []
    bf, bm, bfl = base.get("functions", {}), base.get("modules_mi", {}), base.get("files", {})
    for name, f in sorted(cur["functions"].items(), key=lambda x: -x[1]["cc"]):
        b = bf.get(name)
        limit = max(CC_MAX, b["cc"]) if b else CC_MAX
        if f["cc"] > limit:
            errs.append(f"CC {name}: {f['cc']} > {limit}" + (" (baseline)" if b else " (new code max)"))
        lline = max(FUNC_MAX_LINES, b["lines"]) if b else FUNC_MAX_LINES
        if f["lines"] > lline:
            errs.append(f"length {name}: {f['lines']} lines > {lline}")
        if f["cc"] > CC_MAX:
            rows.append((name, f["cc"], rank(f["cc"]), b["cc"] if b else "-"))
    for path, mi in cur["modules_mi"].items():
        b = bm.get(path)
        floor = (b - MI_SLACK) if b is not None and b < MI_MIN else MI_MIN
        if mi < floor:
            errs.append(f"MI {path}: {mi} < {round(floor, 2)}")
    for path, n in cur["files"].items():
        b = bfl.get(path)
        limit = max(FILE_MAX_LINES, int(b * 1.1)) if b else FILE_MAX_LINES
        if n > limit:
            errs.append(f"file size {path}: {n} lines > {limit}")
    return errs, rows


def report(cur, errs, rows):
    cc_all = [f["cc"] for f in cur["functions"].values()]
    md = ["## Complexity report", ""]
    md.append(
        f"- functions analysed: **{len(cc_all)}**, average CC **{sum(cc_all) / max(1, len(cc_all)):.2f}**, max **{max(cc_all, default=0)}**"
    )
    worst_mi = sorted(cur["modules_mi"].items(), key=lambda x: x[1])[:5]
    md.append("- lowest maintainability index: " + ", ".join(f"`{p}` {v}" for p, v in worst_mi))
    md.append(
        f"- gate: new code CC ≤ {CC_MAX} (rank C), MI ≥ {MI_MIN}, files ≤ {FILE_MAX_LINES} lines, functions ≤ {FUNC_MAX_LINES} lines; baselined debt may not grow"
    )
    md.append("")
    md.append(f"**Result: {'❌ ' + str(len(errs)) + ' violation(s)' if errs else '✅ pass'}**")
    if errs:
        md += ["", *[f"- {e}" for e in errs]]
    if rows:
        md += [
            "",
            "<details><summary>Baselined hotspots (CC > 15)</summary>",
            "",
            "| function | CC | rank | baseline |",
            "|---|---:|:-:|---:|",
        ]
        md += [f"| `{n}` | {c} | {r} | {b} |" for n, c, r, b in rows[:40]]
        md += ["", "</details>"]
    return "\n".join(md) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--report", default="complexity-report.md")
    a = ap.parse_args()
    cur = collect()
    if a.update:
        os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
        with open(BASELINE, "w") as f:
            json.dump(cur, f, indent=1, sort_keys=True)
        print(f"baseline written: {len(cur['functions'])} functions")
        return 0
    base = json.load(open(BASELINE)) if os.path.exists(BASELINE) else {}
    errs, rows = gate(cur, base)
    md = report(cur, errs, rows)
    with open(a.report, "w") as f:
        f.write(md)
    print(md)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
