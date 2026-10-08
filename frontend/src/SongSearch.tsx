import { useState } from 'react'
import { searchSongs } from './api'
import type { SongResult } from './api'
import { SearchDropdown } from './SearchDropdown'
import { formatDuration } from './timing'

// Searches YouTube Music's songs and reports the one picked. `pickedId` marks
// the song picked last.
export function SongSearch({
  pickedId,
  onPick,
}: {
  pickedId: string | null
  onPick: (song: SongResult) => void
}) {
  // Null until a search has found something to show.
  const [results, setResults] = useState<SongResult[] | null>(null)

  return (
    <SearchDropdown
      id="song-search-query"
      label="Search for a song"
      placeholder="e.g. 夜に駆ける YOASOBI"
      search={searchSongs}
      onResults={(found: SongResult[]) => {
        setResults(found)
        return true
      }}
      failureMessage="Search failed."
    >
      {(close) => {
        if (results === null) return null
        if (results.length === 0) return <p>No songs found.</p>
        return (
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
                    close()
                  }}
                >
                  {song.thumbnail_url && (
                    <img
                      src={song.thumbnail_url}
                      alt=""
                      width={40}
                      height={40}
                    />
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
        )
      }}
    </SearchDropdown>
  )
}
