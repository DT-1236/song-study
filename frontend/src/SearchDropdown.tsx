import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { errorMessage } from './api'
import { useClickOutside } from './useClickOutside'
import { useLatest } from './useLatest'

// A text input of the search besides the box, shown above it.
type SecondInput = {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
}

type Props<T> = {
  id: string
  label: string
  placeholder: string
  // Searched for on mount, when given.
  initialQuery?: string
  search: (query: string) => Promise<T>
  // What `search` looks for, when it can look for more than one thing. A
  // change repeats the last search (if any) for the new kind, unless that
  // kind's results for it are already in hand, and results still coming for
  // the old one never land.
  kind?: string
  // Takes what the search on mount found, and says whether to show it. The
  // results of a search asked for are always shown.
  onMountResults?: (results: T) => boolean
  failureMessage: string
  // Another input the search reads, which `search` takes from the caller's
  // own state. A search needs one of the two filled in, and Enter in either
  // searches.
  secondInput?: SecondInput
  // Holds off searching, say while the server has asked for a pause.
  disabled?: boolean
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
  secondInput,
  disabled = false,
  controls,
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
  // Compared rather than run on mount, which the search on mount covers.
  const lastKind = useRef(kind)
  const lastQuery = useRef(initialQuery)
  // The last query's results, by kind, so flipping `kind` back and forth
  // doesn't search again. A search asked for starts it afresh.
  const found = useRef<{ query: string; byKind: Map<string | undefined, T> }>({
    query: initialQuery,
    byKind: new Map(),
  })
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
      setError(null)
      if (!again) found.current = { query: text, byKind: new Map() }
      // Held on to, so a search settling after a newer one asked for caches
      // into the old query's results rather than the newer one's.
      const cache = found.current
      const searchKind = lastKind.current
      const cached = cache.byKind.get(searchKind)
      if (cached !== undefined) {
        setResults(cached)
        setShowResults(true)
        setSearching(false)
        return
      }
      setSearching(true)
      try {
        const results = await searchRef.current(text)
        // Cached even when a newer search dropped it: it's still that kind's
        // results for that query.
        cache.byKind.set(searchKind, results)
        if (searchId !== latestSearch.current) return
        setResults(results)
        setShowResults(
          !onMount || (onMountResultsRef.current?.(results) ?? true),
        )
      } catch (err) {
        if (searchId !== latestSearch.current) return
        // The previous results stay as they were, shown with a note below.
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

  useEffect(() => {
    if (kind === lastKind.current) return
    lastKind.current = kind
    // Even while a search is in flight: starting another drops its results.
    if (lastQuery.current) void runSearch(lastQuery.current, false, true)
  }, [kind, runSearch])

  const trimmed = query.trim()
  const filledIn = trimmed !== '' || !!secondInput?.value.trim()
  const canSubmit = !searching && !disabled && filledIn

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
        {secondInput && (
          <div className="search-dropdown-fields">
            <input
              id={secondInput.id}
              type="text"
              value={secondInput.value}
              onChange={(e) => secondInput.onChange(e.target.value)}
              onKeyDown={submitOnEnter}
              placeholder={secondInput.label}
              aria-label={secondInput.label}
            />
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
