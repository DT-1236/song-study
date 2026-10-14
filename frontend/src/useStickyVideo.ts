import { usePersistentState } from './usePersistentState'

// Whether the video stays docked with the player bar's buttons, rather than
// sitting after the page's content. Off until asked for.
export function useStickyVideo() {
  return usePersistentState('stickyVideo', false)
}
