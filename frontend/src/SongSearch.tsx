import { useState } from 'react'
import { searchSongs } from './api'
import type { SongResult } from './api'
import { SearchDropdown, SearchResult } from './SearchDropdown'
import { formatDuration } from './timing'

// Searches YouTube Music's songs, or its videos instead when toggled, and
// reports the one picked. `pickedId` marks the song picked last.
export function SongSearch({
  pickedId,
  onPick,
}: {
  pickedId: string | null
  onPick: (song: SongResult) => void
}) {
  const [videos, setVideos] = useState(false)

  return (
    <SearchDropdown
      id="song-search-query"
      label="Search for a song"
      placeholder="e.g. 夜に駆ける YOASOBI"
      search={(query) => searchSongs(query, videos)}
      kind={videos ? 'videos' : 'songs'}
      failureMessage="Search failed."
      controls={
        <label
          className="checkbox-option search-include-videos"
          title="Songs are more likely to sync up with the lyrics: videos can have openings, credits and the like that shift the timing."
        >
          <input
            type="checkbox"
            checked={videos}
            onChange={(e) => setVideos(e.target.checked)}
          />
          Search videos instead
        </label>
      }
    >
      {(songs, close) => (
        <>
          {songs.length === 0 ? (
            <p>{videos ? 'No videos found.' : 'No songs found.'}</p>
          ) : (
            <ul className="search-results">
              {songs.map((song) => (
                <SearchResult
                  key={song.video_id}
                  chosen={song.video_id === pickedId}
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
                  <span className="search-result-text">
                    <span className="search-result-title">{song.title}</span>
                    <span className="search-result-meta">
                      {[song.artists, song.album].filter(Boolean).join(' · ')}
                    </span>
                  </span>
                  {song.duration_seconds !== null && (
                    <span className="search-result-duration">
                      {formatDuration(song.duration_seconds)}
                    </span>
                  )}
                </SearchResult>
              ))}
            </ul>
          )}
        </>
      )}
    </SearchDropdown>
  )
}
