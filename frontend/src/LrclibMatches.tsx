import { useEffect, useState } from 'react'
import { errorMessage, searchLrclib } from './api'
import type { LrclibCandidate, SongResult } from './api'
import { formatDuration } from './timing'
import { useLatest } from './useLatest'

function CandidateOption({
  candidate,
  checked,
  onSelect,
}: {
  candidate: LrclibCandidate
  checked: boolean
  onSelect: () => void
}) {
  const { duration, duration_delta: delta } = candidate
  return (
    <li>
      <label className="lrclib-match">
        <input
          type="radio"
          name="lrclib-match"
          checked={checked}
          onChange={onSelect}
        />
        <span className="lrclib-match-text">
          <span>
            {[candidate.track_name, candidate.artist_name, candidate.album_name]
              .filter(Boolean)
              .join(' · ')}
          </span>
          <span className="lrclib-match-meta">
            {duration !== null && formatDuration(duration)}
            {delta !== null &&
              ` (${delta > 0 ? '+' : ''}${Math.round(delta)}s)`}
            {candidate.synced && (
              <span className="lrclib-match-badge">synced</span>
            )}
          </span>
          {candidate.preview.length > 0 && (
            <span className="lrclib-match-meta">
              {candidate.preview.join(' / ')}
            </span>
          )}
        </span>
      </label>
    </li>
  )
}

// Lists the LRCLIB tracks matching the picked song, and reports the chosen one
// (or null for "none"). Matches whose length differs from the song's sit behind
// a toggle. A synced match within tolerance is chosen up front.
export function LrclibMatches({
  song,
  onChoose,
}: {
  song: SongResult
  onChoose: (candidate: LrclibCandidate | null) => void
}) {
  const [candidates, setCandidates] = useState<LrclibCandidate[] | null>(null)
  const [chosenId, setChosenId] = useState<number | null>(null)
  const [showOthers, setShowOthers] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const onChooseRef = useLatest(onChoose)

  useEffect(() => {
    let cancelled = false
    setCandidates(null)
    setChosenId(null)
    setShowOthers(false)
    setError(null)
    onChooseRef.current(null)

    searchLrclib({
      title: song.title,
      artist: song.artists,
      durationSeconds: song.duration_seconds,
    })
      .then((found) => {
        if (cancelled) return
        setCandidates(found)
        const first = found[0]
        if (first?.within_tolerance && first.synced) {
          setChosenId(first.id)
          onChooseRef.current(first)
        }
      })
      .catch((err) => {
        if (cancelled) return
        setError(errorMessage(err, 'LRCLIB search failed.'))
      })

    return () => {
      cancelled = true
    }
  }, [song, onChooseRef])

  function choose(candidate: LrclibCandidate | null) {
    setChosenId(candidate?.id ?? null)
    onChoose(candidate)
  }

  if (error) return <p className="form-error">{error}</p>
  if (candidates === null) return <p>Searching LRCLIB…</p>

  const matching = candidates.filter((c) => c.within_tolerance)
  const others = candidates.filter((c) => !c.within_tolerance)

  return (
    <fieldset className="lrclib-matches">
      <legend>Lyrics from LRCLIB</legend>
      <ul>
        {matching.map((c) => (
          <CandidateOption
            key={c.id}
            candidate={c}
            checked={chosenId === c.id}
            onSelect={() => choose(c)}
          />
        ))}
        {showOthers &&
          others.map((c) => (
            <CandidateOption
              key={c.id}
              candidate={c}
              checked={chosenId === c.id}
              onSelect={() => choose(c)}
            />
          ))}
        <li>
          <label className="lrclib-match">
            <input
              type="radio"
              name="lrclib-match"
              checked={chosenId === null}
              onChange={() => choose(null)}
            />
            <span>None — I'll paste the lyrics</span>
          </label>
        </li>
      </ul>
      {others.length > 0 && (
        <button
          type="button"
          className="lrclib-matches-toggle"
          onClick={() => setShowOthers((shown) => !shown)}
        >
          {showOthers ? 'Hide' : `Show ${others.length} with other lengths`}
        </button>
      )}
    </fieldset>
  )
}
