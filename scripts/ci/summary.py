#!/usr/bin/env python3
"""Render the aggregated CI gate table from $NEEDS (toJSON(needs)). --check exits 1 if any gate failed."""

import json
import os
import sys

GATES = {
    "changes": ("Routing", "paths-filter: backend / frontend / docs / ci"),
    "hygiene": (
        "Stage 1 · Hygiene",
        "pre-commit (ruff, prettier, markdownlint, shellcheck, editorconfig), actionlint, commitlint",
    ),
    "static": ("Stage 2 · Static", "mypy ratchet, tsc --noEmit, ESLint warning budget"),
    "complexity": ("Complexity", "radon CC/MI ratchet, xenon, lizard, file/function size, jscpd"),
    "security": ("Security", "gitleaks, bandit, pip-audit, npm audit, Trivy fs, SBOM, dependency-review"),
    "test": ("Tests", "pytest py3.11–3.13, coverage gate, diff-cover, junit"),
    "data": ("Data", "dbt parse/compile, sqlfluff, mock evals vs expected outcomes"),
    "frontend": ("Frontend", "vite build, bundle budget, Lighthouse (advisory)"),
    "container": ("Container", "hadolint, buildx build, non-root smoke test"),
}
ICON = {"success": "✅", "failure": "❌", "cancelled": "⚪", "skipped": "⏭️"}


def main():
    needs = json.loads(os.environ.get("NEEDS", "{}"))
    if "--check" in sys.argv:
        bad = [k for k, v in needs.items() if v.get("result") in ("failure", "cancelled")]
        print("failed gates: " + ", ".join(bad) if bad else "all gates green or skipped by path filter")
        return 1 if bad else 0
    rows = ["## CI gates", "", "| gate | result | checks |", "|---|:-:|---|"]
    for k, (title, desc) in GATES.items():
        r = needs.get(k, {}).get("result", "n/a")
        rows.append(f"| {title} | {ICON.get(r, '❔')} {r} | {desc} |")
    rows += [
        "",
        f"[Full run & artifacts]({os.environ.get('RUN_URL', '')}) · details in [docs/CI.md]({os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ.get('GITHUB_REPOSITORY', '')}/blob/main/docs/CI.md)",
        "",
    ]
    print("\n".join(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
