import { useState } from 'react'
import type { ButtonHTMLAttributes, ReactNode, RefObject } from 'react'
import { PlayIcon } from './LinePlayButton'
import { useHeightProperty } from './useHeightProperty'
import { usePlayerShortcuts, useSeekSeconds } from './usePlayerShortcuts'
import type { PlayerShortcut } from './usePlayerShortcuts'
import { useTransient } from './useTransient'
import { useStickyVideo } from './useStickyVideo'
import { YouTubePlayer } from './YouTubePlayer'
import type { YouTubePlayerHandle } from './YouTubePlayer'

// How long a button looks pressed after its key is.
export const PRESS_MS = 150

// The song's player: its video, shown after the page's content or docked to
// the bottom of the screen with the buttons if the sticky video setting is
// on, and a button for each of the player's keys (Space, , and .),
// which looks pressed when its key is. Those move the playhead and nothing
// else, so the page's own buttons, which edit, sit in a row apart from them.
export function PlayerBar({
  playerRef,
  videoId,
  onSeek,
  toggles,
  children,
}: {
  playerRef: RefObject<YouTubePlayerHandle>
  videoId: string
  onSeek?: () => void
  // Toggles for the page's behavior, before the Video toggle.
  toggles?: ReactNode
  // The page's own buttons, in a row of their own after the playback ones.
  children?: ReactNode
}) {
  const [seekSeconds] = useSeekSeconds()
  const [stickyVideo, setStickyVideo] = useStickyVideo()
  const [playing, setPlaying] = useState(false)
  // Its buttons do nothing until the player is ready.
  const [ready, setReady] = useState(false)
  const [pressed, press] = useTransient<PlayerShortcut>(PRESS_MS)

  usePlayerShortcuts(playerRef, seekSeconds, press)

  // Set on the scroll container, which the page's scroll padding and toast
  // read, so what's scrolled into view stops above what's docked: the whole
  // bar, or just its buttons when the video isn't sticky.
  const [bar, setBar] = useState<HTMLDivElement | null>(null)
  const [controls, setControls] = useState<HTMLDivElement | null>(null)
  useHeightProperty(stickyVideo ? bar : controls, '--player-bar-height')

  return (
    <div
      ref={setBar}
      className={stickyVideo ? 'player-bar sticky' : 'player-bar'}
    >
      <YouTubePlayer
        ref={playerRef}
        videoId={videoId}
        onSeek={onSeek}
        onReadyChange={setReady}
        onPlayingChange={setPlaying}
        showVideo
      />
      <div
        ref={setControls}
        className={children ? 'player-controls has-extra' : 'player-controls'}
      >
        <div className="player-transport">
          <KeyButton
            className="seek-button"
            label={`Back ${seekSeconds}s`}
            keyName=","
            pressed={pressed === 'back'}
            disabled={!ready}
            onClick={() => playerRef.current?.seekBy(-seekSeconds)}
          >
            ‹‹ {seekSeconds}s
          </KeyButton>
          <KeyButton
            className="seek-button"
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
            className="seek-button"
            label={`Forward ${seekSeconds}s`}
            keyName="."
            pressed={pressed === 'forward'}
            disabled={!ready}
            onClick={() => playerRef.current?.seekBy(seekSeconds)}
          >
            {seekSeconds}s ››
          </KeyButton>
          {toggles}
          <BarButton
            className="player-video-toggle"
            aria-pressed={stickyVideo}
            onClick={() => setStickyVideo(!stickyVideo)}
          >
            Video
          </BarButton>
        </div>
        {children}
      </div>
    </div>
  )
}

// Switches whether the line being sung is kept on screen.
export function AutoScrollToggle({
  autoScroll,
  onChange,
}: {
  autoScroll: boolean
  onChange: (autoScroll: boolean) => void
}) {
  return (
    <BarButton
      className="player-autoscroll-toggle"
      aria-pressed={autoScroll}
      title="Keep the line being sung on screen"
      onClick={() => onChange(!autoScroll)}
    >
      Auto-scroll
    </BarButton>
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
export function KeyButton({
  label,
  keyName,
  pressed,
  children,
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string
  keyName: string
  pressed: boolean
}) {
  return (
    <BarButton
      className={
        [className, pressed && 'pressed'].filter(Boolean).join(' ') || undefined
      }
      aria-label={label}
      title={`${label} (${keyName})`}
      {...props}
    >
      {children}
      <kbd>{keyName}</kbd>
    </BarButton>
  )
}
