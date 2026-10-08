import { useRef, useState } from 'react'
import { errorMessage, searchSongs } from './api'
import type { SongResult } from './api'
import { formatDuration } from './timing'
import { useClickOutside } from './useClickOutside'

// Searches YouTube Music's songs and reports the one picked. It runs on Enter
// or a click rather than per keystroke, since each search hits an unofficial
// YouTube endpoint. A pick or a click elsewhere closes the results, and
// clicking back into the search box shows them again. A div rather than a
// form, as it sits inside one. `pickedId` marks the song picked last.
export function SongSearch({
  pickedId,
  onPick,
}: {
  pickedId: string | null
  onPick: (song: SongResult) => void
}) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SongResult[] | null>(null)
  const [showResults, setShowResults] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  useClickOutside(rootRef, showResults, () => setShowResults(false))

  async function search() {
    const trimmed = query.trim()
    if (!trimmed || loading) return
    setLoading(true)
    setError(null)
    try {
      setResults(await searchSongs(trimmed))
      setShowResults(true)
    } catch (err) {
      setResults(null)
      setError(errorMessage(err, 'Search failed.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div ref={rootRef} className="song-search">
      <label htmlFor="song-search-query">Search for a song</label>
      <div className="song-search-row">
        <input
          id="song-search-query"
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          // Clicking too, since a box that kept focus after a pick gets no
          // focus event.
          onFocus={() => setShowResults(true)}
          onClick={() => setShowResults(true)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setShowResults(false)
            // Enter would otherwise submit the surrounding form. Enter that
            // confirms an IME conversion isn't a search.
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
              e.preventDefault()
              void search()
            }
          }}
          placeholder="e.g. 夜に駆ける YOASOBI"
        />
        <button
          type="button"
          className="song-search-button"
          onClick={() => void search()}
          disabled={loading || query.trim() === ''}
        >
          {loading ? 'Searching…' : 'Search'}
        </button>
      </div>

      {error && <p className="form-error">{error}</p>}
      {showResults && results?.length === 0 && <p>No songs found.</p>}
      {showResults && results && results.length > 0 && (
        <ul className="song-results">
          {results.map((song) => (
            <li key={song.video_id}>
              <button
                type="button"
                className={
                  song.video_id === pickedId
                    ? 'song-result chosen'
                    : 'song-result'
                }
                onClick={() => {
                  onPick(song)
                  setShowResults(false)
                }}
              >
                {song.thumbnail_url && (
                  <img src={song.thumbnail_url} alt="" width={40} height={40} />
                )}
                <span className="song-result-text">
                  <span className="song-result-title">{song.title}</span>
                  <span className="song-result-meta">
                    {[song.artists, song.album].filter(Boolean).join(' · ')}
                  </span>
                </span>
                {song.duration_seconds !== null && (
                  <span className="song-result-duration">
                    {formatDuration(song.duration_seconds)}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
