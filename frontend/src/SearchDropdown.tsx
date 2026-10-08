import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { errorMessage } from './api'
import { useClickOutside } from './useClickOutside'
import { useLatest } from './useLatest'

type Props<T> = {
  id: string
  label: string
  placeholder: string
  initialQuery?: string
  // Searches for `query` on mount too, rather than only once asked.
  searchOnMount?: boolean
  search: (query: string) => Promise<T>
  // Takes what a search found (`initial` for the one on mount), and says
  // whether to show the results for it.
  onResults: (results: T, initial: boolean) => boolean
  failureMessage: string
  // The results list, given a function that closes it.
  children: (close: () => void) => ReactNode
}

// A search box whose results drop down below it. It searches on Enter or a
// click rather than per keystroke, since each search reaches an outside
// service. A pick (through `children`'s close), a click elsewhere, or Escape
// closes the results, and clicking back into the box shows them again. A div
// rather than a form, as it sits inside one.
export function SearchDropdown<T>({
  id,
  label,
  placeholder,
  initialQuery = '',
  searchOnMount = false,
  search,
  onResults,
  failureMessage,
  children,
}: Props<T>) {
  const [query, setQuery] = useState(initialQuery)
  const [showResults, setShowResults] = useState(false)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  useClickOutside(rootRef, showResults, () => setShowResults(false))
  const close = useCallback(() => setShowResults(false), [])

  // Read when a search settles, so only the latest search's results land,
  // and none once this is gone (a newly picked song's remounts it).
  const searchRef = useLatest(search)
  const onResultsRef = useLatest(onResults)
  const latestSearch = useRef(0)
  // Leaves whatever's in flight to settle for nobody.
  const dropPending = useCallback(() => {
    latestSearch.current++
  }, [])

  const runSearch = useCallback(
    async (text: string, initial: boolean) => {
      const searchId = ++latestSearch.current
      setSearching(true)
      setError(null)
      try {
        const results = await searchRef.current(text)
        if (searchId !== latestSearch.current) return
        setShowResults(onResultsRef.current(results, initial))
      } catch (err) {
        if (searchId !== latestSearch.current) return
        setShowResults(false)
        setError(errorMessage(err, failureMessage))
      } finally {
        if (searchId === latestSearch.current) setSearching(false)
      }
    },
    [searchRef, onResultsRef, failureMessage],
  )

  useEffect(() => {
    if (searchOnMount) void runSearch(initialQuery, true)
    return dropPending
  }, [searchOnMount, initialQuery, runSearch, dropPending])

  function submit() {
    const trimmed = query.trim()
    if (trimmed && !searching) void runSearch(trimmed, false)
  }

  return (
    <div ref={rootRef} className="song-search">
      <label htmlFor={id}>{label}</label>
      <div className="song-search-row">
        <input
          id={id}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          // Clicking too, since a box that kept focus after a pick gets no
          // focus event.
          onFocus={() => setShowResults(true)}
          onClick={() => setShowResults(true)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setShowResults(false)
            // Enter would otherwise submit the surrounding form. Enter that
            // confirms an IME conversion isn't a search.
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
              e.preventDefault()
              submit()
            }
          }}
          placeholder={placeholder}
        />
        <button
          type="button"
          className="song-search-button"
          onClick={submit}
          disabled={searching || query.trim() === ''}
        >
          {searching ? 'Searching…' : 'Search'}
        </button>
      </div>

      {error && <p className="form-error">{error}</p>}
      {showResults && children(close)}
    </div>
  )
}
