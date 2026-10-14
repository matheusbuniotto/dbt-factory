# dbt factory — coding + data agent best practices

## Coding (same bar as any PR)

1. **Build green.** `dbt build --select <model>+` must pass. Fix failures with `dbt_failing_test_rows`.
2. **Docs + tests.** Every model and column has a description. Primary key: `unique` + `not_null`. Foreign keys: `relationships`. Use `accepted_values` for enums, singular tests for ranges.
3. **Naming / layering.** `stg_` (1:1 with sources, rename+cast) → `int_` (joins/business logic) → `fct_`/`dim_`/`mart_`/`rpt_`/`monthly_` (consume only via `ref`).
4. **SQL style.** No `SELECT *` except `select * from {{ ref/source }}` in a CTE. Always `ref()`/`source()` — never hardcode schemas. Prefer explicit column lists in the final SELECT.
5. **Lint.** sqlfluff (dbt/jinja templater) must be clean or waived with a reason.

## Data (the bar coding agents don't have)

1. **Declare grain.** `meta.grain: [col,…]` or unique+not_null on the key. Run `grain_unique` — zero duplicate/null keys.
2. **No join fan-out.** After joins, additive measures must not inflate vs upstream. `no_fanout` must pass.
3. **Nulls.** Keys/`_id` columns: 0% null. Other columns: within declared thresholds.
4. **Reconcile vs prod (or a reference).** Aggregates of measures by dimensions must match prod within tolerance, OR match a `reference_sql`, OR emit `<waiver id="reconciles">reason</waiver>`.
5. **Row-count delta.** Explain any change > ±5% vs prod (`row_count_delta`) or waive.
6. **Preview sanity.** Non-empty; no all-null columns in the sample.
7. **Unit tests** (dbt ≥ 1.8) for non-trivial logic; scaffold with `generate_dbt_tests`.

## Definition of Done

Call `definition_of_done` (or `data_quality_gate` + code checks) at the end of every turn. Iterate until `passed: true`. If a check must stay red, emit:

```text
<waiver id="CHECK_ID">plain-language reason a human reviewer can accept</waiver>
```

Never waive `dbt_compile`, `dbt_build`, or `grain_unique` without explicit human approval in the request.

## Review for humans

When shipping: state the grain, what changed vs prod (rows, measures), downstream impact, and any waivers. Prefer data compare + profile over prose.
