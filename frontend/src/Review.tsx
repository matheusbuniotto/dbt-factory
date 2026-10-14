import { useEffect, useMemo, useState } from 'react'
import { j, post, RISK_STYLE, RISK_LABEL, CHECK_LABEL, STATUS_STYLE } from './ui'

const plain = (m: string) => m.replace(/^\[(\w+)\/(\w+)\]\s*/, (_: string, _g: string, id: string) => `${(CHECK_LABEL[id] || [id])[0]} — `)
type Line = { kind: 'add' | 'del' | 'ctx' | 'hunk'; text: string; n?: number }
function parseDiff(diff: string): Line[] {
  const out: Line[] = []; let n = 0
  for (const l of diff.split('\n')) {
    if (/^(diff --git|index |--- |\+\+\+ |new file|deleted file)/.test(l)) continue
    const h = l.match(/^@@ -\d+(?:,\d+)? \+(\d+)/)
    if (h) { n = +h[1]; out.push({ kind: 'hunk', text: l }); continue }
    if (l.startsWith('+')) out.push({ kind: 'add', text: l.slice(1), n: n++ })
    else if (l.startsWith('-')) out.push({ kind: 'del', text: l.slice(1) })
    else if (l.length || out.length) { out.push({ kind: 'ctx', text: l.slice(1), n: n++ }) }
  }
  return out
}

function RiskBadge({ level, big }: { level: string; big?: boolean }) {
  return <span className={`inline-flex items-center gap-1.5 rounded-full border font-medium ${big ? 'px-3 py-1 text-[13px]' : 'px-2 py-0.5 text-[11.5px]'} ${RISK_STYLE[level] || RISK_STYLE.low}`}>
    <span className="h-1.5 w-1.5 rounded-full bg-current" />{RISK_LABEL[level] || level}</span>
}

function CommentBox({ onSave, onCancel, placeholder, autoFocus }: { onSave: (b: string) => void; onCancel?: () => void; placeholder?: string; autoFocus?: boolean }) {
  const [v, setV] = useState('')
  return <div className="rounded-lg border border-line2 bg-page p-2">
    <textarea autoFocus={autoFocus} value={v} onChange={e => setV(e.target.value)} rows={2} placeholder={placeholder || 'Leave a comment for the droid or a teammate…'}
      className="w-full resize-none bg-transparent text-[13px] text-ink-1 outline-none placeholder:text-ink-5" />
    <div className="flex justify-end gap-2">{onCancel && <button onClick={onCancel} className="rounded-md px-2.5 py-1 text-[12px] text-ink-4 hover:text-ink-2">Cancel</button>}
      <button onClick={() => { if (v.trim()) { onSave(v.trim()); setV('') } }} className="rounded-md bg-ink-1 px-2.5 py-1 text-[12px] font-medium text-page hover:bg-white">Comment</button></div></div>
}

function Thread({ c, onResolve }: { c: any; onResolve: (id: string, r: boolean) => void }) {
  return <div className={`rounded-lg border px-3 py-2 ${c.resolved ? 'border-line bg-sunken opacity-60' : 'border-[#60a5fa]/30 bg-[#60a5fa]/[.06]'}`}>
    <div className="flex items-center gap-2 text-[11.5px] text-ink-4"><span className="grid h-5 w-5 place-items-center rounded-full bg-raised text-[9px] text-ink-2">MB</span>You
      {c.path && <span className="font-mono text-ink-5">{c.path}{c.line ? `:${c.line}` : ''}</span>}
      <button onClick={() => onResolve(c.id, !c.resolved)} className="ml-auto text-ink-4 hover:text-ink-1">{c.resolved ? 'Reopen' : 'Resolve'}</button></div>
    <div className="mt-1 whitespace-pre-wrap text-[13px] text-ink-1">{c.body}</div></div>
}

