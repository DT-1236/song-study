import type { CardKanji, KanjiEntry } from './api'

// How many of the user's other words with the kanji are listed under it.
const MAX_DECK_WORDS = 5

function KanjiCard({
  kanji,
  entry,
  cardId,
}: {
  kanji: CardKanji
  entry: KanjiEntry
  cardId: number
}) {
  const deckWords = entry.deck_words
    .filter((word) => word.card_id !== cardId)
    .slice(0, MAX_DECK_WORDS)
  const meta = [
    entry.grade !== null && `grade ${entry.grade}`,
    entry.frequency !== null && `freq ${entry.frequency}`,
  ]
    .filter(Boolean)
    .join(' · ')
  const readings = [...entry.on_readings, ...kanji.kun_readings]

  return (
    <section className="kanji-card">
      <div className="kanji-card-head">
        <span className="kanji-character">{kanji.character}</span>
        <span className="kanji-readings">
          {readings.join('・')}
          {kanji.more_kun > 0 && (
            <span className="kanji-more"> +{kanji.more_kun} more</span>
          )}
        </span>
      </div>
      {meta && <div className="kanji-meta">{meta}</div>}
      <div className="kanji-meanings">{entry.meanings.join(', ')}</div>
      {entry.radical && (
        <div className="kanji-radical">
          radical {entry.radical.character} {entry.radical.meaning}
          {entry.components.length > 0 && (
            <span className="kanji-components">
              {' '}
              ・ also {entry.components.join(' ')}
            </span>
          )}
        </div>
      )}
      {deckWords.length > 0 && (
        <div className="kanji-deck">
          also in your deck:{' '}
          {deckWords.map((word, i) => (
            <span key={word.card_id}>
              {i > 0 && ' · '}
              {word.lookup_form}{' '}
              <span className={`kanji-status ${word.status}`}>
                ({word.status})
              </span>
            </span>
          ))}
        </div>
      )}
    </section>
  )
}

// What the reveal shows of each kanji of the card's word or group, in order.
export function KanjiSidebar({
  kanji,
  entries,
  cardId,
}: {
  kanji: CardKanji[]
  entries: Record<string, KanjiEntry>
  cardId: number
}) {
  // A kanji KANJIDIC2 has no entry for is left out of both.
  const shown = kanji.filter((k) => entries[k.character])
  if (shown.length === 0) return null

  return (
    <aside className="kanji-sidebar" aria-label="Kanji in this word">
      {shown.map((k) => (
        <KanjiCard
          key={k.character}
          kanji={k}
          entry={entries[k.character]}
          cardId={cardId}
        />
      ))}
    </aside>
  )
}
