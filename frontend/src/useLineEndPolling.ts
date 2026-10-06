import { useEffect, useRef } from 'react'
import type { RefObject } from 'react'
import type { YouTubePlayerHandle } from './YouTubePlayer'

// How often to check whether the playing line has reached its end.
const LINE_END_POLL_MS = 100

// Calls `onEnd` with the playback time on each check once the player has
// reached `end` seconds, for as long as `end` isn't null.
export function useLineEndPolling(
  playerRef: RefObject<YouTubePlayerHandle | null>,
  end: number | null,
  onEnd: (time: number) => void,
) {
  // Read when a check fires, so a new callback doesn't restart the polling.
  const onEndRef = useRef(onEnd)
  useEffect(() => {
    onEndRef.current = onEnd
  }, [onEnd])

  useEffect(() => {
    if (end === null) return
    const timer = window.setInterval(() => {
      const time = playerRef.current?.getCurrentTime()
      if (time != null && time >= end) onEndRef.current(time)
    }, LINE_END_POLL_MS)
    return () => window.clearInterval(timer)
  }, [playerRef, end])
}
