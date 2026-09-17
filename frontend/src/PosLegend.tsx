import { useEffect, useRef } from 'react'

// One kanji (or kanji run) paired with just the reading it covers, so ruby
// text lines up with the character it belongs to instead of floating over
// the whole term.
export type PosSegment = { text: string; reading: string }

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
    examples: ['猫 (cat)', '学校 (school)', '愛 (love)'],
  },
  {
    term: '動詞',
    segments: [
      { text: '動', reading: 'どう' },
      { text: '詞', reading: 'し' },
    ],
    label: 'Verb',
    description: 'Describes an action or state of being.',
    examples: ['食べる (to eat)', '行く (to go)', 'ある (to exist)'],
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
    examples: ['高い (tall/expensive)', '楽しい (fun)', '無い (nonexistent)'],
  },
  {
    term: '形状詞',
    segments: [
      { text: '形', reading: 'けい' },
      { text: '状', reading: 'じょう' },
      { text: '詞', reading: 'し' },
    ],
    label: 'na-Adjective',
    description: 'A descriptive word that takes な before a noun (e.g. 静かな部屋).',
    examples: ['静か (quiet)', '綺麗 (pretty)', '便利 (convenient)'],
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
    description: 'A short word marking grammatical role, attached after another word.',
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
    description: 'Attaches to a verb or adjective stem to add meaning like tense, negation, or politeness.',
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
    examples: ['私 (I)', 'これ (this)', '彼 (he)'],
  },
  {
    term: '連体詞',
    segments: [
      { text: '連', reading: 'れん' },
      { text: '体', reading: 'たい' },
      { text: '詞', reading: 'し' },
    ],
    label: 'Adnominal',
    description: "Directly modifies a following noun; doesn't conjugate on its own.",
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
    examples: ['お茶 (polite お-)', '真夜中 (true, 真-)', '不安 (un-, 不-)'],
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
    examples: ['～さん (Mr./Ms.)', '～たち (plural)', '～的 (-like/-ic)'],
  },
]

const POS_BY_TERM = new Map(POS_LEGEND.map((info) => [info.term, info]))

export function getPosInfo(term: string): PosInfo | undefined {
  return POS_BY_TERM.get(term)
}

// One ruby element per segment, so each reading sits over the character(s)
// it actually belongs to rather than being centered over the whole term.
export function PosTermRuby({ segments }: { segments: PosSegment[] }) {
  return (
    <>
      {segments.map((segment, i) => (
        <ruby key={i}>
          {segment.text}
          <rt>{segment.reading}</rt>
        </ruby>
      ))}
    </>
  )
}

// A modal listing all parts of speech, shown while `open`. Escape and the
// Close button both call onClose.
export function PosLegendModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) {
      dialog.showModal()
    } else if (!open && dialog.open) {
      dialog.close()
    }
  }, [open])

  return (
    <dialog
      ref={dialogRef}
      className="pos-legend-dialog"
      onCancel={(e) => {
        e.preventDefault()
        onClose()
      }}
      onClick={(e) => {
        // The dialog element covers the whole viewport, so a click landing
        // on it directly (not on a descendant) means it hit the backdrop.
        if (e.target === dialogRef.current) onClose()
      }}
    >
      <div className="pos-legend-title">Parts of Speech</div>
      <ul className="pos-legend-list">
        {POS_LEGEND.map((info) => (
          <li key={info.term} className="pos-legend-item">
            <span className="pos-legend-item-term">
              <PosTermRuby segments={info.segments} />
            </span>
            <span className="pos-legend-item-label">{info.label}</span>
            <span className="pos-legend-item-description">{info.description}</span>
            <span className="pos-legend-item-examples">{info.examples.join(' ・ ')}</span>
          </li>
        ))}
      </ul>
      <div className="pos-legend-dialog-actions">
        <button type="button" onClick={onClose}>
          Close
        </button>
      </div>
    </dialog>
  )
}
