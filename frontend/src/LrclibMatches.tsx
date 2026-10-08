import { useState } from 'react'
import { searchLrclib } from './api'
import type { LrclibCandidate, SongResult } from './api'
import { SearchDropdown } from './SearchDropdown'
import { formatDuration } from './timing'

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

// Searches LRCLIB for the picked song's lyrics, by track title (the song's
// to start with), and reports the match chosen (or null for "none"). The
// song's artist and length still rank what's found, and matches of another
// length sit behind a toggle. A synced match of the right length is chosen up
// front; otherwise the results open. `chosen` is the choice the parent kept,
// or undefined while there's none, and shows below the search box as the
// video shows the picked song. The parent remounts it (by key) for each newly
// picked song.
export function LrclibMatches({
  song,
  chosen,
  onChoose,
}: {
  song: SongResult
  chosen: LrclibCandidate | null | undefined
  onChoose: (candidate: LrclibCandidate | null) => void
}) {
  // Null until a search has found something to show.
  const [candidates, setCandidates] = useState<LrclibCandidate[] | null>(null)
  const [showOthers, setShowOthers] = useState(false)

  function handleResults(found: LrclibCandidate[], initial: boolean) {
    setCandidates(found)
    setShowOthers(false)
    const first = found[0]
    if (initial && first?.within_tolerance && first.synced) {
      onChoose(first)
      return false
    }
    return true
  }

  function renderResults(close: () => void) {
    if (candidates === null) return null
    const choose = (candidate: LrclibCandidate | null) => {
      onChoose(candidate)
      close()
    }
    // The chosen match stays listed, even if it's one of the others.
    const matching = candidates.filter(
      (c) => c.within_tolerance || c === chosen,
    )
    const hiddenCount = candidates.length - matching.length
    const shown = showOthers ? candidates : matching

    return (
      <>
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
      </>
    )
  }

  return (
    <>
      <SearchDropdown
        id="lrclib-search-query"
        label="Lyrics from LRCLIB"
        placeholder="Track title"
        initialQuery={song.title}
        searchOnMount
        search={(title) =>
          searchLrclib({
            title,
            artist: song.artists,
            durationSeconds: song.duration_seconds,
          })
        }
        onResults={handleResults}
        failureMessage="LRCLIB search failed."
      >
        {renderResults}
      </SearchDropdown>
      {chosen !== undefined && (
        <div className="lrclib-choice">
          {chosen ? (
            <CandidateText candidate={chosen} />
          ) : (
            <span className="song-result-text">{NONE_LABEL}</span>
          )}
        </div>
      )}
    </>
  )
}
