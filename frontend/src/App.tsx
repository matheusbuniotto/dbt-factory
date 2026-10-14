import { useEffect, useMemo, useRef, useState } from 'react'

type Ev = { i: number; turn?: number; kind: string; text?: string; id?: string; name?: string; input?: any; is_error?: boolean; cost?: number; turns?: number; status?: string; ts?: number }
type Turn = { prompt: string; status: string; started?: number }
type Task = { id: string; engine?: string; prompt: string; status: string; branch: string; created: number; mock: boolean; cleaned?: boolean; turns?: Turn[]; plan?: string; sql?: Record<string, string>; preview_model?: string; pr?: any; session_id?: string }
type Health = { engine?: string; engines?: string[]; model?: string | null; base_url?: string | null; mock_mode?: boolean; adapter?: string; gh_authed?: boolean; auth?: string | null; project?: string }

const j = (u: string, o?: RequestInit) => fetch(u, o).then(r => r.json())
const ago = (s: number) => { const d = Date.now() / 1000 - s; return d < 60 ? 'Now' : d < 3600 ? `${Math.floor(d / 60)}m` : d < 86400 ? `${Math.floor(d / 3600)}h` : `${Math.floor(d / 86400)}d` }
const projectName = (h: Health) => h.project?.split('/').pop() || 'project'

/* ---------- tiny icon set (stroke, 14px) ---------- */
const I = {
  plus: <path d="M8 3v10M3 8h10" />, search: <><circle cx="7" cy="7" r="4.5" /><path d="M10.5 10.5 14 14" /></>,
  chev: <path d="M6 4l4 4-4 4" />, term: <><path d="M3 4.5 6.5 8 3 11.5" /><path d="M8 12h5" /></>,
  file: <><path d="M4 2h5l3 3v9H4z" /><path d="M9 2v3h3" /></>, edit: <><path d="M3 13h3l7-7-3-3-7 7z" /></>,
  glob: <><circle cx="8" cy="8" r="5.5" /><path d="M2.5 8h11M8 2.5c2 2 2 9 0 11M8 2.5c-2 2-2 9 0 11" /></>,
  zap: <path d="M9 1.5 3.5 9H8l-1 5.5L12.5 7H8z" />, stop: <rect x="4" y="4" width="8" height="8" rx="1.5" />,
  up: <path d="M8 13V3M4 7l4-4 4 4" />, branch: <><circle cx="4.5" cy="3.5" r="1.5" /><circle cx="4.5" cy="12.5" r="1.5" /><circle cx="11.5" cy="6" r="1.5" /><path d="M4.5 5v6M11.5 7.5c0 2.5-7 1.5-7 3.5" /></>,
  trash: <><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.7 9h5.6l.7-9" /></>, check: <path d="M3.5 8.5 6.5 11.5 12.5 4.5" />,
  table: <><rect x="2.5" y="3" width="11" height="10" rx="1.5" /><path d="M2.5 6.5h11M6.5 6.5V13" /></>, diff: <><path d="M5 2v7M1.5 5.5h7M8 12.5h6.5" /></>,
  list: <><path d="M6 4h7.5M6 8h7.5M6 12h7.5" /><circle cx="3" cy="4" r=".6" /><circle cx="3" cy="8" r=".6" /><circle cx="3" cy="12" r=".6" /></>,
  code: <path d="M5.5 4.5 2 8l3.5 3.5M10.5 4.5 14 8l-3.5 3.5" />, panel: <><rect x="2" y="3" width="12" height="10" rx="1.5" /><path d="M10 3v10" /></>,
}
const Icon = ({ n, className = '' }: { n: keyof typeof I; className?: string }) =>
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" className={`h-3.5 w-3.5 shrink-0 ${className}`}>{I[n]}</svg>

const Logo = () => <svg viewBox="0 0 24 24" className="h-[18px] w-[18px] text-ink-1" fill="currentColor">{[0, 45, 90, 135, 180, 225, 270, 315].map(r =>
  <path key={r} transform={`rotate(${r} 12 12)`} d="M12 12c-.6-2.6-.2-5.6 1.6-8.6 1 2.8.6 5.8-1.6 8.6z" opacity={0.92} />)}</svg>

function StatusDot({ s }: { s: string }) {
  if (s === 'running') return <span className="relative flex h-2 w-2"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-60" /><span className="relative h-2 w-2 rounded-full bg-accent" /></span>
  const c: Record<string, string> = { succeeded: 'bg-[#4ade80]/80', failed: 'bg-[#f87171]', cancelled: 'bg-ink-5', interrupted: 'bg-ink-5' }
  return <span className={`h-1.5 w-1.5 rounded-full ${c[s] || 'bg-ink-5'}`} />
}

/* ---------- timeline pieces ---------- */
const toolIcon = (n?: string): keyof typeof I => n?.startsWith('mcp__') ? (n.includes('__data_') ? 'table' : 'zap') : n === 'Skill' ? 'list' : n === 'Bash' ? 'term' : n === 'Read' ? 'file' : n === 'Write' || n === 'Edit' ? 'edit' : n === 'Glob' || n === 'Grep' ? 'glob' : 'zap'
const toolArg = (e: Ev) => e.input?.command || e.input?.file_path || e.input?.pattern || e.input?.skill ||
  (e.name?.startsWith('mcp__') ? Object.entries(e.input ?? {}).map(([k, v]) => k === 'relation' || k === 'name' ? String(v) : `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`).join('  ') : JSON.stringify(e.input ?? {}).slice(0, 100))
