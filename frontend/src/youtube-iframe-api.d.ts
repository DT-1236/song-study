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
      destroy(): void
    }

    interface PlayerOptions {
      videoId: string
      width?: string | number
      height?: string | number
      events?: {
        onReady?: (event: { target: Player }) => void
      }
    }

    interface VideoData {
      video_id: string
      title: string
      author: string
    }
  }
}
