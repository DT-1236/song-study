import { useCallback, useSyncExternalStore } from 'react'

// Below this the nav and the lookup become drawers. Must match the query
// repeated in each narrow-screen @media block in App.css, since CSS media
// queries can't read a custom property.
export const NARROW_SCREEN = '(max-width: 900px), (max-height: 500px)'

// No mouse to hover with (a phone, or a tablet without a pointer). Must match
// the `(hover: none)` query in App.css, since CSS can't read a TS constant.
export const NO_HOVER = '(hover: none)'

/** Whether `query` currently matches, re-rendering when that changes. */
export function useMediaQuery(query: string): boolean {
  // Stable per query, so a re-render doesn't unsubscribe and resubscribe.
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = window.matchMedia(query)
      list.addEventListener('change', onChange)
      return () => list.removeEventListener('change', onChange)
    },
    [query],
  )
  return useSyncExternalStore(subscribe, () => window.matchMedia(query).matches)
}
