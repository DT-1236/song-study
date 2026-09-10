import { memo, useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { fetchDocument, fetchTokens } from './api'
import type { Token } from './api'
import { useTabs } from './TabsContext'
import { useApiResource } from './useApiResource'
import { YouTubePlayer } from './YouTubePlayer'

const REVIEW_REASON_LABELS: Record<string, string> = {
  oov: 'Not in dictionary',
  heteronym: 'Multiple possible readings',
  no_kana_anchor: 'Ambiguous furigana split',
}

const TokenizedText = memo(function TokenizedText({ tokens }: { tokens: Token[] }) {
  return (
    <p className="lyrics-box">
      {tokens.map((token) => {
        const spans = token.furigana_override ?? token.furigana_spans
        const reviewLabel = token.review_reason ? REVIEW_REASON_LABELS[token.review_reason] ?? 'Needs review' : undefined
        return (
          <span
            key={token.id}
            className={token.needs_review ? 'token needs-review' : 'token'}
            title={reviewLabel ? `Needs review: ${reviewLabel}` : undefined}
          >
            {spans.map((span, i) =>
              span.reading ? (
                <ruby key={i}>
                  {span.text}
                  <rt>{span.reading}</rt>
                </ruby>
              ) : (
                <span key={i}>{span.text}</span>
              ),
            )}
          </span>
        )
      })}
    </p>
  )
})

function SizeSlider({
  id,
  label,
  value,
  onChange,
  min,
  max,
}: {
  id: string
  label: string
  value: number
  onChange: (value: number) => void
  min: number
  max: number
}) {
  return (
    <>
      <label htmlFor={id}>
        {label} {value}px
      </label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </>
  )
}

export function DocumentViewPage() {
  const { id } = useParams<{ id: string }>()
  const documentId = Number(id)

  const { visitDocument } = useTabs()

  const fetchDocFn = useCallback(() => fetchDocument(documentId), [documentId])
  const { data: doc, loading, error } = useApiResource(fetchDocFn, [documentId], 'Failed to load document.')

  const fetchTokensFn = useCallback(() => fetchTokens(documentId), [documentId])
  const {
    data: tokens,
    loading: tokensLoading,
    error: tokensError,
  } = useApiResource(fetchTokensFn, [documentId], 'Failed to load furigana.')

  const [fontSize, setFontSize] = useState(18)
  const [furiganaSize, setFuriganaSize] = useState(11)

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
      <p id="title" className="readonly-text">{doc.title}</p>

      <label htmlFor="lyrics">Lyrics</label>
      <div className="text-size-controls">
        <SizeSlider id="font-size" label="Text size" value={fontSize} onChange={setFontSize} min={14} max={32} />
        <SizeSlider
          id="furigana-size"
          label="Furigana size"
          value={furiganaSize}
          onChange={setFuriganaSize}
          min={6}
          max={20}
        />
      </div>
      <div
        id="lyrics"
        style={
          {
            '--lyrics-font-size': `${fontSize}px`,
            '--furigana-font-size': `${furiganaSize}px`,
          } as React.CSSProperties
        }
      >
        {tokensLoading && <p>Tokenizing…</p>}
        {tokens && <TokenizedText tokens={tokens} />}
        {tokensError && (
          <>
            <p className="form-error">{tokensError} Showing plain lyrics instead.</p>
            <p className="lyrics-box">{doc.text}</p>
          </>
        )}
      </div>

      <label htmlFor="youtube-video-id">YouTube video ID</label>
      {doc.youtube_video_id ? (
        <YouTubePlayer videoId={doc.youtube_video_id} />
      ) : (
        <input type="text" value="—" readOnly />
      )}
    </div>
  )
}
