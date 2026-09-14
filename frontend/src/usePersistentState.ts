import { useCallback, useState } from 'react'

const KEY_PREFIX = 'song-study:'

// Like useState, but a value that's set is kept in this browser's
// localStorage under `key`, so it survives reloads and is shared by
// everything using the same key. Until then the default applies, so an
// untouched setting keeps following it. A stored value of a different type
// than the default is ignored.
export function usePersistentState<T>(key: string, initial: T | (() => T)) {
  const [value, setValue] = useState<T>(() => {
    const fallback = typeof initial === 'function' ? (initial as () => T)() : initial
    try {
      const stored = window.localStorage.getItem(KEY_PREFIX + key)
      if (stored !== null) {
        const parsed: unknown = JSON.parse(stored)
        if (typeof parsed === typeof fallback) return parsed as T
      }
    } catch {
      // Storage unavailable, or a value that isn't JSON: use the default.
    }
    return fallback
  })

  const setAndStore = useCallback(
    (next: T) => {
      setValue(next)
      try {
        window.localStorage.setItem(KEY_PREFIX + key, JSON.stringify(next))
      } catch {
        // Storage full or disabled: the value just isn't kept.
      }
    },
    [key],
  )

  return [value, setAndStore] as const
}
