import { useCallback, useRef, useState } from 'react'
import { LRCLIB_URI_PLACEHOLDER, createDocument, errorMessage } from './api'
import type { LrclibCandidate, SongResult } from './api'
import { LrclibMatches } from './LrclibMatches'
import { SongSearch } from './SongSearch'
import { SyncedLyrics } from './SyncedLyrics'
import { useLrclibChoice } from './useLrclibChoice'
import { usePlayerShortcuts, useSeekSeconds } from './usePlayerShortcuts'
import { usePlayingLine } from './usePlayingLine'
import { YouTubePlayer } from './YouTubePlayer'
import type { YouTubePlayerHandle } from './YouTubePlayer'

export function NewDocumentForm() {
  const [title, setTitle] = useState('')
  // The lyrics as pasted, kept while LRCLIB's are shown in their place.
  const [lyrics, setLyrics] = useState('')
  const [lrclibUri, setLrclibUri] = useState('')
  const [youtubeVideoId, setYoutubeVideoId] = useState('')
  // The title a song pick last filled in. While the title still equals it, a
  // later pick may replace it; once it's edited, it never is.
  const [pickedTitle, setPickedTitle] = useState('')
  const [pickedSong, setPickedSong] = useState<SongResult | null>(null)
  // The LRCLIB match chosen for the picked song. Its track is set as
  // lrclibUri only once its lyrics have loaded.
  const {
    choice,
    choose,
    lyrics: choiceLyrics,
    loading: loadingLyrics,
    error: lyricsError,
  } = useLrclibChoice((id) => setLrclibUri(String(id)))
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [savedTitle, setSavedTitle] = useState<string | null>(null)

  const playerRef = useRef<YouTubePlayerHandle>(null)
  const [seekSeconds] = useSeekSeconds()
  usePlayerShortcuts(playerRef, seekSeconds)
  const handlePlayLine = useCallback(
    (start: number) => playerRef.current?.playFrom(start),
    [],
  )

  const usingLrclib = lrclibUri.trim() !== ''
  const hasVideo = youtubeVideoId.trim() !== ''
  const { playingLine, onSeek } = usePlayingLine(
    playerRef,
    hasVideo ? (choiceLyrics?.lines ?? null) : null,
  )

  function handlePick(song: SongResult) {
    // Picking the song already shown keeps its matches and the choice made.
    if (song.video_id === pickedSong?.video_id) return
    setPickedSong(song)
    // The previous song's track doesn't belong to this one.
    choose(undefined)
    setLrclibUri('')
    setYoutubeVideoId(song.video_id)
    if (title === '' || title === pickedTitle) {
      setTitle(song.title)
      setPickedTitle(song.title)
    }
  }

  function handleChoose(candidate: LrclibCandidate | null) {
    // The same objects as before, from LrclibMatches' own list.
    if (candidate === choice) return
    choose(candidate)
    // Set again once the new track's lyrics load.
    setLrclibUri('')
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setSavedTitle(null)
    setSubmitting(true)

    try {
      // LRCLIB's lyrics take precedence server-side, so any pasted ones are
      // just ignored when a track is given.
      const document = await createDocument({
        title,
        text: lyrics,
        youtubeVideoId,
        lrclibUri,
      })
      setSavedTitle(document.title)
      setTitle('')
      setLyrics('')
      setLrclibUri('')
      setYoutubeVideoId('')
      setPickedTitle('')
      setPickedSong(null)
      choose(undefined)
    } catch (err) {
      setError(errorMessage(err, 'Something went wrong.'))
    } finally {
      setSubmitting(false)
    }
  }

  let lyricsField
  if (choiceLyrics?.lines) {
    lyricsField = (
      <SyncedLyrics
        id="lyrics"
        aria-labelledby="lyrics-label"
        lyrics={choiceLyrics}
        playingLine={playingLine}
        onPlayLine={handlePlayLine}
      />
    )
  } else if (loadingLyrics || usingLrclib) {
    lyricsField = (
      <textarea
        id="lyrics"
        value={choiceLyrics?.text ?? ''}
        rows={16}
        // A track typed into the manual field has its lyrics loaded on saving.
        placeholder={loadingLyrics ? 'Loading lyrics…' : 'Loaded from LRCLIB'}
        disabled
      />
    )
  } else {
    lyricsField = (
      <textarea
        id="lyrics"
        value={lyrics}
        onChange={(e) => setLyrics(e.target.value)}
        rows={16}
        placeholder="Paste the full lyrics here"
        required
      />
    )
  }

  return (
    <form className="new-document-form" onSubmit={handleSubmit}>
      <h1>New document</h1>

      <SongSearch pickedId={pickedSong?.video_id ?? null} onPick={handlePick} />
      {hasVideo && (
        <YouTubePlayer
          ref={playerRef}
          videoId={youtubeVideoId.trim()}
          onSeek={onSeek}
        />
      )}
      {hasVideo && (
        <p className="lyrics-editor-note">
          <kbd>Space</kbd> plays and pauses, and <kbd>,</kbd> / <kbd>.</kbd>{' '}
          seek {seekSeconds}s (set on a document page).
        </p>
      )}

      <label htmlFor="title">Title</label>
      <input
        id="title"
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        required
      />

      {pickedSong && (
        <LrclibMatches
          key={pickedSong.video_id}
          song={pickedSong}
          chosen={choice}
          onChoose={handleChoose}
          noneLabel="None — I'll paste the lyrics"
        />
      )}

      <label id="lyrics-label" htmlFor="lyrics">
        Lyrics
      </label>
      {lyricsField}
      {lyricsError && <p className="form-error">{lyricsError}</p>}

      <details className="manual-ids">
        <summary>Enter IDs manually</summary>

        <label htmlFor="lrclib-uri">LRCLIB track (optional)</label>
        <input
          id="lrclib-uri"
          type="text"
          value={lrclibUri}
          onChange={(e) => {
            setLrclibUri(e.target.value)
            // A typed track isn't the chosen match any more.
            choose(undefined)
          }}
          placeholder={LRCLIB_URI_PLACEHOLDER}
        />
        <p className="lyrics-editor-note">
          When set, the lyrics and their timing are loaded from LRCLIB instead
          of pasted.
        </p>

        <label htmlFor="youtube-video-id">YouTube video ID (optional)</label>
        <input
          id="youtube-video-id"
          type="text"
          value={youtubeVideoId}
          onChange={(e) => setYoutubeVideoId(e.target.value)}
          placeholder="e.g. dQw4w9WgXcQ"
        />
      </details>

      <button type="submit" disabled={submitting || loadingLyrics}>
        {submitting ? 'Saving…' : 'Save'}
      </button>

      {error && <p className="form-error">{error}</p>}
      {savedTitle && <p className="form-success">Saved "{savedTitle}".</p>}
    </form>
  )
}
