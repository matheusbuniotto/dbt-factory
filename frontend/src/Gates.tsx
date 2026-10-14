import { STATUS_STYLE, CHECK_LABEL } from './ui'

export function GateChip({ gate }: { gate: any }) {
  if (!gate?.checks) return null
  const counted = gate.checks.filter((c: any) => c.status !== 'skip')
  const ok = counted.filter((c: any) => c.status === 'pass' || c.status === 'waived').length
  return <span className={`flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-mono text-[11px] ${gate.passed ? 'border-[#4ade80]/30 text-[#86efac]' : 'border-[#f87171]/35 text-[#fca5a5]'}`}>
    <span className={`h-1.5 w-1.5 rounded-full ${gate.passed ? 'bg-[#4ade80]' : 'bg-[#f87171]'}`} />Done {ok}/{counted.length}</span>
}

export function GateScorecard({ gate, onRefresh, busy }: { gate: any; onRefresh?: () => void; busy?: boolean }) {
  if (!gate?.checks) return <div className="grid h-full place-items-center p-8 text-[12.5px] text-ink-5">The Definition of Done runs after each droid turn.</div>
  const groups: [string, string][] = [['code', 'Code'], ['data', 'Data']]
  const s = gate.summary || {}
  return <div className="p-4">
    <div className={`mb-4 rounded-xl border p-4 ${gate.passed ? 'border-[#4ade80]/25 bg-[#4ade80]/[.06]' : 'border-[#f87171]/25 bg-[#f87171]/[.06]'}`}>
      <div className="flex items-center gap-3">
        <div className={`grid h-9 w-9 place-items-center rounded-full text-[15px] ${gate.passed ? 'bg-[#4ade80]/20 text-[#86efac]' : 'bg-[#f87171]/20 text-[#fca5a5]'}`}>{gate.passed ? '✓' : '!'}</div>
        <div><div className="text-[14px] font-medium text-ink-1">{gate.passed ? 'Definition of Done met' : 'Not done yet'}</div>
          <div className="text-[12px] text-ink-4">for <span className="font-mono text-ink-2">{gate.model}</span>{gate.grain && <> · grain <span className="font-mono text-ink-2">{gate.grain.join(', ')}</span></>}</div></div>
        {onRefresh && <button onClick={onRefresh} disabled={busy} className="ml-auto rounded-md border border-line2 px-2.5 py-1 text-[12px] text-ink-3 hover:text-ink-1 disabled:opacity-50">{busy ? 'Running…' : 'Re-run'}</button>}
      </div>
      <div className="mt-3 flex gap-4 font-mono text-[11px]">{(['pass', 'fail', 'warn', 'waived', 'skip'] as const).map(k => s[k] ? <span key={k} className={STATUS_STYLE[k].text}>{s[k]} {STATUS_STYLE[k].label.toLowerCase()}</span> : null)}</div>
    </div>
    {groups.map(([g, title]) => {
      const cs = gate.checks.filter((c: any) => (c.group || 'data') === g)
      if (!cs.length) return null
      return <div key={g} className="mb-4"><div className="label mb-2">{title} checks</div>
        <div className="overflow-hidden rounded-xl border border-line">{cs.map((c: any) => { const st = STATUS_STYLE[c.status] || STATUS_STYLE.skip; const [name, help] = CHECK_LABEL[c.id] || [c.id, '']
          return <div key={c.id} className="flex gap-3 border-b border-line px-3.5 py-2.5 last:border-0">
            <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${st.dot}`} />
            <div className="min-w-0 flex-1"><div className="flex items-baseline gap-2"><span className="text-[13px] text-ink-1">{name}</span><span className={`text-[11px] ${st.text}`}>{st.label}</span><span className="ml-auto truncate text-[11px] text-ink-5">{help}</span></div>
              <div className="mt-0.5 break-words font-mono text-[11.5px] leading-5 text-ink-4">{c.detail}</div></div></div> })}</div></div>
    })}
  </div>
}
