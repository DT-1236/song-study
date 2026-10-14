import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { errorMessage } from './api'
import { useClickOutside } from './useClickOutside'
import { useLatest } from './useLatest'

type Props<T> = {
  id: string
  label: string
  placeholder: string
  // Searched for on mount, when given.
  initialQuery?: string
  search: (query: string) => Promise<T>
  // Takes what the search on mount found, and says whether to show it. The
  // results of a search asked for are always shown.
  onMountResults?: (results: T) => boolean
  failureMessage: string
  // The results list, given the latest results, a function that closes it,
  // and one that repeats the last search with the `search` to use for it, for
  // a setting changed since.
  children: (
    results: T,
    close: () => void,
    searchAgain: (search: (query: string) => Promise<T>) => void,
  ) => ReactNode
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
  search,
  onMountResults,
  failureMessage,
  children,
}: Props<T>) {
  const [query, setQuery] = useState(initialQuery)
  // Null until a search has found something.
  const [results, setResults] = useState<T | null>(null)
  const [showResults, setShowResults] = useState(false)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  useClickOutside(rootRef, showResults, () => setShowResults(false))

  // Read when a search settles, so only the latest search's results land,
  // and none once this is gone (a newly picked song's remounts it).
  const searchRef = useLatest(search)
  const onMountResultsRef = useLatest(onMountResults)
  const latestSearch = useRef(0)
  const lastQuery = useRef(initialQuery)
  // Leaves whatever's in flight to settle for nobody. A named callback, since
  // the linter can't tell that the cleanup means to read the ref's latest
  // value.
  const dropPending = useCallback(() => {
    latestSearch.current++
  }, [])

  const runSearch = useCallback(
    async (text: string, onMount: boolean, searchWith = searchRef.current) => {
      lastQuery.current = text
      const searchId = ++latestSearch.current
      setSearching(true)
      setError(null)
      try {
        const found = await searchWith(text)
        if (searchId !== latestSearch.current) return
        setResults(found)
        setShowResults(!onMount || (onMountResultsRef.current?.(found) ?? true))
      } catch (err) {
        if (searchId !== latestSearch.current) return
        setShowResults(false)
        setError(errorMessage(err, failureMessage))
      } finally {
        if (searchId === latestSearch.current) setSearching(false)
      }
    },
    [searchRef, onMountResultsRef, failureMessage],
  )

  useEffect(() => {
    if (initialQuery) void runSearch(initialQuery, true)
    return dropPending
  }, [initialQuery, runSearch, dropPending])

  function submit() {
    const trimmed = query.trim()
    if (trimmed && !searching) void runSearch(trimmed, false)
  }

  return (
    <div className="search-dropdown">
      {/* Named by aria-labelledby rather than htmlFor, so a click on the label
          (or the space beside it) isn't forwarded to the input, which would
          reopen the results. */}
      <label id={`${id}-label`}>{label}</label>
      <div ref={rootRef}>
        <div className="search-dropdown-row">
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
            aria-labelledby={`${id}-label`}
          />
          <button
            type="button"
            className="search-dropdown-button"
            onClick={submit}
            disabled={searching || query.trim() === ''}
          >
            {searching ? 'Searching…' : 'Search'}
          </button>
        </div>

        {error && <p className="form-error">{error}</p>}
        {showResults &&
          results !== null &&
          children(
            results,
            () => setShowResults(false),
            (searchWith) =>
              void runSearch(lastQuery.current, false, searchWith),
          )}
      </div>
    </div>
  )
}

// A row of a SearchDropdown's results, marked when `chosen`.
export function SearchResult({
  chosen,
  onClick,
  children,
}: {
  chosen: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <li>
      <button
        type="button"
        className={chosen ? 'search-result chosen' : 'search-result'}
        onClick={onClick}
      >
        {children}
      </button>
    </li>
  )
}
