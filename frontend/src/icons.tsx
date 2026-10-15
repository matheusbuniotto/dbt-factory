/* ---------- tiny icon set (stroke, 14px) ---------- */
export const I = {
  plus: <path d="M8 3v10M3 8h10" />,
  search: (
    <>
      <circle cx="7" cy="7" r="4.5" />
      <path d="M10.5 10.5 14 14" />
    </>
  ),
  chev: <path d="M6 4l4 4-4 4" />,
  term: (
    <>
      <path d="M3 4.5 6.5 8 3 11.5" />
      <path d="M8 12h5" />
    </>
  ),
  file: (
    <>
      <path d="M4 2h5l3 3v9H4z" />
      <path d="M9 2v3h3" />
    </>
  ),
  edit: (
    <>
      <path d="M3 13h3l7-7-3-3-7 7z" />
    </>
  ),
  glob: (
    <>
      <circle cx="8" cy="8" r="5.5" />
      <path d="M2.5 8h11M8 2.5c2 2 2 9 0 11M8 2.5c-2 2-2 9 0 11" />
    </>
  ),
  zap: <path d="M9 1.5 3.5 9H8l-1 5.5L12.5 7H8z" />,
  stop: <rect x="4" y="4" width="8" height="8" rx="1.5" />,
  up: <path d="M8 13V3M4 7l4-4 4 4" />,
  branch: (
    <>
      <circle cx="4.5" cy="3.5" r="1.5" />
      <circle cx="4.5" cy="12.5" r="1.5" />
      <circle cx="11.5" cy="6" r="1.5" />
      <path d="M4.5 5v6M11.5 7.5c0 2.5-7 1.5-7 3.5" />
    </>
  ),
  trash: (
    <>
      <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.7 9h5.6l.7-9" />
    </>
  ),
  check: <path d="M3.5 8.5 6.5 11.5 12.5 4.5" />,
  table: (
    <>
      <rect x="2.5" y="3" width="11" height="10" rx="1.5" />
      <path d="M2.5 6.5h11M6.5 6.5V13" />
    </>
  ),
  diff: (
    <>
      <path d="M5 2v7M1.5 5.5h7M8 12.5h6.5" />
    </>
  ),
  list: (
    <>
      <path d="M6 4h7.5M6 8h7.5M6 12h7.5" />
      <circle cx="3" cy="4" r=".6" />
      <circle cx="3" cy="8" r=".6" />
      <circle cx="3" cy="12" r=".6" />
    </>
  ),
  code: <path d="M5.5 4.5 2 8l3.5 3.5M10.5 4.5 14 8l-3.5 3.5" />,
  panel: (
    <>
      <rect x="2" y="3" width="12" height="10" rx="1.5" />
      <path d="M10 3v10" />
    </>
  ),
}
export const Icon = ({ n, className = '' }: { n: keyof typeof I; className?: string }) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.4}
    strokeLinecap="round"
    strokeLinejoin="round"
    className={`h-3.5 w-3.5 shrink-0 ${className}`}
  >
    {I[n]}
  </svg>
)

export const Logo = () => (
  <svg viewBox="0 0 24 24" className="h-[18px] w-[18px] text-ink-1" fill="currentColor">
    {[0, 45, 90, 135, 180, 225, 270, 315].map((r) => (
      <path key={r} transform={`rotate(${r} 12 12)`} d="M12 12c-.6-2.6-.2-5.6 1.6-8.6 1 2.8.6 5.8-1.6 8.6z" opacity={0.92} />
    ))}
  </svg>
)

export function StatusDot({ s }: { s: string }) {
  if (s === 'running')
    return (
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-60" />
        <span className="relative h-2 w-2 rounded-full bg-accent" />
      </span>
    )
  const c: Record<string, string> = { succeeded: 'bg-[#4ade80]/80', failed: 'bg-[#f87171]', cancelled: 'bg-ink-5', interrupted: 'bg-ink-5' }
  return <span className={`h-1.5 w-1.5 rounded-full ${c[s] || 'bg-ink-5'}`} />
}
