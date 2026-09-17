import { useEffect, useState } from 'react'
import { toKana } from 'wanakana'
import { errorMessage, searchJmdict } from './api'
import type { JmdictEntry } from './api'

const DEBOUNCE_MS = 300

// A standalone, ad-hoc JMDict lookup — not tied to any document or token.
// Paste in a word (kanji or kana), or type it in romaji in the second box,
// and see every entry JMDict has for it, same as the per-token gloss popups
// but without needing a reading match or any surrounding sentence context.
export function JmdictSearch() {
  // What each box shows. Typing in one clears the other, so the results are
  // always for the box in use.
  const [pasted, setPasted] = useState('')
  const [romaji, setRomaji] = useState('')
  // What's looked up: the pasted text, or the romaji box's kana.
  const [query, setQuery] = useState('')
  const [maxResultsPerTier, setMaxResultsPerTier] = useState(3)
  const [results, setResults] = useState<JmdictEntry[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const trimmed = query.trim()
    if (!trimmed) {
      setResults(null)
      setError(null)
      setLoading(false)
      return
    }

    let cancelled = false
    setLoading(true)
    setError(null)

    const timeout = window.setTimeout(() => {
      searchJmdict(trimmed, maxResultsPerTier)
        .then((entries) => {
          if (cancelled) return
          setResults(entries)
        })
        .catch((err) => {
          if (cancelled) return
          setError(errorMessage(err, 'Lookup failed.'))
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
    }, DEBOUNCE_MS)

    return () => {
      cancelled = true
      window.clearTimeout(timeout)
    }
  }, [query, maxResultsPerTier])

  return (
    <div className="jmdict-search">
      <div className="jmdict-search-header">
        <div className="jmdict-search-title">JMDict Lookup</div>
        <input
          type="text"
          className="jmdict-search-input"
          placeholder="Paste a word…"
          value={pasted}
          onChange={(e) => {
            setPasted(e.target.value)
            setRomaji('')
            setQuery(e.target.value)
          }}
        />
        <input
          type="text"
          className="jmdict-search-input jmdict-search-romaji"
          placeholder="Romaji lookup…"
          autoComplete="off"
          spellCheck={false}
          value={romaji}
          onChange={(e) => {
            // Converted as typed, the way an input method does it: a trailing
            // n waits for the next letter, since it could start な or にゃ.
            const kana = toKana(e.target.value, { IMEMode: true })
            setRomaji(kana)
            setPasted('')
            // Looked up with that n as ん, as it is once typing stops.
            setQuery(toKana(kana))
          }}
        />
        <div className="jmdict-search-hint">Capitals for katakana: TEREBI → テレビ</div>
        <label className="jmdict-search-tier-limit">
          Prefix/suffix/substring matches per group
          <input
            type="number"
            min={1}
            max={20}
            value={maxResultsPerTier}
            onChange={(e) => setMaxResultsPerTier(Math.min(20, Math.max(1, Number(e.target.value) || 1)))}
          />
        </label>
      </div>
      <div className="jmdict-search-results-wrap">
        {loading && <div className="jmdict-search-status">Searching…</div>}
        {error && <div className="jmdict-search-status form-error">{error}</div>}
        {!loading && !error && results !== null && results.length === 0 && (
          <div className="jmdict-search-status">No entries found.</div>
        )}
        {results && results.length > 0 && (
          <ul className="jmdict-search-results">
            {results.map((entry) => (
              <li key={entry.idseq} className="jmdict-entry">
                <div className="jmdict-entry-headword">
                  {entry.kanji_forms.length > 0 ? entry.kanji_forms.join('、') : entry.kana_forms.join('、')}
                </div>
                {entry.kanji_forms.length > 0 && (
                  <div className="jmdict-entry-reading">{entry.kana_forms.join('、')}</div>
                )}
                <ol className="gloss-senses">
                  {entry.senses.map((sense, i) => (
                    <li key={i}>
                      {sense.gloss.join('; ')}
                      {(sense.field.length > 0 || sense.misc.length > 0) && (
                        <span className="gloss-tag"> ({[...sense.field, ...sense.misc].join(', ')})</span>
                      )}
                    </li>
                  ))}
                </ol>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