const toolLabel = (n?: string) => { if (!n?.startsWith('mcp__')) return <>{n}</>; const [, srv, t] = n.split('__'); return <><span className="text-ink-4">{srv} /</span> {t}</> }
const tryJson = (t?: string) => { try { return JSON.parse(t || '') } catch { return null } }
function badgeFor(use: Ev, res?: Ev): JSX.Element | null {
  const j = tryJson(res?.text); const t = use.name?.split('__').pop()
  const cls = (ok: boolean) => `ml-auto shrink-0 rounded border px-1.5 py-px font-mono text-[10.5px] ${ok ? 'border-[#4ade80]/25 text-[#86efac]' : 'border-[#f87171]/30 text-[#fca5a5]'}`
  if (j?.error) return <span className={cls(false)}>{j.error}</span>
  if (t === 'dbt_build' && j?.summary) return <span className={cls(j.success)}>{Object.entries(j.summary).map(([k, v]) => `${k.toUpperCase()} ${v}`).join(' · ')}</span>
  if (t === 'data_profile' && j?.columns) return <span className={cls(true)}>{j.row_count} rows · {j.columns.length} cols</span>
  if (t === 'data_compare' && j?.status) return <span className={cls(j.identical !== false)}>{j.status === 'new_relation' ? 'new in this change' : j.identical ? 'identical to prod' : `Δ rows ${j.row_count.delta} · ${j.key_diff?.changed_rows ?? 0} changed`}</span>
  if (t === 'data_histogram' && j?.buckets) return <span className={cls(true)}>{j.buckets.length} buckets</span>
  return null
}
function ResultBody({ use, res }: { use: Ev; res: Ev }) {
  const j = tryJson(res.text); const t = use.name?.split('__').pop()
  const box = 'mb-2 ml-7 mt-1 overflow-auto rounded-lg border border-line bg-sunken animate-fadein'
  if (t === 'data_profile' && j?.columns) return <div className={box}><table className="w-full font-mono text-[11px]"><thead><tr className="text-ink-4">{['column', 'type', 'nulls', 'distinct', 'min', 'max', 'top values'].map(h => <th key={h} className="border-b border-line px-2.5 py-1.5 text-left font-normal">{h}</th>)}</tr></thead>
    <tbody>{j.columns.map((c: any) => <tr key={c.name} className="border-b border-line/50"><td className="px-2.5 py-1 text-ink-1">{c.name}</td><td className="px-2.5 text-ink-5">{c.data_type}</td><td className={`px-2.5 ${c.nulls ? 'text-[#fcd34d]' : 'text-ink-3'}`}>{c.nulls} <span className="text-ink-6">({c.null_pct}%)</span></td><td className="px-2.5 text-ink-3">{c.distinct}</td><td className="px-2.5 text-ink-3">{String(c.min).replace(' 00:00:00', '')}</td><td className="px-2.5 text-ink-3">{String(c.max).replace(' 00:00:00', '')}</td>
      <td className="px-2.5 text-ink-4">{(c.top_values || []).slice(0, 3).map((v: any) => `${String(v.value).replace(' 00:00:00', '')}×${v.count}`).join('  ')}</td></tr>)}</tbody></table></div>
  if (t === 'data_histogram' && j?.buckets) { const mx = Math.max(...j.buckets.map((b: any) => b.count), 1); return <div className={`${box} p-3 space-y-1`}>{j.buckets.map((b: any, k: number) =>
    <div key={k} className="flex items-center gap-2 font-mono text-[11px]"><span className="w-28 shrink-0 text-right text-ink-4">{b.value ?? `${b.from}–${b.to}`}</span><span className="h-3 rounded-sm bg-accent/70" style={{ width: `${(b.count / mx) * 60}%` }} /><span className="text-ink-3">{b.count}</span></div>)}</div> }
  if (t === 'data_compare' && j?.status) return <div className={`${box} p-3 font-mono text-[11.5px] leading-6 text-ink-3`}>
    <div><span className="text-ink-5">base</span> {j.base} <span className="text-ink-5">→ new</span> {j.new}</div>
    {j.status === 'new_relation' ? <div className="text-[#fcd34d]">{j.message}</div> : <>
      <div>rows: {j.row_count.base} → {j.row_count.new} <span className={j.row_count.delta ? 'text-[#fcd34d]' : 'text-[#86efac]'}>(Δ {j.row_count.delta})</span></div>
      <div>schema: +{j.columns_added.length} −{j.columns_removed.length} cols{j.columns_added.length ? ` (${j.columns_added.join(', ')})` : ''}, {j.type_changes.length} type changes</div>
      <div>column stat changes: {j.column_stat_changes.length ? j.column_stat_changes.map((c: any) => c.column).join(', ') : 'none'}</div>
      {j.key_diff && <div>key {j.key_diff.key}: {j.key_diff.compared_rows} matched · {j.key_diff.only_in_base} only in base · {j.key_diff.only_in_new} only in new · {j.key_diff.changed_rows} changed</div>}
      <div className={j.identical ? 'text-[#86efac]' : 'text-[#fcd34d]'}>{j.identical ? '✓ identical' : '△ differs'}</div></>}</div>
  return <pre className={`${box} max-h-72 p-3 font-mono text-[11.5px] leading-[1.55] text-ink-3 whitespace-pre-wrap`}>{j ? JSON.stringify(j, null, 2) : res.text}</pre>
}

