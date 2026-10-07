import type { CardOption } from './api'

// The code points of `text` from `begin` to `end`, which is how the backend
// counts the offsets of a line.
export function codePointSlice(
  text: string,
  begin: number,
  end?: number,
): string {
  return Array.from(text).slice(begin, end).join('')
}

export function optionText(option: CardOption): string {
  if (option.note !== null) return option.note
  return (option.senses ?? []).map((gloss) => gloss.join(', ')).join(' · ')
}

// A word with its reading, as a card's reveal names it: 辛い（からい）.
export function wordLabel(lookupForm: string, reading: string | null): string {
  return reading ? `${lookupForm}（${reading}）` : lookupForm
}
