import { useEffect } from 'react'
import type { RefObject } from 'react'
import { usePersistentState } from './usePersistentState'

// Whether the line being sung is kept on screen, as set by the player bar's
// Auto-scroll toggle. One setting for every page that has the toggle.
export function useAutoScroll() {
  return usePersistentState('autoScroll', true)
}

// Scrolls the line being sung, `playingLine`, back on screen inside `boxRef`
// when it moves off it, as little as possible, while `autoScroll` is on.
export function useScrollPlayingIntoView(
  boxRef: RefObject<HTMLElement | null>,
  playingLine: number | null,
  autoScroll: boolean,
) {
  useEffect(() => {
    if (!autoScroll) return
    // The first element marked playing: where the line starts, even when it
    // wraps or is split into tokens.
    boxRef.current
      ?.querySelector('.playing')
      ?.scrollIntoView({ block: 'nearest' })
  }, [boxRef, playingLine, autoScroll])
}
