import { Fragment } from 'react'
import type { ComponentProps } from 'react'
import type { LineTiming } from './api'
import { LinePlayButton } from './LinePlayButton'
import { useHighlightSettings } from './useHighlightSettings'

// Lyrics without tokens (LRCLIB's, or a document's own before it's
// processed), read-only, as the document page shows tokenized ones: a play
// button before each timed line, and the line being sung at `playingLine`
// highlighted. `id` and `aria-labelledby` go on the lyrics box.
export function SyncedLyrics({
  lyrics,
  playingLine,
  onPlayLine,
  ...props
}: {
  // A document's own timings can leave a line untimed (null).
  lyrics: { text: string; lines: (LineTiming | null)[] | null }
  playingLine: number | null
  onPlayLine: (start: number) => void
} & Pick<ComponentProps<'p'>, 'id' | 'aria-labelledby'>) {
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
