import { memo, useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { fetchDocument, fetchTokens } from './api'
import type { Token } from './api'
import { useTabs } from './TabsContext'
import { useApiResource } from './useApiResource'
import { YouTubePlayer } from './YouTubePlayer'
import type { YouTubePlayerHandle } from './YouTubePlayer'

// Elements where a focused Space already activates the control natively
// (typing targets are handled separately, in isTypingTarget) — the global
// play/pause listener must not override this.
const SPACE_HANDLED_NATIVELY = new Set(['BUTTON', 'SELECT', 'A'])

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
  const [seekSeconds, setSeekSeconds] = useState(3)

  const youtubePlayerRef = useRef<YouTubePlayerHandle>(null)

  // Spacebar play/pause and ,/. seek by seekSeconds, same as YouTube's own
  // page — but only when focus isn't on something these keys already have
  // a native meaning for: typing (the lyrics textarea, a reading-correction
  // input) for all three, or activating a focused button/link for Space
  // specifically, which would otherwise get silently overridden.
  useEffect(() => {
    function isTypingTarget(active: Element | null): boolean {
      return active instanceof HTMLElement && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.isContentEditable)
    }

    function handleKeyDown(event: KeyboardEvent) {
      const active = document.activeElement

      if (event.code === 'Space') {
        const isNativeSpaceTarget =
          active instanceof HTMLElement && SPACE_HANDLED_NATIVELY.has(active.tagName)
        if (isNativeSpaceTarget || isTypingTarget(active)) return
        event.preventDefault()
        youtubePlayerRef.current?.togglePlay()
        return
      }

      if (event.code === 'Comma' || event.code === 'Period') {
        if (isTypingTarget(active)) return
        event.preventDefault()
        youtubePlayerRef.current?.seekBy(event.code === 'Comma' ? -seekSeconds : seekSeconds)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [seekSeconds])

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
        <label htmlFor="seek-seconds">Seek step {seekSeconds}s</label>
        <input
          id="seek-seconds"
          type="range"
          min={1}
          max={30}
          value={seekSeconds}
          onChange={(e) => setSeekSeconds(Number(e.target.value))}
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
        <YouTubePlayer ref={youtubePlayerRef} videoId={doc.youtube_video_id} />
      ) : (
        <input type="text" value="—" readOnly />
      )}
    </div>
  )
}
