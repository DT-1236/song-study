import { useState } from 'react'

export type PosInfo = {
  term: string
  furigana: string
  label: string
  description: string
  examples: string[]
}

// Furigana readings verified against Sudachi's own tokenizer, not typed
// from memory. Descriptions and examples are hand-written reference
// content, not derived from JMDict/Sudachi.
export const POS_LEGEND: PosInfo[] = [
  {
    term: '名詞',
    furigana: 'めいし',
    label: 'Noun',
    description: 'A word for a person, place, thing, or idea.',
    examples: ['猫 (cat)', '学校 (school)', '愛 (love)'],
  },
  {
    term: '動詞',
    furigana: 'どうし',
    label: 'Verb',
    description: 'Describes an action or state of being.',
    examples: ['食べる (to eat)', '行く (to go)', 'ある (to exist)'],
  },
  {
    term: '形容詞',
    furigana: 'けいようし',
    label: 'i-Adjective',
    description: 'A descriptive word ending in い that conjugates on its own.',
    examples: ['高い (tall/expensive)', '楽しい (fun)', '無い (nonexistent)'],
  },
  {
    term: '形状詞',
    furigana: 'けいじょうし',
    label: 'na-Adjective',
    description: 'A descriptive word that takes な before a noun (e.g. 静かな部屋).',
    examples: ['静か (quiet)', '綺麗 (pretty)', '便利 (convenient)'],
  },
  {
    term: '副詞',
    furigana: 'ふくし',
    label: 'Adverb',
    description: 'Modifies a verb, adjective, or another adverb.',
    examples: ['とても (very)', 'もう (already)', 'ゆっくり (slowly)'],
  },
  {
    term: '助詞',
    furigana: 'じょし',
    label: 'Particle',
    description: 'A short word marking grammatical role, attached after another word.',
    examples: ['は', 'が', 'を', 'に', 'で'],
  },
  {
    term: '助動詞',
    furigana: 'じょどうし',
    label: 'Auxiliary verb',
    description: 'Attaches to a verb or adjective stem to add meaning like tense, negation, or politeness.',
    examples: ['ない (negative)', 'た (past)', 'です (polite copula)'],
  },
  {
    term: '接続詞',
    furigana: 'せつぞくし',
    label: 'Conjunction',
    description: 'Connects clauses or sentences.',
    examples: ['そして (and then)', 'しかし (however)', 'だから (so)'],
  },
  {
    term: '感動詞',
    furigana: 'かんどうし',
    label: 'Interjection',
    description: 'A standalone exclamation or reaction.',
    examples: ['ああ (ah)', 'はい (yes)', 'おい (hey)'],
  },
  {
    term: '代名詞',
    furigana: 'だいめいし',
    label: 'Pronoun',
    description: 'Stands in for a noun already understood from context.',
    examples: ['私 (I)', 'これ (this)', '彼 (he)'],
  },
  {
    term: '連体詞',
    furigana: 'れんたいし',
    label: 'Adnominal',
    description: "Directly modifies a following noun; doesn't conjugate on its own.",
    examples: ['この (this)', 'ある (a certain)', 'いわゆる (so-called)'],
  },
  {
    term: '接頭辞',
    furigana: 'せっとうじ',
    label: 'Prefix',
    description: 'Attaches before a word to modify its meaning.',
    examples: ['お茶 (polite お-)', '真夜中 (true, 真-)', '不安 (un-, 不-)'],
  },
  {
    term: '接尾辞',
    furigana: 'せつびじ',
    label: 'Suffix',
    description: 'Attaches after a word to modify its meaning.',
    examples: ['～さん (Mr./Ms.)', '～たち (plural)', '～的 (-like/-ic)'],
  },
]

const POS_BY_TERM = new Map(POS_LEGEND.map((info) => [info.term, info]))

export function getPosInfo(term: string): PosInfo | undefined {
  return POS_BY_TERM.get(term)
}

export function PosLegend() {
  const [hoveredTerm, setHoveredTerm] = useState<string | null>(null)

  return (
    <div className="pos-legend">
      <div className="pos-legend-title">Parts of Speech</div>
      <ul className="pos-legend-list">
        {POS_LEGEND.map((info) => (
          <li
            key={info.term}
            className="pos-legend-item"
            onMouseEnter={() => setHoveredTerm(info.term)}
            onMouseLeave={() => setHoveredTerm((prev) => (prev === info.term ? null : prev))}
          >
            <ruby>
              {info.term}
              <rt>{info.furigana}</rt>
            </ruby>
            {hoveredTerm === info.term && (
              <div className="pos-legend-popup">
                <div className="pos-legend-popup-label">{info.label}</div>
                <div className="pos-legend-popup-description">{info.description}</div>
                <div className="pos-legend-popup-examples">{info.examples.join(' ・ ')}</div>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
