import { forwardRef, useEffect, useState } from 'react'
import type { ReactNode, RefObject } from 'react'
import { usePersistentState } from './usePersistentState'
import { usePlayerShortcuts, useSeekSeconds } from './usePlayerShortcuts'
import type { PlayerShortcut } from './usePlayerShortcuts'
import { YouTubePlayer } from './YouTubePlayer'
import type { YouTubePlayerHandle } from './YouTubePlayer'

// How long a button looks pressed after its key is.
const PRESS_MS = 150

type Props = {
  playerRef: RefObject<YouTubePlayerHandle>
  videoId: string
  onSeek?: () => void
}

// The song's player, docked to the bottom of the screen: its video, hidden
// unless shown, and a button for each of the player's keys (Space, , and .),
// which looks pressed when its key is.
export const PlayerBar = forwardRef<HTMLDivElement, Props>(function PlayerBar(
  { playerRef, videoId, onSeek },
  ref,
) {
  const [seekSeconds] = useSeekSeconds()
  // Shared by every page, and hidden until it's asked for: most of these
  // songs are found through YouTube Music, whose videos are just the cover.
  const [showVideo, setShowVideo] = usePersistentState('showVideo', false)
  const [playing, setPlaying] = useState(false)
  // The video the player last became ready for: its buttons do nothing
  // before then.
  const [readyVideoId, setReadyVideoId] = useState<string | null>(null)
  const ready = readyVideoId === videoId
  // The key last pressed: an object, so pressing it again restarts the press.
  const [pressed, setPressed] = useState<{ shortcut: PlayerShortcut } | null>(
    null,
  )

  usePlayerShortcuts(playerRef, seekSeconds, (shortcut) =>
    setPressed({ shortcut }),
  )

  useEffect(() => {
    if (!pressed) return
    const timeout = window.setTimeout(() => setPressed(null), PRESS_MS)
    return () => window.clearTimeout(timeout)
  }, [pressed])

  const isPressed = (shortcut: PlayerShortcut) => pressed?.shortcut === shortcut

  return (
    <div ref={ref} className="player-bar">
      <YouTubePlayer
        ref={playerRef}
        videoId={videoId}
        onSeek={onSeek}
        onReady={() => setReadyVideoId(videoId)}
        onPlayingChange={setPlaying}
        showVideo={showVideo}
      />
      <div className="player-controls">
        <KeyButton
          label={`Back ${seekSeconds}s`}
          disabled={!ready}
          keyName=","
          pressed={isPressed('back')}
          onClick={() => playerRef.current?.seekBy(-seekSeconds)}
        >
          −{seekSeconds}s
        </KeyButton>
        <KeyButton
          label={playing ? 'Pause' : 'Play'}
          disabled={!ready}
          keyName="Space"
          pressed={isPressed('play')}
          onClick={() => playerRef.current?.togglePlay()}
        >
          <svg viewBox="0 0 10 10" aria-hidden="true">
            <path
              d={playing ? 'M2 1h2.5v8H2ZM5.5 1H8v8H5.5Z' : 'M2 1 9 5 2 9Z'}
            />
          </svg>
        </KeyButton>
        <KeyButton
          label={`Forward ${seekSeconds}s`}
          disabled={!ready}
          keyName="."
          pressed={isPressed('forward')}
          onClick={() => playerRef.current?.seekBy(seekSeconds)}
        >
          +{seekSeconds}s
        </KeyButton>
        <button
          type="button"
          className="player-video-toggle"
          aria-pressed={showVideo}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => setShowVideo(!showVideo)}
        >
          Video
        </button>
      </div>
    </div>
  )
})

// A button doing what the key `keyName` does, showing that key.
function KeyButton({
  label,
  keyName,
  pressed,
  disabled,
  onClick,
  children,
}: {
  label: string
  keyName: string
  pressed: boolean
  disabled: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      className={pressed ? 'pressed' : undefined}
      aria-label={label}
      title={`${label} (${keyName})`}
      disabled={disabled}
      // Leaves focus where it was, so Space keeps playing and pausing rather
      // than pressing this again.
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
    >
      {children}
      <kbd>{keyName}</kbd>
    </button>
  )
}
