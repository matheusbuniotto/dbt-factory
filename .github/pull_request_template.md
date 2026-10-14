## Summary

<!-- What does this change and why? -->

## Type

- [ ] feat
- [ ] fix
- [ ] refactor / perf
- [ ] docs / ci / chore

## Checklist

- [ ] PR title follows Conventional Commits (`type(scope): summary`)
- [ ] `pre-commit run --all-files` passes locally
- [ ] Tests added/updated; `pytest` passes
- [ ] All data access still goes through the configured dbt adapter (no direct file reads of warehouse data)
- [ ] No complexity-baseline growth (`scripts/ci/complexity_gate.py`), or justified below
- [ ] Docs updated (`README.md`, `docs/`)

## Notes for reviewers
