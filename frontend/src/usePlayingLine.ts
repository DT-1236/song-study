import { useEffect, useState } from 'react'
import type { RefObject } from 'react'
import type { LineTiming } from './api'
import { lastStartedBy } from './timing'
import type { YouTubePlayerHandle } from './YouTubePlayer'

// The IFrame API has no time-update event, so playback is followed by
// polling its current time.
const PLAYBACK_POLL_MS = 100

// The index of the line in `timings` (null for an untimed line) being sung
// at the player's current time, or null between lines, before any, or while
// `timings` is null. `seeks` should change on each seek, and on any other
// change the highlight should follow at once rather than at the next check.
export function usePlayingLine(
  playerRef: RefObject<YouTubePlayerHandle | null>,
  timings: (LineTiming | null)[] | null,
  seeks: number,
): number | null {
  const [playingLine, setPlayingLine] = useState<number | null>(null)

  useEffect(() => {
    if (!timings) return
    // The line last found, which the next search starts from. A seek or new
    // timings re-run this effect, which starts the search over.
    let found = -1
    const update = () => {
      const time = playerRef.current?.getCurrentTime() ?? null
      if (time === null) return setPlayingLine(null)
      found = lastStartedBy(timings, time, found)
      const line = timings[found]
      // An index, so React skips the re-render while the line is unchanged.
      setPlayingLine(line && time < line.end ? found : null)
    }
    // Right away as well, so a seek or a nudge moves the highlight at once
    // rather than at the next poll.
    update()
    const interval = window.setInterval(update, PLAYBACK_POLL_MS)
    return () => {
      window.clearInterval(interval)
      // Whatever lines come next, this index isn't into them.
      setPlayingLine(null)
    }
  }, [playerRef, timings, seeks])

  return playingLine
}
