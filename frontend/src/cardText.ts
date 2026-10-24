import type { CardOption } from './api'
import type { FuriganaSegment } from './furigana'

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

// The code-point range [begin, end) of `text` as furigana segments, one per
// reading inside the range. A reading that crosses an edge of the range stays
// whole over the part of its run where the run begins: a run's kana can't be
// divided by character without misreading compounds like 今日 (きょう), and
// of the slices a line is cut into, exactly one holds the run's start.
export function sliceSegments(
  text: string,
  readings: { begin: number; end: number; reading: string }[],
  begin: number,
  end?: number,
): FuriganaSegment[] {
  const stop = end ?? Array.from(text).length
  const segments: FuriganaSegment[] = []
  let at = begin
  for (const r of readings) {
    const from = Math.max(r.begin, begin)
    const to = Math.min(r.end, stop)
    if (from >= to) continue
    segments.push({ text: codePointSlice(text, at, from), reading: null })
    segments.push({
      text: codePointSlice(text, from, to),
      reading: from === r.begin ? r.reading : null,
    })
    at = to
  }
  segments.push({ text: codePointSlice(text, at, stop), reading: null })
  return segments
}
