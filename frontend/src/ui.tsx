// FastAPI detail can be a string or {message, errors[]}
type Detail = string | { message?: string; errors?: string[] } | null | undefined
export const errText = (d: Detail): string =>
  !d ? '' : typeof d === 'string' ? d : [d.message, ...(d.errors || [])].filter(Boolean).join(' · ') || JSON.stringify(d)

export const j = (u: string, o?: RequestInit) =>
  fetch(u, o).then(async (r) => {
    const d = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(errText(d.detail) || r.statusText)
    return d
  })
export const post = (u: string, body?: any) =>
  j(u, { method: 'POST', headers: { 'content-type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })

export const STATUS_STYLE: Record<string, { dot: string; text: string; label: string }> = {
  pass: { dot: 'bg-[#4ade80]', text: 'text-[#86efac]', label: 'Pass' },
  fail: { dot: 'bg-[#f87171]', text: 'text-[#fca5a5]', label: 'Fail' },
  warn: { dot: 'bg-[#facc15]', text: 'text-[#fde68a]', label: 'Warning' },
  waived: { dot: 'bg-[#60a5fa]', text: 'text-[#93c5fd]', label: 'Waived' },
  skip: { dot: 'bg-ink-5', text: 'text-ink-4', label: 'Skipped' },
}
export const RISK_STYLE: Record<string, string> = {
  high: 'border-[#f87171]/40 bg-[#f87171]/10 text-[#fca5a5]',
  med: 'border-[#facc15]/40 bg-[#facc15]/10 text-[#fde68a]',
  low: 'border-[#4ade80]/30 bg-[#4ade80]/10 text-[#86efac]',
}
export const RISK_LABEL: Record<string, string> = { high: 'High risk', med: 'Medium risk', low: 'Low risk' }

// Plain-language names for gate checks (analyst-facing)
export const CHECK_LABEL: Record<string, [string, string]> = {
  dbt_compile: ['Model compiles', 'The SQL is valid dbt'],
  dbt_build: ['Builds and tests pass', 'dbt build on the model and everything downstream'],
  docs_and_tests: ['Documented and tested', 'Description, column docs and at least one test'],
  grain_declared: ['Grain is declared', 'What one row means is written down'],
  naming_layer: ['Follows naming', 'stg_ / int_ / fct_ / dim_ conventions'],
  no_select_star: ['Explicit columns', 'No bare SELECT *'],
  ref_source_only: ['Uses ref/source', 'No hardcoded schemas or tables'],
  sqlfluff: ['SQL style (lint)', 'sqlfluff rules'],
  grain_unique: ['One row per grain', 'No duplicated or null keys'],
  no_fanout: ['No join fan-out', 'Joins did not multiply rows or inflate totals'],
  nulls_within_threshold: ['Nulls within limits', 'Keys never null; others within thresholds'],
  row_count_delta: ['Row count vs prod', 'Change in rows is within ±5% or explained'],
  reconciles: ['Totals reconcile', 'Aggregates match prod or a reference query'],
  preview_sanity: ['Preview looks sane', 'Non-empty, no all-null columns'],
  protected_paths: ['Protected paths untouched', 'No edits under protected_paths in .factory/config.yml'],
  data_gates: ['Data checks', 'Skipped: plain SQL repo (no dbt target)'],
  sql_changed: ['SQL changed', 'At least one .sql file was edited'],
}
