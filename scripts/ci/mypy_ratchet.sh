#!/usr/bin/env bash
# mypy with a ratchet: errors already listed in .ci/mypy-baseline.txt are tolerated, any new error fails.
# Refresh the baseline (only ever shrinking it) with: scripts/ci/mypy_ratchet.sh --update
set -uo pipefail
baseline=.ci/mypy-baseline.txt
out=$(mypy backend evals scripts/ci 2>&1 | grep -E ': error:' | sed -E 's/:[0-9]+:[0-9]+:/:/; s/:[0-9]+:/:/' | sort -u)
if [ "${1:-}" = "--update" ]; then printf '%s\n' "$out" | sed '/^$/d' > "$baseline"; echo "baseline: $(wc -l < "$baseline") entries"; exit 0; fi
new=$(comm -23 <(printf '%s\n' "$out" | sed '/^$/d') <(sort -u "$baseline"))
fixed=$(comm -13 <(printf '%s\n' "$out" | sed '/^$/d') <(sort -u "$baseline"))
echo "mypy: $(printf '%s' "$out" | grep -c . || true) error(s), baseline $(grep -c . "$baseline" || true)"
[ -n "$fixed" ] && printf 'fixed since baseline (run --update to shrink it):\n%s\n' "$fixed"
if [ -n "$new" ]; then printf '::error::new mypy errors:\n%s\n' "$new"; exit 1; fi
echo "no new mypy errors"
