import type { ReactNode } from 'react'

// Parses inline furigana markup: a run of kanji immediately followed by its
// reading in brackets, e.g. `書[か]いた`. Kana and punctuation outside
// brackets pass through unchanged, so only the exact kanji span written by
// hand gets a ruby reading — no lookup table, so irregular verbs like 来る
// (whose reading shifts between き/く/こ depending on conjugation) are just
// written correctly at each call site instead of guessed at runtime.
const FURIGANA_RE = /([一-鿿々]+)\[([^[\]]+)\]/g

export function Furigana({ text }: { text: string }): ReactNode {
  const nodes: ReactNode[] = []
  let lastIndex = 0
  let key = 0
  for (const match of text.matchAll(FURIGANA_RE)) {
    const index = match.index ?? 0
    if (index > lastIndex) nodes.push(text.slice(lastIndex, index))
    nodes.push(
      <ruby key={key++}>
        {match[1]}
        <rt>{match[2]}</rt>
      </ruby>,
    )
    lastIndex = index + match[0].length
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex))
  return <>{nodes}</>
}

// The shared "examples" column format used by both reference legends: a
// list of furigana-marked-up strings rendered inline, joined by " ・ ".
export function FuriganaExampleList({ examples }: { examples: string[] }): ReactNode {
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