function CodeDiff({ path, diff, findings, comments, onComment, onResolve }: any) {
  const lines = useMemo(() => parseDiff(diff || ''), [diff])
  const [open, setOpen] = useState<number | null>(null)
  const byLine = (n?: number) => comments.filter((c: any) => c.path === path && c.line === n)
  const findingAt = (l: Line) => l.kind === 'del' ? [] : findings.filter((f: any) => f.path === path && (f.line ? f.line === l.n : l.kind === 'add' && f.line_hint && l.text.trim().startsWith(f.line_hint.slice(0, 40))))
  if (!lines.length) return <div className="p-4 text-[12.5px] text-ink-5">No code changes in this file.</div>
  return <div className="font-mono text-[12px] leading-[1.7]">{lines.map((l, i) => {
    if (l.kind === 'hunk') return <div key={i} className="bg-sunken px-3 text-[11px] text-ink-5">{l.text}</div>
    const fs = findingAt(l); const cs = byLine(l.n)
    return <div key={i}>
      <div className={`group flex ${l.kind === 'add' ? 'bg-[#4ade80]/[.07]' : l.kind === 'del' ? 'bg-[#f87171]/[.08]' : ''}`}>
        <span className="w-10 shrink-0 select-none pr-2 text-right text-ink-6">{l.n ?? ''}</span>
        <button title="Comment on this line" onClick={() => l.n && setOpen(open === i ? null : i)} className={`w-5 shrink-0 text-center text-[#60a5fa] ${l.n ? 'opacity-0 group-hover:opacity-100' : 'invisible'}`}>+</button>
        <span className={`w-3 shrink-0 select-none ${l.kind === 'add' ? 'text-[#86efac]' : l.kind === 'del' ? 'text-[#fca5a5]' : 'text-ink-6'}`}>{l.kind === 'add' ? '+' : l.kind === 'del' ? '−' : ''}</span>
        <span className={`whitespace-pre-wrap break-all pr-3 ${l.kind === 'add' ? 'text-[#dcfce7]' : l.kind === 'del' ? 'text-[#fecaca]' : 'text-ink-3'}`}>{l.text || ' '}</span></div>
      {fs.map((f: any, k: number) => <div key={k} className={`mx-3 my-1.5 ml-[4.5rem] rounded-lg border px-3 py-2 font-sans text-[12.5px] ${f.kind === 'sql_style' ? 'border-[#60a5fa]/30 bg-[#60a5fa]/[.07] text-[#bfdbfe]' : 'border-[#facc15]/30 bg-[#facc15]/[.07] text-[#fde68a]'}`}>{f.kind === 'sql_style' ? '✎ Style' : '⚑'} {plain(f.message)}</div>)}
      {cs.map((c: any) => <div key={c.id} className="my-1.5 ml-[4.5rem] mr-3 font-sans"><Thread c={c} onResolve={onResolve} /></div>)}
      {open === i && <div className="my-1.5 ml-[4.5rem] mr-3 font-sans"><CommentBox autoFocus onCancel={() => setOpen(null)} onSave={b => { onComment({ body: b, path, line: l.n, line_hint: l.text.trim().slice(0, 80) }); setOpen(null) }} /></div>}
    </div>
  })}</div>
}