function ToolRow({ use, res }: { use: Ev; res?: Ev }) {
  const [open, setOpen] = useState(false)
  const pending = !res
  const passed = res?.text?.match(/Done\. PASS=(\d+) WARN=(\d+) ERROR=(\d+)/)
  const badge = res && !passed ? badgeFor(use, res) : null
  return <div className="animate-fadein">
    <button onClick={() => res && setOpen(o => !o)} className={`group flex w-full items-center gap-2.5 rounded-md py-[5px] pl-1 pr-2 text-left hover:bg-hover ${pending ? 'opacity-90' : ''}`}>
      <Icon n={toolIcon(use.name)} className={res?.is_error ? 'text-[#f87171]' : 'text-accent'} />
      <span className="shrink-0 text-[13px] text-ink-2">{toolLabel(use.name)}</span>
      <span className={`truncate font-mono text-[12px] ${pending ? 'shimmer-text' : 'text-ink-4'}`}>{toolArg(use)}</span>
      {passed && <span className={`ml-auto shrink-0 rounded border px-1.5 py-px font-mono text-[10.5px] ${passed[3] === '0' ? 'border-[#4ade80]/25 text-[#86efac]' : 'border-[#f87171]/30 text-[#fca5a5]'}`}>PASS {passed[1]} · ERR {passed[3]}</span>}
      {badge}
      {res && <Icon n="chev" className={`${passed || badge ? '' : 'ml-auto'} text-ink-5 opacity-0 transition group-hover:opacity-100 ${open ? 'rotate-90 opacity-100' : ''}`} />}
    </button>
    {open && res && <ResultBody use={use} res={res} />}
  </div>
}

