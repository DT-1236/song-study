import type { SongReadiness } from './api'

// A song's readiness as a bar and the counts behind it.
export function ReadinessMeter({ readiness }: { readiness: SongReadiness }) {
  if (readiness.words === 0) return <span>—</span>
  const percent = Math.round(readiness.readiness * 100)

  return (
    <div className="readiness">
      <div
        className="readiness-bar"
        role="meter"
        aria-label="Readiness"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <div className="readiness-fill" style={{ width: `${percent}%` }} />
      </div>
      <span className="readiness-percent">{percent}%</span>
      <span className="readiness-counts">
        {readiness.words} words · {readiness.enrolled} enrolled ·{' '}
        {readiness.mature} mature · {readiness.due} due
      </span>
    </div>
  )
}
