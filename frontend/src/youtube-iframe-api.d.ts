export {}

// Minimal surface of the YouTube IFrame Player API that this app actually
// uses. The real API is much larger; see
// https://developers.google.com/youtube/iframe_api_reference
declare global {
  interface Window {
    YT?: typeof YT
    onYouTubeIframeAPIReady?: () => void
  }

  namespace YT {
    class Player {
      constructor(element: HTMLElement, options: PlayerOptions)
      getCurrentTime(): number
      getDuration(): number
      getVideoData(): VideoData
      playVideo(): void
      pauseVideo(): void
      seekTo(seconds: number, allowSeekAhead: boolean): void
      // 1 = playing, 2 = paused, among others — see PlayerState in the real
      // API reference. Only "is it currently playing" is needed here, so
      // the full enum isn't declared.
      getPlayerState(): number
      destroy(): void
    }

    interface PlayerOptions {
      videoId: string
      width?: string | number
      height?: string | number
      playerVars?: { playsinline?: 0 | 1 }
      events?: {
        onReady?: (event: { target: Player }) => void
        // `data` is the new state, as getPlayerState() would return it.
        onStateChange?: (event: { target: Player; data: number }) => void
      }
    }

    interface VideoData {
      video_id: string
      title: string
      author: string
    }
  }
}
