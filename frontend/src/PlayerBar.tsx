import { useRef, useState } from 'react'
import type { ButtonHTMLAttributes, RefObject } from 'react'
import { PlayIcon } from './LinePlayButton'
import { useHeightProperty } from './useHeightProperty'
import { usePersistentState } from './usePersistentState'
import { usePlayerShortcuts, useSeekSeconds } from './usePlayerShortcuts'
import type { PlayerShortcut } from './usePlayerShortcuts'
import { useTransient } from './useTransient'
import { YouTubePlayer } from './YouTubePlayer'
import type { YouTubePlayerHandle } from './YouTubePlayer'

// How long a button looks pressed after its key is.
const PRESS_MS = 150

// The song's player, docked to the bottom of the screen: its video, hidden
// unless shown, and a button for each of the player's keys (Space, , and .),
// which looks pressed when its key is.
export function PlayerBar({
  playerRef,
  videoId,
  onSeek,
}: {
  playerRef: RefObject<YouTubePlayerHandle>
  videoId: string
  onSeek?: () => void
}) {
  const [seekSeconds] = useSeekSeconds()
  // Shared by every page, and hidden until it's asked for: most of these
  // songs are found through YouTube Music, whose videos are just the cover.
  const [showVideo, setShowVideo] = usePersistentState('showVideo', false)
  const [playing, setPlaying] = useState(false)
  // Its buttons do nothing until the player is ready.
  const [ready, setReady] = useState(false)
  const [pressed, press] = useTransient<PlayerShortcut>(PRESS_MS)

  usePlayerShortcuts(playerRef, seekSeconds, press)

  // Set on the scroll container, which the page's scroll padding and toast
  // read, so what's scrolled into view stops above the bar.
  const barRef = useRef<HTMLDivElement>(null)
  useHeightProperty(barRef, '--player-bar-height')

  return (
    <div ref={barRef} className="player-bar">
      <YouTubePlayer
        ref={playerRef}
        videoId={videoId}
        onSeek={onSeek}
        onReadyChange={setReady}
        onPlayingChange={setPlaying}
        showVideo={showVideo}
      />
      <div className="player-controls">
        <KeyButton
          label={`Back ${seekSeconds}s`}
          keyName=","
          pressed={pressed === 'back'}
          disabled={!ready}
          onClick={() => playerRef.current?.seekBy(-seekSeconds)}
        >
          −{seekSeconds}s
        </KeyButton>
        <KeyButton
          label={playing ? 'Pause' : 'Play'}
          keyName="Space"
          pressed={pressed === 'play'}
          disabled={!ready}
          onClick={() => playerRef.current?.togglePlay()}
        >
          {playing ? (
            <svg viewBox="0 0 10 10" aria-hidden="true">
              <path d="M2 1h2.5v8H2ZM5.5 1H8v8H5.5Z" />
            </svg>
          ) : (
            <PlayIcon />
          )}
        </KeyButton>
        <KeyButton
          label={`Forward ${seekSeconds}s`}
          keyName="."
          pressed={pressed === 'forward'}
          disabled={!ready}
          onClick={() => playerRef.current?.seekBy(seekSeconds)}
        >
          +{seekSeconds}s
        </KeyButton>
        <BarButton
          className="player-video-toggle"
          aria-pressed={showVideo}
          onClick={() => setShowVideo(!showVideo)}
        >
          Video
        </BarButton>
      </div>
    </div>
  )
}

// A button in the bar.
function BarButton(props: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      // Leaves focus where it was, so Space keeps playing and pausing rather
      // than pressing this again.
      onMouseDown={(e) => e.preventDefault()}
      {...props}
    />
  )
}

// A button doing what the key `keyName` does, showing that key.
function KeyButton({
  label,
  keyName,
  pressed,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string
  keyName: string
  pressed: boolean
}) {
  return (
    <BarButton
      className={pressed ? 'pressed' : undefined}
      aria-label={label}
      title={`${label} (${keyName})`}
      {...props}
    >
      {children}
      <kbd>{keyName}</kbd>
    </BarButton>
  )
}
