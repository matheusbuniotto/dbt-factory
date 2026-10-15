---
name: dbt-model-conventions
description: Team conventions for new or changed dbt models in jaffle_shop (naming, layering, required tests and docs). Use whenever creating or editing a model or schema.yml.
---
# dbt model conventions (jaffle_shop)

- Layers: `stg_*` (1:1 with seeds/sources, rename + cast only) → marts (`customers`, `orders`, new marts) built only from `ref()`s.
- Every new model gets an entry in a `.yml` file with a description and a description for every column.
- Primary key column: `unique` + `not_null` tests. Foreign keys: `relationships` test when the parent model exists.
- Money columns are `amount`/`revenue` style, rounded to 2 decimals in marts.
- Before finishing: `dbt_build` (slim default: changed models + children, deferred to prod), then call `data_profile` on the model and `data_compare` (prod vs dev) on every changed existing model.
- Never read seed CSVs or the warehouse file directly; inspect data only via the dbt-factory-tools MCP tools.
