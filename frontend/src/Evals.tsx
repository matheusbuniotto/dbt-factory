import { useEffect, useState } from 'react'
import { j, post } from './ui'

const pct = (x: any) => (x == null ? '—' : `${Math.round(x * 100)}%`)
const tone = (x: number) => (x >= 0.999 ? 'text-[#86efac]' : x >= 0.6 ? 'text-[#fde68a]' : 'text-[#fca5a5]')
const when = (ts: number) =>
  ts
    ? new Date(ts * 1000).toLocaleString('en-GB', {
        timeZone: 'America/Sao_Paulo',
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      }) + ' BRT'
    : ''

function Bar({ v }: { v: number }) {
  return (
    <div className="h-1.5 w-full rounded bg-raised">
      <div
        className={`h-full rounded ${v >= 0.999 ? 'bg-[#4ade80]' : v >= 0.6 ? 'bg-[#facc15]' : 'bg-[#f87171]'}`}
        style={{ width: `${Math.round((v || 0) * 100)}%` }}
      />
    </div>
  )
}

function CaseCard({ c, other }: { c: any; other?: any }) {
  const [open, setOpen] = useState(!c.passed)
  const s = c.scores || {}
  const d = (k: string) => (other?.scores ? (s[k] ?? 0) - (other.scores[k] ?? 0) : null)
  return (
    <div className="overflow-hidden rounded-xl border border-line">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 bg-sunken px-4 py-3 text-left">
        <span
          className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${c.status === 'running' || c.status === 'pending' ? 'bg-raised text-ink-4' : c.passed ? 'bg-[#4ade80]/15 text-[#86efac]' : 'bg-[#f87171]/15 text-[#fca5a5]'}`}
        >
          {c.status === 'running' || c.status === 'pending' ? c.status : c.passed ? 'PASS' : 'FAIL'}
        </span>
        <span className="text-[13.5px] text-ink-1">{c.title || c.id}</span>
        <span className="font-mono text-[11px] text-ink-5">{c.id}</span>
        <div className="ml-auto flex gap-5 font-mono text-[12px]">
          {['data', 'code', 'gates', 'overall'].map((k) => (
            <span key={k} className="w-20 text-right">
              <span className="text-ink-5">{k} </span>
              <span className={tone(s[k] ?? 0)}>{pct(s[k])}</span>
              {d(k) ? (
                <span className={`ml-1 text-[10.5px] ${d(k)! > 0 ? 'text-[#86efac]' : 'text-[#fca5a5]'}`}>{d(k)! > 0 ? '▲' : '▼'}</span>
              ) : null}
            </span>
          ))}
        </div>
      </button>
      {open && (
        <div className="space-y-3 px-4 py-3">
          <div className="flex flex-wrap gap-4 font-mono text-[11.5px] text-ink-4">
            <span>model {c.model || '—'}</span>
            <span>{c.turns ?? 0} turns</span>
            <span>${(c.cost_usd || 0).toFixed(3)}</span>
            <span>{c.seconds ?? 0}s</span>
            {c.gate?.summary && (
              <span>
                gate {c.gate.passed ? 'passed' : 'failed'} (
                {Object.entries(c.gate.summary)
                  .map(([k, v]) => `${v} ${k}`)
                  .join(', ')}
                )
              </span>
            )}
            {c.task_id && (
              <a href={`/?task=${c.task_id}&tab=review`} className="text-[#93c5fd] hover:underline">
                open task →
              </a>
            )}
          </div>
          {c.error && <div className="text-[12.5px] text-[#fca5a5]">{c.error}</div>}
          <table className="w-full text-[12.5px]">
            <tbody>
              {(c.assertions || []).map((a: any, i: number) => (
                <tr key={i} className="border-t border-line/60 align-top">
                  <td className="w-5 py-1.5">
                    {a.passed ? <span className="text-[#86efac]">✓</span> : <span className="text-[#fca5a5]">✗</span>}
                  </td>
                  <td className="w-14 py-1.5 font-mono text-[11px] text-ink-5">{a.kind}</td>
                  <td className="py-1.5 text-ink-2">{a.name}</td>
                  <td className="py-1.5 font-mono text-[11px] text-ink-4">{a.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {c.judge && c.judge.score != null && (
            <div className="text-[12px] text-ink-3">
              Judge: {pct(c.judge.score)} — {c.judge.rationale}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function EvalsPage() {
  const [runs, setRuns] = useState<any[]>([])
  const [sel, setSel] = useState<string>('')
  const [run, setRun] = useState<any>(null)
  const [cmpId, setCmpId] = useState('')
  const [cmp, setCmp] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const loadRuns = () =>
    j('/api/evals/runs').then((r: any[]) => {
      setRuns(r)
      if (!sel && r[0]) setSel(r[0].run_id)
    })
  useEffect(() => {
    loadRuns()
    const t = setInterval(loadRuns, 4000)
    return () => clearInterval(t)
  }, [])
  useEffect(() => {
    if (!sel) return
    const f = () => j(`/api/evals/runs/${sel}`).then(setRun)
    f()
    const t = setInterval(f, 3000)
    return () => clearInterval(t)
  }, [sel])
  useEffect(() => {
    if (cmpId) j(`/api/evals/runs/${cmpId}`).then(setCmp)
    else setCmp(null)
  }, [cmpId])
  const start = async () => {
    setBusy(true)
    try {
      const r = await post('/api/evals/run', { engine: 'mock', label: 'mock run' })
      setSel(r.run_id)
      loadRuns()
    } finally {
      setBusy(false)
    }
  }
  const a = run?.aggregate || {}
  const b = cmp?.aggregate
  return (
    <div className="flex h-full min-h-0">
      <aside className="w-72 shrink-0 overflow-auto border-r border-line p-3">
        <button
          onClick={start}
          disabled={busy}
          className="mb-3 w-full rounded-lg bg-accent py-2 text-[13px] font-medium text-page hover:bg-accent-2"
        >
          Run mock evals
        </button>
        <div className="label mb-2 px-1">Runs</div>
        {runs.map((r) => (
          <button
            key={r.run_id}
            onClick={() => setSel(r.run_id)}
            className={`mb-1 w-full rounded-lg px-2.5 py-2 text-left ${sel === r.run_id ? 'bg-raised' : 'hover:bg-sunken'}`}
          >
            <div className="flex items-center gap-2 text-[12.5px] text-ink-1">
              {r.label || r.engine}
              <span className="ml-auto font-mono text-[11px] text-ink-4">
                {r.status === 'done' ? `${r.aggregate?.passed}/${r.aggregate?.cases}` : r.status}
              </span>
            </div>
            <div className="font-mono text-[10.5px] text-ink-5">
              {r.engine} · {when(r.started)}
            </div>
          </button>
        ))}
        {!runs.length && <div className="px-1 text-[12px] text-ink-5">No runs yet.</div>}
      </aside>
      <main className="min-w-0 flex-1 overflow-auto p-6">
        {!run ? (
          <div className="text-ink-5">Select a run</div>
        ) : (
          <>
            <div className="mb-5 flex flex-wrap items-center gap-3">
              <h1 className="text-[18px] font-medium text-ink-1">{run.label || 'Eval run'}</h1>
              <span className="font-mono text-[11.5px] text-ink-4">
                {run.run_id} · {run.engine} · judge {run.judge} · {when(run.started)}
              </span>
              <label className="ml-auto flex items-center gap-2 text-[12px] text-ink-4">
                Compare with
                <select
                  value={cmpId}
                  onChange={(e) => setCmpId(e.target.value)}
                  className="rounded-md border border-line2 bg-page px-2 py-1 text-ink-2"
                >
                  <option value="">—</option>
                  {runs
                    .filter((r) => r.run_id !== sel)
                    .map((r) => (
                      <option key={r.run_id} value={r.run_id}>
                        {r.label || r.engine} · {when(r.started)}
                      </option>
                    ))}
                </select>
              </label>
            </div>
            <div className="mb-6 grid grid-cols-3 gap-3 lg:grid-cols-7">
              {[
                ['pass_rate', 'Pass rate', 1],
                ['overall', 'Overall', 1],
                ['data', 'Data correctness', 1],
                ['code', 'Code quality', 1],
                ['gates', 'Gate pass rate', 1],
                ['avg_turns', 'Avg turns', 0],
                ['avg_seconds', 'Avg time (s)', 0],
              ].map(([k, l, isPct]: any) => {
                const v = a[k]
                const dv = b && v != null && b[k] != null ? v - b[k] : null
                return (
                  <div key={k} className="rounded-xl border border-line bg-sunken p-3">
                    <div className="text-[11px] text-ink-5">{l}</div>
                    <div className={`font-mono text-[20px] ${isPct ? tone(v ?? 0) : 'text-ink-1'}`}>{isPct ? pct(v) : (v ?? '—')}</div>
                    {isPct ? <Bar v={v ?? 0} /> : null}
                    {dv != null && Math.abs(dv) > 1e-9 && (
                      <div className={`mt-1 font-mono text-[11px] ${dv > 0 === !!isPct ? 'text-[#86efac]' : 'text-[#fca5a5]'}`}>
                        {dv > 0 ? '+' : ''}
                        {isPct ? `${Math.round(dv * 100)} pts` : dv.toFixed(1)} vs compare
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
            <div className="mb-2 text-[11.5px] text-ink-5">
              Score = data {run.weights?.data} · code {run.weights?.code} · gates {run.weights?.gates}. A case passes when every data
              assertion (incl. golden-query equivalence) holds and code ≥ 75%.
            </div>
            <div className="space-y-2">
              {(run.cases || []).map((c: any) => (
                <CaseCard key={c.id} c={c} other={cmp?.cases?.find((x: any) => x.id === c.id)} />
              ))}
            </div>
          </>
        )}
      </main>
    </div>
  )
}
