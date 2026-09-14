import { Fragment, memo, useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  LRCLIB_URI_PLACEHOLDER,
  applyReading,
  errorMessage,
  fetchDocument,
  linkLrclib,
  setTokensIgnored,
  unlinkLrclib,
  updateDocumentText,
} from './api'
import type { Document, FuriganaSpan, GlossSense, LineTiming, Token } from './api'
import { getPosInfo } from './PosLegend'
import { useTabs } from './TabsContext'
import { usePersistentState } from './usePersistentState'
import { YouTubePlayer } from './YouTubePlayer'
import type { YouTubePlayerHandle } from './YouTubePlayer'

const REVIEW_REASON_LABELS: Record<string, string> = {
  heteronym: 'Multiple possible readings',
  no_kana_anchor: 'Ambiguous furigana split',
}

const SENSE_LIMIT = 5

// A stable empty list, for props that must keep one identity.
const NO_TOKENS: Token[] = []

// Elements where a focused Space already activates the control natively
// (typing targets are handled separately, in isTypingTarget) — the global
// play/pause listener must not override this.
const SPACE_HANDLED_NATIVELY = new Set(['BUTTON', 'SELECT', 'A'])

// The IFrame API has no time-update event, so playback is followed by
// polling its current time.
const PLAYBACK_POLL_MS = 100

const LRCLIB_LINK_NOTE =
  "Linking replaces these lyrics with LRCLIB's. If they differ, furigana and glosses are re-processed from " +
  "scratch and any readings you've manually selected are reset."
const LRCLIB_KEEP_NOTE =
  'Only the track ID is saved: these lyrics and the readings picked for them stay as they are. Lines are ' +
  "highlighted with LRCLIB's timings while its lyrics match these line for line."
const LRCLIB_KEPT_NOTE =
  "These lyrics are this document's own. LRCLIB supplies their line timings while its lyrics match them line " +
  'for line.'
const LRCLIB_SYNC_NOTE =
  'Lyrics load from LRCLIB each time this page opens. If they change there (say, someone uploads a corrected ' +
  "version), they replace these and any readings you've manually selected are reset — a timing-only update " +
  'keeps them.'

// The index of the line being sung at `time`, given each line's timing in
// order.
function linePlayingAt(lines: LineTiming[], time: number): number | null {
  // Binary search for the first line starting after `time`. Of lines that
  // start together, only the last has any length.
  let lo = 0
  let hi = lines.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (lines[mid].start <= time) lo = mid + 1
    else hi = mid
  }
  return lo > 0 && time < lines[lo - 1].end ? lo - 1 : null
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

// A clean JMDict miss under the reading we currently have — a real gloss
// lookup ran and came back with zero senses, so a manual reading correction
// could still fix it. Excludes composite glosses (a compound with no single
// JMDict entry of its own, shown broken into parts instead — see
// gloss.source): those already found real content via their pieces, just
// not as one entry, so an empty top-level senses list there doesn't mean
// the same thing it does for a plain jmdict/english_stub gloss.
function hasMissingGloss(token: Token): boolean {
  return token.gloss !== null && token.gloss.senses.length === 0 && token.gloss.source !== 'composite'
}

// Whether a token has reading options to pick from. An OOV token's options
// are only its own past corrections, which aren't offered.
function hasReadingOptions(token: Token): boolean {
  return token.review_reason !== 'oov' && token.conflicts.length > 0
}

// Whether a token opens a gloss popup, and so can be hovered, pinned, and
// selected.
function hasPopup(token: Token): boolean {
  return !token.is_english && (token.gloss !== null || token.conflicts.length > 0 || token.review_reason === 'oov')
}

