import type { LineTiming, Token } from './api'

// The last line to start by `time`, given each line's timing in order (null
// for an untimed line), or -1 before any: the line being sung, or in a gap
// after one, that line. Of lines that start together, it's the last, the
// only one with any length. Searches from `from`, the line last found, since
// playback mostly moves on a line at a time; -1 searches from the top.
export function lastStartedBy(
  lines: (LineTiming | null)[],
  time: number,
  from: number,
): number {
  let i = Math.min(from, lines.length - 1)
  // Back past lines that haven't started (after a seek back)...
  while (i >= 0 && (lines[i]?.start ?? Infinity) > time) i--
  // ...then on through lines that have started since.
  for (let j = i + 1; j < lines.length; j++) {
    const start = lines[j]?.start
    if (start === undefined) continue
    if (start > time) break
    i = j
  }
  return i
}

// Each line's timing, given its start (null for an untimed line): until the
// next timed line starts, as in LRC, and for the last timed line, until
// `songEnd`.
export function timingsFromStarts(
  starts: (number | null)[],
  songEnd: number,
): (LineTiming | null)[] {
  let end = songEnd
  const result: (LineTiming | null)[] = starts.map(() => null)
  for (let i = starts.length - 1; i >= 0; i--) {
    const start = starts[i]
    if (start === null) continue
    // Every other line ends where the next timed one starts, but the last
    // can start after `songEnd`: past LRCLIB's end (its track can be shorter
    // than the video), or while the video's length isn't known yet (0). It
    // then gets no length, rather than ending before it starts, which the
    // backend refuses.
    result[i] = { start, end: Math.max(end, start) }
    end = start
  }
  return result
}

// `seconds` as m:ss.cc, the precision LRC timestamps have.
export function formatTimestamp(seconds: number): string {
  const centiseconds = Math.round(seconds * 100)
  const minutes = Math.floor(centiseconds / 6000)
  return `${minutes}:${((centiseconds % 6000) / 100).toFixed(2).padStart(5, '0')}`
}

// A token on a line, or `text` alone: what follows the last line break in
// a token spanning one (such as the space a line starts with).
export type LinePiece = { token: Token; text?: string }

// A line of the lyrics: its pieces, and whether they have any text (blank
// lines, between stanzas, may go untimed).
export type LyricsLine = { pieces: LinePiece[]; hasText: boolean }

// Each line of `tokens`, without the line breaks between lines: the same
// lines, in the same order, as the backend's `text.split("\n")` of the
// document's text, which its timings are checked against.
export function linesOf(tokens: Token[]): LyricsLine[] {
  const lines: LinePiece[][] = [[]]
  for (const token of tokens) {
    const parts = token.surface.split('\n')
    if (parts.length === 1) {
      lines[lines.length - 1].push({ token })
      continue
    }
    for (let k = 1; k < parts.length; k++) lines.push([])
    const rest = parts[parts.length - 1]
    if (rest) lines[lines.length - 1].push({ token, text: rest })
  }
  return lines.map((pieces) => ({
    pieces,
    hasText: pieces.some(
      ({ token, text }) => (text ?? token.surface).trim() !== '',
    ),
  }))
}

// The start of the nearest timed line in `direction` (-1 or 1) from `line`.
export function startFrom(
  starts: (number | null)[],
  line: number,
  direction: number,
): number | null {
  for (let i = line + direction; i >= 0 && i < starts.length; i += direction) {
    const start = starts[i]
    if (start !== null) return start
  }
  return null
}

// Why `line` can't start at `start`, or null if it can: a line may start
// with a neighbor, but not past it.
export function overlapFor(
  starts: (number | null)[],
  line: number,
  start: number,
): string | null {
  const before = startFrom(starts, line, -1)
  const after = startFrom(starts, line, 1)
  if (start < (before ?? 0)) {
    return before === null
      ? "A line can't start before the song does."
      : "Can't overlap with the previous line."
  }
  return after !== null && start > after
    ? "Can't overlap with the next line."
    : null
}

// `start` moved by `deltaMs`, in whole milliseconds, the precision starts
// are kept to, so nudges don't pile up floating-point error.
export function nudgedStart(start: number, deltaMs: number): number {
  return (Math.round(start * 1000) + deltaMs) / 1000
}

// `time` in whole milliseconds, the precision starts are kept to.
export function roundedToMs(time: number): number {
  return Math.round(time * 1000) / 1000
}

// The line starting at `start` stamps: the one after the last timed line to
// start by then (the one being sung or, between lines, the nearest before),
// or the first line before any has.
export function lineToStamp(starts: (number | null)[], start: number): number {
  let sung = -1
  starts.forEach((s, i) => {
    if (s !== null && s <= start) sung = i
  })
  return sung + 1
}
