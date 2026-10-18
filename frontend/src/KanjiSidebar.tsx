import type { CardKanji, KanjiEntry } from './api'

// How hard a kanji is to learn, 0 (easiest) to 9: KANJIDIC2 grades 1-6 are
// the school years, 8 the rest of the jōyō kanji, 9-10 the name kanji.
function gradeTier(grade: number): number {
  return Math.min(Math.max(grade - 1, 0), 9)
}

// How rare a kanji is, 0 (most common) to 9, from its KANJIDIC2 newspaper
// frequency rank (1-2500, 1 being the most common): one tier per 250 ranks.
function frequencyTier(frequency: number): number {
  return Math.min(Math.floor((frequency - 1) / 250), 9)
}

function KanjiCard({
  kanji,
  entry,
  cardId,
  maxDeckWords,
}: {
  kanji: CardKanji
  entry: KanjiEntry
  cardId: number
  maxDeckWords: number
}) {
  const deckWords = entry.deck_words
    .filter((word) => word.card_id !== cardId)
    .slice(0, maxDeckWords)
  return (
    <section className="kanji-card">
      <div className="kanji-card-head">
        <span className="kanji-character">{kanji.character}</span>
        <span className="kanji-kun">
          {kanji.kun_readings.join('・')}
          {kanji.more_kun > 0 && (
            <span className="kanji-more"> +{kanji.more_kun} more</span>
          )}
        </span>
        <span className="kanji-on">{entry.on_readings.join('・')}</span>
      </div>
      {(entry.grade !== null || entry.frequency !== null) && (
        <div className="kanji-meta">
          {entry.grade !== null && (
            <span className={`kanji-tier-${gradeTier(entry.grade)}`}>
              grade {entry.grade}
            </span>
          )}
          {entry.grade !== null && entry.frequency !== null && ' · '}
          {entry.frequency !== null && (
            <span className={`kanji-tier-${frequencyTier(entry.frequency)}`}>
              freq {entry.frequency}
            </span>
          )}
        </div>
      )}
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
  maxDeckWords,
}: {
  kanji: CardKanji[]
  entries: Record<string, KanjiEntry>
  cardId: number
  maxDeckWords: number
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
          maxDeckWords={maxDeckWords}
        />
      ))}
    </aside>
  )
}
