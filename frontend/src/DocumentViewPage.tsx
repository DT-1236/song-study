import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { ApiError, correctReading, fetchDocument, resolveConflict, updateDocumentText } from './api'
import type { Document, FuriganaSpan, Gloss, GlossSense, Token } from './api'
import { getPosInfo } from './PosLegend'
import { useTabs } from './TabsContext'
import { YouTubePlayer } from './YouTubePlayer'
import type { YouTubePlayerHandle } from './YouTubePlayer'

const REVIEW_REASON_LABELS: Record<string, string> = {
  heteronym: 'Multiple possible readings',
  no_kana_anchor: 'Ambiguous furigana split',
}

const SENSE_LIMIT = 5

// Elements where a focused Space already activates the control natively
// (typing targets are handled separately, in isTypingTarget) — the global
// play/pause listener must not override this.
const SPACE_HANDLED_NATIVELY = new Set(['BUTTON', 'SELECT', 'A'])

// What's actually written in the lyrics, not what Sudachi normalized it to.
// gloss.source === 'english_stub' alone isn't enough: Sudachi normalizes
// some Latin-script tokens to katakana loanword-slang internally (Bling ->
// ブリン, It's -> イッツ, don't -> ドント), which routes them through a real
// JMDict lookup (gloss.source 'jmdict') even though they're clearly English
// as written — so those were leaking through. Checking surface directly
// catches every clearly-English token regardless of how Sudachi normalized
// it, so gloss.source doesn't need to be consulted here at all anymore.
const LATIN_LETTER_RE = /[A-Za-z]/
const JAPANESE_SCRIPT_RE = /[ぁ-んァ-ヶー一-龥]/

function isProbablyEnglish(token: Token): boolean {
  return LATIN_LETTER_RE.test(token.surface) && !JAPANESE_SCRIPT_RE.test(token.surface)
}

// True when a composite gloss (a compound with no JMDict entry of its own,
// shown broken into parts instead — see gloss.source) has a piece whose own
// reading is itself ambiguous (e.g. 女神 within 勝利の女神). There's no picker
// for this yet — see GlossPopup's composite note — but it's still something
// the user hasn't reviewed, so it counts for the same purposes needs_review
// conflicts normally would.
function hasAmbiguousCompositePiece(token: Token): boolean {
  return token.gloss?.source === 'composite' && token.gloss.pieces.some((p) => p.ambiguous_readings.length > 0)
}

function renderFuriganaSpans(spans: FuriganaSpan[]) {
  return spans.map((span, i) =>
    span.reading ? (
      <ruby key={i}>
        {span.text}
        <rt>{span.reading}</rt>
      </ruby>
    ) : (
      <span key={i}>{span.text}</span>
    ),
  )
}

function ReadingCorrectionForm({
  token,
  documentId,
  onTokenUpdated,
}: {
  token: Token
  documentId: number
  onTokenUpdated: (token: Token) => void
}) {
  const [value, setValue] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  return (
    <form
      className="reading-correction"
      onClick={(e) => e.stopPropagation()}
      onSubmit={async (e) => {
        e.preventDefault()
        const reading = value.trim()
        if (!reading) return
        setSubmitting(true)
        setError(null)
        try {
          const updated = await correctReading(documentId, token.id, reading)
          onTokenUpdated(updated)
          setValue('')
        } catch (err) {
          setError(err instanceof ApiError ? err.message : 'Failed to save — try again.')
        } finally {
          setSubmitting(false)
        }
      }}
    >
      <label htmlFor={`correct-reading-${token.id}`}>Correct the reading</label>
      <div className="reading-correction-row">
        <input
          id={`correct-reading-${token.id}`}
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="かな reading"
          disabled={submitting}
        />
        <button type="submit" disabled={submitting || !value.trim()}>
          Save
        </button>
      </div>
      {error && <div className="conflict-error">{error}</div>}
    </form>
  )
}

