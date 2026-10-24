import { describe, expect, it } from 'vitest'
import { sliceSegments } from './cardText'

// 今日 (きょう) is one kanji run whose kana can't be divided by character.
const text = 'あ今日い'
const readings = [{ begin: 1, end: 3, reading: 'きょう' }]

describe('sliceSegments', () => {
  it('keeps a reading that lies within the range', () => {
    expect(sliceSegments(text, readings, 0)).toEqual([
      { text: 'あ', reading: null },
      { text: '今日', reading: 'きょう' },
      { text: 'い', reading: null },
    ])
  })

  it('keeps a straddling reading whole on one side of the cut', () => {
    const left = sliceSegments(text, readings, 0, 2)
    const right = sliceSegments(text, readings, 2)
    expect(left[1]).toEqual({ text: '今', reading: 'きょう' })
    expect(right[1]).toEqual({ text: '日', reading: null })
  })

  it('gives a straddling reading to the side holding more of its run', () => {
    const run = [{ begin: 0, end: 3, reading: 'あいう' }]
    expect(sliceSegments('一二三', run, 0, 1)[1].reading).toBeNull()
    expect(sliceSegments('一二三', run, 1)[1].reading).toBe('あいう')
  })
})
