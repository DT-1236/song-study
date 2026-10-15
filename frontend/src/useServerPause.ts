import { useCallback, useEffect, useState } from 'react'
import { ApiError } from './api'

// A pause the server asked for (say, a rate limit): `paused` is true until
// the seconds given to the latest `pauseFor` have passed. `pauseIfAsked`
// pauses for an error's Retry-After, when it carries one.
export function useServerPause() {
  // When the pause ends, as a Date.now().
  const [pausedUntil, setPausedUntil] = useState<number | null>(null)

  useEffect(() => {
    if (pausedUntil === null) return
    const timer = window.setTimeout(
      () => setPausedUntil(null),
      pausedUntil - Date.now(),
    )
    return () => window.clearTimeout(timer)
  }, [pausedUntil])

  const pauseFor = useCallback(
    (seconds: number) => setPausedUntil(Date.now() + seconds * 1000),
    [],
  )

  const pauseIfAsked = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.retryAfterSeconds) {
        pauseFor(err.retryAfterSeconds)
      }
    },
    [pauseFor],
  )

  return { paused: pausedUntil !== null, pauseFor, pauseIfAsked }
}
