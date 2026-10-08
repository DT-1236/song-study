import { useEffect } from 'react'
import type { RefObject } from 'react'
import { useLatest } from './useLatest'

// Calls `onOutside` when a click starts anywhere on the page outside the
// element at `ref`, while `active`.
export function useClickOutside(
  ref: RefObject<HTMLElement | null>,
  active: boolean,
  onOutside: () => void,
) {
  // Read when a click lands, so a new callback doesn't re-add the listener.
  const onOutsideRef = useLatest(onOutside)

  useEffect(() => {
    if (!active) return
    // On press rather than click, so a press that moves focus elsewhere
    // closes at once. A click inside the YouTube iframe never reaches this
    // document, so it doesn't count.
    function handlePointerDown(event: PointerEvent) {
      if (!ref.current?.contains(event.target as Node)) onOutsideRef.current()
    }
    document.addEventListener('pointerdown', handlePointerDown)
    return () => document.removeEventListener('pointerdown', handlePointerDown)
  }, [ref, active, onOutsideRef])
}
