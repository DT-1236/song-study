import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import { loadYouTubeIframeApi } from './loadYouTubeIframeApi'

// Playback time (getCurrentTime/getDuration) and getVideoData() (title,
// channel/"author" name) are all the YouTube IFrame Player API exposes.
// There's no album, and no access to the raw audio signal — the player is a
// cross-origin iframe, so it can't be routed into Web Audio API.
const YT_PLAYING_STATE = 1

export type YouTubePlayerHandle = {
  getCurrentTime: () => number
  getDuration: () => number
  getVideoData: () => YT.VideoData | null
  togglePlay: () => void
  seekBy: (deltaSeconds: number) => void
}

type Props = {
  videoId: string
}

export const YouTubePlayer = forwardRef<YouTubePlayerHandle, Props>(function YouTubePlayer(
  { videoId },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null)
  const playerRef = useRef<YT.Player | null>(null)

  useEffect(() => {
    let cancelled = false

    loadYouTubeIframeApi().then((YT) => {
      if (cancelled || !containerRef.current) return
      playerRef.current = new YT.Player(containerRef.current, {
        videoId,
        width: '100%',
        height: '100%',
      })
    })

    return () => {
      cancelled = true
      playerRef.current?.destroy()
      playerRef.current = null
    }
  }, [videoId])

  useImperativeHandle(ref, () => ({
    getCurrentTime: () => playerRef.current?.getCurrentTime() ?? 0,
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
    seekBy: (deltaSeconds) => {
      const player = playerRef.current
      if (!player) return
      const target = player.getCurrentTime() + deltaSeconds
      const clamped = Math.min(Math.max(target, 0), player.getDuration())
      player.seekTo(clamped, true)
    },
  }), [])

  return (
    <div className="youtube-player">
      <div ref={containerRef} />
    </div>
  )
})
