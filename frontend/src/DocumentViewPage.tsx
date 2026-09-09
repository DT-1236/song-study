import { useCallback, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { fetchDocument } from './api'
import { useTabs } from './TabsContext'
import { useApiResource } from './useApiResource'
import { YouTubePlayer } from './YouTubePlayer'

export function DocumentViewPage() {
  const { id } = useParams<{ id: string }>()
  const documentId = Number(id)

  const { visitDocument } = useTabs()

  const fetchFn = useCallback(() => fetchDocument(documentId), [documentId])
  const { data: doc, loading, error } = useApiResource(fetchFn, [documentId], 'Failed to load document.')

  useEffect(() => {
    if (doc) {
      visitDocument(doc.id, doc.title)
    }
  }, [doc, visitDocument])

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
