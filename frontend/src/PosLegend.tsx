import {
  FuriganaExampleList,
  renderSegments,
  type FuriganaSegment,
} from './furigana'
import { useDialogModal } from './useDialogModal'

// One kanji (or kanji run) paired with just the reading it covers, so ruby
// text lines up with the character it belongs to instead of floating over
// the whole term. Term headers are short enough (2-4 characters) to author
// directly as segments rather than through furigana.tsx's bracket markup.
export type PosSegment = FuriganaSegment

export type PosInfo = {
  term: string
  segments: PosSegment[]
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
    segments: [
      { text: '名', reading: 'めい' },
      { text: '詞', reading: 'し' },
    ],
    label: 'Noun',
    description: 'A word for a person, place, thing, or idea.',
    examples: ['猫[ねこ] (cat)', '学校[がっこう] (school)', '愛[あい] (love)'],
  },
  {
    term: '動詞',
    segments: [
      { text: '動', reading: 'どう' },
      { text: '詞', reading: 'し' },
    ],
    label: 'Verb',
    description: 'Describes an action or state of being.',
    examples: ['食[た]べる (to eat)', '行[い]く (to go)', 'ある (to exist)'],
  },
  {
    term: '形容詞',
    segments: [
      { text: '形', reading: 'けい' },
      { text: '容', reading: 'よう' },
      { text: '詞', reading: 'し' },
    ],
    label: 'i-Adjective',
    description: 'A descriptive word ending in い that conjugates on its own.',
    examples: [
      '高[たか]い (tall/expensive)',
      '楽[たの]しい (fun)',
      '無[な]い (nonexistent)',
    ],
  },
  {
    term: '形状詞',
    segments: [
      { text: '形', reading: 'けい' },
      { text: '状', reading: 'じょう' },
      { text: '詞', reading: 'し' },
    ],
    label: 'na-Adjective',
    description:
      'A descriptive word that takes な before a noun (e.g. 静かな部屋).',
    examples: [
      '静[しず]か (quiet)',
      '綺麗[きれい] (pretty)',
      '便利[べんり] (convenient)',
    ],
  },
  {
    term: '副詞',
    segments: [
      { text: '副', reading: 'ふく' },
      { text: '詞', reading: 'し' },
    ],
    label: 'Adverb',
    description: 'Modifies a verb, adjective, or another adverb.',
    examples: ['とても (very)', 'もう (already)', 'ゆっくり (slowly)'],
  },
  {
    term: '助詞',
    segments: [
      { text: '助', reading: 'じょ' },
      { text: '詞', reading: 'し' },
    ],
    label: 'Particle',
    description:
      'A short word marking grammatical role, attached after another word.',
    examples: ['は', 'が', 'を', 'に', 'で'],
  },
  {
    term: '助動詞',
    segments: [
      { text: '助', reading: 'じょ' },
      { text: '動', reading: 'どう' },
      { text: '詞', reading: 'し' },
    ],
    label: 'Auxiliary verb',
    description:
      'Attaches to a verb or adjective stem to add meaning like tense, negation, or politeness.',
    examples: ['ない (negative)', 'た (past)', 'です (polite copula)'],
  },
  {
    term: '接続詞',
    segments: [
      { text: '接', reading: 'せつ' },
      { text: '続', reading: 'ぞく' },
      { text: '詞', reading: 'し' },
    ],
    label: 'Conjunction',
    description: 'Connects clauses or sentences.',
    examples: ['そして (and then)', 'しかし (however)', 'だから (so)'],
  },
  {
    term: '感動詞',
    segments: [
      { text: '感', reading: 'かん' },
      { text: '動', reading: 'どう' },
      { text: '詞', reading: 'し' },
    ],
    label: 'Interjection',
    description: 'A standalone exclamation or reaction.',
    examples: ['ああ (ah)', 'はい (yes)', 'おい (hey)'],
  },
  {
    term: '代名詞',
    segments: [
      { text: '代', reading: 'だい' },
      { text: '名', reading: 'めい' },
      { text: '詞', reading: 'し' },
    ],
    label: 'Pronoun',
    description: 'Stands in for a noun already understood from context.',
    examples: ['私[わたし] (I)', 'これ (this)', '彼[かれ] (he)'],
  },
  {
    term: '連体詞',
    segments: [
      { text: '連', reading: 'れん' },
      { text: '体', reading: 'たい' },
      { text: '詞', reading: 'し' },
    ],
    label: 'Adnominal',
    description:
      "Directly modifies a following noun; doesn't conjugate on its own.",
    examples: ['この (this)', 'ある (a certain)', 'いわゆる (so-called)'],
  },
  {
    term: '接頭辞',
    segments: [
      { text: '接', reading: 'せっ' },
      { text: '頭', reading: 'とう' },
      { text: '辞', reading: 'じ' },
    ],
    label: 'Prefix',
    description: 'Attaches before a word to modify its meaning.',
    examples: [
      'お茶[ちゃ] (polite お-)',
      '真夜中[まよなか] (true, 真-)',
      '不安[ふあん] (un-, 不-)',
    ],
  },
  {
    term: '接尾辞',
    segments: [
      { text: '接', reading: 'せつ' },
      { text: '尾', reading: 'び' },
      { text: '辞', reading: 'じ' },
    ],
    label: 'Suffix',
    description: 'Attaches after a word to modify its meaning.',
    examples: ['～さん (Mr./Ms.)', '～たち (plural)', '～的[てき] (-like/-ic)'],
  },
]

const POS_BY_TERM = new Map(POS_LEGEND.map((info) => [info.term, info]))

export function getPosInfo(term: string): PosInfo | undefined {
  return POS_BY_TERM.get(term)
}

export function PosTermRuby({ segments }: { segments: PosSegment[] }) {
  return renderSegments(segments)
}

// A modal listing all parts of speech, shown while `open`. Escape and the
// Close button both call onClose.
export function PosLegendModal({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const { dialogRef, hasOpened, onCancel, onClick } = useDialogModal(
    open,
    onClose,
  )

  return (
    <dialog
      ref={dialogRef}
      className="pos-legend-dialog"
      onCancel={onCancel}
      onClick={onClick}
    >
      {hasOpened && (
        <>
          <div className="pos-legend-title">Parts of Speech</div>
          <ul className="pos-legend-list">
            {POS_LEGEND.map((info) => (
              <li key={info.term} className="pos-legend-item">
                <span className="pos-legend-item-term">
                  <PosTermRuby segments={info.segments} />
                </span>
                <span className="pos-legend-item-label">{info.label}</span>
                <span className="pos-legend-item-description">
                  {info.description}
                </span>
                <span className="pos-legend-item-examples">
                  <FuriganaExampleList examples={info.examples} />
                </span>
              </li>
            ))}
          </ul>
          <div className="pos-legend-dialog-actions">
            <button type="button" onClick={onClose}>
              Close
            </button>
          </div>
        </>
      )}
    </dialog>
  )
}