function DataCompare({ cmp }: { cmp: any }) {
  if (!cmp) return <div className="p-4 text-[12.5px] text-ink-5">Data compare runs once the droid is idle.</div>
  if (cmp.status === 'error') return <div className="p-4 text-[12.5px] text-[#fca5a5]">Could not compare: {cmp.message}</div>
  if (cmp.status === 'new_relation') return <div className="space-y-3 p-4 text-[13px]">
    <div className="rounded-lg border border-[#60a5fa]/30 bg-[#60a5fa]/[.06] px-3 py-2 text-[#bfdbfe]">This is a <b>new model</b> — nothing in production to compare against.</div>
    <Stat label="Rows in this change" value={cmp.row_count?.new} />
    <div><div className="label mb-1">Columns</div><div className="flex flex-wrap gap-1">{(cmp.columns_added || []).map((c: string) => <span key={c} className="rounded border border-line2 px-1.5 py-px font-mono text-[11px] text-ink-2">{c}</span>)}</div></div></div>
  const rc = cmp.row_count || {}; const kd = cmp.key_diff
  return <div className="space-y-4 p-4 text-[13px]">
    <div className={`rounded-lg border px-3 py-2 ${cmp.identical ? 'border-[#4ade80]/30 bg-[#4ade80]/[.06] text-[#bbf7d0]' : 'border-[#facc15]/30 bg-[#facc15]/[.06] text-[#fde68a]'}`}>
      {cmp.identical ? 'Data is identical to production.' : 'Data differs from production — check the details below.'}</div>
    <div className="grid grid-cols-3 gap-2"><Stat label="Rows in prod" value={rc.base} /><Stat label="Rows now" value={rc.new} /><Stat label="Change" value={rc.delta > 0 ? `+${rc.delta}` : rc.delta} tone={rc.delta ? 'warn' : 'ok'} /></div>
    {(cmp.columns_added?.length || cmp.columns_removed?.length || cmp.type_changes?.length) ? <div><div className="label mb-1">Schema changes</div>
      {cmp.columns_added?.map((c: string) => <div key={c} className="text-[#86efac]">+ added <span className="font-mono">{c}</span></div>)}
      {cmp.columns_removed?.map((c: string) => <div key={c} className="text-[#fca5a5]">− removed <span className="font-mono">{c}</span> (may break downstream)</div>)}
      {cmp.type_changes?.map((c: any) => <div key={c.column} className="text-[#fde68a]">~ <span className="font-mono">{c.column}</span>: {c.base} → {c.new}</div>)}</div> : null}
    {cmp.column_stat_changes?.length ? <div><div className="label mb-1">Columns whose values changed</div>
      <table className="w-full font-mono text-[11.5px]"><tbody>{cmp.column_stat_changes.map((c: any) => <tr key={c.column} className="border-b border-line/60">
        <td className="py-1 pr-2 text-ink-1">{c.column}</td><td className="text-ink-4">{Object.entries(c).filter(([k]) => k !== 'column').map(([k, v]: any) => `${k}: ${v.base} → ${v.new}`).join(' · ')}</td></tr>)}</tbody></table></div> : null}
    {kd && <div><div className="label mb-1">Row-by-row (key {kd.key})</div>
      <div className="grid grid-cols-4 gap-2"><Stat label="Matched" value={kd.compared_rows} /><Stat label="Only in prod" value={kd.only_in_base} tone={kd.only_in_base ? 'warn' : 'ok'} /><Stat label="New rows" value={kd.only_in_new} tone={kd.only_in_new ? 'warn' : 'ok'} /><Stat label="Changed" value={kd.changed_rows} tone={kd.changed_rows ? 'warn' : 'ok'} /></div></div>}
  </div>
}
const Stat = ({ label, value, tone }: any) => <div className="rounded-lg border border-line bg-sunken px-3 py-2"><div className="text-[11px] text-ink-5">{label}</div>
  <div className={`font-mono text-[16px] ${tone === 'warn' ? 'text-[#fde68a]' : tone === 'ok' ? 'text-[#86efac]' : 'text-ink-1'}`}>{value ?? '—'}</div></div>

