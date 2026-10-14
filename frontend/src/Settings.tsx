import { useEffect, useState } from 'react'
import { j } from './ui'

export default function Settings({ onClose }: { onClose: () => void }) {
  const [st, setSt] = useState<any>(null); const [rules, setRules] = useState(''); const [guide, setGuide] = useState(''); const [msg, setMsg] = useState('')
  const load = () => j('/api/style').then(s => { setSt(s); setRules(s.rules?.text || ''); setGuide(s.guide?.text || '') })
  useEffect(() => { load() }, [])
  const file = (set: (s: string) => void) => (e: any) => { const f = e.target.files?.[0]; if (f) f.text().then(set) }
  const save = async () => { try { await j('/api/style', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ sqlfluff: rules, guide }) }); setMsg('Saved to project .factory/'); load() } catch (e: any) { setMsg(e.message) } }
  return <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-6" onClick={onClose}>
    <div className="max-h-full w-full max-w-[900px] overflow-auto rounded-2xl border border-line2 bg-sunken p-6" onClick={e => e.stopPropagation()}>
      <div className="mb-1 flex items-center"><h2 className="text-[16px] font-medium text-ink-1">Settings · SQL style</h2><button onClick={onClose} className="ml-auto text-ink-4 hover:text-ink-1">✕</button></div>
      <p className="mb-4 text-[12.5px] text-ink-4">Active: <span className="text-ink-2">{st?.summary || '…'}</span> · dialect <span className="font-mono text-ink-2">{st?.dialect}</span>. Lookup order: {st?.order?.join(' → ')}. A repo <span className="font-mono">.sqlfluff</span> wins over what you save here.</p>
      <div className="grid gap-4 md:grid-cols-2">
        {[['Machine rules (sqlfluff config)', rules, setRules, '[sqlfluff]\ntemplater = jinja\nmax_line_length = 100\n\n[sqlfluff:rules:capitalisation.keywords]\ncapitalisation_policy = lower', '.sqlfluff,.cfg,.ini'],
          ['Style guide (markdown, given to the agent and reviewer)', guide, setGuide, '# SQL style\n- lowercase keywords\n- one CTE per source…', '.md,.txt']].map(([label, v, set, ph, acc]: any) =>
          <div key={label}><div className="mb-1.5 flex items-center"><span className="label">{label}</span><span className="ml-2 text-[11px] text-ink-5">{(label.startsWith('Machine') ? st?.rules : st?.guide)?.source || 'none'}</span>
            <label className="ml-auto cursor-pointer text-[12px] text-[#93c5fd] hover:underline">Upload<input type="file" accept={acc} className="hidden" onChange={file(set)} /></label></div>
            <textarea value={v} onChange={e => set(e.target.value)} rows={16} placeholder={ph} className="w-full resize-y rounded-lg border border-line2 bg-page p-3 font-mono text-[12px] text-ink-1 outline-none placeholder:text-ink-6" /></div>)}
      </div>
      <div className="mt-4 flex items-center gap-3"><button onClick={save} className="rounded-lg bg-accent px-4 py-2 text-[13px] font-medium text-page hover:bg-accent-2">Save style</button>
        <span className="text-[12px] text-ink-4">{msg}</span><span className="ml-auto text-[11.5px] text-ink-5">Prefilled with the active style. Saving writes the project's .factory/ (empty box removes it).</span></div>
    </div></div>
}
