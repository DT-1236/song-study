import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { ApiError, fetchDocument } from './api'
import type { Document } from './api'
import { useTabs } from './TabsContext'
import { YouTubePlayer } from './YouTubePlayer'

export function DocumentViewPage() {
  const { id } = useParams<{ id: string }>()
  const documentId = Number(id)

  const { visitDocument } = useTabs()

  const [doc, setDoc] = useState<Document | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setDoc(null)
    setLoading(true)
    setError(null)

    fetchDocument(documentId)
      .then((result) => {
        if (cancelled) return
        setDoc(result)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : 'Failed to load document.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [documentId])

  useEffect(() => {
    if (doc) {
      visitDocument(doc.id, doc.title)
    }
    // visitDocument is stable (useCallback in TabsProvider); only re-run when the
    // loaded document changes, not on every tabs-context update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc])

  if (loading) return <p>Loading…</p>
  if (error) return <p className="form-error">{error}</p>
  if (!doc) return null

  return (
    <div className="new-document-form">
      <h1>{doc.title}</h1>

      <label htmlFor="title">Title</label>
      <input id="title" type="text" value={doc.title} readOnly />

      <label htmlFor="lyrics">Lyrics</label>
      <textarea id="lyrics" value={doc.text} rows={16} readOnly />

      <label htmlFor="youtube-video-id">YouTube video ID</label>
      {doc.youtube_video_id ? (
        <YouTubePlayer videoId={doc.youtube_video_id} />
      ) : (
        <input type="text" value="—" readOnly />
      )}
    </div>
  )
}
