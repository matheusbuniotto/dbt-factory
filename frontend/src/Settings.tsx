import { useEffect, useState, type ChangeEvent } from 'react'
import { selectedProjectId } from './projectsData'
import { j } from './ui'

const styleUrl = () => `/api/style?project_id=${encodeURIComponent(selectedProjectId())}`

type StyleSrc = { source?: string; text?: string } | null
type StyleState = { summary?: string; dialect?: string; order?: string[]; rules?: StyleSrc; guide?: StyleSrc }
type Field = [label: string, value: string, set: (s: string) => void, placeholder: string, accept: string]
export type StyleCapsInfo = { summary?: string; dialect?: string }

const OPEN_EVENT = 'factory:sql-style-settings'
const openSettings = () => window.dispatchEvent(new Event(OPEN_EVENT))

/** Sidebar button + the settings dialog; StyleCaps' "edit" opens it too. */
export function SettingsEntry() {
  const [open, setOpen] = useState(new URLSearchParams(location.search).get('settings') === '1')
  useEffect(() => {
    const on = () => setOpen(true)
    window.addEventListener(OPEN_EVENT, on)
    return () => window.removeEventListener(OPEN_EVENT, on)
  }, [])
  return (
    <>
      <SettingsButton onClick={() => setOpen(true)} />
      {open && <SettingsDialog onClose={() => setOpen(false)} />}
    </>
  )
}

function SettingsButton({ onClick }: { onClick: () => void }) {
  return (
    <button onClick={onClick} className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-ink-2 hover:bg-hover">
      <span className="w-4 text-center text-[13px] text-ink-3">⚙</span>
      Settings · SQL style
    </button>
  )
}

/** SQL style line + data-access note for the capabilities popover. */
export function StyleCaps({ style }: { style?: StyleCapsInfo }) {
  return (
    <>
      <div className="label mb-1 mt-3">SQL style</div>
      <div className="text-[12px] text-ink-3">
        {style?.summary || 'default'} <span className="text-ink-5">· dialect {style?.dialect}</span>{' '}
        <button onClick={openSettings} className="ml-1 text-[#93c5fd] hover:underline">
          edit
        </button>
      </div>
      <div className="mt-3 text-[11.5px] text-ink-5">
        Data access: dbt target only (read-only, LIMIT enforced). Local data files are blocked.
      </div>
    </>
  )
}

function SettingsDialog({ onClose }: { onClose: () => void }) {
  const [st, setSt] = useState<StyleState | null>(null)
  const [rules, setRules] = useState('')
  const [guide, setGuide] = useState('')
  const [msg, setMsg] = useState('')
  const load = () =>
    j(styleUrl()).then((s) => {
      setSt(s)
      setRules(s.rules?.text || '')
      setGuide(s.guide?.text || '')
    })
  useEffect(() => {
    load()
  }, [])
  const file = (set: (s: string) => void) => (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) f.text().then(set)
  }
  const save = async () => {
    try {
      await j(styleUrl(), {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ sqlfluff: rules, guide }),
      })
      setMsg('Saved in dbt-factory settings for this project')
      load()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    }
  }
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-6" onClick={onClose}>
      <div
        className="max-h-full w-full max-w-[900px] overflow-auto rounded-2xl border border-line2 bg-sunken p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-1 flex items-center">
          <h2 className="text-[16px] font-medium text-ink-1">Settings · SQL style</h2>
          <button onClick={onClose} className="ml-auto text-ink-4 hover:text-ink-1">
            ✕
          </button>
        </div>
        <p className="mb-4 text-[12.5px] text-ink-4">
          Active: <span className="text-ink-2">{st?.summary || '…'}</span> · dialect{' '}
          <span className="font-mono text-ink-2">{st?.dialect}</span>. Lookup order: {st?.order?.join(' → ')}. Repo style files (
          <span className="font-mono">.sqlfluff</span>, <span className="font-mono">.factory/config.yml</span>) win over what you save here.
        </p>
        <div className="grid gap-4 md:grid-cols-2">
          {(
            [
              [
                'Machine rules (sqlfluff config)',
                rules,
                setRules,
                '[sqlfluff]\ntemplater = jinja\nmax_line_length = 100\n\n[sqlfluff:rules:capitalisation.keywords]\ncapitalisation_policy = lower',
                '.sqlfluff,.cfg,.ini',
              ],
              [
                'Style guide (markdown, given to the agent and reviewer)',
                guide,
                setGuide,
                '# SQL style\n- lowercase keywords\n- one CTE per source…',
                '.md,.txt',
              ],
            ] as Field[]
          ).map(([label, v, set, ph, acc]) => (
            <div key={label}>
              <div className="mb-1.5 flex items-center">
                <span className="label">{label}</span>
                <span className="ml-2 text-[11px] text-ink-5">
                  {(label.startsWith('Machine') ? st?.rules : st?.guide)?.source || 'none'}
                </span>
                <label className="ml-auto cursor-pointer text-[12px] text-[#93c5fd] hover:underline">
                  Upload
                  <input type="file" accept={acc} className="hidden" onChange={file(set)} />
                </label>
              </div>
              <textarea
                value={v}
                onChange={(e) => set(e.target.value)}
                rows={16}
                placeholder={ph}
                className="w-full resize-y rounded-lg border border-line2 bg-page p-3 font-mono text-[12px] text-ink-1 outline-none placeholder:text-ink-6"
              />
            </div>
          ))}
        </div>
        <div className="mt-4 flex items-center gap-3">
          <button onClick={save} className="rounded-lg bg-accent px-4 py-2 text-[13px] font-medium text-page hover:bg-accent-2">
            Save style
          </button>
          <span className="text-[12px] text-ink-4">{msg}</span>
          <span className="ml-auto text-[11.5px] text-ink-5">
            Prefilled with the active style. Saved in dbt-factory state for the selected project, never in your repo (empty box removes it).
          </span>
        </div>
      </div>
    </div>
  )
}
