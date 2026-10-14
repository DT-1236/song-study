import { usePersistentState } from './usePersistentState'

// Whether the line being sung is kept on screen, as set by the player bar's
// Auto-scroll toggle. One setting for every page that has the toggle.
export function useAutoScroll() {
  return usePersistentState('autoScroll', true)
}
