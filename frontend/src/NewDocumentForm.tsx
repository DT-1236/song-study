import { useState } from 'react'
import { ApiError, createDocument } from './api'

export function NewDocumentForm() {
  const [title, setTitle] = useState('')
  const [lyrics, setLyrics] = useState('')
  const [youtubeVideoId, setYoutubeVideoId] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [savedTitle, setSavedTitle] = useState<string | null>(null)

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setSavedTitle(null)
    setSubmitting(true)

    try {
      const document = await createDocument({ title, text: lyrics, youtubeVideoId })
      setSavedTitle(document.title)
      setTitle('')
      setLyrics('')
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

      <label htmlFor="lyrics">Lyrics</label>
      <textarea
        id="lyrics"
        value={lyrics}
        onChange={(e) => setLyrics(e.target.value)}
        rows={16}
        placeholder="Paste the full lyrics here"
        required
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
