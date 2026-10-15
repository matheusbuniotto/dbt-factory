import { useState } from 'react'
import type { Project } from './projectsData'
import { post } from './ui'

const MODE_LABEL: Record<string, string> = { dbt: 'dbt', sql: 'plain SQL', unsupported: 'unsupported' }

function Badge({ children, tone = 'muted' }: { children: React.ReactNode; tone?: 'muted' | 'ok' | 'warn' | 'bad' }) {
  const cls = {
    muted: 'border-line2 text-ink-4',
    ok: 'border-[#4ade80]/30 text-[#86efac]',
    warn: 'border-[#facc15]/40 text-[#fde68a]',
    bad: 'border-[#f87171]/40 text-[#fca5a5]',
  }[tone]
  return <span className={`rounded border px-1.5 py-px font-mono text-[10px] ${cls}`}>{children}</span>
}

/** Project picker on the new-session screen: choose / add a local repo and see what was detected. */
export function ProjectPicker({
  projects,
  current,
  onSelect,
  onChanged,
}: {
  projects: Project[]
  current?: Project
  onSelect: (id: string) => void
  onChanged: () => void
}) {
  const [adding, setAdding] = useState(false)
  const [path, setPath] = useState('')
  const [err, setErr] = useState('')
  const add = async () => {
    setErr('')
    try {
      const p = await post('/api/projects', { path })
      setPath('')
      setAdding(false)
      onChanged()
      onSelect(p.id)
    } catch (e) {
      setErr((e as Error).message)
    }
  }
  return (
    <div className="mb-4 rounded-lg border border-line bg-sunken p-3 text-[12.5px]">
      <div className="flex items-center gap-2">
        <span className="label">Project</span>
        <select
          value={current?.id || ''}
          onChange={(e) => onSelect(e.target.value)}
          className="min-w-0 flex-1 rounded-md border border-line2 bg-page px-2 py-1 text-ink-1 outline-none"
          aria-label="Project"
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} — {p.path}
            </option>
          ))}
        </select>
        <button onClick={() => setAdding((a) => !a)} className="rounded-md border border-line2 px-2 py-1 text-ink-2 hover:bg-hover">
          {adding ? 'Cancel' : 'Add repo'}
        </button>
      </div>
      {adding && (
        <div className="mt-2 flex items-center gap-2">
          <input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && add()}
            placeholder="/absolute/path/to/your/repo"
            className="min-w-0 flex-1 rounded-md border border-line2 bg-page px-2 py-1 font-mono text-ink-1 outline-none"
            autoFocus
          />
          <button onClick={add} disabled={!path.trim()} className="rounded-md bg-accent px-2.5 py-1 text-black disabled:opacity-40">
            Register
          </button>
        </div>
      )}
      {err && <div className="mt-2 text-[#fca5a5]">{err}</div>}
      {current && <ProjectFacts p={current} />}
    </div>
  )
}

function ProjectFacts({ p }: { p: Project }) {
  return (
    <div className="mt-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone={p.ready ? 'ok' : 'bad'}>{p.ready ? 'ready' : 'not ready'}</Badge>
        {p.mode && <Badge>{MODE_LABEL[p.mode]}</Badge>}
        {p.adapter && <Badge>{p.adapter}</Badge>}
        {p.dbt_dir_rel && p.dbt_dir_rel !== '.' && <Badge>dbt in {p.dbt_dir_rel}</Badge>}
        {p.dev_target && (
          <Badge>
            dev {p.dev_target} → prod {p.prod_target || `${p.dev_target} (read-only)`}
          </Badge>
        )}
        {p.profiles_source && <Badge>profile: {p.profiles_source}</Badge>}
        {p.dbt_version && <Badge>dbt {p.dbt_version}</Badge>}
      </div>
      {[...(p.errors || [])].map((e) => (
        <div key={e} className="mt-1.5 text-[#fca5a5]">
          {e}
        </div>
      ))}
      {[...(p.warnings || [])].map((w) => (
        <div key={w} className="mt-1.5 text-[#fde68a]">
          {w}
        </div>
      ))}
    </div>
  )
}
