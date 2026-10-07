import { useEffect } from 'react'
import {
  correctCardReading,
  correctCardWord,
  fetchAlternateReadings,
  fetchPieceWords,
} from './api'
import type { CardCorrection, CardLine, QueuedCard } from './api'
import { wordLabel } from './cardText'
import { useApiResource } from './useApiResource'
import { useSave } from './useSave'

// Another word the token of a card's line could be.
type Choice = {
  // The word, as the card's reveal names one: 辛い（からい）.
  label: string
  // What it means, for words told apart by meaning rather than reading.
  detail: string | null
  apply: () => Promise<CardCorrection>
}

// The other words `line`'s token could be than `card`'s: the other readings
// of a word written in kanji, or for a word sung in katakana, the other
// words with its reading.
async function loadChoices(
  card: QueuedCard,
  line: CardLine,
): Promise<Choice[]> {
  const where = { documentId: line.document_id, tokenId: line.token_id }
  if (line.correction === 'word' && line.piece !== null) {
    const piece = line.piece
    const options = await fetchPieceWords(
      line.document_id,
      line.token_id,
      piece,
    )
    return options
      .filter((option) => option.spelling !== card.lookup_form)
      .map((option) => ({
        label: wordLabel(option.spelling, card.reading),
        detail: option.gloss.slice(0, 3).join(', ') || null,
        apply: () =>
          correctCardWord(card.id, {
            ...where,
            piece,
            idseq: option.idseq,
          }),
      }))
  }
  const options = await fetchAlternateReadings(line.document_id, line.token_id)
  return options
    .filter(
      (option) => (option.citation_reading ?? option.reading) !== card.reading,
    )
    .map((option) => ({
      label: wordLabel(
        card.lookup_form,
        option.citation_reading ?? option.reading,
      ),
      detail: null,
      apply: () =>
        correctCardReading(card.id, {
          ...where,
          reading: option.reading,
          furiganaSpans: option.furigana_spans,
        }),
    }))
}

// What a correction did, said as it happens, since otherwise the card the
// user was studying would seem to vanish (docs/flashcards.md, §4).
function correctionMessage(
  from: string,
  to: string,
  result: CardCorrection,
): string {
  if (!result.card)
    return `Changed to ${to}, which has no dictionary entry to study.`
  const kept = result.kept ? ` Your ${from} card keeps its history.` : ''
  return `Changed to ${to}, which is a card of its own.${kept}`
}

// Picks the word a card's line really has, for a card asking about the wrong
// one. `1`–`9` pick and Esc cancels; `onCorrected` gets what it did.
export function CardCorrectionPanel({
  card,
  line,
  onCorrected,
  onCancel,
}: {
  card: QueuedCard
  // The card's line, which says how its word can be corrected.
  line: CardLine
  onCorrected: (message: string) => void
  onCancel: () => void
}) {
  const {
    data: choices,
    loading,
    error: loadError,
  } = useApiResource(
    () => loadChoices(card, line),
    [card, line],
    'Failed to load the other words.',
  )
  const { saving: applying, error, save } = useSave('Failed to correct it.')

  function pick(choice: Choice) {
    if (applying) return
    save(choice.apply, (result) =>
      onCorrected(
        correctionMessage(
          wordLabel(card.lookup_form, card.reading),
          choice.label,
          result,
        ),
      ),
    )
  }

  useEffect(() => {
    function handleKey(event: KeyboardEvent) {
      if (event.ctrlKey || event.metaKey || event.altKey) return
      if (event.key === 'Escape') {
        onCancel()
      } else if (choices && /^[1-9]$/.test(event.key)) {
        const choice = choices[Number(event.key) - 1]
        if (!choice) return
        pick(choice)
      } else {
        return
      }
      event.preventDefault()
    }

    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  })

  const subject = line.correction === 'word' ? 'word' : 'reading'

  return (
    <div
      className="study-ladder"
      role="group"
      aria-label={`Correct the ${subject}`}
    >
      Which {subject} is it?
      {loading && <span>Loading…</span>}
      {choices?.map((choice, i) => (
        <button
          key={choice.label}
          type="button"
          disabled={applying}
          onClick={() => pick(choice)}
        >
          <kbd>{i + 1}</kbd> {choice.label}
          {choice.detail && ` — ${choice.detail}`}
        </button>
      ))}
      {choices?.length === 0 && <span>No other {subject} was found.</span>}
      <button type="button" onClick={onCancel}>
        Cancel
      </button>
      {(loadError ?? error) && (
        <span className="form-error">{loadError ?? error}</span>
      )}
    </div>
  )
}
