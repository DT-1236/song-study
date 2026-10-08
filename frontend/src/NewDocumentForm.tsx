import { useCallback, useState } from 'react'
import { LRCLIB_URI_PLACEHOLDER, createDocument, errorMessage } from './api'
import type { LrclibCandidate, SongResult } from './api'
import { LrclibMatches } from './LrclibMatches'
import { SongSearch } from './SongSearch'
import { YouTubePlayer } from './YouTubePlayer'

export function NewDocumentForm() {
  const [title, setTitle] = useState('')
  const [lyrics, setLyrics] = useState('')
  const [lrclibUri, setLrclibUri] = useState('')
  const [youtubeVideoId, setYoutubeVideoId] = useState('')
  // The title a song pick last filled in. While the title still equals it, a
  // later pick may replace it; once it's edited, it never is.
  const [pickedTitle, setPickedTitle] = useState('')
  const [pickedSong, setPickedSong] = useState<SongResult | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [savedTitle, setSavedTitle] = useState<string | null>(null)

  const usingLrclib = lrclibUri.trim() !== ''

  function handlePick(song: SongResult) {
    setPickedSong(song)
    setYoutubeVideoId(song.video_id)
    if (title === '' || title === pickedTitle) {
      setTitle(song.title)
      setPickedTitle(song.title)
    }
  }

  const handleChoose = useCallback((candidate: LrclibCandidate | null) => {
    setLrclibUri(candidate ? String(candidate.id) : '')
  }, [])

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
    } catch (err) {
      setError(errorMessage(err, 'Something went wrong.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="new-document-form" onSubmit={handleSubmit}>
      <h1>New document</h1>

      <SongSearch onPick={handlePick} />
      {youtubeVideoId.trim() !== '' && (
        <YouTubePlayer videoId={youtubeVideoId.trim()} />
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
        <LrclibMatches song={pickedSong} onChoose={handleChoose} />
      )}

      {!usingLrclib && (
        <>
          <label htmlFor="lyrics">Lyrics</label>
          <textarea
            id="lyrics"
            value={lyrics}
            onChange={(e) => setLyrics(e.target.value)}
            rows={16}
            placeholder="Paste the full lyrics here"
            required
          />
        </>
      )}

      <details className="manual-ids">
        <summary>Enter IDs manually</summary>

        <label htmlFor="lrclib-uri">LRCLIB track (optional)</label>
        <input
          id="lrclib-uri"
          type="text"
          value={lrclibUri}
          onChange={(e) => setLrclibUri(e.target.value)}
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

      <button type="submit" disabled={submitting}>
        {submitting ? 'Saving…' : 'Save'}
      </button>

      {error && <p className="form-error">{error}</p>}
      {savedTitle && <p className="form-success">Saved "{savedTitle}".</p>}
    </form>
  )
}