export default function ReviewView({ task, onSentToAgent }: { task: any; onSentToAgent: () => void }) {
  const [rev, setRev] = useState<any>(null); const [loading, setLoading] = useState(false); const [err, setErr] = useState('')
  const [verdict, setVerdict] = useState<'approve' | 'request_changes'>('approve'); const [msg, setMsg] = useState(''); const [postGh, setPostGh] = useState(false)
  const [toast, setToast] = useState('')
  const load = (refresh = false) => { setLoading(true); setErr(''); j(`/api/tasks/${task.id}/review${refresh ? '?refresh=true' : ''}`).then(r => { setRev(r); if (r.verdict && r.verdict.verdict !== 'comment') setVerdict(r.verdict.verdict); else setVerdict(r.risk === 'high' || (r.findings || []).some((f: any) => f.severity === 'high') ? 'request_changes' : 'approve') }).catch(e => setErr(String(e.message || e))).finally(() => setLoading(false)) }
  useEffect(() => { load() }, [task.id])
  const comments = rev?.comments || []
  const addComment = async (c: any) => { await post(`/api/tasks/${task.id}/comments`, c); load() }
  const resolve = async (id: string, r: boolean) => { await post(`/api/tasks/${task.id}/comments/${id}/resolve?resolved=${r}`); load() }
  const flash = (s: string) => { setToast(s); setTimeout(() => setToast(''), 4000) }
  const sendToAgent = async () => { try { await post(`/api/tasks/${task.id}/comments/send-to-agent`); flash('Sent open comments to the droid as a follow-up'); onSentToAgent() } catch (e: any) { flash(e.message) } }
  const submit = async () => { try { const r = await post(`/api/tasks/${task.id}/verdict`, { verdict, body: msg, post_to_github: postGh }); flash(postGh ? `Verdict saved · GitHub: ${r.gh}` : 'Verdict saved'); load() } catch (e: any) { flash(e.message) } }
  if (err) return <div className="p-8 text-[13px] text-[#fca5a5]">{err}</div>
  if (!rev) return <div className="grid h-full place-items-center text-[13px] text-ink-4"><span className="shimmer-text">Preparing review — running checks and comparing data with production…</span></div>
  const open = comments.filter((c: any) => !c.resolved)
  return <div className="mx-auto max-w-[1400px] space-y-5 p-6">
    {/* summary */}
    <section className="rounded-2xl border border-line bg-sunken p-5">
      <div className="flex flex-wrap items-center gap-3"><RiskBadge level={rev.risk} big /><h2 className="text-[16px] font-medium text-ink-1">Review this change</h2>
        <button onClick={() => load(true)} disabled={loading} className="ml-auto rounded-md border border-line2 px-2.5 py-1 text-[12px] text-ink-3 hover:text-ink-1 disabled:opacity-50">{loading ? 'Refreshing…' : 'Refresh checks'}</button></div>
      <p className="mt-2 text-[13.5px] leading-6 text-ink-2">{rev.summary}</p>
      {rev.look_first?.length > 0 && <div className="mt-3"><div className="label mb-1.5">Look at these first</div>
        <ol className="space-y-1">{rev.look_first.map((x: any, i: number) => <li key={i} className="flex gap-2 text-[13px]"><span className="text-ink-5">{i + 1}.</span><span className="font-mono text-ink-1">{x.model}</span><span className="text-ink-4">— {plain(x.why)}</span></li>)}</ol></div>}
    </section>

    {rev.style?.guide && <details className="rounded-2xl border border-line px-5 py-3"><summary className="cursor-pointer text-[13px] text-ink-2">Team SQL style guide <span className="text-ink-5">· {rev.style.summary}</span></summary>
      <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap font-mono text-[12px] leading-5 text-ink-3">{rev.style.guide}</pre></details>}
    {(rev.models || []).map((m: any) => <section key={m.model} className="overflow-hidden rounded-2xl border border-line">
      <header className="flex flex-wrap items-center gap-3 border-b border-line bg-sunken px-5 py-3">
        <span className="font-mono text-[14px] text-ink-1">{m.model}</span><RiskBadge level={m.risk.level} />
        <span className="text-[12px] text-ink-4">{m.path}</span>
        <span className="ml-auto text-[12.5px] text-ink-3">{m.impact.count ? <>Affects <b className="text-ink-1">{m.impact.count}</b> downstream model{m.impact.count > 1 ? 's' : ''}</> : 'No downstream models affected'}</span></header>
      <div className="grid gap-4 border-b border-line px-5 py-3 md:grid-cols-2">
        <div><div className="label mb-1.5">Why this risk level</div><ul className="space-y-1 text-[13px] text-ink-2">{m.risk.reasons.map((r: string) => <li key={r} className="flex gap-2"><span className="text-ink-5">•</span>{r[0].toUpperCase() + r.slice(1)}</li>)}</ul></div>
        <div><div className="label mb-1.5">Downstream impact</div>{m.impact.count ? <div className="flex flex-wrap gap-1.5">{[...m.impact.downstream_models, ...m.impact.exposures].map((u: string) =>
          <span key={u} className="rounded-md border border-line2 px-2 py-0.5 font-mono text-[11.5px] text-ink-2">{u.split('.').pop()}<span className="ml-1 text-ink-5">{u.split('.')[0]}</span></span>)}</div> : <div className="text-[13px] text-ink-4">Nothing depends on this model yet.</div>}</div>
      </div>
      {m.gate?.checks && <div className="flex flex-wrap gap-1.5 border-b border-line px-5 py-2.5">{m.gate.checks.map((c: any) => { const st = STATUS_STYLE[c.status] || STATUS_STYLE.skip
        return <span key={c.id} title={c.detail} className="flex items-center gap-1.5 rounded-full border border-line px-2 py-0.5 text-[11.5px] text-ink-3"><span className={`h-1.5 w-1.5 rounded-full ${st.dot}`} />{(CHECK_LABEL[c.id] || [c.id])[0]}</span> })}</div>}
      <div className="grid min-h-[260px] md:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <div className="border-r border-line"><div className="label border-b border-line px-4 py-2">Code changes</div>
          <div className="max-h-[520px] overflow-auto"><CodeDiff path={m.path} diff={m.diff} findings={rev.findings || []} comments={comments} onComment={addComment} onResolve={resolve} /></div></div>
        <div><div className="label border-b border-line px-4 py-2">Data vs production</div><div className="max-h-[520px] overflow-auto"><DataCompare cmp={m.compare} /></div></div>
      </div>
    </section>)}

    {(rev.findings || []).filter((f: any) => !f.line_hint && !f.line).length > 0 && <section className="rounded-2xl border border-line p-5"><div className="label mb-2">Findings</div>
      <div className="space-y-1.5">{rev.findings.filter((f: any) => !f.line_hint && !f.line).map((f: any, i: number) => <div key={i} className="flex gap-2 text-[13px]">
        <span className={`mt-0.5 rounded px-1.5 text-[10.5px] ${f.severity === 'high' ? 'bg-[#f87171]/15 text-[#fca5a5]' : 'bg-[#facc15]/15 text-[#fde68a]'}`}>{f.severity}</span>
        <span className="text-ink-2">{plain(f.message)}</span>
        <button onClick={() => addComment({ body: `Please fix: ${plain(f.message)}`, path: f.path, finding_id: f.kind })} className="ml-auto shrink-0 text-[12px] text-[#93c5fd] hover:underline">Turn into comment</button></div>)}</div></section>}

    <section className="grid gap-5 md:grid-cols-2">
      <div className="rounded-2xl border border-line p-5"><div className="mb-2 flex items-center"><div className="label">Comments</div><span className="ml-2 text-[11.5px] text-ink-5">{open.length} open · {comments.length - open.length} resolved</span>
        <button onClick={sendToAgent} disabled={!open.length || task.status === 'running'} className="ml-auto rounded-md bg-accent px-2.5 py-1 text-[12px] font-medium text-page hover:bg-accent-2 disabled:bg-raised disabled:text-ink-5">Send to droid</button></div>
        <div className="mb-3 space-y-2">{comments.filter((c: any) => !c.line).map((c: any) => <Thread key={c.id} c={c} onResolve={resolve} />)}
          {!comments.length && <div className="text-[12.5px] text-ink-5">No comments yet. Hover a code line and click + to comment on it, or leave a general comment below.</div>}</div>
        <CommentBox onSave={b => addComment({ body: b })} placeholder="General comment…" /></div>
      <div className="rounded-2xl border border-line p-5"><div className="label mb-3">Your verdict</div>
        <div className="mb-3 grid grid-cols-2 gap-2">
          <button onClick={() => setVerdict('approve')} className={`rounded-xl border px-3 py-3 text-left ${verdict === 'approve' ? 'border-[#4ade80]/50 bg-[#4ade80]/10' : 'border-line hover:border-line2'}`}>
            <div className="text-[13.5px] font-medium text-ink-1">✓ Approve</div><div className="text-[12px] text-ink-4">Looks right, ship it</div></button>
          <button onClick={() => setVerdict('request_changes')} className={`rounded-xl border px-3 py-3 text-left ${verdict === 'request_changes' ? 'border-[#f87171]/50 bg-[#f87171]/10' : 'border-line hover:border-line2'}`}>
            <div className="text-[13.5px] font-medium text-ink-1">✎ Request changes</div><div className="text-[12px] text-ink-4">Needs another pass</div></button></div>
        <textarea value={msg} onChange={e => setMsg(e.target.value)} rows={3} placeholder="Message for the author (optional)…" className="w-full resize-none rounded-lg border border-line2 bg-page p-2.5 text-[13px] text-ink-1 outline-none placeholder:text-ink-5" />
        <label className="mt-2 flex items-center gap-2 text-[12.5px] text-ink-3"><input type="checkbox" checked={postGh} onChange={e => setPostGh(e.target.checked)} />Also post to the GitHub pull request{task.pr?.pr_url ? '' : ' (needs a PR — use Commit & PR first)'}</label>
        <button onClick={submit} className={`mt-3 w-full rounded-lg py-2 text-[13px] font-medium ${verdict === 'approve' ? 'bg-[#4ade80] text-page hover:bg-[#86efac]' : 'bg-[#f87171] text-page hover:bg-[#fca5a5]'}`}>Submit {verdict === 'approve' ? 'approval' : 'change request'}</button>
        {rev.verdict && <div className="mt-2 text-[12px] text-ink-4">Last verdict: <b className="text-ink-2">{rev.verdict.verdict.replace('_', ' ')}</b>{rev.verdict.gh ? ` · GitHub: ${rev.verdict.gh}` : ''}</div>}</div>
    </section>
    {toast && <div className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-lg border border-line2 bg-raised px-4 py-2 text-[12.5px] text-ink-1 shadow-2xl">{toast}</div>}
  </div>
}
