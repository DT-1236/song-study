import { useCallback, useEffect, useRef, useState } from 'react'
import {
  LRCLIB_URI_PLACEHOLDER,
  createDocument,
  errorMessage,
  fetchLrclibLyrics,
} from './api'
import type { LrclibCandidate, LrclibLyrics, SongResult } from './api'
import { LrclibMatches } from './LrclibMatches'
import { SongSearch } from './SongSearch'
import { useHighlightSettings } from './useHighlightSettings'
import { usePlayingLine } from './usePlayingLine'
import { YouTubePlayer } from './YouTubePlayer'
import type { YouTubePlayerHandle } from './YouTubePlayer'

// LRCLIB's lyrics as a read-only list of lines, the one being sung at
// `playingLine` highlighted.
function SyncedLyrics({
  text,
  playingLine,
}: {
  text: string
  playingLine: number | null
}) {
  const highlight = useHighlightSettings()
  return (
    <div
      id="lyrics"
      className="lyrics-box synced-lyrics"
      aria-labelledby="lyrics-label"
      style={highlight.style}
    >
      {text.split('\n').map((line, index) => {
        const classNames = ['timing-row']
        if (line.trim() === '') classNames.push('blank')
        if (index === playingLine) classNames.push('playing')
        return (
          <div key={index} className={classNames.join(' ')}>
            <div className="timing-text">
              <span>{line}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

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
  const [choice, setChoice] = useState<LrclibCandidate | null>(null)
  // The last chosen track's lyrics, by its id, so they're never shown for
  // another choice.
  const [loaded, setLoaded] = useState<{
    id: number
    lyrics: LrclibLyrics
  } | null>(null)
  const [lyricsError, setLyricsError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [savedTitle, setSavedTitle] = useState<string | null>(null)

  const playerRef = useRef<YouTubePlayerHandle>(null)
  // Counts the player's seeks, so the highlight follows one at once.
  const [seeks, setSeeks] = useState(0)
  const handleSeek = useCallback(() => setSeeks((count) => count + 1), [])

  const usingLrclib = lrclibUri.trim() !== ''
  const choiceLyrics = choice && loaded?.id === choice.id ? loaded.lyrics : null
  const loadingLyrics = choice !== null && choiceLyrics === null
  const playingLine = usePlayingLine(
    playerRef,
    choiceLyrics?.lines ?? null,
    seeks,
  )

  const choiceId = choice?.id
  useEffect(() => {
    if (choiceId === undefined) return
    let cancelled = false

    fetchLrclibLyrics(choiceId)
      .then((result) => {
        if (cancelled) return
        setLoaded({ id: choiceId, lyrics: result })
        setLrclibUri(String(choiceId))
      })
      .catch((err) => {
        if (cancelled) return
        setLyricsError(errorMessage(err, "Couldn't load the lyrics."))
        // So the form can't be saved with a track whose lyrics didn't load.
        setChoice(null)
      })

    return () => {
      cancelled = true
    }
  }, [choiceId])

  function handlePick(song: SongResult) {
    // Picking the song already shown keeps its matches and the choice made.
    if (song.video_id === pickedSong?.video_id) return
    setPickedSong(song)
    // The previous song's track doesn't belong to this one.
    setChoice(null)
    setLyricsError(null)
    setLrclibUri('')
    setYoutubeVideoId(song.video_id)
    if (title === '' || title === pickedTitle) {
      setTitle(song.title)
      setPickedTitle(song.title)
    }
  }

  function handleChoose(candidate: LrclibCandidate | null) {
    if (candidate?.id === choice?.id) return
    setChoice(candidate)
    setLyricsError(null)
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
      setChoice(null)
    } catch (err) {
      setError(errorMessage(err, 'Something went wrong.'))
    } finally {
      setSubmitting(false)
    }
  }

  let lyricsField
  if (choiceLyrics?.lines) {
    lyricsField = (
      <SyncedLyrics text={choiceLyrics.text} playingLine={playingLine} />
    )
  } else if (loadingLyrics || choiceLyrics || usingLrclib) {
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
      {youtubeVideoId.trim() !== '' && (
        <YouTubePlayer
          ref={playerRef}
          videoId={youtubeVideoId.trim()}
          onSeek={handleSeek}
        />
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
          chosenId={choice?.id ?? null}
          onChoose={handleChoose}
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
            setChoice(null)
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
