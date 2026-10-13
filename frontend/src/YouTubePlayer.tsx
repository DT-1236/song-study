import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import { loadYouTubeIframeApi } from './loadYouTubeIframeApi'
import { useInert } from './useInert'
import { useLatest } from './useLatest'

// Playback time (getCurrentTime/getDuration) and getVideoData() (title,
// channel/"author" name) are all the YouTube IFrame Player API exposes.
// There's no album, and no access to the raw audio signal — the player is a
// cross-origin iframe, so it can't be routed into Web Audio API.
const YT_PLAYING_STATE = 1

// How long after a seek its target stands in for the player's own time,
// should the player never report reaching it.
const SEEK_REPORT_TIMEOUT_MS = 1000
// How far the player's own time may be off a seek's target, once it's
// caught up (a frame's rounding, say).
const SEEK_SLACK_SECONDS = 0.05

export type YouTubePlayerHandle = {
  // Null until the player is ready.
  getCurrentTime: () => number | null
  getDuration: () => number
  getVideoData: () => YT.VideoData | null
  togglePlay: () => void
  pause: () => void
  seekBy: (deltaSeconds: number) => void
  playFrom: (seconds: number) => void
}

type Props = {
  videoId: string
  // Called after each seek made through the handle, so playback-time
  // readers can update at once rather than at their next check.
  onSeek?: () => void
  // Called once the player's methods are usable, for the video it was made for.
  onReady?: () => void
  // Called as the video starts and stops playing.
  onPlayingChange?: (playing: boolean) => void
  // Whether the video shows. Hidden, it plays on as audio: most of these
  // songs' videos are a still of the album cover.
  showVideo?: boolean
}

export const YouTubePlayer = forwardRef<YouTubePlayerHandle, Props>(
  function YouTubePlayer(
    { videoId, onSeek, onReady, onPlayingChange, showVideo = false },
    ref,
  ) {
    const wrapperRef = useRef<HTMLDivElement>(null)
    const containerRef = useRef<HTMLDivElement>(null)
    // Set only once the player is ready, since its methods don't exist before.
    const playerRef = useRef<YT.Player | null>(null)
    // Where the last seek went and when, until the player's own time catches
    // up: it keeps reporting the time from before a seek until the iframe
    // reports back, some 50 ms later.
    const seekRef = useRef<{ seconds: number; at: number } | null>(null)
    // Read when the player becomes ready, which is after the render that
    // made it, so a later render's callback is the one that runs.
    const onReadyRef = useLatest(onReady)
    // Read when the state changes, for the same reason: a callback in the
    // effect's deps would rebuild the player, stopping playback.
    const onPlayingChangeRef = useLatest(onPlayingChange)
    // A hidden video takes no Tab stop and isn't read out.
    useInert(wrapperRef, !showVideo)

    useEffect(() => {
      let cancelled = false
      let player: YT.Player | null = null

      loadYouTubeIframeApi().then((YT) => {
        if (cancelled || !containerRef.current) return
        player = new YT.Player(containerRef.current, {
          videoId,
          width: '100%',
          height: '100%',
          // Plays in the page on an iPhone rather than fullscreen, which a
          // hidden video couldn't be closed from.
          playerVars: { playsinline: 1 },
          events: {
            onReady: (event) => {
              if (cancelled) return
              playerRef.current = event.target
              onReadyRef.current?.()
            },
            onStateChange: (event) => {
              if (cancelled) return
              onPlayingChangeRef.current?.(event.data === YT_PLAYING_STATE)
            },
          },
        })
      })

      return () => {
        cancelled = true
        player?.destroy()
        playerRef.current = null
      }
    }, [videoId, onReadyRef, onPlayingChangeRef])

    useImperativeHandle(ref, () => {
      // The playback time, counting a seek the player hasn't reported yet.
      function currentTime(player: YT.Player): number {
        const time = player.getCurrentTime()
        const seek = seekRef.current
        if (!seek) return time
        const elapsedMs = performance.now() - seek.at
        // Caught up once it's at the target, or as far past it as playback
        // could have gone since: the time from before a seek is short of it
        // (seeking ahead) or further past it (seeking back), however near.
        const caughtUp =
          time >= seek.seconds - SEEK_SLACK_SECONDS &&
          time <= seek.seconds + elapsedMs / 1000 + SEEK_SLACK_SECONDS
        if (!caughtUp && elapsedMs < SEEK_REPORT_TIMEOUT_MS) return seek.seconds
        seekRef.current = null
        return time
      }

      function seekTo(player: YT.Player, seconds: number) {
        player.seekTo(seconds, true)
        seekRef.current = { seconds, at: performance.now() }
        onSeek?.()
      }

      return {
        getCurrentTime: () =>
          playerRef.current ? currentTime(playerRef.current) : null,
        getDuration: () => playerRef.current?.getDuration() ?? 0,
        getVideoData: () => playerRef.current?.getVideoData() ?? null,
        togglePlay: () => {
          const player = playerRef.current
          if (!player) return
          if (player.getPlayerState() === YT_PLAYING_STATE) {
            player.pauseVideo()
          } else {
            player.playVideo()
          }
        },
        pause: () => playerRef.current?.pauseVideo(),
        seekBy: (deltaSeconds) => {
          const player = playerRef.current
          if (!player) return
          // From where the last seek went, so presses in quick succession add up.
          const target = currentTime(player) + deltaSeconds
          const clamped = Math.min(Math.max(target, 0), player.getDuration())
          seekTo(player, clamped)
        },
        playFrom: (seconds) => {
          const player = playerRef.current
          if (!player) return
          seekTo(player, seconds)
          player.playVideo()
        },
      }
    }, [onSeek])

    return (
      <div
        ref={wrapperRef}
        className={showVideo ? 'youtube-player' : 'youtube-player hidden'}
      >
        <div ref={containerRef} />
      </div>
    )
  },
)
