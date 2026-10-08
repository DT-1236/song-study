import { useState } from 'react'
import { searchLrclib } from './api'
import type { LrclibCandidate, SongResult } from './api'
import { SearchDropdown, SearchResult } from './SearchDropdown'
import { formatDuration } from './timing'

// What LRCLIB is searched for: a picked song, or a document's.
export type LrclibSong = Pick<
  SongResult,
  'title' | 'artists' | 'duration_seconds'
>

function CandidateText({ candidate }: { candidate: LrclibCandidate }) {
  const { duration, duration_delta: delta } = candidate
  return (
    <span className="search-result-text">
      <span className="search-result-title">{candidate.track_name}</span>
      <span className="search-result-meta">
        {[candidate.artist_name, candidate.album_name]
          .filter(Boolean)
          .join(' · ')}
      </span>
      <span className="search-result-meta">
        {duration !== null && formatDuration(duration)}
        {delta !== null && ` (${delta > 0 ? '+' : ''}${Math.round(delta)}s)`}
        {candidate.synced && <span className="lrclib-match-badge">synced</span>}
      </span>
      {candidate.preview.length > 0 && (
        <span className="search-result-meta">
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
// video shows the picked song. A last row, labelled `noneLabel`, chooses null,
// and is left out without one, so `chosen` is never null without it. The parent remounts it (by key) for each newly
// picked song.
export function LrclibMatches({
  song,
  chosen,
  onChoose,
  noneLabel,
}: {
  song: LrclibSong
  chosen: LrclibCandidate | null | undefined
  onChoose: (candidate: LrclibCandidate | null) => void
  noneLabel?: string
}) {
  const [showOthers, setShowOthers] = useState(false)

  // Chooses up front a synced match of the right length, the first one found
  // when there is any, and shows the results otherwise.
  function handleMountResults(found: LrclibCandidate[]) {
    const first = found[0]
    if (!first?.within_tolerance || !first.synced) return true
    onChoose(first)
    return false
  }

  function choose(candidate: LrclibCandidate | null, close: () => void) {
    onChoose(candidate)
    close()
  }

  function renderResults(candidates: LrclibCandidate[], close: () => void) {
    // The chosen match stays listed, even if it's one of the others.
    const matching = candidates.filter(
      (c) => c.within_tolerance || c === chosen,
    )
    const hiddenCount = candidates.length - matching.length
    const shown = showOthers ? candidates : matching

    return (
      <>
        <ul className="search-results">
          {shown.map((c) => (
            <SearchResult
              key={c.id}
              chosen={c === chosen}
              onClick={() => choose(c, close)}
            >
              <CandidateText candidate={c} />
            </SearchResult>
          ))}
          {noneLabel && (
            <SearchResult
              chosen={chosen === null}
              onClick={() => choose(null, close)}
            >
              <span className="search-result-text">{noneLabel}</span>
            </SearchResult>
          )}
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
        search={(title) =>
          searchLrclib({
            title,
            artist: song.artists,
            durationSeconds: song.duration_seconds,
          })
        }
        onMountResults={handleMountResults}
        failureMessage="LRCLIB search failed."
      >
        {renderResults}
      </SearchDropdown>
      {chosen !== undefined && (
        <div className="search-results lrclib-choice">
          {chosen ? (
            <CandidateText candidate={chosen} />
          ) : (
            <span className="search-result-text">{noneLabel}</span>
          )}
        </div>
      )}
    </>
  )
}
