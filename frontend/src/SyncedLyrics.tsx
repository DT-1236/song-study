import { Fragment } from 'react'
import type { ComponentProps } from 'react'
import type { LrclibLyrics } from './api'
import { LinePlayButton } from './LinePlayButton'
import { useHighlightSettings } from './useHighlightSettings'

// LRCLIB's lyrics, read-only, as the document page shows its own: a play
// button before each timed line, and the line being sung at `playingLine`
// highlighted. Any other props go on the lyrics box.
export function SyncedLyrics({
  lyrics,
  playingLine,
  onPlayLine,
  ...props
}: {
  lyrics: LrclibLyrics
  playingLine: number | null
  onPlayLine: (start: number) => void
} & ComponentProps<'p'>) {
  const highlight = useHighlightSettings()
  return (
    <p
      {...props}
      className="lyrics-box has-line-play synced-lyrics"
      style={highlight.style}
    >
      {lyrics.text.split('\n').map((line, index) => {
        const start = lyrics.lines?.[index]?.start
        return (
          <Fragment key={index}>
            {index > 0 && '\n'}
            {line.trim() !== '' && start !== undefined && (
              <LinePlayButton start={start} onPlayLine={onPlayLine} />
            )}
            <span className={index === playingLine ? 'token playing' : 'token'}>
              {line}
            </span>
          </Fragment>
        )
      })}
    </p>
  )
}
