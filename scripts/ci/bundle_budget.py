#!/usr/bin/env python3
"""Fail if the production bundle exceeds its gzip budget. usage: bundle_budget.py frontend/dist"""

import gzip
import pathlib
import sys

BUDGET_KB = {".js": 90, ".css": 15}  # gzip; current ~64 KB JS / ~6 KB CSS


def main(dist):
    totals, rows = dict.fromkeys(BUDGET_KB, 0.0), []
    for f in sorted(pathlib.Path(dist, "assets").iterdir()):
        if f.suffix in BUDGET_KB:
            gz = len(gzip.compress(f.read_bytes(), 9)) / 1024
            totals[f.suffix] += gz
            rows.append(f"| `{f.name}` | {f.stat().st_size / 1024:.1f} KB | {gz:.1f} KB |")
    bad = [f"{k} {v:.1f} KB > {BUDGET_KB[k]} KB" for k, v in totals.items() if v > BUDGET_KB[k]]
    md = ["## Bundle size", "", "| asset | raw | gzip |", "|---|---:|---:|", *rows, ""]
    md.append(" · ".join(f"{k} total {v:.1f}/{BUDGET_KB[k]} KB gz" for k, v in totals.items()))
    md.append(f"\n**Result: {'❌ ' + ', '.join(bad) if bad else '✅ within budget'}**\n")
    print("\n".join(md))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "frontend/dist"))
