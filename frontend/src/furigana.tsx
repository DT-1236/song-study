import type { ReactNode } from 'react'

// One run of text paired with the reading that covers it, or a null reading
// for a run with no furigana (kana, punctuation, romaji, ...). Shared shape
// for every hand-authored furigana source in the app: segments parsed from
// bracket markup (see below) and segments authored directly as an array
// (PosLegend's PosTermRuby, for its short 2-4 character term headers, where
// writing `[{ text: '名', reading: 'めい' }, ...]` is no harder than markup).
export type FuriganaSegment = { text: string; reading: string | null }

// One <ruby> per segment with a reading, a plain span otherwise, so a
// reading sits only over the exact characters it belongs to.
export function renderSegments(segments: FuriganaSegment[]): ReactNode {
  return (
    <>
      {segments.map((segment, i) =>
        segment.reading ? (
          <ruby key={i}>
            {segment.text}
            <rt>{segment.reading}</rt>
          </ruby>
        ) : (
          <span key={i}>{segment.text}</span>
        ),
      )}
    </>
  )
}

// Parses inline furigana markup: a run of kanji immediately followed by its
// reading in brackets, e.g. `書[か]いた`. Kana and punctuation outside
// brackets pass through unchanged, so only the exact kanji span written by
// hand gets a ruby reading — no lookup table, so irregular verbs like 来る
// (whose reading shifts between き/く/こ depending on conjugation) are just
// written correctly at each call site instead of guessed at runtime.
const FURIGANA_RE = /([一-鿿々]+)\[([^[\]]+)\]/g

function parseFurigana(text: string): FuriganaSegment[] {
  const segments: FuriganaSegment[] = []
  let lastIndex = 0
  for (const match of text.matchAll(FURIGANA_RE)) {
    const index = match.index ?? 0
    if (index > lastIndex)
      segments.push({ text: text.slice(lastIndex, index), reading: null })
    segments.push({ text: match[1], reading: match[2] })
    lastIndex = index + match[0].length
  }
  if (lastIndex < text.length)
    segments.push({ text: text.slice(lastIndex), reading: null })
  return segments
}

export function Furigana({ text }: { text: string }): ReactNode {
  return renderSegments(parseFurigana(text))
}

// The shared "examples" column format used by both reference legends: a
// list of furigana-marked-up strings rendered inline, joined by " ・ ".
export function FuriganaExampleList({
  examples,
}: {
  examples: string[]
}): ReactNode {
  return (
    <>
      {examples.map((example, i) => (
        <span key={i}>
          {i > 0 && ' ・ '}
          <Furigana text={example} />
        </span>
      ))}
    </>
  )
}
