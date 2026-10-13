import { useCallback, useEffect, useState } from 'react'

// A value that's shown for `ms` after each `show(value)`, and null the rest
// of the time. Showing the same value again restarts its time.
export function useTransient<T>(ms: number) {
  // Wrapped, so the same value again is a new state, which restarts the
  // timer below.
  const [shown, setShown] = useState<{ value: T } | null>(null)
  useEffect(() => {
    if (!shown) return
    const timeout = window.setTimeout(() => setShown(null), ms)
    return () => window.clearTimeout(timeout)
  }, [shown, ms])
  const show = useCallback((value: T) => setShown({ value }), [])
  return [shown?.value ?? null, show] as const
}
