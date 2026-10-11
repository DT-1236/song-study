import { useCallback, useMemo, useState, useSyncExternalStore } from 'react'

const KEY_PREFIX = 'song-study:'

// Each key's stored JSON (null for unset), read from localStorage on first
// use. It's the source of truth rather than localStorage itself, so a value
// that couldn't be stored still reaches everything using its key.
const stored = new Map<string, string | null>()
const listeners = new Map<string, Set<() => void>>()

function read(key: string) {
  if (!stored.has(key)) {
    let raw: string | null = null
    try {
      raw = window.localStorage.getItem(KEY_PREFIX + key)
    } catch {
      // Storage unavailable: the key starts unset.
    }
    stored.set(key, raw)
  }
  return stored.get(key) ?? null
}

function write(key: string, raw: string | null) {
  stored.set(key, raw)
  listeners.get(key)?.forEach((notify) => notify())
}

function subscribe(key: string, notify: () => void) {
  let keyListeners = listeners.get(key)
  if (!keyListeners) listeners.set(key, (keyListeners = new Set()))
  keyListeners.add(notify)
  return () => {
    keyListeners.delete(notify)
  }
}

// Another tab set or cleared a value. A null key means it cleared storage.
window.addEventListener('storage', (event) => {
  if (event.storageArea !== window.localStorage) return
  if (event.key === null) {
    for (const key of stored.keys()) write(key, null)
  } else if (event.key.startsWith(KEY_PREFIX)) {
    const key = event.key.slice(KEY_PREFIX.length)
    if (stored.has(key)) write(key, event.newValue)
  }
})

// Like useState, but a value that's set is kept in this browser's
// localStorage under `key`, so it survives reloads and is shared, live, by
// everything using the same key, in this tab and others. Until then the
// default applies, so an untouched setting keeps following it. A stored
// value of a different type than the default is ignored.
export function usePersistentState<T>(key: string, initial: T | (() => T)) {
  const [fallback] = useState(initial)
  const raw = useSyncExternalStore(
    useCallback((notify: () => void) => subscribe(key, notify), [key]),
    () => read(key),
  )

  // Parsed here rather than in the snapshot, which has to keep its identity
  // between reads: the raw string does, a parsed object wouldn't.
  const value = useMemo(() => {
    if (raw === null) return fallback
    try {
      const parsed: unknown = JSON.parse(raw)
      if (typeof parsed === typeof fallback) return parsed as T
    } catch {
      // A value that isn't JSON: use the default.
    }
    return fallback
  }, [raw, fallback])

  const setAndStore = useCallback(
    (next: T) => {
      const json = JSON.stringify(next)
      try {
        window.localStorage.setItem(KEY_PREFIX + key, json)
      } catch {
        // Storage full or disabled: the value just isn't kept past this tab.
      }
      write(key, json)
    },
    [key],
  )

  return [value, setAndStore] as const
}
