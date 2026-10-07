import {
  Fragment,
  type ReactNode,
  memo,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { Link, useBlocker, useParams } from 'react-router-dom'
import {
  LRCLIB_URI_PLACEHOLDER,
  acceptPhraseSuggestions,
  addTokenCard,
  applyReading,
  errorMessage,
  fetchAlternateReadings,
  fetchDocument,
  fetchDocumentWords,
  fetchPieceWords,
  linkLrclib,
  pickPieceWord,
  resolvePhraseFurigana,
  saveLineTimings,
  setTokensIgnored,
  suspendCard,
  unlinkLrclib,
  unmergePhrase,
  updateDocumentText,
} from './api'
import type {
  Conflict,
  ConflictOptionValue,
  Document,
  DocumentWord,
  FuriganaSpan,
  LineTiming,
  PhraseConflictValue,
  PhraseFuriganaValue,
  PredicateGroupValue,
  StudyCard,
  Token,
  WordOption,
} from './api'
import { ConfirmDialog } from './ConfirmDialog'
import { PosTermRuby, getPosInfo } from './PosLegend'
import { SenseList } from './SenseList'
import { useTabs } from './TabsContext'
import {
  formatTimestamp,
  lastStartedBy,
  lineToStamp,
  linesOf,
  nudgedStart,
  overlapFor,
  roundedToMs,
  timingsFromStarts,
} from './timing'
import type { LyricsLine } from './timing'
import { useLatest } from './useLatest'
import { useSave } from './useSave'
import { usePersistentState } from './usePersistentState'
import { YouTubePlayer } from './YouTubePlayer'
import type { YouTubePlayerHandle } from './YouTubePlayer'

const REVIEW_REASON_LABELS: Record<string, string> = {
  heteronym: 'Multiple possible readings',
  no_kana_anchor: 'Ambiguous furigana split',
}

// Stable empty lists, for props that must keep one identity.
const NO_TOKENS: Token[] = []
const NO_WORDS: DocumentWord[] = []

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

// Whether keys pressed while `element` has focus type into it.
function isTypingTarget(element: Element | null): boolean {
  return (
    element instanceof HTMLElement &&
    (element.tagName === 'INPUT' ||
      element.tagName === 'TEXTAREA' ||
      element.isContentEditable)
  )
}

// True when a composite gloss (a compound with no JMDict entry of its own,
// shown broken into parts instead — see gloss.source) has a piece whose own
// reading is itself ambiguous (e.g. 女神 within 勝利の女神). There's no picker
// for this yet — see GlossPopup's composite note — but it's still something
// the user hasn't reviewed, so it counts for the same purposes needs_review
// conflicts normally would.
function hasAmbiguousCompositePiece(token: Token): boolean {
  return (
    token.gloss?.source === 'composite' &&
    token.gloss.pieces.some((p) => p.ambiguous_readings.length > 0)
  )
}

// A clean JMDict miss under the reading we currently have — a real gloss
// lookup ran and came back with zero senses, so a manual reading correction
// could still fix it. Excludes composite glosses (a compound with no single
// JMDict entry of its own, shown broken into parts instead — see
// gloss.source): those already found real content via their pieces, just
// not as one entry, so an empty top-level senses list there doesn't mean
// the same thing it does for a jmdict_miss or english_stub gloss.
function hasMissingGloss(token: Token): boolean {
  return (
    token.gloss !== null &&
    token.gloss.senses.length === 0 &&
    token.gloss.source !== 'composite'
  )
}

// Conflict rows that aren't reading options, with values of other shapes: a
// phrase suggestion, a phrase's alternative furigana, and a split predicate
// group.
function isPhraseConflict(
  conflict: Conflict,
): conflict is Conflict & { kind: 'phrase'; value: PhraseConflictValue } {
  return conflict.kind === 'phrase'
}

function isPhraseFuriganaConflict(conflict: Conflict): conflict is Conflict & {
  kind: 'phrase_furigana'
  value: PhraseFuriganaValue
} {
  return conflict.kind === 'phrase_furigana'
}

function isPredicateConflict(
  conflict: Conflict,
): conflict is Conflict & { kind: 'predicate'; value: PredicateGroupValue } {
  return conflict.kind === 'predicate'
}

function readingConflicts(
  token: Token,
): (Conflict & { kind: 'heteronym' | 'no_kana_anchor' | 'custom' })[] {
  return token.conflicts.filter(
    (c): c is Conflict & { kind: 'heteronym' | 'no_kana_anchor' | 'custom' } =>
      !isPhraseConflict(c) &&
      !isPhraseFuriganaConflict(c) &&
      !isPredicateConflict(c),
  )
}

// The one phrase suggestion offered starting at this token, if any and if
// it hasn't already been accepted.
function phraseSuggestion(
  token: Token,
): (Conflict & { kind: 'phrase'; value: PhraseConflictValue }) | undefined {
  return token.conflicts.find(
    (c): c is Conflict & { kind: 'phrase'; value: PhraseConflictValue } =>
      isPhraseConflict(c) && !c.selected,
  )
}

// The other valid furigana splits of the accepted phrase this token starts.
function phraseFuriganaOptions(
  token: Token,
): (Conflict & { kind: 'phrase_furigana'; value: PhraseFuriganaValue })[] {
  return token.conflicts.filter(isPhraseFuriganaConflict)
}

// The predicate group starting at this token that can be merged again, if
// it's been split.
function splitPredicateGroup(
  token: Token,
): (Conflict & { kind: 'predicate'; value: PredicateGroupValue }) | undefined {
  if (token.phrase_start_position !== null) return undefined
  return token.conflicts.find(isPredicateConflict)
}

// Whether this token is merged into a group of either kind.
function isMerged(token: Token): boolean {
  return token.phrase_start_position !== null
}

// A token's fused "token group": every token sharing its phrase_start_position,
// or just itself if it isn't merged into one. Used to outline the whole span
// as one unit — a group of one for a standalone token — rather than only the
// token that's actually pinned, hovered, or playing.
function phraseSpanKey(token: Token, index: number): string {
  return token.phrase_start_position !== null
    ? `phrase:${token.phrase_start_position}`
    : `solo:${index}`
}

// Whether this token is part of an accepted phrase, whose tokens are glossed
// as the phrase's headword rather than as themselves.
function isInAcceptedPhrase(token: Token): boolean {
  return token.group_kind === 'phrase'
}

// Whether this noun can combine with a directly-following する to form a
// verb, by Sudachi's サ変可能 ("can take する") tag.
function canTakeSuru(token: Token): boolean {
  return (
    token.part_of_speech[0] === '名詞' && token.part_of_speech[2] === 'サ変可能'
  )
}

// Whether a token has reading options to pick from. An OOV token's options
// are only its own past corrections, which aren't offered.
function hasReadingOptions(token: Token): boolean {
  // Hidden inside an accepted phrase, whose reading is the phrase's: split
  // it first (see UnmergePhraseOption). A predicate group is glossed again
  // with the picked reading instead.
  return (
    token.review_reason !== 'oov' &&
    !isInAcceptedPhrase(token) &&
    readingConflicts(token).length > 0
  )
}

// Whether a token opens a gloss popup, and so can be hovered, pinned, and
// selected.
function hasPopup(token: Token): boolean {
  return (
    !token.is_english &&
    (token.gloss !== null ||
      token.conflicts.length > 0 ||
      token.review_reason === 'oov')
  )
}

// Tokens with the same key are one word, read and parsed the same way, with
// the same reading options apart from the user's own corrections — the only
// tokens one decision can apply to together (the server holds requests to
// the same rule). Built once per token, so each "can these go together"
// check is a lookup. Only reading options count, since the other conflict
// kinds depend on the tokens around a word.
function groupKey(token: Token): string {
  return JSON.stringify([
    token.surface,
    token.reading_katakana,
    token.part_of_speech,
    readingConflicts(token)
      .filter((c) => c.kind !== 'custom')
      .map((c) => c.value),
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

// Takes the tokens an edit changed. `changesWords` is false for an edit that
// can't make a token another word, which spares reloading the song's words.
type TokensUpdated = (tokens: Token[], changesWords?: boolean) => void

function ReadingCorrectionForm({
  targets,
  documentId,
  onTokensUpdated,
}: {
  targets: Token[]
  documentId: number
  onTokensUpdated: TokensUpdated
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

// A button that fetches a list of options on demand, then shows them to
// apply one. Nothing is offered once every option fetched is already selected.
function SearchedOptions<T>({
  searchLabel,
  noneFound,
  heading,
  search,
  apply,
  onTokensUpdated,
  optionKey,
  renderOption,
  isSelected = () => false,
  canRepick = false,
  refetchAfterApply = false,
}: {
  searchLabel: string
  noneFound: string
  heading?: string
  search: () => Promise<T[]>
  apply: (option: T) => Promise<Token[]>
  onTokensUpdated: TokensUpdated
  optionKey: (option: T) => string
  renderOption: (option: T) => ReactNode
  isSelected?: (option: T) => boolean
  canRepick?: boolean
  refetchAfterApply?: boolean
}) {
  const [options, setOptions] = useState<T[] | null>(null)
  const { saving: searching, error: searchError, save: runSearch } = useSave()
  const { saving: applying, error: applyError, save: applyOption } = useSave()

  if (options === null) {
    return (
      <div className="phrase-suggestion">
        <button
          type="button"
          className="conflict-option"
          disabled={searching}
          onClick={(e) => {
            e.stopPropagation()
            runSearch(search, setOptions)
          }}
        >
          {searchLabel}
        </button>
        {searchError && <div className="conflict-error">{searchError}</div>}
      </div>
    )
  }

  if (options.every(isSelected)) {
    return <div className="conflict-note">{noneFound}</div>
  }

  return (
    <div className="phrase-suggestion">
      {heading && <div className="conflict-note">{heading}</div>}
      {applyError && <div className="conflict-error">{applyError}</div>}
      <div className="conflict-options">
        {options.map((option) => {
          const selected = isSelected(option)
          return (
            <button
              key={optionKey(option)}
              type="button"
              className={
                selected ? 'conflict-option selected' : 'conflict-option'
              }
              disabled={applying || (selected && !canRepick)}
              onClick={(e) => {
                e.stopPropagation()
                applyOption(
                  () => apply(option),
                  (tokens) => {
                    onTokensUpdated(tokens)
                    // Separate from the save, so a failed search can't hide
                    // that it worked.
                    if (refetchAfterApply) runSearch(search, setOptions)
                  },
                )
              }}
            >
              {renderOption(option)}
            </button>
          )
        })}
      </div>
    </div>
  )
}

// Offers every other reading JMDict has for the targets' dictionary form,
// searched for on demand, to apply to all of them.
function AlternateReadingSearch({
  targets,
  documentId,
  onTokensUpdated,
}: {
  targets: Token[]
  documentId: number
  onTokensUpdated: TokensUpdated
}) {
  return (
    <SearchedOptions<ConflictOptionValue>
      searchLabel="Look for other readings"
      noneFound="No other readings found for this word."
      search={async () =>
        (await fetchAlternateReadings(documentId, targets[0].id)).filter(
          (option) => !option.own,
        )
      }
      apply={(option) =>
        applyReading(
          documentId,
          targets.map((t) => t.id),
          option.reading,
          option.furigana_spans,
        )
      }
      onTokensUpdated={onTokensUpdated}
      refetchAfterApply
      optionKey={(option) => option.reading}
      renderOption={(option) => renderFuriganaSpans(option.furigana_spans)}
    />
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
  onTokensUpdated: TokensUpdated
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
        {readingConflicts(token).map((conflict) => (
          <button
            key={conflict.id}
            type="button"
            className={
              conflict.selected ? 'conflict-option selected' : 'conflict-option'
            }
            disabled={
              applyingId !== null ||
              (conflict.selected && !token.needs_review && !canRepick)
            }
            onClick={async (e) => {
              e.stopPropagation()
              setApplyingId(conflict.id)
              setError(null)
              try {
                const ids = targets.map((t) => t.id)
                onTokensUpdated(
                  await applyReading(
                    documentId,
                    ids,
                    conflict.value.reading,
                    conflict.value.furigana_spans,
                  ),
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
  onTokensUpdated: TokensUpdated
}) {
  const { saving, error, save } = useSave()
  const ignored = targets.every((t) => t.gloss_ignored)

  return (
    <div className="ignore-gloss">
      {ignored && (
        <div className="conflict-note">Ignored: no gloss expected.</div>
      )}
      <button
        type="button"
        className="conflict-option"
        disabled={saving}
        onClick={(e) => {
          e.stopPropagation()
          save(
            () =>
              setTokensIgnored(
                documentId,
                targets.map((t) => t.id),
                !ignored,
              ),
            (updated) => onTokensUpdated(updated, false),
          )
        }}
      >
        {ignored ? 'Stop ignoring' : 'Ignore — no gloss needed'}
      </button>
      {error && <div className="conflict-error">{error}</div>}
    </div>
  )
}

// Whether `word` is in the user's study list, with the one action that
// changes that: adding it, removing it, or restoring it with its history.
function StudyListControl({
  word,
  documentId,
  onCardChanged,
}: {
  word: DocumentWord
  documentId: number
  onCardChanged: (card: StudyCard) => void
}) {
  const { saving, error, save } = useSave()
  const card = word.card
  const studied = card !== null && !card.suspended

  return (
    <div className="study-list">
      {card && (
        <span className="conflict-note">
          {studied ? 'In your study list ✓' : 'Removed from your study list'}
        </span>
      )}
      <button
        type="button"
        className="conflict-option"
        disabled={saving}
        onClick={(e) => {
          e.stopPropagation()
          save(
            () =>
              studied
                ? suspendCard(card.id)
                : addTokenCard(documentId, word.token_ids[0], word.piece),
            onCardChanged,
          )
        }}
      >
        {studied ? 'Remove' : card ? 'Restore' : 'Add to study list'}
      </button>
      {error && <div className="conflict-error">{error}</div>}
    </div>
  )
}

// Offers the other words JMDict has with the reading of `piece` of the
// targets' gloss, searched for on demand, to make that piece of all of them:
// for katakana, whose kanji the gloss can only guess (アイ as 会う or 合う).
function PieceWordPicker({
  piece,
  targets,
  documentId,
  onTokensUpdated,
}: {
  piece: number
  // Tokens sung in katakana, the first the one the popup is for.
  targets: Token[]
  documentId: number
  onTokensUpdated: TokensUpdated
}) {
  const shown = targets[0].gloss?.pieces[piece]
  if (!shown) return null

  return (
    <SearchedOptions<WordOption>
      searchLabel={`Another word read ${shown.reading}?`}
      noneFound={`No other word is read ${shown.reading}.`}
      heading={`Which word is ${shown.reading}?`}
      search={() => fetchPieceWords(documentId, targets[0].id, piece)}
      apply={(option) =>
        pickPieceWord(
          documentId,
          targets.map((t) => t.id),
          piece,
          option.idseq,
        )
      }
      onTokensUpdated={onTokensUpdated}
      optionKey={(option) => String(option.idseq)}
      renderOption={(option) => (
        <>
          {option.spelling}
          {option.gloss.length > 0 && ` — ${option.gloss.join(', ')}`}
        </>
      )}
      isSelected={(option) => option.current}
      // Re-picking the selected word only does anything when it also brings
      // the other targets in line.
      canRepick={targets.length > 1}
    />
  )
}

// Every suggestion in `instances` for the same phrase as `suggestion`: the
// same span and reading, since one word can start different phrases.
function matchingPhraseSuggestions(
  suggestion: Conflict & { kind: 'phrase'; value: PhraseConflictValue },
  instances: Token[],
): (Conflict & { kind: 'phrase'; value: PhraseConflictValue })[] {
  return instances
    .map(phraseSuggestion)
    .filter(
      (
        other,
      ): other is Conflict & { kind: 'phrase'; value: PhraseConflictValue } =>
        other !== undefined &&
        other.value.surface === suggestion.value.surface &&
        other.value.reading === suggestion.value.reading &&
        other.value.token_count === suggestion.value.token_count,
    )
}

// Offers accepting `suggestion`, optionally for every instance of the same
// phrase. It's never applied otherwise, since a headword match can be a
// coincidence (今日は spelling こんにちは).
function PhraseSuggestionOption({
  suggestion,
  instances,
  documentId,
  onTokensUpdated,
}: {
  suggestion: Conflict & { kind: 'phrase'; value: PhraseConflictValue }
  instances: Token[]
  documentId: number
  onTokensUpdated: TokensUpdated
}) {
  const [applyToAll, setApplyToAll] = useState(false)
  const { saving, error, save } = useSave()

  const matches = matchingPhraseSuggestions(suggestion, instances)
  const conflictIds = applyToAll ? matches.map((c) => c.id) : [suggestion.id]

  return (
    <div className="phrase-suggestion phrase-suggestion-promoted">
      <div className="conflict-note">
        Combine {suggestion.value.surface} into one{' '}
        {suggestion.value.token_count ===
        (suggestion.value.phrase_token_count ?? suggestion.value.token_count)
          ? 'word'
          : 'word with its grammar'}
        ?
      </div>
      {matches.length > 1 && (
        <ApplyToAllOption
          count={matches.length}
          surface={suggestion.value.surface}
          checked={applyToAll}
          onChange={setApplyToAll}
        />
      )}
      <button
        type="button"
        className="conflict-option phrase-combine-option"
        disabled={saving}
        onClick={(e) => {
          e.stopPropagation()
          save(
            () => acceptPhraseSuggestions(documentId, conflictIds),
            onTokensUpdated,
          )
        }}
      >
        Combine as {suggestion.value.lookup_form}「{suggestion.value.reading}」
      </button>
      {error && <div className="conflict-error">{error}</div>}
    </div>
  )
}

// Offers splitting the group covering `token` — any member of it, not just
// its first token (see unmergePhrase).
function UnmergePhraseOption({
  token,
  documentId,
  onTokensUpdated,
}: {
  token: Token
  documentId: number
  onTokensUpdated: TokensUpdated
}) {
  const { saving, error, save } = useSave()

  if (token.phrase_start_position === null) return null

  return (
    <div className="phrase-suggestion">
      <div className="conflict-note">
        {isInAcceptedPhrase(token)
          ? 'Combined with neighboring tokens into one word.'
          : 'Grouped with the grammar attached to it.'}
      </div>
      <button
        type="button"
        className="conflict-option"
        disabled={saving}
        onClick={(e) => {
          e.stopPropagation()
          save(() => unmergePhrase(documentId, token.id), onTokensUpdated)
        }}
      >
        Split into separate words
      </button>
      {error && <div className="conflict-error">{error}</div>}
    </div>
  )
}

// Offers merging `group`, a split predicate group, again.
function RegroupOption({
  group,
  documentId,
  onTokensUpdated,
}: {
  group: Conflict & { kind: 'predicate'; value: PredicateGroupValue }
  documentId: number
  onTokensUpdated: TokensUpdated
}) {
  const { saving, error, save } = useSave()

  return (
    <div className="phrase-suggestion">
      <button
        type="button"
        className="conflict-option"
        disabled={saving}
        onClick={(e) => {
          e.stopPropagation()
          save(
            () => acceptPhraseSuggestions(documentId, [group.id]),
            onTokensUpdated,
          )
        }}
      >
        Group {group.value.surface} with its grammar again
      </button>
      {error && <div className="conflict-error">{error}</div>}
    </div>
  )
}

// Offers the other valid furigana splits of the accepted phrase `token`
// starts, if it has any.
function PhraseFuriganaOptions({
  token,
  documentId,
  onTokensUpdated,
}: {
  token: Token
  documentId: number
  onTokensUpdated: TokensUpdated
}) {
  const options = phraseFuriganaOptions(token)
  const { saving: applying, error, save } = useSave()

  if (options.length === 0) return null

  return (
    <div className="phrase-suggestion">
      <div className="conflict-note">
        This word's reading could be split more than one way:
      </div>
      <div className="conflict-options">
        {options.map((option) => (
          <button
            key={option.id}
            type="button"
            className="conflict-option"
            disabled={applying}
            onClick={(e) => {
              e.stopPropagation()
              save(
                () => resolvePhraseFurigana(documentId, option.id),
                (updated) => onTokensUpdated(updated, false),
              )
            }}
          >
            {renderFuriganaSpans(
              [...option.value.updates]
                .sort((a, b) => a.offset - b.offset)
                .flatMap((u) => u.furigana_spans),
            )}
          </button>
        ))}
      </div>
      {error && <div className="conflict-error">{error}</div>}
    </div>
  )
}

// The decisions to make for `targets`, instances of one word: a reading,
// from their options or typed in, and whether the ones with no gloss need
// one. The first target with options supplies them — a word's options are
// the same wherever it has any, but not every instance is flagged.
function TokenDecisions({
  targets: allTargets,
  offerCorrection,
  documentId,
  onTokensUpdated,
}: {
  targets: Token[]
  // Whether to offer typing a reading even when every target has a gloss.
  offerCorrection: boolean
  documentId: number
  onTokensUpdated: TokensUpdated
}) {
  // A token in an accepted phrase is read as the phrase: split it first.
  // Filtered here too, so a selection including one can't sweep it in.
  const targets = allTargets.filter((t) => !isInAcceptedPhrase(t))
  if (targets.length === 0) return null
  const source = targets.find(hasReadingOptions)
  // A missing gloss is worth offering a correction for regardless of
  // whether anything else flagged the token — Sudachi's own heteronym check
  // only catches disagreement within its own dictionary, not "JMDict would
  // match a different reading than the one Sudachi chose" (e.g. 三股 as
  // みまた vs さんまた).
  const missingGloss = targets.filter(hasMissingGloss)
  // Typing a reading is only for OOV tokens, which have no dictionary entry
  // to search. Every target shares one review_reason (see groupKey).
  const isOov = targets[0]?.review_reason === 'oov'

  return (
    <>
      {source && (
        <ReadingOptions
          token={source}
          targets={targets}
          documentId={documentId}
          onTokensUpdated={onTokensUpdated}
        />
      )}
      {isOov ? (
        (offerCorrection || missingGloss.length > 0) && (
          <ReadingCorrectionForm
            targets={targets}
            documentId={documentId}
            onTokensUpdated={onTokensUpdated}
          />
        )
      ) : (
        <AlternateReadingSearch
          targets={targets}
          documentId={documentId}
          onTokensUpdated={onTokensUpdated}
        />
      )}
      {missingGloss.length > 0 && (
        <IgnoreGlossButton
          targets={missingGloss}
          documentId={documentId}
          onTokensUpdated={onTokensUpdated}
        />
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
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      Apply to all {count} matching {surface} in this document
    </label>
  )
}

function ConflictResolver({
  token,
  instances,
  wordPieces,
  documentId,
  onTokensUpdated,
}: {
  token: Token
  // Every token in the document in `token`'s group (see groupKey), `token`
  // included.
  instances: Token[]
  // For a token sung in katakana, the pieces of its gloss that are words.
  wordPieces: number[]
  documentId: number
  onTokensUpdated: TokensUpdated
}) {
  const [applyToAll, setApplyToAll] = useState(false)
  // `token` first, so its own options are the ones offered if it has any.
  // Instances in accepted phrases are excluded even when "apply to all" is
  // checked, as a pick on one directly would be (see hasReadingOptions).
  const targets = applyToAll
    ? [token, ...instances.filter((t) => t !== token && !isInAcceptedPhrase(t))]
    : [token]
  const isOov = token.review_reason === 'oov'
  const suggestion = phraseSuggestion(token)
  const regroup = splitPredicateGroup(token)

  // No early return: the reading search is offered for every non-OOV token,
  // flagged or not (期 read ご never is).

  return (
    <div className="conflict-resolver">
      {/* Promoted above everything else, where it's hard to miss. */}
      {suggestion && (
        <PhraseSuggestionOption
          suggestion={suggestion}
          instances={instances}
          documentId={documentId}
          onTokensUpdated={onTokensUpdated}
        />
      )}
      {isInAcceptedPhrase(token) ? (
        <>
          <PhraseFuriganaOptions
            token={token}
            documentId={documentId}
            onTokensUpdated={onTokensUpdated}
          />
          <UnmergePhraseOption
            token={token}
            documentId={documentId}
            onTokensUpdated={onTokensUpdated}
          />
        </>
      ) : (
        <>
          {isMerged(token) && (
            <UnmergePhraseOption
              token={token}
              documentId={documentId}
              onTokensUpdated={onTokensUpdated}
            />
          )}
          {regroup && (
            <RegroupOption
              group={regroup}
              documentId={documentId}
              onTokensUpdated={onTokensUpdated}
            />
          )}
          {isOov && !token.gloss?.looked_up_as && (
            <>
              <div className="conflict-title">Not in dictionary</div>
              <div className="conflict-note">
                No automatic reading candidates.
              </div>
            </>
          )}
          {hasReadingOptions(token) && (
            <div className="conflict-title">
              {REVIEW_REASON_LABELS[token.review_reason ?? ''] ??
                'Needs review'}
            </div>
          )}
          {instances.length > 1 && (
            <ApplyToAllOption
              count={instances.length}
              surface={token.surface}
              checked={applyToAll}
              onChange={setApplyToAll}
            />
          )}
          {wordPieces.map((piece) => (
            <PieceWordPicker
              key={piece}
              piece={piece}
              targets={targets}
              documentId={documentId}
              onTokensUpdated={onTokensUpdated}
            />
          ))}
          <TokenDecisions
            targets={targets}
            offerCorrection={false}
            documentId={documentId}
            onTokensUpdated={onTokensUpdated}
          />
        </>
      )}
    </div>
  )
}

// A token's dictionary form, part of speech, and gloss, as its popup and the
// selection panel show them, with `pieceControls` under each piece of a
// gloss shown as its parts.
function GlossDetails({
  token,
  pieceControls,
}: {
  token: Token
  pieceControls?: (piece: number) => ReactNode
}) {
  const gloss = token.gloss
  const posInfo = getPosInfo(token.part_of_speech[0])
  // A merged token shows its group's lookup form and reading, not its own
  // dictionary form, reading, and part of speech (期, き, 名詞).
  const merged = isMerged(token)

  // Glosses are never shown for English tokens (see hasPopup), but are for
  // genuine Japanese words Sudachi doesn't recognize (review_reason 'oov') —
  // for those, dictionary_form/pos are fabricated placeholders (see is_oov),
  // not real analysis, so they're hidden.
  return (
    <>
      {merged && gloss ? (
        <div className="dictionary-form-line">
          Combined: {gloss.lookup_form}（{gloss.reading}）
        </div>
      ) : gloss?.looked_up_as ? (
        // Sudachi's analysis of the katakana itself found no word to show.
        <div className="dictionary-form-line">
          Looked up as: {gloss.looked_up_as}
        </div>
      ) : (
        !token.is_oov && (
          <>
            <div className="dictionary-form-line">
              Dictionary form: {token.dictionary_form}（
              {token.dictionary_form_reading}）
            </div>
            {token.dictionary_form_note && (
              <div className="dictionary-form-note">
                {token.dictionary_form_note}
              </div>
            )}
            {posInfo && (
              <div className="token-pos-line">
                <PosTermRuby segments={posInfo.segments} />
              </div>
            )}
            {canTakeSuru(token) && (
              <div className="dictionary-form-note">
                Can combine with する to form a verb: {token.dictionary_form}
                する
              </div>
            )}
          </>
        )
      )}
      {gloss && gloss.source === 'composite' ? (
        <div className="gloss-composite">
          <div className="gloss-composite-note">
            {gloss.looked_up_as
              ? 'Written in katakana, which has no dictionary entry — looked up as hiragana.'
              : gloss.pieces.some((p) => p.note)
                ? 'A word and the grammar attached to it — shown here as its parts.'
                : 'No single dictionary entry for this whole word — shown here as its parts.'}
          </div>
          {gloss.pieces.map((piece, i) => (
            <div key={i} className="gloss-piece">
              <div className="gloss-popup-reading">
                {piece.surface}
                {piece.reading !== piece.surface && `「${piece.reading}」`}
              </div>
              {piece.note && (
                <div className="dictionary-form-note">{piece.note}</div>
              )}
              {/* A grammar word has its note instead of senses. */}
              {(piece.senses.length > 0 || !piece.note) && (
                <SenseList senses={piece.senses} />
              )}
              {piece.ambiguous_readings.length > 0 && (
                <div className="dictionary-form-note">
                  Sudachi also lists {piece.ambiguous_readings.join(', ')} as
                  readings for {piece.surface} — picking between them isn't
                  supported within a compound yet. Use "Correct the reading"
                  below for the whole word if this one is wrong.
                </div>
              )}
              {pieceControls?.(i)}
            </div>
          ))}
        </div>
      ) : (
        gloss && (
          <>
            {!merged && (
              <div className="gloss-popup-reading">{gloss.reading}</div>
            )}
            <SenseList senses={gloss.senses} />
          </>
        )
      )}
    </>
  )
}

// The popup is centered under its token by default (see .gloss-popup's
// left/transform in App.css), which can push it under the floating sidebar
// or JMDict column for a token near either edge of the lyrics — both sit
// outside .content, which clips anything that overflows its own box. Nudge
// it back inside .content's bounds instead, so it's never covered or
// clipped by either floating column.
const EDGE_MARGIN_PX = 8

function GlossPopup({
  token,
  instances,
  words,
  documentId,
  onTokensUpdated,
  onCardChanged,
  onMouseEnter,
  onMouseLeave,
}: {
  token: Token
  instances: Token[]
  // The words and grammar `token` is part of that the user can add to their
  // cards: its own, and for a token sung in katakana or in a group, those of
  // its gloss's pieces.
  words: DocumentWord[]
  documentId: number
  onTokensUpdated: TokensUpdated
  onCardChanged: (card: StudyCard) => void
  onMouseEnter?: () => void
  onMouseLeave?: () => void
}) {
  const popupRef = useRef<HTMLDivElement>(null)
  const ownWord = words.find((word) => word.piece === null)
  const pieceWords = new Map<number, DocumentWord>()
  for (const word of words) {
    if (word.piece !== null) pieceWords.set(word.piece, word)
  }
  // From the gloss rather than `words`, which lists only the pieces whose
  // shown word is studyable.
  const wordPieces =
    token.gloss?.looked_up_as != null
      ? token.gloss.pieces.flatMap((piece, i) => (piece.is_word ? [i] : []))
      : []

  // Sets the popup's own transform directly (not through React state), so
  // this never costs a second render: the shift lands within the same
  // pre-paint layout-effect pass that measures it, with nothing for the
  // browser to paint in between.
  useLayoutEffect(() => {
    function reposition() {
      const popup = popupRef.current
      const container = popup?.closest('.content')
      if (!popup || !container) return
      popup.style.transform = ''
      const popupRect = popup.getBoundingClientRect()
      const containerRect = container.getBoundingClientRect()
      let shift = 0
      if (popupRect.left < containerRect.left + EDGE_MARGIN_PX) {
        shift = containerRect.left + EDGE_MARGIN_PX - popupRect.left
      } else if (popupRect.right > containerRect.right - EDGE_MARGIN_PX) {
        shift = containerRect.right - EDGE_MARGIN_PX - popupRect.right
      }
      if (shift) popup.style.transform = `translateX(calc(-50% + ${shift}px))`
    }
    reposition()
    window.addEventListener('resize', reposition)
    // Content loaded on demand (a word's other spellings) can widen it.
    // Observers report before paint, and the transform doesn't change the
    // size observed, so this neither flickers nor loops.
    const observer = new ResizeObserver(reposition)
    if (popupRef.current) observer.observe(popupRef.current)
    return () => {
      window.removeEventListener('resize', reposition)
      observer.disconnect()
    }
  }, [])

  return (
    <div
      ref={popupRef}
      className="gloss-popup"
      onClick={(e) => e.stopPropagation()}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <GlossDetails
        token={token}
        pieceControls={(piece) => {
          const word = pieceWords.get(piece)
          return (
            word && (
              <StudyListControl
                word={word}
                documentId={documentId}
                onCardChanged={onCardChanged}
              />
            )
          )
        }}
      />
      {ownWord && (
        <StudyListControl
          word={ownWord}
          documentId={documentId}
          onCardChanged={onCardChanged}
        />
      )}
      {/* Always mounted: the reading search is offered for every non-OOV token. */}
      {!token.is_english && (
        <ConflictResolver
          token={token}
          instances={instances}
          wordPieces={wordPieces}
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
function selectionKind(
  tokens: Token[],
  keys: string[],
  indices: number[],
): SelectionKind | null {
  if (indices.every((i) => keys[i] === keys[indices[0]])) return 'group'
  for (let k = 1; k < indices.length; k++) {
    const between = tokens.slice(indices[k - 1] + 1, indices[k])
    if (
      !between.every(
        (t) => t.part_of_speech[0] === '空白' && !t.surface.includes('\n'),
      )
    )
      return null
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
  onTokensUpdated: TokensUpdated
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
  const targets = applyToAll
    ? [...selected, ...instances.filter((t) => !selected.includes(t))]
    : selected

  // Pinned to the top of the screen, and no taller than the page content
  // above the lyrics (see .selection-anchor). Clicks inside stop here, since
  // a click anywhere else ends the selection.
  return (
    <div
      className="selection-panel"
      ref={panelRef}
      onClick={(e) => e.stopPropagation()}
    >
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
              Click the outlined instances of this word to decide for them
              together, or shift-click neighboring words to mark a run. Click
              anywhere else to finish.
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
          <TokenDecisions
            targets={targets}
            offerCorrection
            documentId={documentId}
            onTokensUpdated={onTokensUpdated}
          />
        </>
      ) : (
        <div className="conflict-note">
          Joining tokens into one gloss isn't supported yet.
        </div>
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
  words,
  documentId,
  onTokensUpdated,
  onCardChanged,
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
  // The words its popup offers to add to the user's cards.
  words: DocumentWord[]
  documentId: number
  onTokensUpdated: TokensUpdated
  onCardChanged: (card: StudyCard) => void
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
          words={words}
          documentId={documentId}
          onTokensUpdated={onTokensUpdated}
          onCardChanged={onCardChanged}
          onMouseEnter={() => onHoverEnter(token.id)}
          onMouseLeave={() => onHoverLeave(token.id)}
        />
      )}
    </span>
  )
})

const TokenizedText = memo(function TokenizedText({
  tokens,
  wordsByToken,
  documentId,
  onTokensUpdated,
  onCardChanged,
  playingLine,
  lineTimings,
  onPlayLine,
}: {
  tokens: Token[]
  // The words each token is part of that the user can add to their cards,
  // by token id.
  wordsByToken: Map<number, DocumentWord[]>
  documentId: number
  onTokensUpdated: TokensUpdated
  onCardChanged: (card: StudyCard) => void
  playingLine: number | null
  // Each line's timing (null for an untimed line), when lines can be played
  // from; null hides the play buttons.
  lineTimings: (LineTiming | null)[] | null
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
    return {
      keys,
      instancesByKey,
      indexById: new Map(tokens.map((token, index) => [token.id, index])),
    }
  }, [tokens])

  const panelRef = useRef<HTMLDivElement>(null)
  const boxRef = useRef<HTMLParagraphElement>(null)

  // Scrolls the line being sung onto the screen when it moves off it, as
  // little as possible: its first highlighted token, where it starts even
  // when it wraps.
  useEffect(() => {
    boxRef.current
      ?.querySelector('.token.playing')
      ?.scrollIntoView({ block: 'nearest' })
  }, [playingLine])

  // Scrolls `element` out from under the selection panel, which is pinned to
  // the top of the screen, if it's there once the panel has rendered.
  function revealBelowPanel(element: HTMLElement) {
    requestAnimationFrame(() => {
      const coveredTo = panelRef.current?.getBoundingClientRect().bottom ?? 0
      const top = element.getBoundingClientRect().top
      if (top < coveredTo)
        element.closest('.content')?.scrollBy({ top: top - coveredTo - 8 })
    })
  }

  function toggleSelected(index: number, element: HTMLElement) {
    const adding = !selected.includes(index)
    const next = adding
      ? [...selected, index].sort((a, b) => a - b)
      : selected.filter((i) => i !== index)
    // A token that fits neither kind of selection starts a new one.
    setSelected(
      next.length === 0 || selectionKind(tokens, keys, next) ? next : [index],
    )
    if (adding) {
      setLastAdded(index)
      revealBelowPanel(element)
    }
  }

  const kind =
    selected.length > 0 ? selectionKind(tokens, keys, selected) : null
  const focus =
    lastAdded !== null && selected.includes(lastAdded)
      ? lastAdded
      : selected[selected.length - 1]
  // Pinning and hovering outline independently, both at once: pinning a
  // token's gloss open shouldn't lose its own mirrors/token group just
  // because the mouse moves on to preview a different word (hover alone
  // never opens a second popup though — see isActive below, which keeps
  // pinnedId's own priority for that).
  const pinnedAt = indexById.get(pinnedId ?? -1)
  const hoveredAt = indexById.get(hoveredId ?? -1)
  const eligibleKeys = new Set<string>()
  if (selected.length > 0) {
    if (kind === 'group') eligibleKeys.add(keys[selected[0]])
  } else {
    if (pinnedAt !== undefined) eligibleKeys.add(keys[pinnedAt])
    if (hoveredAt !== undefined) eligibleKeys.add(keys[hoveredAt])
  }

  // Whether the token at `index` is outlined as eligible — not the pinned or
  // hovered token itself, which is already highlighted.
  function isEligible(index: number): boolean {
    return (
      hasPopup(tokens[index]) &&
      !selected.includes(index) &&
      eligibleKeys.has(keys[index]) &&
      (selected.length > 0 || (index !== pinnedAt && index !== hoveredAt))
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

  // The token-group spans outlined right now: the pinned token's and the
  // hovered token's, both at once (each may be a span of one) — while
  // nothing's selected, a selection's own tokens outline via .selected
  // instead. Independent of playback — the line being sung gets its own
  // .playing highlight (see below), not every phrase within it outlined at
  // once.
  const activeSpanKeys = useMemo(() => {
    const active = new Set<string>()
    if (selected.length === 0) {
      if (pinnedAt !== undefined)
        active.add(phraseSpanKey(tokens[pinnedAt], pinnedAt))
      if (hoveredAt !== undefined)
        active.add(phraseSpanKey(tokens[hoveredAt], hoveredAt))
    }
    return active
  }, [tokens, selected.length, pinnedAt, hoveredAt])

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
  const handleClickRef = useLatest(handleClick)
  const onTokenClick = useCallback(
    (index: number, event: React.MouseEvent<HTMLElement>) =>
      handleClickRef.current(index, event),
    [handleClickRef],
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
      <p
        ref={boxRef}
        className={lineTimings ? 'lyrics-box has-line-play' : 'lyrics-box'}
      >
        {tokens.map((token, index) => {
          // Lines past the last timing (blank ones at the end) have none.
          const lineStart = firstWithText.has(index)
            ? lineTimings?.[lineOf[index]]?.start
            : undefined
          const interactive = hasPopup(token)
          const isPinned = pinnedId === token.id
          const isActive =
            isPinned || (pinnedId === null && hoveredId === token.id)
          // While selecting, the selection panel shows the gloss instead.
          const showPopup = isActive && interactive && selected.length === 0

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
            interactive && hasMissingGloss(token) && !token.gloss_ignored
          const needsReadingReview =
            (hasReadingOptions(token) && token.needs_review) ||
            hasAmbiguousCompositePiece(token)

          // An accepted phrase is underlined as one run (see .phrase-merged).
          // Predicate groups are too common to underline, so they're only
          // highlighted while one of their tokens is looked at.
          const inPhrase = isInAcceptedPhrase(token)
          const mergedWithPrev =
            inPhrase &&
            index > 0 &&
            tokens[index - 1].phrase_start_position ===
              token.phrase_start_position
          const mergedWithNext =
            inPhrase &&
            index < tokens.length - 1 &&
            tokens[index + 1].phrase_start_position ===
              token.phrase_start_position

          const classNames = ['token']
          if (needsReadingReview) classNames.push('needs-review')
          if (needsCorrection) classNames.push('needs-correction')
          if (interactive) classNames.push('has-gloss')
          if (isPinned) classNames.push('pinned')
          if (lineOf[index] === playingLine) classNames.push('playing')
          if (selected.includes(index)) classNames.push('selected')
          if (isEligible(index)) classNames.push('eligible')
          if (inPhrase) classNames.push('phrase-merged')
          if (mergedWithPrev) classNames.push('phrase-merged-prev')
          if (mergedWithNext) classNames.push('phrase-merged-next')
          if (!inPhrase && phraseSuggestion(token))
            classNames.push('has-phrase-suggestion')
          // One outline around the whole token group, not one per member: its
          // left/right caps only go on the span's first/last token (a
          // standalone token is both). See .phrase-outline in App.css.
          const spanKey = phraseSpanKey(token, index)
          if (activeSpanKeys.has(spanKey)) {
            classNames.push('phrase-outline')
            if (
              index === 0 ||
              phraseSpanKey(tokens[index - 1], index - 1) !== spanKey
            )
              classNames.push('phrase-outline-start')
            if (
              index === tokens.length - 1 ||
              phraseSpanKey(tokens[index + 1], index + 1) !== spanKey
            )
              classNames.push('phrase-outline-end')
          }

          return (
            <Fragment key={token.id}>
              {lineStart !== undefined && (
                <LinePlayButton start={lineStart} onPlayLine={onPlayLine} />
              )}
              <TokenSpan
                token={token}
                index={index}
                className={classNames.join(' ')}
                showPopup={showPopup}
                instances={instancesByKey.get(keys[index]) ?? NO_TOKENS}
                // Only the token showing its popup needs them, so the rest
                // keep their memo when the words change.
                words={
                  showPopup
                    ? (wordsByToken.get(token.id) ?? NO_WORDS)
                    : NO_WORDS
                }
                documentId={documentId}
                onTokensUpdated={onTokensUpdated}
                onCardChanged={onCardChanged}
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

function LrclibSource({
  doc,
  onDocumentUpdated,
  locked,
}: {
  doc: Document
  onDocumentUpdated: (doc: Document) => void
  // Hides linking and unlinking, while timings are being edited that either
  // could change the lyrics under.
  locked: boolean
}) {
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
        {!editing && !locked && (
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
            <button
              type="button"
              disabled={saving}
              onClick={() => setEditing(false)}
            >
              Cancel
            </button>
          </div>
          <p className="lyrics-editor-note">
            {replaceText ? LRCLIB_LINK_NOTE : LRCLIB_KEEP_NOTE}
          </p>
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
          {doc.lrclib_sync_error && (
            <p className="form-error">{doc.lrclib_sync_error}</p>
          )}
        </>
      )}
      {error && <p className="form-error">{error}</p>}
    </>
  )
}

const ARROW_KEYS = new Set(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'])

const TOAST_MS = 2500

// A change to a line's timing that's confirmed first.
type TimingAction =
  | { kind: 'delete'; line: number }
  | { kind: 'overwrite'; line: number; start: number }

// The lyrics as one row per line while their timings are edited, `starts`
// holding each line's start (null once its timing is deleted). The picked
// line follows playback; ↑/↓ or a click pick another and play from it; ←/→
// move the picked line's start by `nudgeMs` and play from there; / starts
// the line after the one being sung at the current playback time (the first
// line, before any is) and scrolls down a line. Memoized, so page updates
// that don't touch it (a toast, say) don't re-render every row.
const TimingEditor = memo(function TimingEditor({
  lines,
  starts,
  onStartChange,
  playingLine,
  onPlayLine,
  getTime,
  nudgeMs,
  onToast,
}: {
  lines: LyricsLine[]
  starts: (number | null)[]
  // Sets `line`'s start, null to leave it untimed.
  onStartChange: (line: number, start: number | null) => void
  playingLine: number | null
  onPlayLine: (start: number) => void
  // The current playback time, or null until the player is ready.
  getTime: () => number | null
  nudgeMs: number
  // Shows why a key did nothing.
  onToast: (message: string) => void
}) {
  const [selected, setSelected] = useState(() => playingLine ?? 0)
  // A change waiting on its confirmation.
  const [pending, setPending] = useState<TimingAction | null>(null)
  // The open confirmation's "don't ask again".
  const [dontAskAgain, setDontAskAgain] = useState(false)
  // Set by "don't ask again": that kind of change skips its confirmation
  // until editing ends, which unmounts this.
  const [skipConfirm, setSkipConfirm] = useState({
    delete: false,
    overwrite: false,
  })
  const selectedRowRef = useRef<HTMLDivElement>(null)
  // The rows' container: row i is its child i.
  const rowsRef = useRef<HTMLDivElement>(null)

  // Each line's text, built once: the rows re-render as playback moves, but
  // their furigana never changes.
  const lineTexts = useMemo(
    () =>
      lines.map(({ pieces }) => (
        <div className="timing-text">
          {pieces.map(({ token, text }) => (
            <span key={token.id}>
              {text ??
                renderFuriganaSpans(
                  token.furigana_override ?? token.furigana_spans,
                )}
            </span>
          ))}
        </div>
      )),
    [lines],
  )

  // The picked line follows the one being sung. Picking a line plays from
  // it, so the two only part when an untimed line is picked.
  useEffect(() => {
    if (playingLine !== null) setSelected(playingLine)
  }, [playingLine])

  // Scrolls the picked line onto the screen when it moves off it, as little
  // as possible.
  useEffect(() => {
    selectedRowRef.current?.scrollIntoView({ block: 'nearest' })
  }, [selected])

  // Picks `line` and plays from its start, if it has one.
  function pick(line: number) {
    setSelected(line)
    const start = starts[line] ?? null
    if (start !== null) onPlayLine(start)
  }

  // Sets `line`'s start and picks it.
  function setStart(line: number, start: number) {
    onStartChange(line, start)
    setSelected(line)
  }

  // Sets `line`'s start from /, and scrolls the page down by the line and
  // the space after it, so the next line to time sits where this one was
  // and timing along needs no scrolling by hand.
  function stamp(line: number, start: number) {
    setStart(line, start)
    const rows = rowsRef.current?.children
    const row = rows?.[line]
    if (!rows || !row) return
    const next = rows[line + 1]
    const { top, height } = row.getBoundingClientRect()
    row
      .closest('.content')
      ?.scrollBy(0, next ? next.getBoundingClientRect().top - top : height)
    // Timing that began with the next line off screen brings it on.
    next?.scrollIntoView({ block: 'nearest' })
  }

  function apply(action: TimingAction) {
    if (action.kind === 'delete') onStartChange(action.line, null)
    // Only / overwrites a start.
    else stamp(action.line, action.start)
  }

  // Applies `action`, asking first unless "don't ask again" was checked for
  // its kind.
  function confirmThen(action: TimingAction) {
    if (skipConfirm[action.kind]) return apply(action)
    setDontAskAgain(false)
    setPending(action)
  }

  function nudge(direction: number) {
    const start = starts[selected] ?? null
    if (start === null) return onToast('This line has no timing to nudge.')
    const moved = nudgedStart(start, direction * nudgeMs)
    const overlap = overlapFor(starts, selected, moved)
    if (overlap) return onToast(overlap)
    setStart(selected, moved)
    onPlayLine(moved)
  }

  // Starts the line after the one being sung at the current playback time
  // then, or the first line before any is, asking first if that replaces a
  // time it already has.
  function timeNextLine() {
    const time = getTime()
    if (time === null) return onToast("The video isn't ready yet.")
    const start = roundedToMs(time)
    const line = lineToStamp(starts, start)
    if (line >= lines.length) return onToast('There are no more lines to time.')
    const overlap = overlapFor(starts, line, start)
    if (overlap) return onToast(overlap)
    if ((starts[line] ?? null) === null) return stamp(line, start)
    confirmThen({ kind: 'overwrite', line, start })
  }

  function handleKeyDown(event: KeyboardEvent) {
    // / is typed with Shift on some layouts, so only the arrows rule it out.
    if (event.altKey || event.ctrlKey || event.metaKey) return
    if (event.key !== '/' && (!ARROW_KEYS.has(event.key) || event.shiftKey))
      return
    const active = document.activeElement
    // A slider doesn't count as typing here, so the keys still work once
    // one's been dragged; an open dialog's controls do. (A closed one's
    // button keeps focus for a moment after it closes.)
    if (active?.closest('dialog[open]')) return
    if (
      isTypingTarget(active) &&
      !(active instanceof HTMLInputElement && active.type === 'range')
    )
      return
    event.preventDefault()
    if (event.key === '/') {
      // Held down, it would time line after line at almost the same moment.
      if (!event.repeat) timeNextLine()
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      nudge(event.key === 'ArrowLeft' ? -1 : 1)
    } else {
      const line = selected + (event.key === 'ArrowUp' ? -1 : 1)
      if (line >= 0 && line < lines.length) pick(line)
    }
  }

  // Kept current by an effect, so the listener can be added once and still
  // see the latest state.
  const handleKeyDownRef = useLatest(handleKeyDown)
  useEffect(() => {
    const listener = (event: KeyboardEvent) => handleKeyDownRef.current(event)
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  }, [handleKeyDownRef])

  return (
    <>
      <p className="lyrics-editor-note">
        The picked line follows playback. ↑/↓ or a click pick another and play
        from it, ←/→ nudge the picked line's start and play from there, and /
        starts the next line at the current playback time (the first line, if
        none has started yet) and moves the page down a line. Outlined lines
        have no time yet, and need one before saving. A blank line between
        stanzas can be timed too, to end the line before it there (for an
        instrumental break), but needn't be.
      </p>
      <div ref={rowsRef} className="lyrics-box">
        {lines.map(({ hasText }, line) => {
          const start = starts[line] ?? null
          const classNames = ['timing-row']
          if (!hasText) classNames.push('blank')
          if (line === selected) classNames.push('selected')
          if (line === playingLine) classNames.push('playing')
          if (start === null && hasText) classNames.push('untimed')
          return (
            <div
              key={line}
              ref={line === selected ? selectedRowRef : undefined}
              className={classNames.join(' ')}
              onClick={() => pick(line)}
            >
              <div className="timing-gutter">
                {start !== null && (
                  <button
                    type="button"
                    className="timing-delete"
                    aria-label="Delete this line's timing"
                    title="Delete this line's timing"
                    // Leaves focus where it was, so Space keeps playing and
                    // pausing rather than pressing this again.
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={(e) => {
                      e.stopPropagation()
                      confirmThen({ kind: 'delete', line })
                    }}
                  >
                    <svg viewBox="0 0 10 10" aria-hidden="true">
                      <path
                        d="M2 2 8 8M8 2 2 8"
                        stroke="currentColor"
                        strokeWidth="1.5"
                      />
                    </svg>
                  </button>
                )}
                <span>
                  {start === null ? 'untimed' : formatTimestamp(start)}
                </span>
              </div>
              {lineTexts[line]}
            </div>
          )
        })}
      </div>
      <ConfirmDialog
        open={pending !== null}
        message={
          pending?.kind === 'overwrite'
            ? `${pending.line === 0 ? 'The first line' : 'The next line'} already starts at ` +
              `${formatTimestamp(starts[pending.line] ?? 0)}. Overwrite it with ${formatTimestamp(pending.start)}?`
            : "Delete this line's timing?"
        }
        confirmLabel={pending?.kind === 'overwrite' ? 'Overwrite' : 'Delete'}
        onConfirm={() => {
          if (!pending) return
          if (dontAskAgain)
            setSkipConfirm({ ...skipConfirm, [pending.kind]: true })
          apply(pending)
          setPending(null)
        }}
        onCancel={() => setPending(null)}
      >
        <label className="checkbox-option">
          <input
            type="checkbox"
            checked={dontAskAgain}
            onChange={(e) => setDontAskAgain(e.target.checked)}
          />
          {pending?.kind === 'overwrite'
            ? 'Overwrite without asking'
            : "Don't ask again"}{' '}
          until I stop editing timings
        </label>
      </ConfirmDialog>
    </>
  )
})

function RangeControl({
  id,
  label,
  unit,
  value,
  onChange,
  min,
  max,
  step,
  hint,
}: {
  id: string
  label: string
  unit: string
  value: number
  onChange: (value: number) => void
  min: number
  max: number
  step?: number
  // Shown after the value, e.g. the keys that use the setting.
  hint?: React.ReactNode
}) {
  return (
    <div className="control">
      <label htmlFor={id}>
        {label} {value}
        {unit}
        {hint && <> {hint}</>}
      </label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
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
  // Counts the player's seeks. The playing-line effect depends on it, so a
  // seek re-runs it at once rather than waiting for the next poll, and after
  // any other state the same keypress changed (a nudge's new timings).
  const [seeks, setSeeks] = useState(0)
  const handleSeek = useCallback(() => setSeeks((count) => count + 1), [])

  // Viewing settings: the same for every document, and kept across reloads.
  const [fontSize, setFontSize] = usePersistentState('fontSize', 18)
  const [furiganaSize, setFuriganaSize] = usePersistentState('furiganaSize', 11)
  const [seekSeconds, setSeekSeconds] = usePersistentState('seekSeconds', 3)
  // Defaults to the theme's accent, which is hex, as a color input needs.
  const [highlightColor, setHighlightColor] = usePersistentState(
    'highlightColor',
    () =>
      getComputedStyle(document.documentElement)
        .getPropertyValue('--accent')
        .trim(),
  )
  const [highlightOpacity, setHighlightOpacity] = usePersistentState(
    'highlightOpacity',
    25,
  )
  const [nudgeMs, setNudgeMs] = usePersistentState('nudgeMs', 50)

  const [editingLyrics, setEditingLyrics] = useState(false)
  const [lyricsDraft, setLyricsDraft] = useState('')
  const {
    saving: savingLyrics,
    error: lyricsSaveError,
    setError: setLyricsSaveError,
    save: saveLyrics,
  } = useSave()
  // Counts lyrics saves, each of which deletes the tokens even when the text
  // comes back unchanged, so they're loaded again.
  const [lyricsSaves, setLyricsSaves] = useState(0)

  // While timings are being edited, each line's start as edited, null once
  // its timing is deleted; null the rest of the time.
  const [timingDraft, setTimingDraft] = useState<(number | null)[] | null>(null)
  const [confirmingDiscard, setConfirmingDiscard] = useState(false)
  const {
    saving: savingTimings,
    error: timingsSaveError,
    setError: setTimingsSaveError,
    save: saveTimings,
  } = useSave()

  // A short notice at the bottom of the screen: an object, so showing the
  // same message again restarts its timer.
  const [toast, setToast] = useState<{ message: string } | null>(null)
  const showToast = useCallback((message: string) => setToast({ message }), [])
  useEffect(() => {
    if (!toast) return
    const timeout = window.setTimeout(() => setToast(null), TOAST_MS)
    return () => window.clearTimeout(timeout)
  }, [toast])

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
    function handleKeyDown(event: KeyboardEvent) {
      const active = document.activeElement

      if (event.code === 'Space') {
        const isNativeSpaceTarget =
          active instanceof HTMLElement &&
          SPACE_HANDLED_NATIVELY.has(active.tagName)
        if (isNativeSpaceTarget || isTypingTarget(active)) return
        event.preventDefault()
        youtubePlayerRef.current?.togglePlay()
        return
      }

      if (event.code === 'Comma' || event.code === 'Period') {
        if (isTypingTarget(active)) return
        event.preventDefault()
        youtubePlayerRef.current?.seekBy(
          event.code === 'Comma' ? -seekSeconds : seekSeconds,
        )
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [seekSeconds])

  useEffect(() => {
    let cancelled = false
    setDoc(null)
    setLoading(true)
    // Another document's timings, if they were being edited when it was
    // left: this page stays mounted from one document to the next.
    setTimingDraft(null)
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

  // The tokens follow the document's text, not the whole document, so
  // saving anything else (its timings, say) doesn't reload them.
  const docId = doc?.id
  const docTitle = doc?.title
  const docText = doc?.text

  useEffect(() => {
    if (docId === undefined || docTitle === undefined) return

    let cancelled = false
    setTokens(null)
    setTokensLoading(true)
    setTokensError(null)

    // Runs the same furigana + gloss pipeline (and tab registration) the
    // documents list kicks off on click, so arriving here directly (a
    // pasted URL, a refresh, a sidebar tab) still processes and registers
    // a tab the same way.
    ensureProcessed(docId, docTitle)
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
  }, [docId, docTitle, docText, lyricsSaves, ensureProcessed])

  // Counts the edits that can change which word a token is.
  const [wordEdits, setWordEdits] = useState(0)
  const handleTokensUpdated = useCallback<TokensUpdated>(
    (updated, changesWords = true) => {
      const byId = new Map(updated.map((t) => [t.id, t]))
      setTokens((prev) => prev?.map((t) => byId.get(t.id) ?? t) ?? prev)
      if (changesWords) setWordEdits((n) => n + 1)
    },
    [],
  )

  // The words the user can add to their cards, loaded again whenever the
  // tokens are (re)processed or an edit can make a token another word (a new
  // reading, a word picked for katakana, a phrase accepted or split). The
  // last ones loaded stay meanwhile; if they can't be loaded, the popups
  // offer no study list.
  const [words, setWords] = useState<DocumentWord[] | null>(null)
  const hasTokens = tokens !== null
  useEffect(() => {
    if (!hasTokens) return
    let cancelled = false
    fetchDocumentWords(documentId)
      .then((result) => {
        if (!cancelled) setWords(result)
      })
      .catch(() => {
        if (!cancelled) setWords(null)
      })
    return () => {
      cancelled = true
    }
  }, [documentId, hasTokens, wordEdits])

  const wordsByToken = useMemo(() => {
    const byToken = new Map<number, DocumentWord[]>()
    for (const word of words ?? []) {
      for (const id of word.token_ids) {
        const list = byToken.get(id)
        if (list) list.push(word)
        else byToken.set(id, [word])
      }
    }
    return byToken
  }, [words])

  // Puts `card` on every word it's the card of.
  const handleCardChanged = useCallback((card: StudyCard) => {
    setWords(
      (prev) =>
        prev?.map((word) =>
          word.kind === card.kind &&
          word.lookup_form === card.lookup_form &&
          word.reading === card.reading &&
          word.idseq === card.idseq
            ? { ...word, card }
            : word,
        ) ?? prev,
    )
  }, [])

  const handlePlayLine = useCallback(
    (start: number) => youtubePlayerRef.current?.playFrom(start),
    [],
  )
  const getPlaybackTime = useCallback(
    () => youtubePlayerRef.current?.getCurrentTime() ?? null,
    [],
  )
  // Sets `line`'s start in the timings being edited, null to leave it
  // untimed.
  const handleStartChange = useCallback(
    (line: number, start: number | null) =>
      setTimingDraft(
        (draft) => draft && draft.map((s, i) => (i === line ? start : s)),
      ),
    [],
  )

  // The lyrics' lines, as the timing editor shows them.
  const lyricsLines = useMemo(() => (tokens ? linesOf(tokens) : null), [tokens])

  // The document's line timings: as edited here, or else LRCLIB's.
  const lineTimings = doc?.edited_lines ?? doc?.lrclib_lines ?? null
  const hasVideo = Boolean(doc?.youtube_video_id)
  // What's highlighted: the timings as edited so far, while editing them.
  const shownTimings = useMemo(() => {
    if (!timingDraft) return lineTimings
    // The last timed line lasts until the song ends: where the timings being
    // edited ended, or without any, where the video does. The video's length
    // is read whenever a time is set, which takes the video playing.
    let songEnd = 0
    for (const timing of lineTimings ?? []) if (timing) songEnd = timing.end
    return timingsFromStarts(
      timingDraft,
      songEnd || (youtubePlayerRef.current?.getDuration() ?? 0),
    )
  }, [timingDraft, lineTimings])

  useEffect(() => {
    if (!shownTimings || !hasVideo) return
    // The line last found, which the next search starts from. A seek or new
    // timings re-run this effect, which starts the search over.
    let found = -1
    const update = () => {
      const time = youtubePlayerRef.current?.getCurrentTime() ?? null
      if (time === null) return setPlayingLine(null)
      found = lastStartedBy(shownTimings, time, found)
      const line = shownTimings[found]
      // An index, so React skips the re-render while the line is unchanged.
      setPlayingLine(line && time < line.end ? found : null)
    }
    // Right away as well, so a seek or a nudge moves the highlight at once
    // rather than at the next poll.
    update()
    const interval = window.setInterval(update, PLAYBACK_POLL_MS)
    return () => {
      window.clearInterval(interval)
      // Whatever lines come next, this index isn't into them.
      setPlayingLine(null)
    }
  }, [shownTimings, hasVideo, seeks])

  useEffect(() => {
    if (!headerEl) return
    const observer = new ResizeObserver(() =>
      setHeaderHeight(headerEl.offsetHeight),
    )
    observer.observe(headerEl)
    return () => observer.disconnect()
  }, [headerEl])

  // Whether the timings being edited differ from those saved, which leaving
  // them would lose.
  const timingsChanged =
    timingDraft?.some(
      (start, i) => start !== (lineTimings?.[i]?.start ?? null),
    ) ?? false

  // Asks before leaving them for another page or document of the app...
  const leaveBlocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      timingsChanged && nextLocation.pathname !== currentLocation.pathname,
  )

  // ...and has the browser ask before leaving the app: closing the tab,
  // reloading, or going to another site.
  useEffect(() => {
    if (!timingsChanged) return
    function warn(event: BeforeUnloadEvent) {
      event.preventDefault()
      // What older browsers need to ask.
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [timingsChanged])

  if (loading) return <p>Loading…</p>
  if (error) return <p className="form-error">{error}</p>
  if (!doc) return null

  function handleSaveLyrics() {
    const trimmed = lyricsDraft.trim()
    if (!trimmed) return
    saveLyrics(
      () => updateDocumentText(documentId, trimmed),
      (updated) => {
        setDoc(updated)
        // The backend already deleted the old tokens/conflicts/gloss links
        // on save, so loading them again regenerates everything from
        // scratch, same as a never-before-processed document.
        setLyricsSaves((count) => count + 1)
        setEditingLyrics(false)
      },
    )
  }

  function handleDocumentLinked(updated: Document) {
    setDoc(updated)
    // Its lyrics are LRCLIB's now, so there's nothing left to edit.
    if (updated.lrclib_replaces_text) setEditingLyrics(false)
  }

  const editingTimings = timingDraft !== null
  // Timings need the lyrics to show them against, and a video to play them
  // in.
  const canEditTimings = hasVideo && tokens !== null

  function startEditingTimings() {
    if (!lyricsLines) return
    setTimingsSaveError(null)
    // From the document's timings, or without any, every line untimed.
    setTimingDraft(
      lineTimings
        ? lineTimings.map((timing) => timing?.start ?? null)
        : lyricsLines.map(() => null),
    )
  }

  function handleSaveTimings() {
    if (!doc || !timingDraft || !shownTimings || !lyricsLines) return
    // Only blank lines, between stanzas, may go untimed.
    const untimed = lyricsLines.filter(
      (line, i) => line.hasText && (timingDraft[i] ?? null) === null,
    ).length
    if (untimed > 0) {
      return showToast(
        untimed === 1
          ? 'A line still needs a time (outlined).'
          : `${untimed} lines still need times (outlined).`,
      )
    }
    saveTimings(
      () => saveLineTimings(doc.id, doc.text, shownTimings),
      (updated) => {
        setDoc(updated)
        setTimingDraft(null)
      },
    )
  }

  function handleCancelTimings() {
    if (timingsChanged) setConfirmingDiscard(true)
    else setTimingDraft(null)
  }

  return (
    <div className="new-document-form">
      <div className="document-header" ref={setHeaderEl}>
        <h1>{doc.title}</h1>
        <Link to={`/documents/${doc.id}/study`}>Study this song</Link>
        {' · '}
        <Link to={`/documents/${doc.id}/run-through`}>Run through it</Link>

        <label htmlFor="title">Title</label>
        <p id="title" className="readonly-text">
          {doc.title}
        </p>

        <LrclibSource
          doc={doc}
          onDocumentUpdated={handleDocumentLinked}
          locked={editingTimings}
        />

        <div className="lyrics-header">
          <label htmlFor="lyrics">Lyrics</label>
          {!editingLyrics && !doc.lrclib_replaces_text && !editingTimings && (
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
            {!editingTimings && (
              <>
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
              </>
            )}
            <RangeControl
              id="seek-seconds"
              label="Seek step"
              unit="s"
              value={seekSeconds}
              onChange={setSeekSeconds}
              min={1}
              max={30}
              hint={
                <>
                  (<kbd>,</kbd> / <kbd>.</kbd>)
                </>
              }
            />
            {editingTimings ? (
              <>
                <RangeControl
                  id="nudge-ms"
                  // Not "Nudge step": with its keys, that won't fit the label
                  // column.
                  label="Nudge"
                  unit="ms"
                  value={nudgeMs}
                  onChange={setNudgeMs}
                  min={10}
                  max={500}
                  step={10}
                  hint={
                    <>
                      (<kbd>←</kbd>
                      <kbd>→</kbd>)
                    </>
                  }
                />
                <div className="control-actions">
                  <button
                    type="button"
                    disabled={savingTimings}
                    onClick={handleSaveTimings}
                  >
                    {savingTimings ? 'Saving…' : 'Save timings'}
                  </button>
                  <button
                    type="button"
                    disabled={savingTimings}
                    onClick={handleCancelTimings}
                  >
                    Cancel
                  </button>
                </div>
              </>
            ) : (
              <>
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
                <div className="control-actions">
                  <button
                    type="button"
                    disabled={!canEditTimings}
                    title={canEditTimings ? undefined : 'Needs a video'}
                    onClick={startEditingTimings}
                  >
                    Edit timings
                  </button>
                </div>
              </>
            )}
          </div>
        )}
        {timingsSaveError && <p className="form-error">{timingsSaveError}</p>}
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
            <button
              type="button"
              disabled={savingLyrics || !lyricsDraft.trim()}
              onClick={handleSaveLyrics}
            >
              {savingLyrics ? 'Saving…' : 'Save'}
            </button>
            <button
              type="button"
              disabled={savingLyrics}
              onClick={() => setEditingLyrics(false)}
            >
              Cancel
            </button>
          </div>
          <p className="lyrics-editor-note">
            Saving replaces the lyrics and re-processes furigana and glosses
            from scratch — any reading corrections or reviewed alternatives for
            this document will be lost.
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
          {tokens &&
            (timingDraft && lyricsLines ? (
              <TimingEditor
                lines={lyricsLines}
                starts={timingDraft}
                onStartChange={handleStartChange}
                playingLine={playingLine}
                onPlayLine={handlePlayLine}
                getTime={getPlaybackTime}
                nudgeMs={nudgeMs}
                onToast={showToast}
              />
            ) : (
              <TokenizedText
                tokens={tokens}
                wordsByToken={wordsByToken}
                documentId={documentId}
                onTokensUpdated={handleTokensUpdated}
                onCardChanged={handleCardChanged}
                playingLine={playingLine}
                // Without a video there's nothing to play them from.
                lineTimings={hasVideo ? lineTimings : null}
                onPlayLine={handlePlayLine}
              />
            ))}
          {tokensError && (
            <>
              <p className="form-error">
                {tokensError} Showing plain lyrics instead.
              </p>
              <p className="lyrics-box">{doc.text}</p>
            </>
          )}
        </div>
      )}

      <label htmlFor="youtube-video-id">YouTube video ID</label>
      {doc.youtube_video_id ? (
        <YouTubePlayer
          ref={youtubePlayerRef}
          videoId={doc.youtube_video_id}
          onSeek={handleSeek}
        />
      ) : (
        <input type="text" value="—" readOnly />
      )}

      <ConfirmDialog
        open={confirmingDiscard}
        message="Discard your timing changes?"
        confirmLabel="Discard"
        onConfirm={() => {
          setConfirmingDiscard(false)
          setTimingDraft(null)
        }}
        onCancel={() => setConfirmingDiscard(false)}
      />
      <ConfirmDialog
        open={leaveBlocker.state === 'blocked'}
        message="Leave without saving your timing changes?"
        confirmLabel="Leave"
        onConfirm={() => leaveBlocker.proceed?.()}
        onCancel={() => leaveBlocker.reset?.()}
      />
      {toast && (
        <div className="toast" role="status">
          {toast.message}
        </div>
      )}
    </div>
  )
}
