import type { CardKanji, KanjiEntry } from './api'

// Easy to hard, green through amber to red.
const TIER_COLORS = [
  '#4ade80',
  '#71e577',
  '#97eb6d',
  '#bef264',
  '#d2e14f',
  '#e7d039',
  '#fbbf24',
  '#fca33c',
  '#fe8753',
  '#ff6b6b',
]

const clampTier = (tier: number) =>
  Math.min(Math.max(Math.floor(tier), 0), TIER_COLORS.length - 1)

// A grade or frequency, colored by how hard `tier` (0, easiest, to 9) says
// the kanji is.
function Tier({ tier, children }: { tier: number; children: string }) {
  return <span style={{ color: TIER_COLORS[clampTier(tier)] }}>{children}</span>
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
  // KANJIDIC2 grades 1-6 are the school years, 8 the rest of the jōyō kanji
  // and 9-10 the name kanji; its newspaper frequency rank runs 1-2500, 1
  // being the most common, so a tier is 250 ranks.
  const meta = [
    entry.grade !== null && (
      <Tier tier={entry.grade - 1}>{`grade ${entry.grade}`}</Tier>
    ),
    entry.frequency !== null && (
      <Tier
        tier={(entry.frequency - 1) / 250}
      >{`freq ${entry.frequency}`}</Tier>
    ),
  ].filter(Boolean)

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
      {meta.length > 0 && (
        <div className="kanji-meta">
          {meta.map((item, i) => (
            <span key={i}>
              {i > 0 && ' · '}
              {item}
            </span>
          ))}
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
