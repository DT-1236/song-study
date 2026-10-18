import type { CardLine, QueuedCard } from './api'
import { codePointSlice, optionText, wordLabel } from './cardText'
import { renderSegments, type FuriganaSegment } from './furigana'
import { SenseList } from './SenseList'

// The line's text from `begin` to `end`, with its furigana over the kanji
// runs inside the range.
function lineSlice(line: CardLine, begin: number, end?: number) {
  const stop = end ?? Array.from(line.text).length
  const segments: FuriganaSegment[] = []
  let at = begin
  // Each reading lies within one token, so none straddles the range's edges.
  for (const reading of line.furigana) {
    if (reading.begin < at || reading.end > stop) continue
    segments.push({
      text: codePointSlice(line.text, at, reading.begin),
      reading: null,
    })
    segments.push({
      text: codePointSlice(line.text, reading.begin, reading.end),
      reading: reading.reading,
    })
    at = reading.end
  }
  segments.push({ text: codePointSlice(line.text, at, stop), reading: null })
  return renderSegments(segments)
}

// The card's line, dimmed except its target until the reveal brightens it.
function LineText({ card, revealed }: { card: QueuedCard; revealed: boolean }) {
  const line = card.line
  if (!line) return null

  const [focusBegin, focusEnd] = line.focus
  const [groupBegin, groupEnd] = line.group
  // A grammar card asks about one element of its predicate group, so the
  // group is bracketed; a word card shows only the word.
  const bracketed = card.kind === 'grammar'
  // The group's parts either side of the focus; just the word's own
  // surroundings on a word card.
  const begin = bracketed ? groupBegin : focusBegin
  const end = bracketed ? groupEnd : focusEnd
  const dim = revealed ? '' : 'study-dim'

  return (
    <p className={`study-line ${revealed ? 'revealed' : ''}`}>
      <span className={dim}>
        {lineSlice(line, 0, begin)}
        {bracketed && '['}
        {lineSlice(line, begin, focusBegin)}
      </span>
      <mark className="study-focus">
        {lineSlice(line, focusBegin, focusEnd)}
      </mark>
      {line.written_as && (
        <span className="study-written-as">（{line.written_as}）</span>
      )}
      <span className={dim}>
        {lineSlice(line, focusEnd, end)}
        {bracketed && ']'}
        {lineSlice(line, end, undefined)}
      </span>
    </p>
  )
}

function question(card: QueuedCard): string {
  if (card.kind === 'grammar') return `What is ${card.lookup_form} doing here?`
  return 'What are some of the meanings of this word?'
}

// One card: the line with its question and options, and once `picked` is
// set, the answer's reveal.
export function StudyCardView({
  card,
  picked,
  onPick,
}: {
  card: QueuedCard
  // The option chosen; null before the card is answered.
  picked: number | null
  onPick: (index: number) => void
}) {
  const revealed = picked !== null
  const answer = card.answer
  const shownSenses = card.options[0]?.senses?.length ?? 0

  return (
    <div className="study-card">
      <div className="study-card-title">
        ♪ {card.line ? card.line.title : 'This word is in none of your songs'}
      </div>
      <LineText card={card} revealed={revealed} />
      <p className="study-question">{question(card)}</p>
      {card.kind === 'recognition' && card.senses.length > shownSenses && (
        <p className="study-showing">
          showing {shownSenses} of {card.senses.length} senses
        </p>
      )}
      <ol className="study-options">
        {card.options.map((option, i) => {
          const state = !revealed
            ? ''
            : i === answer
              ? 'correct'
              : i === picked
                ? 'wrong'
                : 'other'
          return (
            <li key={i}>
              <button
                type="button"
                className={`study-option ${state}`}
                disabled={revealed}
                onClick={() => onPick(i)}
              >
                <kbd>{i + 1}</kbd>
                <span>{optionText(option)}</span>
              </button>
            </li>
          )
        })}
      </ol>
      {revealed && (
        <div className="study-reveal">
          <p className={picked === answer ? 'study-right' : 'study-missed'}>
            {picked === answer ? 'Correct' : 'Not quite'}
          </p>
          {card.kind === 'recognition' ? (
            <>
              <div className="study-word">
                {wordLabel(card.lookup_form, card.reading)}
              </div>
              <SenseList senses={card.senses} />
            </>
          ) : (
            <p className="study-note">
              <strong>{card.lookup_form}</strong>
              {answer !== null && ` — ${optionText(card.options[answer])}`}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
