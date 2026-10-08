import { useEffect } from 'react'
import type { RefObject } from 'react'
import { usePersistentState } from './usePersistentState'
import type { YouTubePlayerHandle } from './YouTubePlayer'

// Elements where a focused Space already activates the control natively
// (typing targets are handled separately, in isTypingTarget) — the global
// play/pause listener must not override this.
const SPACE_HANDLED_NATIVELY = new Set(['BUTTON', 'SELECT', 'A'])

// Whether keys pressed while `element` has focus type into it.
export function isTypingTarget(element: Element | null): boolean {
  return (
    element instanceof HTMLElement &&
    (element.tagName === 'INPUT' ||
      element.tagName === 'TEXTAREA' ||
      element.isContentEditable)
  )
}

// How far , and . seek, in seconds: the same on every page, and kept across
// reloads.
export function useSeekSeconds() {
  return usePersistentState('seekSeconds', 3)
}

// Spacebar play/pause and ,/. seek by `seekSeconds` on the player at
// `playerRef`, same as YouTube's own page — but only when focus isn't on
// something these keys already have a native meaning for: typing (a
// textarea, an input) for all three, or activating a focused button/link for
// Space specifically, which would otherwise get silently overridden.
export function usePlayerShortcuts(
  playerRef: RefObject<YouTubePlayerHandle | null>,
  seekSeconds: number,
) {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const active = document.activeElement

      if (event.code === 'Space') {
        const isNativeSpaceTarget =
          active instanceof HTMLElement &&
          SPACE_HANDLED_NATIVELY.has(active.tagName)
        if (isNativeSpaceTarget || isTypingTarget(active)) return
        event.preventDefault()
        playerRef.current?.togglePlay()
        return
      }

      if (event.code === 'Comma' || event.code === 'Period') {
        if (isTypingTarget(active)) return
        event.preventDefault()
        playerRef.current?.seekBy(
          event.code === 'Comma' ? -seekSeconds : seekSeconds,
        )
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [playerRef, seekSeconds])
}
