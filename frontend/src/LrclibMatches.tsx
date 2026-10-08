import { useEffect, useState } from 'react'
import { errorMessage, searchLrclib } from './api'
import type { LrclibCandidate, SongResult } from './api'
import { formatDuration } from './timing'
import { useLatest } from './useLatest'

const NONE_LABEL = "None — I'll paste the lyrics"

function CandidateText({ candidate }: { candidate: LrclibCandidate }) {
  const { duration, duration_delta: delta } = candidate
  return (
    <span className="song-result-text">
      <span className="song-result-title">{candidate.track_name}</span>
      <span className="song-result-meta">
        {[candidate.artist_name, candidate.album_name]
          .filter(Boolean)
          .join(' · ')}
      </span>
      <span className="song-result-meta">
        {duration !== null && formatDuration(duration)}
        {delta !== null && ` (${delta > 0 ? '+' : ''}${Math.round(delta)}s)`}
        {candidate.synced && <span className="lrclib-match-badge">synced</span>}
      </span>
      {candidate.preview.length > 0 && (
        <span className="song-result-meta">
          {candidate.preview.join(' / ')}
        </span>
      )}
    </span>
  )
}

// Lists the LRCLIB tracks matching the picked song, and reports the one
// chosen (or null for "none"). `chosen` is the choice the parent kept, or
// undefined while there's none: a choice collapses the list to its row, which
// reopens it when clicked. Matches whose length differs from the song's sit
// behind a toggle. A synced match within tolerance is chosen up front. The
// parent remounts it (by key) for each newly picked song.
export function LrclibMatches({
  song,
  chosen,
  onChoose,
}: {
  song: SongResult
  chosen: LrclibCandidate | null | undefined
  onChoose: (candidate: LrclibCandidate | null) => void
}) {
  const [candidates, setCandidates] = useState<LrclibCandidate[] | null>(null)
  // Whether the list was reopened on a choice, until the next one.
  const [reopened, setReopened] = useState(false)
  const [showOthers, setShowOthers] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const onChooseRef = useLatest(onChoose)

  useEffect(() => {
    let cancelled = false

    searchLrclib({
      title: song.title,
      artist: song.artists,
      durationSeconds: song.duration_seconds,
    })
      .then((found) => {
        if (cancelled) return
        setCandidates(found)
        const first = found[0]
        if (first?.within_tolerance && first.synced) onChooseRef.current(first)
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
    setReopened(false)
    onChoose(candidate)
  }

  if (error) return <p className="form-error">{error}</p>
  if (candidates === null) return <p>Searching LRCLIB…</p>

  if (chosen !== undefined && !reopened) {
    return (
      <fieldset className="lrclib-matches">
        <legend>Lyrics from LRCLIB</legend>
        <ul className="song-results">
          <li>
            <button
              type="button"
              className="song-result chosen"
              onClick={() => setReopened(true)}
            >
              {chosen ? (
                <CandidateText candidate={chosen} />
              ) : (
                <span className="song-result-text">{NONE_LABEL}</span>
              )}
              <span className="lrclib-match-change">Change</span>
            </button>
          </li>
        </ul>
      </fieldset>
    )
  }

  // The chosen match stays listed, even if it's one of the others.
  const matching = candidates.filter((c) => c.within_tolerance || c === chosen)
  const hiddenCount = candidates.length - matching.length
  const shown = showOthers ? candidates : matching

  return (
    <fieldset className="lrclib-matches">
      <legend>Lyrics from LRCLIB</legend>
      <ul className="song-results">
        {shown.map((c) => (
          <li key={c.id}>
            <button
              type="button"
              className={c === chosen ? 'song-result chosen' : 'song-result'}
              onClick={() => choose(c)}
            >
              <CandidateText candidate={c} />
            </button>
          </li>
        ))}
        <li>
          <button
            type="button"
            className={chosen === null ? 'song-result chosen' : 'song-result'}
            onClick={() => choose(null)}
          >
            <span className="song-result-text">{NONE_LABEL}</span>
          </button>
        </li>
      </ul>
      {hiddenCount > 0 && (
        <button
          type="button"
          className="lrclib-matches-toggle"
          onClick={() => setShowOthers((shown) => !shown)}
        >
          {showOthers ? 'Hide' : `Show ${hiddenCount} with other lengths`}
        </button>
      )}
    </fieldset>
  )
}
