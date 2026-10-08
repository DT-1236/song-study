import { memo } from 'react'

// Plays the song from `start`, the start of the line it's placed before.
// Memoized, so the playing line moving doesn't re-render it.
export const LinePlayButton = memo(function LinePlayButton({
  start,
  onPlayLine,
}: {
  start: number
  onPlayLine: (start: number) => void
}) {
  return (
    <button
      type="button"
      className="icon-button line-play"
      aria-label="Play from this line"
      title="Play from this line"
      // Leaves focus where it was, so Space keeps playing and pausing rather
      // than pressing this again.
      onMouseDown={(e) => e.preventDefault()}
      onClick={() => onPlayLine(start)}
    >
      <svg viewBox="0 0 10 10" aria-hidden="true">
        <path d="M2 1 9 5 2 9Z" />
      </svg>
    </button>
  )
})