function PlanList({ plan, done }: { plan: string; done: boolean }) {
  const items = plan.split('\n').map(l => l.replace(/^\s*[-*\d.]+\s*/, '').trim()).filter(Boolean)
  return <div className="my-3 animate-fadein">
    <div className="mb-2 text-[13px] text-ink-3">{done ? 'Plan' : <span className="shimmer-text">Something's taking shape…</span>}</div>
    <div className="space-y-1.5">{items.map((it, k) => <div key={k} className="flex items-start gap-2.5 text-[13px]">
      {done ? <span className="mt-[3px] grid h-3.5 w-3.5 place-items-center rounded-full bg-[#4ade80]/85 text-page"><Icon n="check" className="h-2.5 w-2.5" /></span>
        : <span className="mt-[3px] h-3.5 w-3.5 rounded-full border border-ink-5" />}
      <span className={done ? 'text-ink-4 line-through decoration-ink-6' : 'text-ink-2'} dangerouslySetInnerHTML={{ __html: it.replace(/`([^`]+)`/g, '<code class="font-mono text-[12px] text-ink-1 bg-raised px-1 rounded">$1</code>') }} />
    </div>)}</div>
  </div>
}

const clean = (t = '') => t.replace(/<plan>[\s\S]*?<\/plan>/g, '').replace(/<\/?preview_model>/g, '').replace(/^\s*monthly_revenue\s*$/m, '').replace(/\[MOCK MODE\]\s*/g, '').replace(/\n{3,}/g, '\n\n').trim()
const md = (t: string) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/`([^`]+)`/g, '<code class="font-mono text-[12px] text-ink-1 bg-raised px-1 py-px rounded">$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b class="text-ink-1 font-medium">$1</b>')

function TurnView({ turn, evs, task }: { turn?: Turn; evs: Ev[]; task: Task }) {
  const results = useMemo(() => Object.fromEntries(evs.filter(e => e.kind === 'tool_result').map(e => [e.id, e])), [evs])
  const status = turn?.status ?? task.status
  const blocks: JSX.Element[] = []
  let tools: Ev[] = []
  const flush = (k: string) => { if (tools.length) { const ts = tools; blocks.push(<div key={k} className="ml-[3px] border-l border-line pl-4">{ts.map(u => <ToolRow key={u.i} use={u} res={results[u.id!]} />)}</div>); tools = [] } }
  let firstText = true
  for (const e of evs) {
    if (e.kind === 'tool_use') { tools.push(e); continue }
    if (e.kind === 'tool_result' || e.kind === 'user' || e.kind === 'done' || e.kind === 'system') continue
    flush(`f${e.i}`)
    if (e.kind === 'text') {
      const plan = e.text?.match(/<plan>([\s\S]*?)<\/plan>/)
      const body = clean(e.text)
      if (body) blocks.push(<div key={e.i} className="animate-fadein flex items-start gap-2.5 py-1.5">
        <span className={`mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full ${firstText ? 'bg-accent' : 'bg-ink-5'}`} />
        <div className={`text-[13.5px] leading-6 whitespace-pre-wrap ${firstText ? 'text-ink-1 font-medium' : 'text-ink-2'}`} dangerouslySetInnerHTML={{ __html: md(body) }} /></div>)
      firstText = false
      if (plan) blocks.push(<PlanList key={`p${e.i}`} plan={plan[1]} done={status === 'succeeded'} />)
    } else if (e.kind === 'result') {
      if (e.is_error) { blocks.push(<div key={e.i} className="animate-fadein mt-3 rounded-lg border border-[#f87171]/25 bg-[#f87171]/[.06] px-3.5 py-2.5">
        <div className="mb-1 flex items-center gap-2 text-[12.5px] font-medium text-[#fca5a5]"><Icon n="stop" className="h-3 w-3" />Engine error</div>
        <pre className="whitespace-pre-wrap font-mono text-[11.5px] leading-5 text-ink-2">{e.text}</pre></div>); continue }
      blocks.push(<div key={e.i} className="animate-fadein mt-3 flex items-center gap-2 text-[12.5px] text-ink-3">
        <span className="grid h-4 w-4 place-items-center rounded-full bg-[#4ade80]/15 text-[#86efac]"><Icon n="check" className="h-2.5 w-2.5" /></span>
        <span className="text-ink-2">{e.text}</span><span className="font-mono text-[11px] text-ink-5">{e.turns} steps{e.cost != null ? ` · $${e.cost.toFixed(4)}` : ''}</span></div>)
    } else if (e.kind === 'cancel') {
      blocks.push(<div key={e.i} className="animate-fadein mt-3 flex items-center gap-2 text-[12.5px] text-ink-4"><Icon n="stop" className="text-ink-4" /> Stopped by you</div>)
    } else blocks.push(<div key={e.i} className="font-mono text-[11.5px] text-ink-5">{e.text || e.status}</div>)
  }
  flush('end')
  return <div className="mb-8">
    <div className="mb-4 rounded-lg border border-line bg-raised px-4 py-3 text-[13.5px] leading-6 text-ink-1 animate-fadein">{turn?.prompt || task.prompt}</div>
    {blocks}
    {status === 'running' && <div className="mt-2 flex items-center gap-2 pl-1 text-[13px]"><StatusDot s="running" /><span className="shimmer-text">Droid is working</span></div>}
  </div>
}

/* ---------- right-side artifacts ---------- */
function DiffView({ text }: { text: string }) {
  const files = useMemo(() => text.split(/^diff --git /m).filter(Boolean).map(chunk => {
    const name = chunk.match(/ b\/(.+)\n/)?.[1] || '?'
    const lines = chunk.split('\n').filter(l => !/^(index |--- |\+\+\+ |new file|a\/)/.test(l)).slice(1)
    return { name, lines, add: lines.filter(l => l.startsWith('+')).length, del: lines.filter(l => l.startsWith('-')).length }
  }), [text])
  if (!files.length) return <Empty>No changes yet.</Empty>
  return <div className="space-y-3 p-3">{files.map(f => <div key={f.name} className="overflow-hidden rounded-lg border border-line">
    <div className="flex items-center gap-2 border-b border-line bg-sunken px-3 py-2"><Icon n="file" className="text-ink-4" /><span className="font-mono text-[12px] text-ink-2">{f.name}</span>
      <span className="ml-auto font-mono text-[11px]"><span className="text-[#86efac]">+{f.add}</span> <span className="text-[#fca5a5]">−{f.del}</span></span></div>
    <pre className="overflow-auto py-1 font-mono text-[11.5px] leading-[1.65]">{f.lines.map((l, i) => <div key={i} className={`px-3 ${l.startsWith('+') ? 'bg-[#4ade80]/[.07] text-[#bbf7d0]' : l.startsWith('-') ? 'bg-[#f87171]/[.08] text-[#fecaca]' : l.startsWith('@@') ? 'text-ink-5' : 'text-ink-4'}`}><span className="inline-block w-3 select-none text-ink-6">{l[0] === '+' || l[0] === '-' ? l[0] : ''}</span>{l.slice(l.startsWith('@@') ? 0 : 1) || ' '}</div>)}</pre>
  </div>)}</div>
}
const Empty = ({ children }: any) => <div className="grid h-full place-items-center p-8 text-[12.5px] text-ink-5">{children}</div>

function PreviewTable({ prev }: { prev: any }) {
  if (!prev?.columns?.length) return <Empty>Preview appears after the droid builds a model.</Empty>
  return <div className="p-3"><div className="mb-2 flex items-center gap-2"><span className="font-mono text-[12px] text-ink-2">{prev.relation}</span><span className="label !text-[10px]">first {prev.rows.length} rows · duckdb</span></div>
    <div className="overflow-auto rounded-lg border border-line"><table className="w-full font-mono text-[11.5px]">
      <thead className="sticky top-0 bg-sunken"><tr>{prev.columns.map((c: string) => <th key={c} className="whitespace-nowrap border-b border-line px-3 py-2 text-left font-normal text-ink-4">{c}</th>)}</tr></thead>
      <tbody>{prev.rows.map((r: any[], i: number) => <tr key={i} className="hover:bg-hover">{r.map((v, k) => <td key={k} className={`whitespace-nowrap border-b border-line/60 px-3 py-[6px] ${typeof v === 'number' ? 'text-right text-ink-1' : 'text-ink-3'}`}>{v === null ? <span className="text-ink-6">null</span> : String(v).replace(' 00:00:00', '')}</td>)}</tr>)}</tbody></table></div></div>
}

/* ---------- composer ---------- */
function Composer({ value, set, onSend, disabled, placeholder, chips, autoFocus }: any) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useEffect(() => { if (ref.current) { ref.current.style.height = '0'; ref.current.style.height = Math.min(ref.current.scrollHeight, 180) + 'px' } }, [value])
  return <div className={`rounded-xl border border-line2 bg-sunken transition focus-within:border-ink-5 ${disabled ? 'opacity-60' : ''}`}>
    <textarea ref={ref} autoFocus={autoFocus} value={value} disabled={disabled} onChange={e => set(e.target.value)} rows={1} placeholder={placeholder}
      onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSend() } }}
      className="block w-full resize-none bg-transparent px-3.5 pt-3 pb-2 text-[13.5px] leading-6 text-ink-1 outline-none placeholder:text-ink-5" />
    <div className="flex items-center gap-1.5 px-2 pb-2">
      {chips.map((c: any, i: number) => <span key={i} className="flex items-center gap-1 rounded-md border border-line2 px-1.5 py-[3px] font-mono text-[10.5px] text-ink-3">{c}</span>)}
      <button onClick={onSend} disabled={disabled || !value.trim()} className="ml-auto grid h-7 w-7 place-items-center rounded-md bg-accent text-page transition hover:bg-accent-2 disabled:bg-raised disabled:text-ink-5"><Icon n="up" /></button>
    </div></div>
}

/* ---------- app ---------- */
import { GateChip, GateScorecard } from './Gates'
import ReviewView from './Review'
import EvalsPage from './Evals'

export default function App() {
  const qs = new URLSearchParams(location.search)
  const [page, setPage] = useState<'tasks' | 'evals'>(qs.get('page') === 'evals' ? 'evals' : 'tasks')
  const [mode, setMode] = useState<'session' | 'review'>(qs.get('tab') === 'review' ? 'review' : 'session')
  const [gateBusy, setGateBusy] = useState(false)
  const [health, setHealth] = useState<Health>({}); const [tasks, setTasks] = useState<Task[]>([])
  const [sel, setSel] = useState<string | null>(new URLSearchParams(location.search).get('task'))
  const [task, setTask] = useState<Task | null>(null); const [evs, setEvs] = useState<Ev[]>([])
  const [diff, setDiff] = useState(''); const [prev, setPrev] = useState<any>(null)
  const [draft, setDraft] = useState(''); const [msg, setMsg] = useState(''); const [q, setQ] = useState('')
  const [tab, setTab] = useState<'preview' | 'changes' | 'sql' | 'plan' | 'gates'>((['preview','changes','sql','plan','gates'].includes(qs.get('tab') || '') ? qs.get('tab') : 'preview') as any)
  const [panel, setPanel] = useState(true); const [gen, setGen] = useState(0); const [toast, setToast] = useState<string | null>(null)
  const [engine, setEngine] = useState<string>(''); const [caps, setCaps] = useState<any>(null); const [capsOpen, setCapsOpen] = useState(false); const evCount = useRef(0); const scroller = useRef<HTMLDivElement>(null)

  const refreshList = () => j('/api/tasks').then(setTasks)
  useEffect(() => { j('/api/health').then(setHealth); refreshList(); const t = setInterval(refreshList, 4000); return () => clearInterval(t) }, [])
  const refreshPreview = (id: string) => fetch(`/api/tasks/${id}/preview`).then(r => r.ok ? r.json() : r.status === 409 ? undefined : null).then(p => { if (p !== undefined) setPrev(p) })
  const refreshArtifacts = (id: string, withPreview = false) => { j(`/api/tasks/${id}`).then(t => { setTask(t); if (withPreview || t.status !== 'running') refreshPreview(id) }); j(`/api/tasks/${id}/diff`).then(d => setDiff(d.diff || '')); j(`/api/tasks/${id}/capabilities`).then(setCaps) }
  useEffect(() => { if (!sel) { setTask(null); return } setEvs([]); evCount.current = 0; setDiff(''); setPrev(null); setGen(g => g + 1); history.replaceState(null, '', `?task=${sel}${mode === 'review' ? '&tab=review' : ''}`) }, [sel])
  useEffect(() => {
    if (!sel || !gen) return; refreshArtifacts(sel)
    const es = new EventSource(`/api/tasks/${sel}/events?since=${evCount.current}`)
    es.onmessage = m => { const e = JSON.parse(m.data); if (e.i < evCount.current) return; evCount.current = e.i + 1; setEvs(x => [...x, e])
      if (['tool_result', 'text', 'done', 'cancel', 'system', 'gate'].includes(e.kind)) refreshArtifacts(sel, e.kind === 'done'); if (e.kind === 'done') refreshList() }
    es.onerror = () => es.close(); return () => es.close()
  }, [gen])
  useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' }) }, [evs.length])
  const flash = (s: string) => { setToast(s); setTimeout(() => setToast(null), 3500) }

  const post = (p: string, body?: any) => fetch(`/api/tasks/${sel}/${p}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: body && JSON.stringify(body) })
    .then(async r => { const d = await r.json(); if (!r.ok) flash(d.detail); return r.ok ? d : null })
  const dispatch = async () => { if (!draft.trim()) return; const r = await j('/api/tasks', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ prompt: draft, engine: engine || health.engine }) }); setDraft(''); await refreshList(); setSel(r.id) }
  const followUp = async () => { if (!msg.trim()) return; const d = await post('messages', { content: msg }); if (d) { setMsg(''); setTask(t => t && { ...t, status: 'running', turns: [...(t.turns || []), { prompt: msg, status: 'running' }] }); setGen(g => g + 1); refreshList() } }
  const cancel = async () => { await post('cancel'); refreshList(); sel && refreshArtifacts(sel) }
  const cleanup = async () => { if (!confirm("Remove this session's worktree? The branch is kept.")) return; if (await post('cleanup')) flash('Worktree removed'); refreshList(); sel && refreshArtifacts(sel) }
  const commit = async () => { const r = await post('pr'); if (r) flash(r.pr_url ? `PR opened: ${r.pr_url}` : r.committed ? `Committed to ${r.branch} · ${r.gh}` : 'Nothing to commit'); sel && refreshArtifacts(sel) }

  const byTurn = useMemo(() => { const m: Ev[][] = []; evs.forEach(e => { (m[e.turn ?? 0] ||= []).push(e) }); return m }, [evs])
  const stats = useMemo(() => { const l = diff.split('\n'); return { add: l.filter(x => x.startsWith('+') && !x.startsWith('+++')).length, del: l.filter(x => x.startsWith('-') && !x.startsWith('---')).length } }, [diff])
  const filtered = tasks.filter(t => t.prompt.toLowerCase().includes(q.toLowerCase()))
  const running = task?.status === 'running'
  const ENGINE_LABEL: Record<string, string> = { mock: 'mock-replay', cli: 'claude -p', sdk: 'agent-sdk' }
  const authLabel = health.auth === 'gateway' ? 'litellm' : health.auth === 'claude_login' ? 'subscription' : health.auth === 'api_key' ? 'api key' : 'no auth'
  const tail = [health.model || 'default model', health.adapter || 'duckdb']
  const engineSelect = <label className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-accent" />
    <select value={engine || health.engine || 'mock'} onChange={e => setEngine(e.target.value)} className="cursor-pointer bg-transparent text-ink-2 outline-none [&>option]:bg-raised">
      {(health.engines || ['mock']).map(x => <option key={x} value={x}>{ENGINE_LABEL[x] || x}</option>)}</select></label>
  const newChips = [engineSelect, (engine || health.engine) === 'mock' ? 'replay' : authLabel, ...tail]
  const taskEngine = task ? (task.engine || (task.mock ? 'mock' : 'cli')) : 'mock'
  const skills: any[] = caps?.skills || []; const mcpTools: string[] = caps?.mcp_tools || []
  const capsChip = <button onClick={() => setCapsOpen(o => !o)} className="flex items-center gap-1 text-ink-2 hover:text-ink-1"><Icon n="zap" className="h-3 w-3 text-accent" />{skills.length} skill{skills.length === 1 ? '' : 's'} · {mcpTools.length} mcp tools</button>
  const chips = [<><span className="h-1.5 w-1.5 rounded-full bg-accent" />{ENGINE_LABEL[taskEngine]}</>, taskEngine === 'mock' ? 'replay' : authLabel, capsChip, ...tail]

  return <div className="flex h-full overflow-hidden bg-page">
    {/* sidebar */}
    <aside className="flex w-[260px] shrink-0 flex-col border-r border-line bg-sunken">
      <div className="flex h-12 items-center gap-2.5 px-4"><Logo /><span className="text-[13.5px] font-medium tracking-tight text-ink-1">dbt factory</span>
        <span className="ml-auto rounded border border-line2 px-1.5 py-px font-mono text-[10px] text-ink-4">MVP</span></div>
      <div className="px-2">
        <button onClick={() => { setPage('evals'); history.replaceState(null, '', '?page=evals') }} className={`flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 hover:bg-hover ${page === 'evals' ? 'bg-hover text-ink-1' : 'text-ink-2'}`}><Icon n="list" className="text-ink-3" />Evals</button>
        <button onClick={() => { setPage('tasks'); setSel(null); history.replaceState(null, '', '/') }} className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-ink-2 hover:bg-hover"><Icon n="plus" className="text-ink-3" />New session</button>
        <label className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-ink-3 focus-within:bg-hover"><Icon n="search" /><input value={q} onChange={e => setQ(e.target.value)} placeholder="Search" className="w-full bg-transparent outline-none placeholder:text-ink-3" /></label>
      </div>
      <div className="mt-4 flex items-center px-4 pb-1.5"><span className="label">Sessions</span><span className="ml-auto font-mono text-[10.5px] text-ink-5">{tasks.length}</span></div>
      <div className="flex-1 overflow-auto px-2 pb-3">
        <div className="flex items-center gap-1.5 px-2 py-1.5 text-[13px] text-ink-1"><Icon n="chev" className="rotate-90 text-ink-4" />{projectName(health)}</div>
        {filtered.map(t => <button key={t.id} onClick={() => { setPage('tasks'); setSel(t.id) }} className={`group flex w-full items-center gap-2 rounded-md py-[6px] pl-6 pr-2 text-left transition ${sel === t.id ? 'bg-hover text-ink-1' : 'text-ink-3 hover:bg-hover/70 hover:text-ink-2'}`}>
          <span className="w-2"><StatusDot s={t.status} /></span>
          <span className={`flex-1 truncate text-[13px] ${t.cleaned ? 'text-ink-5' : ''}`}>{t.prompt}</span>
          {t.engine && t.engine !== 'mock' && <span className="rounded border border-line2 px-1 font-mono text-[9.5px] text-ink-4">{t.engine}</span>}<span className="font-mono text-[11px] text-ink-5">{ago(t.created)}</span></button>)}
        {!filtered.length && <div className="px-6 py-2 text-[12px] text-ink-5">No sessions</div>}
      </div>
      <div className="border-t border-line p-3">
        <div className="flex items-center gap-2.5"><div className="grid h-6 w-6 place-items-center rounded-full bg-raised font-mono text-[10px] text-ink-2">MB</div><span className="text-[12.5px] text-ink-2">Matheus</span>
          <span className="ml-auto flex items-center gap-1.5 font-mono text-[10.5px] text-ink-4"><span className={`h-1.5 w-1.5 rounded-full ${health.mock_mode ? 'bg-[#facc15]' : 'bg-[#4ade80]'}`} />{health.engine ? ENGINE_LABEL[health.engine] : '…'}</span></div>
        <div className="mt-2 font-mono text-[10.5px] text-ink-5">gh {health.gh_authed ? 'connected' : 'not connected'} · {health.adapter}</div>
      </div>
    </aside>

    {/* main */}
    {page === 'evals' ? <main className="min-w-0 flex-1"><EvalsPage /></main> : !task ? <main className="relative flex flex-1 flex-col items-center justify-center px-8">
      <div className="pointer-events-none absolute inset-0 opacity-[.35] [background-image:linear-gradient(#141312_1px,transparent_1px),linear-gradient(90deg,#141312_1px,transparent_1px)] [background-size:48px_48px] [mask-image:radial-gradient(ellipse_at_center,black_20%,transparent_70%)]" />
      <div className="relative w-full max-w-[640px]">
        <div className="mb-5 flex justify-center"><span className="flex items-center gap-2 rounded-full border border-line2 bg-sunken px-3 py-1 font-mono text-[10.5px] tracking-[.16em] text-ink-3"><span className="h-1.5 w-1.5 rounded-full bg-accent" />YOUR ANALYTICS FACTORY</span></div>
        <h1 className="mb-2 text-center font-mono text-[30px] leading-tight tracking-tight text-ink-1">What should the droid build?</h1>
        <p className="mb-7 text-center text-[13.5px] text-ink-4">Each session gets its own git worktree of <span className="font-mono text-ink-3">{projectName(health)}</span>, builds with dbt, and previews the data.</p>
        <Composer value={draft} set={setDraft} onSend={dispatch} autoFocus placeholder="Build a monthly revenue mart with AOV and tests…" chips={newChips} />
        <div className="mt-4 flex flex-wrap justify-center gap-2">{['Build a monthly revenue mart with AOV', 'Add customer lifetime value tiers to customers', 'Add not_null and accepted_values tests to staging'].map(s =>
          <button key={s} onClick={() => setDraft(s)} className="rounded-md border border-line px-2.5 py-1 text-[12px] text-ink-4 transition hover:border-line2 hover:text-ink-2">{s}</button>)}</div>
      </div>
    </main> : <>
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line px-5">
          <StatusDot s={task.status} />
          <h1 className="min-w-0 truncate text-[13.5px] font-medium text-ink-1" title={task.prompt}>{task.prompt}</h1>
          <span className="hidden shrink-0 text-[12.5px] text-ink-4 2xl:inline">{projectName(health)}</span>
          <span className="flex shrink-0 items-center gap-1 font-mono text-[11px] text-ink-5"><Icon n="branch" className="h-3 w-3" />{task.branch}</span>
          <div className="ml-3 flex shrink-0 rounded-lg border border-line p-0.5">{(['session', 'review'] as const).map(m => <button key={m} onClick={() => { setMode(m); history.replaceState(null, '', `?task=${sel}${m === 'review' ? '&tab=review' : ''}`) }} className={`rounded-md px-2.5 py-0.5 text-[12px] ${mode === m ? 'bg-raised text-ink-1' : 'text-ink-4 hover:text-ink-2'}`}>{m === 'session' ? 'Session' : 'Review'}</button>)}</div>
          <button onClick={() => { setPanel(true); setTab('gates'); setMode('session') }}><GateChip gate={(task as any).gate} /></button>
          <div className="ml-auto flex shrink-0 items-center gap-1.5">
            {running && <button onClick={cancel} className="flex items-center gap-1.5 rounded-md border border-line2 px-2.5 py-1 text-[12px] text-ink-2 hover:border-[#f87171]/50 hover:text-[#fca5a5]"><Icon n="stop" className="h-3 w-3" />Stop</button>}
            {!running && !task.cleaned && <button onClick={cleanup} title="Remove worktree" className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[12px] text-ink-4 hover:bg-hover hover:text-ink-2"><Icon n="trash" className="h-3 w-3" />Clean up</button>}
            {task.cleaned && <span className="font-mono text-[11px] text-ink-5">worktree removed</span>}
            <button onClick={commit} disabled={running || task.cleaned} className="flex items-center gap-1.5 rounded-md bg-ink-1 px-2.5 py-1 text-[12px] font-medium text-page hover:bg-white disabled:bg-raised disabled:text-ink-5"><Icon n="branch" className="h-3 w-3" />{task.pr?.committed ? 'Committed' : 'Commit & PR'}</button>
            <button onClick={() => setPanel(p => !p)} className={`rounded-md p-1.5 hover:bg-hover ${panel ? 'text-ink-2' : 'text-ink-5'}`}><Icon n="panel" /></button>
          </div>
        </header>
        {mode === 'review' ? <div className="flex-1 overflow-auto"><ReviewView key={task.id + (task.turns?.length || 0) + task.status} task={task} onSentToAgent={() => { setMode('session'); setGen(g => g + 1); refreshList(); refreshArtifacts(task.id) }} /></div> : <>
        <div ref={scroller} className="flex-1 overflow-auto"><div className="mx-auto max-w-[760px] px-6 py-6">
          {(task.turns?.length ? task.turns : [undefined]).map((t, n) => <TurnView key={n} turn={t} evs={byTurn[n] || []} task={task} />)}
        </div></div>
        <div className="relative mx-auto w-full max-w-[760px] px-6 pb-5">
          {capsOpen && <div className="absolute bottom-[calc(100%-8px)] left-6 right-6 z-10 max-h-80 overflow-auto rounded-xl border border-line2 bg-raised p-3 shadow-2xl animate-fadein">
            <div className="label mb-1.5">Project skills <span className="normal-case tracking-normal text-ink-5">· .claude/skills</span></div>
            {skills.length ? skills.map(sk => <div key={sk.name} className="mb-1.5"><span className="font-mono text-[12px] text-ink-1">{sk.name}</span><div className="text-[12px] text-ink-4">{sk.description}</div></div>) : <div className="text-[12px] text-ink-5">none found</div>}
            <div className="label mb-1.5 mt-3">MCP · {caps?.mcp_server || 'dbt-factory-tools'} <span className="normal-case tracking-normal text-ink-5">· from {caps?.source}</span></div>
            <div className="flex flex-wrap gap-1">{mcpTools.map(t => <span key={t} className="rounded border border-line2 px-1.5 py-px font-mono text-[10.5px] text-ink-3">{t.split('__').pop()}</span>)}</div>
            <div className="mt-3 text-[11.5px] text-ink-5">Data access: dbt target only (read-only, LIMIT enforced). Local data files are blocked.</div>
          </div>}
          <Composer value={msg} set={setMsg} onSend={followUp} disabled={running || task.cleaned}
            placeholder={task.cleaned ? 'Worktree removed: start a new session' : running ? 'Droid is working… stop it to send a new instruction' : 'Type your message…'} chips={chips} />
        </div></>}
      </main>

      {panel && mode === 'session' && <aside className="flex w-[44%] min-w-[420px] max-w-[720px] shrink-0 flex-col border-l border-line bg-sunken">
        <div className="flex h-12 shrink-0 items-center gap-1 border-b border-line px-2">
          {([['preview', 'table', 'Data preview'], ['changes', 'diff', 'Changes'], ['sql', 'code', 'SQL'], ['plan', 'list', 'Plan'], ['gates', 'zap', 'Done']] as const).map(([k, ic, label]) =>
            <button key={k} onClick={() => setTab(k)} className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12.5px] transition ${tab === k ? 'bg-raised text-ink-1' : 'text-ink-4 hover:text-ink-2'}`}>
              <Icon n={ic} />{label}{k === 'changes' && (stats.add + stats.del > 0) && <span className="font-mono text-[10.5px]"><span className="text-[#86efac]">+{stats.add}</span> <span className="text-[#fca5a5]">−{stats.del}</span></span>}</button>)}
        </div>
        <div className="flex-1 overflow-auto">
          {tab === 'preview' && <PreviewTable prev={prev} />}
          {tab === 'changes' && <DiffView text={diff} />}
          {tab === 'sql' && (Object.keys(task.sql || {}).length ? <div className="space-y-3 p-3">{Object.entries(task.sql || {}).map(([f, s]) => <div key={f} className="overflow-hidden rounded-lg border border-line">
            <div className="flex items-center gap-2 border-b border-line bg-page px-3 py-2"><Icon n="code" className="text-accent" /><span className="font-mono text-[12px] text-ink-2">{f}</span></div>
            <pre className="overflow-auto p-3 font-mono text-[11.5px] leading-[1.65] text-ink-2">{s}</pre></div>)}</div> : <Empty>No SQL written yet.</Empty>)}
          {tab === 'gates' && <GateScorecard gate={(task as any).gate} busy={gateBusy} onRefresh={running ? undefined : async () => { setGateBusy(true); try { const g = await j(`/api/tasks/${task.id}/gate?refresh=true`); setTask(t => t && ({ ...t, gate: g } as any)) } finally { setGateBusy(false) } }} />}
          {tab === 'plan' && (task.plan ? <div className="p-5"><PlanList plan={task.plan} done={task.status === 'succeeded'} /></div> : <Empty>Waiting for the droid's plan…</Empty>)}
        </div>
        <div className="flex items-center gap-3 border-t border-line px-4 py-2 font-mono text-[10.5px] text-ink-5">
          <span>engine: {ENGINE_LABEL[taskEngine]}</span>{task.session_id && <span>session {task.session_id.slice(0, 8)}</span>}<span>{task.turns?.length || 1} turns</span><span>{evs.length} events</span>{task.preview_model && <span>model: {task.preview_model}</span>}</div>
      </aside>}
    </>}
    {toast && <div className="fixed bottom-5 left-1/2 -translate-x-1/2 animate-fadein rounded-lg border border-line2 bg-raised px-4 py-2 text-[12.5px] text-ink-1 shadow-2xl">{toast}</div>}
  </div>
}