function ConflictResolver({
  token,
  documentId,
  onTokenUpdated,
}: {
  token: Token
  documentId: number
  onTokenUpdated: (token: Token) => void
}) {
  const [resolvingId, setResolvingId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  // A clean JMDict miss under the reading we currently have is worth
  // offering a correction for regardless of whether anything else flagged
  // this token — Sudachi's own heteronym check only catches disagreement
  // within its own dictionary, not "JMDict would match a different
  // reading than the one Sudachi chose" (e.g. 三股 as みまた vs さんまた).
  const missingGloss = token.gloss !== null && token.gloss.senses.length === 0

  if (token.review_reason === 'oov') {
    return (
      <div className="conflict-resolver">
        <div className="conflict-title">Not in dictionary</div>
        <div className="conflict-note">No automatic reading candidates.</div>
        {missingGloss && (
          <ReadingCorrectionForm token={token} documentId={documentId} onTokenUpdated={onTokenUpdated} />
        )}
      </div>
    )
  }

  if (token.conflicts.length === 0 && !missingGloss) return null

  return (
    <div className="conflict-resolver">
      {token.conflicts.length > 0 && (
        <>
          <div className="conflict-title">{REVIEW_REASON_LABELS[token.review_reason ?? ''] ?? 'Needs review'}</div>
          {error && <div className="conflict-error">{error}</div>}
          <div className="conflict-options">
            {token.conflicts.map((conflict) => (
              <button
                key={conflict.id}
                type="button"
                className={conflict.selected ? 'conflict-option selected' : 'conflict-option'}
                disabled={resolvingId !== null || (conflict.selected && !token.needs_review)}
                onClick={async (e) => {
                  e.stopPropagation()
                  setResolvingId(conflict.id)
                  setError(null)
                  try {
                    const updated = await resolveConflict(documentId, token.id, conflict.id)
                    onTokenUpdated(updated)
                  } catch {
                    setError('Failed to save — try again.')
                  } finally {
                    setResolvingId(null)
                  }
                }}
              >
                {renderFuriganaSpans(conflict.value.furigana_spans)}
              </button>
            ))}
          </div>
        </>
      )}
      {missingGloss && (
        <ReadingCorrectionForm token={token} documentId={documentId} onTokenUpdated={onTokenUpdated} />
      )}
    </div>
  )
}

function SenseBlock({ senses }: { senses: GlossSense[] }) {
  const [expanded, setExpanded] = useState(false)

  if (senses.length === 0) {
    return <div className="gloss-popup-empty">No dictionary entry found.</div>
  }

  const sensesToShow = senses.slice(0, expanded ? undefined : SENSE_LIMIT)

  return (
    <>
      <ol className="gloss-senses">
        {sensesToShow.map((sense, i) => (
          <li key={`${sense.entry_idseq}-${i}`}>
            {sense.gloss.join('; ')}
            {(sense.field.length > 0 || sense.misc.length > 0) && (
              <span className="gloss-tag"> ({[...sense.field, ...sense.misc].join(', ')})</span>
            )}
          </li>
        ))}
      </ol>
      {!expanded && senses.length > SENSE_LIMIT && (
        <button
          type="button"
          className="gloss-show-more"
          onClick={(e) => {
            e.stopPropagation()
            setExpanded(true)
          }}
        >
          Show {senses.length - SENSE_LIMIT} more
        </button>
      )}
    </>
  )
}

function GlossPopup({
  token,
  documentId,
  onTokenUpdated,
  onMouseEnter,
  onMouseLeave,
}: {
  token: Token
  documentId: number
  onTokenUpdated: (token: Token) => void
  onMouseEnter?: () => void
  onMouseLeave?: () => void
}) {
  const gloss = token.gloss as Gloss | null
  const posTerm = token.part_of_speech[0]
  const posInfo = getPosInfo(posTerm)

  // TokenizedText never opens this popup for English tokens (see hasPopup),
  // but it does still open for genuine Japanese words Sudachi doesn't
  // recognize (review_reason 'oov') — for those, dictionary_form/pos are
  // fabricated placeholders (see is_oov), not real analysis, so hide them.
  return (
    <div
      className="gloss-popup"
      onClick={(e) => e.stopPropagation()}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      {!token.is_oov && (
        <>
          <div className="dictionary-form-line">
            Dictionary form: {token.dictionary_form}（{token.dictionary_form_reading}）
          </div>
          {token.dictionary_form_note && (
            <div className="dictionary-form-note">{token.dictionary_form_note}</div>
          )}
          {posInfo && (
            <div className="token-pos-line">
              <ruby>
                {posInfo.term}
                <rt>{posInfo.furigana}</rt>
              </ruby>
            </div>
          )}
        </>
      )}
      {gloss && gloss.source === 'composite' ? (
        <div className="gloss-composite">
          <div className="gloss-composite-note">
            No single dictionary entry for this whole word — shown here as its parts.
          </div>
          {gloss.pieces.map((piece, i) => (
            <div key={i} className="gloss-piece">
              <div className="gloss-popup-reading">
                {piece.surface}「{piece.reading}」
              </div>
              <SenseBlock senses={piece.senses} />
              {piece.ambiguous_readings.length > 0 && (
                <div className="dictionary-form-note">
                  Sudachi also lists {piece.ambiguous_readings.join(', ')} as readings for {piece.surface} —
                  picking between them isn't supported within a compound yet. Use "Correct the reading" below
                  for the whole word if this one is wrong.
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        gloss && (
          <>
            <div className="gloss-popup-reading">{gloss.reading}</div>
            <SenseBlock senses={gloss.senses} />
          </>
        )
      )}
      {(token.needs_review ||
        token.conflicts.length > 0 ||
        (gloss !== null && gloss.senses.length === 0 && gloss.source !== 'composite') ||
        hasAmbiguousCompositePiece(token)) && (
        <ConflictResolver token={token} documentId={documentId} onTokenUpdated={onTokenUpdated} />
      )}
    </div>
  )
}

function TokenizedText({
  tokens,
  documentId,
  onTokenUpdated,
}: {
  tokens: Token[]
  documentId: number
  onTokenUpdated: (token: Token) => void
}) {
  const [hoveredId, setHoveredId] = useState<number | null>(null)
  const [pinnedId, setPinnedId] = useState<number | null>(null)

  // The popup sits below the token with a small margin gap (see .gloss-popup
  // in App.css), which the cursor has to cross to reach it. Clearing
  // hoveredId immediately on mouseleave means that gap crossing dismisses
  // the popup before the cursor ever reaches it — it's gone by the time
  // mouseenter would fire on the popup. A short grace period, cancelled by
  // either the token or the popup re-entering, bridges that gap without
  // otherwise changing hover behavior.
  const hoverLeaveTimeoutRef = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (hoverLeaveTimeoutRef.current !== null) {
        window.clearTimeout(hoverLeaveTimeoutRef.current)
      }
    }
  }, [])

  function handleHoverEnter(tokenId: number) {
    if (hoverLeaveTimeoutRef.current !== null) {
      window.clearTimeout(hoverLeaveTimeoutRef.current)
      hoverLeaveTimeoutRef.current = null
    }
    setHoveredId(tokenId)
  }

  function handleHoverLeave(tokenId: number) {
    if (hoverLeaveTimeoutRef.current !== null) {
      window.clearTimeout(hoverLeaveTimeoutRef.current)
    }
    hoverLeaveTimeoutRef.current = window.setTimeout(() => {
      setHoveredId((prev) => (prev === tokenId ? null : prev))
    }, 150)
  }

  useEffect(() => {
    function dismissPinned() {
      setPinnedId(null)
    }
    document.addEventListener('click', dismissPinned)
    return () => document.removeEventListener('click', dismissPinned)
  }, [])

  return (
    <p className="lyrics-box">
      {tokens.map((token) => {
        const spans = token.furigana_override ?? token.furigana_spans
        const hasPopup =
          !isProbablyEnglish(token) &&
          (token.gloss !== null || token.conflicts.length > 0 || token.review_reason === 'oov')
        const isPinned = pinnedId === token.id
        const isActive = isPinned || (pinnedId === null && hoveredId === token.id)

        // Two independent signals, deliberately not the same underline:
        // - needs-correction (red): no dictionary entry under the current
        //   reading at all — a manual correction could fix it. Not tied to
        //   needs_review, since Sudachi's own heteronym check doesn't catch
        //   this case (e.g. 三股 as みまた never got flagged, but still has
        //   no JMDict hit). A composite gloss (勝利の女神 -> 勝利/の/女神) means
        //   real content WAS found, just as parts, so it's excluded here.
        // - needs-review (blue): Sudachi surfaced real alternative readings
        //   and the user hasn't picked one yet. Excludes plain 'oov' tokens,
        //   which have needs_review set but no actual alternatives to
        //   review — those are a needs-correction case instead. Also covers
        //   a composite piece with its own unresolved reading ambiguity
        //   (e.g. 女神 within 勝利の女神) — same "hasn't been reviewed yet"
        //   signal, just without a picker behind it yet.
        const needsCorrection =
          hasPopup && token.gloss !== null && token.gloss.senses.length === 0 && token.gloss.source !== 'composite'
        const needsReadingReview =
          (token.needs_review && token.conflicts.length > 0) || hasAmbiguousCompositePiece(token)

        const classNames = ['token']
        if (needsReadingReview) classNames.push('needs-review')
        if (needsCorrection) classNames.push('needs-correction')
        if (hasPopup) classNames.push('has-gloss')
        if (isPinned) classNames.push('pinned')

        return (
          <span
            key={token.id}
            className={classNames.join(' ')}
            onMouseEnter={hasPopup ? () => handleHoverEnter(token.id) : undefined}
            onMouseLeave={hasPopup ? () => handleHoverLeave(token.id) : undefined}
            onClick={
              hasPopup
                ? (e) => {
                    e.stopPropagation()
                    setPinnedId((prev) => (prev === token.id ? null : token.id))
                  }
                : undefined
            }
          >
            {renderFuriganaSpans(spans)}
            {isActive && hasPopup && (
              <GlossPopup
                token={token}
                documentId={documentId}
                onTokenUpdated={onTokenUpdated}
                onMouseEnter={() => handleHoverEnter(token.id)}
                onMouseLeave={() => handleHoverLeave(token.id)}
              />
            )}
          </span>
        )
      })}
    </p>
  )
}

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

  const { ensureProcessed } = useTabs()

  const [doc, setDoc] = useState<Document | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [tokens, setTokens] = useState<Token[] | null>(null)
  const [tokensLoading, setTokensLoading] = useState(true)
  const [tokensError, setTokensError] = useState<string | null>(null)

  const [fontSize, setFontSize] = useState(18)
  const [furiganaSize, setFuriganaSize] = useState(11)
  const [seekSeconds, setSeekSeconds] = useState(3)

  const [editingLyrics, setEditingLyrics] = useState(false)
  const [lyricsDraft, setLyricsDraft] = useState('')
  const [savingLyrics, setSavingLyrics] = useState(false)
  const [lyricsSaveError, setLyricsSaveError] = useState<string | null>(null)

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
    if (!doc) return

    let cancelled = false
    setTokens(null)
    setTokensLoading(true)
    setTokensError(null)

    // Runs the same furigana + gloss pipeline (and tab registration) the
    // documents list kicks off on click, so arriving here directly (a
    // pasted URL, a refresh, a sidebar tab) still processes and registers
    // a tab the same way.
    ensureProcessed(doc.id, doc.title)
      .then((result) => {
        if (cancelled) return
        setTokens(result)
      })
      .catch((err) => {
        if (cancelled) return
        setTokensError(err instanceof ApiError ? err.message : 'Failed to load furigana.')
      })
      .finally(() => {
        if (!cancelled) setTokensLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [doc, ensureProcessed])

  if (loading) return <p>Loading…</p>
  if (error) return <p className="form-error">{error}</p>
  if (!doc) return null

  async function handleSaveLyrics() {
    const trimmed = lyricsDraft.trim()
    if (!trimmed) return
    setSavingLyrics(true)
    setLyricsSaveError(null)
    try {
      const updated = await updateDocumentText(documentId, trimmed)
      // A new object reference so the token-processing effect re-runs —
      // the backend already deleted the old tokens/conflicts/gloss links
      // on save, so this regenerates everything from scratch, same as a
      // never-before-processed document.
      setDoc(updated)
      setEditingLyrics(false)
    } catch (err) {
      setLyricsSaveError(err instanceof ApiError ? err.message : 'Failed to save — try again.')
    } finally {
      setSavingLyrics(false)
    }
  }

  return (
    <div className="new-document-form">
      <h1>{doc.title}</h1>

      <label htmlFor="title">Title</label>
      <p id="title" className="readonly-text">{doc.title}</p>

      <div className="lyrics-header">
        <label htmlFor="lyrics">Lyrics</label>
        {!editingLyrics && (
          <button
            type="button"
            className="lyrics-edit-toggle"
            onClick={() => {
              setLyricsDraft(doc.text)
              setLyricsSaveError(null)
              setEditingLyrics(true)
            }}
          >
            Edit lyrics
          </button>
        )}
      </div>

      {editingLyrics ? (
        <div className="lyrics-editor">
          <textarea
            id="lyrics"
            value={lyricsDraft}
            onChange={(e) => setLyricsDraft(e.target.value)}
            rows={16}
            disabled={savingLyrics}
          />
          {lyricsSaveError && <p className="form-error">{lyricsSaveError}</p>}
          <div className="lyrics-editor-actions">
            <button type="button" disabled={savingLyrics || !lyricsDraft.trim()} onClick={handleSaveLyrics}>
              {savingLyrics ? 'Saving…' : 'Save'}
            </button>
            <button type="button" disabled={savingLyrics} onClick={() => setEditingLyrics(false)}>
              Cancel
            </button>
          </div>
          <p className="lyrics-editor-note">
            Saving replaces the lyrics and re-processes furigana and glosses from scratch — any reading
            corrections or reviewed alternatives for this document will be lost.
          </p>
        </div>
      ) : (
        <>
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
            {tokensLoading && <p>Processing…</p>}
            {tokens && (
              <TokenizedText
                tokens={tokens}
                documentId={documentId}
                onTokenUpdated={(updated) =>
                  setTokens((prev) => prev?.map((t) => (t.id === updated.id ? updated : t)) ?? prev)
                }
              />
            )}
            {tokensError && (
              <>
                <p className="form-error">{tokensError} Showing plain lyrics instead.</p>
                <p className="lyrics-box">{doc.text}</p>
              </>
            )}
          </div>
        </>
      )}

      <label htmlFor="youtube-video-id">YouTube video ID</label>
      {doc.youtube_video_id ? (
        <YouTubePlayer ref={youtubePlayerRef} videoId={doc.youtube_video_id} />
      ) : (
        <input type="text" value="—" readOnly />
      )}
    </div>
  )
}
