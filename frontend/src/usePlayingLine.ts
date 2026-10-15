import { useCallback, useEffect, useState } from 'react'
import type { RefObject } from 'react'
import type { LineTiming } from './api'
import { lastStartedBy } from './timing'
import type { YouTubePlayerHandle } from './YouTubePlayer'

// The IFrame API has no time-update event, so playback is followed by
// polling its current time.
const PLAYBACK_POLL_MS = 100

// `playingLine`, the index of the line in `timings` (null for an untimed
// line) being sung at the player's current time, or null between lines,
// before any, or while `timings` is null; and `onSeek`, for the player to
// call on each seek so the highlight follows it at once rather than at the
// next check; and `playing`, whether the video is playing, as of the same
// check.
export function usePlayingLine(
  playerRef: RefObject<YouTubePlayerHandle | null>,
  timings: (LineTiming | null)[] | null,
) {
  const [playingLine, setPlayingLine] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)
  // Counts the player's seeks: the effect below depends on it, so a seek
  // re-runs it at once, after any other state the same keypress changed (a
  // nudge's new timings).
  const [seeks, setSeeks] = useState(0)
  const onSeek = useCallback(() => setSeeks((count) => count + 1), [])

  useEffect(() => {
    if (!timings) return
    // The line last found, which the next search starts from. A seek or new
    // timings re-run this effect, which starts the search over.
    let found = -1
    const update = () => {
      setPlaying(playerRef.current?.isPlaying() ?? false)
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
      setPlaying(false)
    }
  }, [playerRef, timings, seeks])

  return { playingLine, playing, onSeek }
}
