import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError, errorMessage } from './api'
import { useClickOutside } from './useClickOutside'
import { useLatest } from './useLatest'

type Props<T> = {
  id: string
  label: string
  placeholder: string
  // Searched for on mount, when given.
  initialQuery?: string
  // `again` is true when it repeats the last search because `kind` changed,
  // rather than for a search asked for or the one on mount.
  search: (query: string, again: boolean) => Promise<T>
  // What `search` looks for, when it can look for more than one thing. A
  // change repeats the last search (if any) for the new kind, and results
  // still coming for the old one never land.
  kind?: string
  // Takes what the search on mount found, and says whether to show it. The
  // results of a search asked for are always shown.
  onMountResults?: (results: T) => boolean
  failureMessage: string
  // Whether `query` (trimmed) can be searched. By default, when it isn't
  // empty; a search that has other fields may allow an empty query.
  canSearch?: (query: string) => boolean
  // Further fields of the search, shown above the box. Enter in one of their
  // text inputs searches, as it does in the box.
  fields?: ReactNode
  // Settings shown under the box whether or not there are results.
  controls?: ReactNode
  // The results list, given the latest results and a function that closes it.
  children: (results: T, close: () => void) => ReactNode
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
  kind,
  onMountResults,
  failureMessage,
  canSearch = (text) => text !== '',
  fields,
  controls,
  children,
}: Props<T>) {
  const [query, setQuery] = useState(initialQuery)
  // Null until a search has found something.
  const [results, setResults] = useState<T | null>(null)
  const [showResults, setShowResults] = useState(false)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // When the server's request for a pause in searching ends, as a Date.now().
  const [pausedUntil, setPausedUntil] = useState<number | null>(null)
  const paused = pausedUntil !== null
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
    async (text: string, onMount: boolean, again = false) => {
      lastQuery.current = text
      const searchId = ++latestSearch.current
      setSearching(true)
      setError(null)
      try {
        const found = await searchRef.current(text, again)
        if (searchId !== latestSearch.current) return
        setResults(found)
        setShowResults(!onMount || (onMountResultsRef.current?.(found) ?? true))
      } catch (err) {
        if (searchId !== latestSearch.current) return
        // The previous results stay as they were, shown with a note below.
        setError(errorMessage(err, failureMessage))
        if (err instanceof ApiError && err.retryAfterSeconds) {
          setPausedUntil(Date.now() + err.retryAfterSeconds * 1000)
        }
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

  // Compared rather than run on mount, which the search on mount covers.
  const lastKind = useRef(kind)
  useEffect(() => {
    if (kind === lastKind.current) return
    lastKind.current = kind
    // Even while a search is in flight: starting another drops its results.
    if (lastQuery.current) void runSearch(lastQuery.current, false, true)
  }, [kind, runSearch])

  useEffect(() => {
    if (pausedUntil === null) return
    const timer = window.setTimeout(
      () => setPausedUntil(null),
      pausedUntil - Date.now(),
    )
    return () => window.clearTimeout(timer)
  }, [pausedUntil])

  const trimmed = query.trim()
  const canSubmit = !searching && !paused && canSearch(trimmed)

  function submit() {
    if (canSubmit) void runSearch(trimmed, false)
  }

  // Enter would otherwise submit the surrounding form. Enter that confirms an
  // IME conversion isn't a search.
  function submitOnEnter(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="search-dropdown">
      {/* Named by aria-labelledby rather than htmlFor, so a click on the label
          (or the space beside it) isn't forwarded to the input, which would
          reopen the results. */}
      <label id={`${id}-label`}>{label}</label>
      <div ref={rootRef}>
        {fields && (
          <div
            className="search-dropdown-fields"
            onKeyDown={(e) => {
              if (e.target instanceof HTMLInputElement) submitOnEnter(e)
            }}
          >
            {fields}
          </div>
        )}
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
              submitOnEnter(e)
            }}
            placeholder={placeholder}
            aria-labelledby={`${id}-label`}
          />
          <button
            type="button"
            className="search-dropdown-button"
            onClick={submit}
            disabled={!canSubmit}
          >
            {searching ? 'Searching…' : 'Search'}
          </button>
        </div>

        {controls}
        {error && <p className="form-error">{error}</p>}
        {error && results !== null && (
          <p className="search-dropdown-stale">
            Any results shown are from your previous search, so they may not
            match what's entered above.
          </p>
        )}
        {showResults &&
          results !== null &&
          children(results, () => setShowResults(false))}
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
