import { useEffect, useState } from 'react'
import { ApiError, searchJmdict } from './api'
import type { JmdictEntry } from './api'

const DEBOUNCE_MS = 300

// A standalone, ad-hoc JMDict lookup — not tied to any document or token.
// Paste in a word (kanji or kana) and see every entry JMDict has for it,
// same as the per-token gloss popups but without needing a reading match or
// any surrounding sentence context.
export function JmdictSearch() {
  const [query, setQuery] = useState('')
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
      searchJmdict(trimmed)
        .then((entries) => {
          if (cancelled) return
          setResults(entries)
        })
        .catch((err) => {
          if (cancelled) return
          setError(err instanceof ApiError ? err.message : 'Lookup failed.')
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
    }, DEBOUNCE_MS)

    return () => {
      cancelled = true
      window.clearTimeout(timeout)
    }
  }, [query])

  return (
    <div className="jmdict-search">
      <div className="jmdict-search-title">JMDict Lookup</div>
      <input
        type="text"
        className="jmdict-search-input"
        placeholder="Paste a word…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
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
  )
}
