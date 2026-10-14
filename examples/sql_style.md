# Team SQL style guide (example)

Copy to `.factory/sql_style.md` (or `.claude/sql_style.md`) in your dbt repo, set `FACTORY_SQL_STYLE`,
or paste it in the UI. The agent gets it in its system prompt; the reviewer shows it next to findings.

## Layout
- Lowercase keywords and functions; snake_case identifiers.
- 4-space indents, trailing commas, one column per line in the final select.
- Max 100 characters per line.

## Structure
- Start with import CTEs, one per `ref()`/`source()`: `with orders as (select ... from {{ ref('orders') }})`.
- Then logical CTEs with descriptive names; end with `select ... from final`.
- No `select *` in the final select. `select *` is OK only inside import CTEs.
- Aggregate before joining when the join could fan out (payments → orders).

## Naming & aliasing
- Always alias tables with `as` (`from orders as o`) and qualify columns in joins.
- Booleans start with `is_`/`has_`; dates end with `_date`, timestamps with `_at`; money with `_amount`.
- Count columns: `number_of_<entity>` or `<entity>_count`, always `count(distinct <key>)` after joins.

## Joins & filters
- Write `inner join` / `left join` explicitly, never bare `join`.
- Date ranges are half-open: `>= '2018-01-01' and < '2018-04-01'`.
