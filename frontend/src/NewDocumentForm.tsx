import { useState } from 'react'
import { ApiError, LRCLIB_URI_PLACEHOLDER, createDocument } from './api'

export function NewDocumentForm() {
  const [title, setTitle] = useState('')
  const [lyrics, setLyrics] = useState('')
  const [lrclibUri, setLrclibUri] = useState('')
  const [youtubeVideoId, setYoutubeVideoId] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [savedTitle, setSavedTitle] = useState<string | null>(null)

  const usingLrclib = lrclibUri.trim() !== ''

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setSavedTitle(null)
    setSubmitting(true)

    try {
      // LRCLIB's lyrics take precedence server-side, so any pasted ones are
      // just ignored when a track is given.
      const document = await createDocument({ title, text: lyrics, youtubeVideoId, lrclibUri })
      setSavedTitle(document.title)
      setTitle('')
      setLyrics('')
      setLrclibUri('')
      setYoutubeVideoId('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="new-document-form" onSubmit={handleSubmit}>
      <h1>New document</h1>

      <label htmlFor="title">Title</label>
      <input
        id="title"
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        required
      />

      <label htmlFor="lrclib-uri">LRCLIB track (optional)</label>
      <input
        id="lrclib-uri"
        type="text"
        value={lrclibUri}
        onChange={(e) => setLrclibUri(e.target.value)}
        placeholder={LRCLIB_URI_PLACEHOLDER}
      />
      <p className="lyrics-editor-note">
        When set, the lyrics and their timing are loaded from LRCLIB instead of pasted below.
      </p>

      <label htmlFor="lyrics">Lyrics</label>
      <textarea
        id="lyrics"
        value={usingLrclib ? '' : lyrics}
        onChange={(e) => setLyrics(e.target.value)}
        rows={16}
        placeholder={usingLrclib ? 'Loaded from LRCLIB' : 'Paste the full lyrics here'}
        required={!usingLrclib}
        disabled={usingLrclib}
      />

      <label htmlFor="youtube-video-id">YouTube video ID (optional)</label>
      <input
        id="youtube-video-id"
        type="text"
        value={youtubeVideoId}
        onChange={(e) => setYoutubeVideoId(e.target.value)}
        placeholder="e.g. dQw4w9WgXcQ"
      />

      <button type="submit" disabled={submitting}>
        {submitting ? 'Saving…' : 'Save'}
      </button>

      {error && <p className="form-error">{error}</p>}
      {savedTitle && <p className="form-success">Saved "{savedTitle}".</p>}
    </form>
  )
}