// Tokens with the same key are one word, read and parsed the same way, with
// the same reading options apart from the user's own corrections — the only
// tokens one decision can apply to together (the server holds requests to
// the same rule). Built once per token, so each "can these go together"
// check is a lookup.
function groupKey(token: Token): string {
  return JSON.stringify([
    token.surface,
    token.reading_katakana,
    token.part_of_speech,
    token.conflicts.filter((c) => c.kind !== 'custom').map((c) => c.value),
  ])
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

// State for a control that saves with one request: whether it's saving, and
// the message its last attempt failed with. save() runs `request`, then
// `onSaved` with its result, or records why it failed.
function useSave() {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save<T>(request: () => Promise<T>, onSaved: (result: T) => void) {
    setSaving(true)
    setError(null)
    try {
      onSaved(await request())
    } catch (err) {
      setError(errorMessage(err, 'Failed to save — try again.'))
    } finally {
      setSaving(false)
    }
  }

  return { saving, error, setError, save }
}

function ReadingCorrectionForm({
  targets,
  documentId,
  onTokensUpdated,
}: {
  targets: Token[]
  documentId: number
  onTokensUpdated: (tokens: Token[]) => void
}) {
  const inputId = useId()
  const [value, setValue] = useState('')
  const { saving: submitting, error, save } = useSave()

  return (
    <form
      className="reading-correction"
      onClick={(e) => e.stopPropagation()}
      onSubmit={(e) => {
        e.preventDefault()
        const reading = value.trim()
        if (!reading) return
        save(
          () =>
            applyReading(
              documentId,
              targets.map((t) => t.id),
              reading,
            ),
          (updated) => {
            onTokensUpdated(updated)
            setValue('')
          },
        )
      }}
    >
      <label htmlFor={inputId}>Correct the reading</label>
      <div className="reading-correction-row">
        <input
          id={inputId}
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

// Buttons for `token`'s reading options, each applying its reading to all
// of `targets`: `token` itself, or other instances of the same word too.
function ReadingOptions({
  token,
  targets,
  documentId,
  onTokensUpdated,
}: {
  token: Token
  targets: Token[]
  documentId: number
  onTokensUpdated: (tokens: Token[]) => void
}) {
  const [applyingId, setApplyingId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Re-picking the option already selected only does anything when it also
  // brings other tokens in line.
  const canRepick = targets.length > 1

  return (
    <>
      {error && <div className="conflict-error">{error}</div>}
      <div className="conflict-options">
        {token.conflicts.map((conflict) => (
          <button
            key={conflict.id}
            type="button"
            className={conflict.selected ? 'conflict-option selected' : 'conflict-option'}
            disabled={applyingId !== null || (conflict.selected && !token.needs_review && !canRepick)}
            onClick={async (e) => {
              e.stopPropagation()
              setApplyingId(conflict.id)
              setError(null)
              try {
                const ids = targets.map((t) => t.id)
                onTokensUpdated(
                  await applyReading(documentId, ids, conflict.value.reading, conflict.value.furigana_spans),
                )
              } catch (err) {
                setError(errorMessage(err, 'Failed to save — try again.'))
              } finally {
                setApplyingId(null)
              }
            }}
          >
            {renderFuriganaSpans(conflict.value.furigana_spans)}
          </button>
        ))}
      </div>
    </>
  )
}

// Marks `targets` as needing no gloss, or, if they all already are, not.
function IgnoreGlossButton({
  targets,
  documentId,
  onTokensUpdated,
}: {
  targets: Token[]
  documentId: number
  onTokensUpdated: (tokens: Token[]) => void
}) {
  const { saving, error, save } = useSave()
  const ignored = targets.every((t) => t.gloss_ignored)

  return (
    <div className="ignore-gloss">
      {ignored && <div className="conflict-note">Ignored: no gloss expected.</div>}
      <button
        type="button"
        className="conflict-option"
        disabled={saving}
        onClick={(e) => {
          e.stopPropagation()
          save(() => setTokensIgnored(documentId, targets.map((t) => t.id), !ignored), onTokensUpdated)
        }}
      >
        {ignored ? 'Stop ignoring' : 'Ignore — no gloss needed'}
      </button>
      {error && <div className="conflict-error">{error}</div>}
    </div>
  )
}

// The decisions to make for `targets`, instances of one word: a reading,
// from their options or typed in, and whether the ones with no gloss need
// one. The first target with options supplies them — a word's options are
// the same wherever it has any, but not every instance is flagged.
function TokenDecisions({
  targets,
  offerCorrection,
  documentId,
  onTokensUpdated,
}: {
  targets: Token[]
  // Whether to offer typing a reading even when every target has a gloss.
  offerCorrection: boolean
  documentId: number
  onTokensUpdated: (tokens: Token[]) => void
}) {
  const source = targets.find(hasReadingOptions)
  // A missing gloss is worth offering a correction for regardless of
  // whether anything else flagged the token — Sudachi's own heteronym check
  // only catches disagreement within its own dictionary, not "JMDict would
  // match a different reading than the one Sudachi chose" (e.g. 三股 as
  // みまた vs さんまた).
  const missingGloss = targets.filter(hasMissingGloss)

  return (
    <>
      {source && (
        <ReadingOptions token={source} targets={targets} documentId={documentId} onTokensUpdated={onTokensUpdated} />
      )}
      {(offerCorrection || missingGloss.length > 0) && (
        <ReadingCorrectionForm targets={targets} documentId={documentId} onTokensUpdated={onTokensUpdated} />
      )}
      {missingGloss.length > 0 && (
        <IgnoreGlossButton targets={missingGloss} documentId={documentId} onTokensUpdated={onTokensUpdated} />
      )}
    </>
  )
}

function ApplyToAllOption({
  count,
  surface,
  checked,
  onChange,
}: {
  count: number
  surface: string
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="checkbox-option apply-to-all">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      Apply to all {count} matching {surface} in this document
    </label>
  )
}

function ConflictResolver({
  token,
  instances,
  documentId,
  onTokensUpdated,
}: {
  token: Token
  // Every token in the document in `token`'s group (see groupKey), `token`
  // included.
  instances: Token[]
  documentId: number
  onTokensUpdated: (tokens: Token[]) => void
}) {
  const [applyToAll, setApplyToAll] = useState(false)
  // `token` first, so its own options are the ones offered if it has any.
  const targets = applyToAll ? [token, ...instances.filter((t) => t !== token)] : [token]
  const isOov = token.review_reason === 'oov'
  const hasDecisions = hasReadingOptions(token) || hasMissingGloss(token)

  if (!isOov && !hasDecisions) return null

  return (
    <div className="conflict-resolver">
      {isOov && (
        <>
          <div className="conflict-title">Not in dictionary</div>
          <div className="conflict-note">No automatic reading candidates.</div>
        </>
      )}
      {hasReadingOptions(token) && (
        <div className="conflict-title">{REVIEW_REASON_LABELS[token.review_reason ?? ''] ?? 'Needs review'}</div>
      )}
      {instances.length > 1 && hasDecisions && (
        <ApplyToAllOption
          count={instances.length}
          surface={token.surface}
          checked={applyToAll}
          onChange={setApplyToAll}
        />
      )}
      <TokenDecisions
        targets={targets}
        offerCorrection={false}
        documentId={documentId}
        onTokensUpdated={onTokensUpdated}
      />
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

// A token's dictionary form, part of speech, and gloss, as its popup and the
// selection panel show them.
function GlossDetails({ token }: { token: Token }) {
  const gloss = token.gloss
  const posInfo = getPosInfo(token.part_of_speech[0])

  // Glosses are never shown for English tokens (see hasPopup), but are for
  // genuine Japanese words Sudachi doesn't recognize (review_reason 'oov') —
  // for those, dictionary_form/pos are fabricated placeholders (see is_oov),
  // not real analysis, so they're hidden.
  return (
    <>
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
    </>
  )
}

function GlossPopup({
  token,
  instances,
  documentId,
  onTokensUpdated,
  onMouseEnter,
  onMouseLeave,
}: {
  token: Token
  instances: Token[]
  documentId: number
  onTokensUpdated: (tokens: Token[]) => void
  onMouseEnter?: () => void
  onMouseLeave?: () => void
}) {
  return (
    <div
      className="gloss-popup"
      onClick={(e) => e.stopPropagation()}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <GlossDetails token={token} />
      {(token.needs_review ||
        token.conflicts.length > 0 ||
        hasMissingGloss(token) ||
        hasAmbiguousCompositePiece(token)) && (
        <ConflictResolver
          token={token}
          instances={instances}
          documentId={documentId}
          onTokensUpdated={onTokensUpdated}
        />
      )}
    </div>
  )
}

type SelectionKind = 'group' | 'adjacent'

// What the tokens at `indices` (ascending) can be selected as together:
// instances of one group (see groupKey), which decisions can apply to, or a
// run of neighbors, which may have spaces between them but not a line
// break — shown as a run only, since nothing acts on one yet. Null if
// neither. `keys` holds each token's group key.
function selectionKind(tokens: Token[], keys: string[], indices: number[]): SelectionKind | null {
  if (indices.every((i) => keys[i] === keys[indices[0]])) return 'group'
  for (let k = 1; k < indices.length; k++) {
    const between = tokens.slice(indices[k - 1] + 1, indices[k])
    if (!between.every((t) => t.part_of_speech[0] === '空白' && !t.surface.includes('\n'))) return null
  }
  return 'adjacent'
}

function SelectionPanel({
  tokens,
  keys,
  indices,
  focus,
  instances,
  panelRef,
  documentId,
  onTokensUpdated,
  onClear,
}: {
  tokens: Token[]
  // Each token's group key.
  keys: string[]
  // Positions of the selected tokens, ascending.
  indices: number[]
  // Position of the token whose gloss to show.
  focus: number
  // Every token in the first selected token's group, selected or not.
  instances: Token[]
  panelRef: React.Ref<HTMLDivElement>
  documentId: number
  onTokensUpdated: (tokens: Token[]) => void
  onClear: () => void
}) {
  const [applyToAll, setApplyToAll] = useState(false)
  const selected = indices.map((i) => tokens[i])
  const kind = selectionKind(tokens, keys, indices)
  const title =
    selected.length === 1
      ? `Selected ${selected[0].surface}`
      : kind === 'group'
        ? `${selected.length} × ${selected[0].surface} selected`
        : `${selected.length} adjacent tokens selected: ${tokens
            .slice(indices[0], indices[indices.length - 1] + 1)
            .map((t) => t.surface)
            .join('')}`
  // The selected tokens first, so theirs are the options offered.
  const targets = applyToAll ? [...selected, ...instances.filter((t) => !selected.includes(t))] : selected

  // Pinned to the top of the screen, and no taller than the page content
  // above the lyrics (see .selection-anchor). Clicks inside stop here, since
  // a click anywhere else ends the selection.
  return (
    <div className="selection-panel" ref={panelRef} onClick={(e) => e.stopPropagation()}>
      <div className="lyrics-header">
        <span className="selection-panel-title">{title}</span>
        <button type="button" className="lyrics-edit-toggle" onClick={onClear}>
          Clear
        </button>
      </div>
      <div className="selection-gloss">
        <GlossDetails token={tokens[focus]} />
      </div>
      {kind === 'group' ? (
        <>
          {selected.length === 1 && (
            <div className="conflict-note">
              Click the outlined instances of this word to decide for them together, or shift-click neighboring
              words to mark a run. Click anywhere else to finish.
            </div>
          )}
          {instances.length > selected.length && (
            <ApplyToAllOption
              count={instances.length}
              surface={selected[0].surface}
              checked={applyToAll}
              onChange={setApplyToAll}
            />
          )}
          <TokenDecisions targets={targets} offerCorrection documentId={documentId} onTokensUpdated={onTokensUpdated} />
        </>
      ) : (
        <div className="conflict-note">Joining tokens into one gloss isn't supported yet.</div>
      )}
    </div>
  )
}

// Plays the song from `start`, the start of the line it's placed before.
// Memoized like TokenSpan, so the playing line moving doesn't re-render it.
const LinePlayButton = memo(function LinePlayButton({
  start,
  onPlayLine,
}: {
  start: number
  onPlayLine: (start: number) => void
}) {
  return (
    <button
      type="button"
      className="line-play"
      aria-label="Play from this line"
      title="Play from this line"
      // Leaves focus where it was, so Space keeps playing and pausing rather
      // than pressing this again.
      onMouseDown={(e) => e.preventDefault()}
      onClick={() => onPlayLine(start)}
    >
      <svg viewBox="0 0 10 10" aria-hidden="true">
        <path d="M2 1 9 5 2 9Z" />
      </svg>
    </button>
  )
})

// One token of the lyrics. Memoized, with every prop either a primitive or
// stable across renders, so a change that doesn't touch this token (the
// playing line moving elsewhere, another token hovered) doesn't re-render it.
const TokenSpan = memo(function TokenSpan({
  token,
  index,
  className,
  showPopup,
  instances,
  documentId,
  onTokensUpdated,
  onClick,
  onHoverEnter,
  onHoverLeave,
}: {
  token: Token
  index: number
  className: string
  showPopup: boolean
  // Every token in this token's group (see groupKey), itself included.
  instances: Token[]
  documentId: number
  onTokensUpdated: (tokens: Token[]) => void
  onClick: (index: number, event: React.MouseEvent<HTMLElement>) => void
  onHoverEnter: (tokenId: number) => void
  onHoverLeave: (tokenId: number) => void
}) {
  const interactive = hasPopup(token)

  return (
    <span
      className={className}
      onMouseEnter={interactive ? () => onHoverEnter(token.id) : undefined}
      onMouseLeave={interactive ? () => onHoverLeave(token.id) : undefined}
      // Keeps a shift-click from selecting text.
      onMouseDown={
        interactive
          ? (e) => {
              if (e.shiftKey) e.preventDefault()
            }
          : undefined
      }
      onClick={interactive ? (e) => onClick(index, e) : undefined}
    >
      {renderFuriganaSpans(token.furigana_override ?? token.furigana_spans)}
      {showPopup && (
        <GlossPopup
          token={token}
          instances={instances}
          documentId={documentId}
          onTokensUpdated={onTokensUpdated}
          onMouseEnter={() => onHoverEnter(token.id)}
          onMouseLeave={() => onHoverLeave(token.id)}
        />
      )}
    </span>
  )
})

const TokenizedText = memo(function TokenizedText({
  tokens,
  documentId,
  onTokensUpdated,
  playingLine,
  lineTimings,
  onPlayLine,
}: {
  tokens: Token[]
  documentId: number
  onTokensUpdated: (tokens: Token[]) => void
  playingLine: number | null
  // Each line's timing, when lines can be played from; null hides the
  // play buttons.
  lineTimings: LineTiming[] | null
  onPlayLine: (start: number) => void
}) {
  const [hoveredId, setHoveredId] = useState<number | null>(null)
  const [pinnedId, setPinnedId] = useState<number | null>(null)
  // Positions of the tokens shift-clicked together, ascending, to decide for
  // (or, later, group) at once. They stay valid while this is mounted:
  // tokens are only ever replaced in place, and new text remounts it.
  const [selected, setSelected] = useState<number[]>([])
  // Position of the token last added to the selection, whose gloss the
  // selection panel shows.
  const [lastAdded, setLastAdded] = useState<number | null>(null)

  // Each token's group key, every token of each group (so a decision can
  // apply to all of them), and each token's position by id.
  const { keys, instancesByKey, indexById } = useMemo(() => {
    const keys = tokens.map(groupKey)
    const instancesByKey = new Map<string, Token[]>()
    tokens.forEach((token, index) => {
      const instances = instancesByKey.get(keys[index])
      if (instances) instances.push(token)
      else instancesByKey.set(keys[index], [token])
    })
    return { keys, instancesByKey, indexById: new Map(tokens.map((token, index) => [token.id, index])) }
  }, [tokens])

  const panelRef = useRef<HTMLDivElement>(null)

  // Scrolls `element` out from under the selection panel, which is pinned to
  // the top of the screen, if it's there once the panel has rendered.
  function revealBelowPanel(element: HTMLElement) {
    requestAnimationFrame(() => {
      const coveredTo = panelRef.current?.getBoundingClientRect().bottom ?? 0
      const top = element.getBoundingClientRect().top
      if (top < coveredTo) window.scrollBy({ top: top - coveredTo - 8 })
    })
  }

  function toggleSelected(index: number, element: HTMLElement) {
    const adding = !selected.includes(index)
    const next = adding ? [...selected, index].sort((a, b) => a - b) : selected.filter((i) => i !== index)
    // A token that fits neither kind of selection starts a new one.
    setSelected(next.length === 0 || selectionKind(tokens, keys, next) ? next : [index])
    if (adding) {
      setLastAdded(index)
      revealBelowPanel(element)
    }
  }

  const kind = selected.length > 0 ? selectionKind(tokens, keys, selected) : null
  const focus = lastAdded !== null && selected.includes(lastAdded) ? lastAdded : selected[selected.length - 1]
  // The group whose tokens are outlined as eligible to decide for together:
  // the selection's (a run has none), or else the pinned or hovered token's.
  const lookedAt = indexById.get(pinnedId ?? hoveredId ?? -1)
  const eligibleKey =
    selected.length > 0 ? (kind === 'group' ? keys[selected[0]] : null) : lookedAt !== undefined ? keys[lookedAt] : null

  // Whether the token at `index` is outlined as eligible — not the looked-at
  // token itself, which is already highlighted.
  function isEligible(index: number): boolean {
    return (
      hasPopup(tokens[index]) &&
      !selected.includes(index) &&
      keys[index] === eligibleKey &&
      (selected.length > 0 || index !== lookedAt)
    )
  }

  // Each token's line, by the line breaks before it: the index of its
  // timing in the document's lrclib_lines. And the first token with text on
  // each line, which that line's play button goes before — blank lines get
  // none.
  const { lineOf, firstWithText } = useMemo(() => {
    const lineOf: number[] = []
    const firstWithText = new Set<number>()
    let line = 0
    let lastLineWithText = -1
    tokens.forEach((token, index) => {
      lineOf.push(line)
      if (line !== lastLineWithText && token.surface.trim()) {
        firstWithText.add(index)
        lastLineWithText = line
      }
      line += token.surface.split('\n').length - 1
    })
    return { lineOf, firstWithText }
  }, [tokens])

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

  const handleHoverEnter = useCallback((tokenId: number) => {
    if (hoverLeaveTimeoutRef.current !== null) {
      window.clearTimeout(hoverLeaveTimeoutRef.current)
      hoverLeaveTimeoutRef.current = null
    }
    setHoveredId(tokenId)
  }, [])

  const handleHoverLeave = useCallback((tokenId: number) => {
    if (hoverLeaveTimeoutRef.current !== null) {
      window.clearTimeout(hoverLeaveTimeoutRef.current)
    }
    hoverLeaveTimeoutRef.current = window.setTimeout(() => {
      setHoveredId((prev) => (prev === tokenId ? null : prev))
    }, 150)
  }, [])

  function handleClick(index: number, event: React.MouseEvent<HTMLElement>) {
    event.stopPropagation()
    if (event.shiftKey) {
      setPinnedId(null)
      toggleSelected(index, event.currentTarget)
      return
    }
    // While selecting, a click on a selected or outlined token adds or
    // removes it; one on any other token ends the selection, then pins as
    // usual.
    if (selected.length > 0) {
      if (selected.includes(index) || isEligible(index)) {
        toggleSelected(index, event.currentTarget)
        return
      }
      setSelected([])
    }
    const id = tokens[index].id
    setPinnedId((prev) => (prev === id ? null : id))
  }

  // Kept current by an effect, so onTokenClick can keep one identity (and
  // TokenSpan's memo hold) while still seeing the latest selection.
  const handleClickRef = useRef(handleClick)
  useLayoutEffect(() => {
    handleClickRef.current = handleClick
  })
  const onTokenClick = useCallback(
    (index: number, event: React.MouseEvent<HTMLElement>) => handleClickRef.current(index, event),
    [],
  )

  // A click that reaches the document — anywhere but a token or the
  // selection panel, which stop their own clicks — closes the pinned popup
  // and ends the selection.
  useEffect(() => {
    function dismiss() {
      setPinnedId(null)
      setSelected([])
    }
    document.addEventListener('click', dismiss)
    return () => document.removeEventListener('click', dismiss)
  }, [])

  useEffect(() => {
    function clearSelection(event: KeyboardEvent) {
      if (event.key === 'Escape') setSelected([])
    }
    window.addEventListener('keydown', clearSelection)
    return () => window.removeEventListener('keydown', clearSelection)
  }, [])

  return (
    <>
      {selected.length > 0 && (
        <div className="selection-anchor">
          <SelectionPanel
            tokens={tokens}
            keys={keys}
            indices={selected}
            focus={focus}
            instances={instancesByKey.get(keys[selected[0]]) ?? NO_TOKENS}
            panelRef={panelRef}
            documentId={documentId}
            onTokensUpdated={onTokensUpdated}
            onClear={() => setSelected([])}
          />
        </div>
      )}
      <p className={lineTimings ? 'lyrics-box has-line-play' : 'lyrics-box'}>
        {tokens.map((token, index) => {
          // Lines past the last timing (blank ones at the end) have none.
          const lineStart = firstWithText.has(index) ? lineTimings?.[lineOf[index]]?.start : undefined
          const interactive = hasPopup(token)
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
          const needsCorrection = interactive && hasMissingGloss(token) && !token.gloss_ignored
          const needsReadingReview =
            (token.needs_review && token.conflicts.length > 0) || hasAmbiguousCompositePiece(token)

          const classNames = ['token']
          if (needsReadingReview) classNames.push('needs-review')
          if (needsCorrection) classNames.push('needs-correction')
          if (interactive) classNames.push('has-gloss')
          if (isPinned) classNames.push('pinned')
          if (lineOf[index] === playingLine) classNames.push('playing')
          if (selected.includes(index)) classNames.push('selected')
          if (isEligible(index)) classNames.push('eligible')

          return (
            <Fragment key={token.id}>
              {lineStart !== undefined && <LinePlayButton start={lineStart} onPlayLine={onPlayLine} />}
              <TokenSpan
                token={token}
                index={index}
                className={classNames.join(' ')}
                // While selecting, the selection panel shows the gloss instead.
                showPopup={isActive && interactive && selected.length === 0}
                instances={instancesByKey.get(keys[index]) ?? NO_TOKENS}
                documentId={documentId}
                onTokensUpdated={onTokensUpdated}
                onClick={onTokenClick}
                onHoverEnter={handleHoverEnter}
                onHoverLeave={handleHoverLeave}
              />
            </Fragment>
          )
        })}
      </p>
    </>
  )
})

function LrclibSource({ doc, onDocumentUpdated }: { doc: Document; onDocumentUpdated: (doc: Document) => void }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [replaceText, setReplaceText] = useState(false)
  const { saving, error, setError, save: run } = useSave()

  function save(request: () => Promise<Document>) {
    run(request, (updated) => {
      onDocumentUpdated(updated)
      setEditing(false)
    })
  }

  return (
    <>
      <div className="lyrics-header">
        <label htmlFor="lrclib-uri">LRCLIB</label>
        {!editing && (
          <div className="lyrics-editor-actions">
            <button
              type="button"
              className="lyrics-edit-toggle"
              disabled={saving}
              onClick={() => {
                setDraft(doc.lrclib_uri ?? '')
                // Keeping the lyrics loses nothing, so it's the default.
                setReplaceText(doc.lrclib_replaces_text ?? false)
                setError(null)
                setEditing(true)
              }}
            >
              {doc.lrclib_uri ? 'Change' : 'Link to LRCLIB'}
            </button>
            {doc.lrclib_uri && (
              <button
                type="button"
                className="lyrics-edit-toggle"
                disabled={saving}
                onClick={() => save(() => unlinkLrclib(doc.id))}
              >
                Unlink
              </button>
            )}
          </div>
        )}
      </div>

      {editing ? (
        <form
          className="lyrics-editor"
          onSubmit={(e) => {
            e.preventDefault()
            const uri = draft.trim()
            if (uri) save(() => linkLrclib(doc.id, uri, replaceText))
          }}
        >
          <input
            id="lrclib-uri"
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={LRCLIB_URI_PLACEHOLDER}
            disabled={saving}
          />
          <label className="checkbox-option">
            <input
              type="checkbox"
              checked={replaceText}
              onChange={(e) => setReplaceText(e.target.checked)}
              disabled={saving}
            />
            Replace these lyrics with LRCLIB's
          </label>
          <div className="lyrics-editor-actions">
            <button type="submit" disabled={saving || !draft.trim()}>
              {saving ? 'Loading…' : 'Save'}
            </button>
            <button type="button" disabled={saving} onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
          <p className="lyrics-editor-note">{replaceText ? LRCLIB_LINK_NOTE : LRCLIB_KEEP_NOTE}</p>
        </form>
      ) : (
        <>
          <p id="lrclib-uri" className="readonly-text">
            {doc.lrclib_uri ? (
              <a href={doc.lrclib_uri} target="_blank" rel="noreferrer">
                {doc.lrclib_uri}
              </a>
            ) : (
              '—'
            )}
          </p>
          {doc.lrclib_uri && (
            <p className="lyrics-editor-note">
              {doc.lrclib_replaces_text ? LRCLIB_SYNC_NOTE : LRCLIB_KEPT_NOTE}
              {!doc.lrclib_replaces_text &&
                !doc.lrclib_lines &&
                " LRCLIB's lyrics for this track don't match these right now, so lines aren't highlighted."}
            </p>
          )}
          {doc.lrclib_sync_error && <p className="form-error">{doc.lrclib_sync_error}</p>}
        </>
      )}
      {error && <p className="form-error">{error}</p>}
    </>
  )
}

function RangeControl({
  id,
  label,
  unit,
  value,
  onChange,
  min,
  max,
}: {
  id: string
  label: string
  unit: string
  value: number
  onChange: (value: number) => void
  min: number
  max: number
}) {
  return (
    <div className="control">
      <label htmlFor={id}>
        {label} {value}
        {unit}
      </label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
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
  const [playingLine, setPlayingLine] = useState<number | null>(null)

  // Viewing settings: the same for every document, and kept across reloads.
  const [fontSize, setFontSize] = usePersistentState('fontSize', 18)
  const [furiganaSize, setFuriganaSize] = usePersistentState('furiganaSize', 11)
  const [seekSeconds, setSeekSeconds] = usePersistentState('seekSeconds', 3)
  // Defaults to the theme's accent, which is hex, as a color input needs.
  const [highlightColor, setHighlightColor] = usePersistentState('highlightColor', () =>
    getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
  )
  const [highlightOpacity, setHighlightOpacity] = usePersistentState('highlightOpacity', 25)

  const [editingLyrics, setEditingLyrics] = useState(false)
  const [lyricsDraft, setLyricsDraft] = useState('')
  const {
    saving: savingLyrics,
    error: lyricsSaveError,
    setError: setLyricsSaveError,
    save: saveLyrics,
  } = useSave()

  const youtubePlayerRef = useRef<YouTubePlayerHandle>(null)
  // The page content above the lyrics, and its height: the most the pinned
  // selection panel may cover (see .selection-anchor).
  const [headerEl, setHeaderEl] = useState<HTMLDivElement | null>(null)
  const [headerHeight, setHeaderHeight] = useState(0)

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
        setError(errorMessage(err, 'Failed to load document.'))
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
        setTokensError(errorMessage(err, 'Failed to load furigana.'))
      })
      .finally(() => {
        if (!cancelled) setTokensLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [doc, ensureProcessed])

  const handleTokensUpdated = useCallback((updated: Token[]) => {
    const byId = new Map(updated.map((t) => [t.id, t]))
    setTokens((prev) => prev?.map((t) => byId.get(t.id) ?? t) ?? prev)
  }, [])

  const handlePlayLine = useCallback((start: number) => youtubePlayerRef.current?.playFrom(start), [])

  const lrclibLines = doc?.lrclib_lines ?? null
  const hasVideo = Boolean(doc?.youtube_video_id)

  useEffect(() => {
    if (!lrclibLines || !hasVideo) return
    const interval = window.setInterval(() => {
      const time = youtubePlayerRef.current?.getCurrentTime() ?? null
      // An index, so React skips the re-render while the line is unchanged.
      setPlayingLine(time === null ? null : linePlayingAt(lrclibLines, time))
    }, PLAYBACK_POLL_MS)
    return () => {
      window.clearInterval(interval)
      // Whatever lines come next, this index isn't into them.
      setPlayingLine(null)
    }
  }, [lrclibLines, hasVideo])

  useEffect(() => {
    if (!headerEl) return
    const observer = new ResizeObserver(() => setHeaderHeight(headerEl.offsetHeight))
    observer.observe(headerEl)
    return () => observer.disconnect()
  }, [headerEl])

  if (loading) return <p>Loading…</p>
  if (error) return <p className="form-error">{error}</p>
  if (!doc) return null

  function handleSaveLyrics() {
    const trimmed = lyricsDraft.trim()
    if (!trimmed) return
    saveLyrics(
      () => updateDocumentText(documentId, trimmed),
      (updated) => {
        // A new object reference so the token-processing effect re-runs —
        // the backend already deleted the old tokens/conflicts/gloss links
        // on save, so this regenerates everything from scratch, same as a
        // never-before-processed document.
        setDoc(updated)
        setEditingLyrics(false)
      },
    )
  }

  function handleDocumentLinked(updated: Document) {
    setDoc(updated)
    // Its lyrics are LRCLIB's now, so there's nothing left to edit.
    if (updated.lrclib_replaces_text) setEditingLyrics(false)
  }

  return (
    <div className="new-document-form">
      <div className="document-header" ref={setHeaderEl}>
        <h1>{doc.title}</h1>

        <label htmlFor="title">Title</label>
        <p id="title" className="readonly-text">{doc.title}</p>

        <LrclibSource doc={doc} onDocumentUpdated={handleDocumentLinked} />

        <div className="lyrics-header">
          <label htmlFor="lyrics">Lyrics</label>
          {!editingLyrics && !doc.lrclib_replaces_text && (
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

        {!editingLyrics && (
          <div className="text-size-controls">
            <RangeControl
              id="font-size"
              label="Text size"
              unit="px"
              value={fontSize}
              onChange={setFontSize}
              min={14}
              max={32}
            />
            <RangeControl
              id="furigana-size"
              label="Furigana size"
              unit="px"
              value={furiganaSize}
              onChange={setFuriganaSize}
              min={6}
              max={20}
            />
            <RangeControl
              id="seek-seconds"
              label="Seek step"
              unit="s"
              value={seekSeconds}
              onChange={setSeekSeconds}
              min={1}
              max={30}
            />
            <div className="control">
              <label htmlFor="highlight-color">Highlight color</label>
              <input
                id="highlight-color"
                type="color"
                value={highlightColor}
                onChange={(e) => setHighlightColor(e.target.value)}
              />
            </div>
            <RangeControl
              id="highlight-opacity"
              label="Highlight opacity"
              unit="%"
              value={highlightOpacity}
              onChange={setHighlightOpacity}
              min={5}
              max={100}
            />
          </div>
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
        <div
          id="lyrics"
          style={
            {
              '--lyrics-font-size': `${fontSize}px`,
              '--furigana-font-size': `${furiganaSize}px`,
              '--highlight-color': highlightColor,
              '--highlight-opacity': `${highlightOpacity}%`,
              '--header-height': `${headerHeight}px`,
            } as React.CSSProperties
          }
        >
          {tokensLoading && <p>Processing…</p>}
          {tokens && (
            <TokenizedText
              tokens={tokens}
              documentId={documentId}
              onTokensUpdated={handleTokensUpdated}
              playingLine={playingLine}
              // Without a video there's nothing to play them from.
              lineTimings={hasVideo ? lrclibLines : null}
              onPlayLine={handlePlayLine}
            />
          )}
          {tokensError && (
            <>
              <p className="form-error">{tokensError} Showing plain lyrics instead.</p>
              <p className="lyrics-box">{doc.text}</p>
            </>
          )}
        </div>
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
