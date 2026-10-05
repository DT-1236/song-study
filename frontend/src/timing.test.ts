import { describe, expect, it } from 'vitest'
import type { Token } from './api'
import {
  lastStartedBy,
  lineToStamp,
  linesOf,
  nudgedStart,
  overlapFor,
  timingsFromStarts,
  formatTimestamp,
} from './timing'

// Only `surface` matters to `linesOf`.
function token(surface: string, id = 0): Token {
  return { id, surface } as Token
}

// Tokens that spell `text`, with the line breaks as tokens of their own, and
// with spaces (as tokenization has them) folded into the token before.
function tokensOf(text: string): Token[] {
  return text
    .split(/(\n+)/)
    .filter(Boolean)
    .map((s, i) => token(s, i))
}

function lineTexts(tokens: Token[]): string[] {
  return linesOf(tokens).map(({ pieces }) =>
    pieces.map(({ token, text }) => text ?? token.surface).join(''),
  )
}

describe('linesOf', () => {
  const texts = [
    'a\nb\nc',
    'a\n\nb',
    'a\n',
    '\na',
    '\n\n',
    'a\n\n\nb\n',
    '',
    'one line',
  ]

  it.each(texts)(
    'gives the lines of %j that the backend splits it into',
    (text) => {
      expect(lineTexts(tokensOf(text))).toEqual(text.split('\n'))
    },
  )

  it('counts a token spanning line breaks once per break', () => {
    // A single token holding a break and the space a line starts with.
    const tokens = [token('a'), token('\n '), token('b')]
    expect(lineTexts(tokens)).toEqual(['a', ' b'])
    expect(linesOf(tokens)).toHaveLength(2)
  })

  it('marks lines with only whitespace as having no text, like strip()', () => {
    const lines = linesOf(tokensOf('a\n \nb'))
    expect(lines.map((l) => l.hasText)).toEqual([true, false, true])
  })
})

describe('lastStartedBy', () => {
  const t = (start: number) => ({ start, end: start + 1 })

  it('is -1 before any line starts', () => {
    expect(lastStartedBy([t(5), t(10)], 1, -1)).toBe(-1)
  })

  it('finds the line being sung, or the nearest before in a gap', () => {
    const lines = [t(1), t(5), t(10)]
    expect(lastStartedBy(lines, 5, -1)).toBe(1)
    expect(lastStartedBy(lines, 7, -1)).toBe(1)
    expect(lastStartedBy(lines, 99, -1)).toBe(2)
  })

  it('goes back after a seek back', () => {
    expect(lastStartedBy([t(1), t(5), t(10)], 2, 2)).toBe(0)
    expect(lastStartedBy([t(1), t(5), t(10)], 0, 2)).toBe(-1)
  })

  it('takes the last of lines that start together', () => {
    expect(lastStartedBy([t(1), t(5), t(5), t(10)], 6, -1)).toBe(2)
  })

  it('skips untimed lines', () => {
    expect(lastStartedBy([t(1), null, t(5), null], 9, -1)).toBe(2)
    expect(lastStartedBy([null, t(5)], 1, 1)).toBe(-1)
  })
})

describe('timingsFromStarts', () => {
  it('ends each line where the next timed one starts', () => {
    expect(timingsFromStarts([1, null, 4, 9], 20)).toEqual([
      { start: 1, end: 4 },
      null,
      { start: 4, end: 9 },
      { start: 9, end: 20 },
    ])
  })

  it('gives a last line starting past the song end no length', () => {
    expect(timingsFromStarts([1, 30], 20)[1]).toEqual({ start: 30, end: 30 })
  })
})

describe('formatTimestamp', () => {
  it('writes m:ss.cc', () => {
    expect(formatTimestamp(0)).toBe('0:00.00')
    expect(formatTimestamp(65.5)).toBe('1:05.50')
    expect(formatTimestamp(59.999)).toBe('1:00.00')
  })
})

describe('lineToStamp', () => {
  const starts = [2, null, 6]

  it('is the first line before any has started', () => {
    expect(lineToStamp(starts, 1)).toBe(0)
    expect(lineToStamp([null, null], 5)).toBe(0)
  })

  it('is the line after the one being sung, between lines', () => {
    expect(lineToStamp(starts, 3)).toBe(1)
    expect(lineToStamp(starts, 2)).toBe(1)
  })

  it('is past the end once the last line has started', () => {
    expect(lineToStamp(starts, 7)).toBe(3)
  })
})

describe('overlapFor', () => {
  const starts = [2, null, 6, 8]

  it('allows starting with a neighbor', () => {
    expect(overlapFor(starts, 2, 8)).toBeNull()
    expect(overlapFor(starts, 2, 2)).toBeNull()
    expect(overlapFor(starts, 1, 2)).toBeNull()
  })

  it('refuses starting past the previous or next timed line', () => {
    expect(overlapFor(starts, 2, 1.9)).toMatch(/previous/)
    expect(overlapFor(starts, 1, 6.1)).toMatch(/next/)
    expect(overlapFor(starts, 3, 5)).toMatch(/previous/)
  })

  it('refuses starting before the song does', () => {
    expect(overlapFor(starts, 0, -0.1)).toMatch(/before the song/)
  })
})

describe('nudgedStart', () => {
  it('stays in whole milliseconds', () => {
    let start = 0.1
    for (let i = 0; i < 30; i++) start = nudgedStart(start, 10)
    expect(start).toBe(0.4)
    expect(nudgedStart(1.0004, -50)).toBe(0.95)
  })
})
