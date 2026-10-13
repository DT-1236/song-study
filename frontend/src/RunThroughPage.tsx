import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchRunThrough } from './api'
import type { RunLine, RunThrough } from './api'
import { codePointSlice, optionText, wordLabel } from './cardText'
import { useApiResource } from './useApiResource'
import { useLineEndPolling } from './useLineEndPolling'
import { YouTubePlayer } from './YouTubePlayer'
import type { YouTubePlayerHandle } from './YouTubePlayer'

// A gap before the next line longer than this is skipped rather than played.
const SKIPPED_GAP_SECONDS = 0.5

type Status = 'idle' | 'playing' | 'paused' | 'done'

// The line with each of its weak words marked.
function LineText({ line }: { line: RunLine }) {
  const parts = []
  let at = 0
  // In order of position, which isn't the weakest-first order they come in.
  const words = [...line.weak].sort((a, b) => a.focus[0] - b.focus[0])
  for (const word of words) {
    const [begin, end] = word.focus
    if (begin < at) continue
    parts.push(codePointSlice(line.text, at, begin))
    parts.push(
      <mark key={`${word.card_id}-${begin}`}>
        {codePointSlice(line.text, begin, end)}
      </mark>,
    )
    at = end
  }
  parts.push(codePointSlice(line.text, at))
  return <>{parts}</>
}

function WeakWords({ line }: { line: RunLine }) {
  return (
    <ul className="run-weak">
      {line.weak.map((word) => (
        <li key={`${word.card_id}-${word.focus[0]}`}>
          <strong>{wordLabel(word.lookup_form, word.reading)}</strong>{' '}
          {word.meaning ? `— ${optionText(word.meaning)}` : ''}{' '}
          <span className="run-recall">
            {Math.round(word.retrievability * 100)}% recalled
          </span>
        </li>
      ))}
    </ul>
  )
}

function RunThroughPlayer({
  run,
  documentId,
}: {
  run: RunThrough
  documentId: number
}) {
  const playable = useMemo(
    () => run.lines.filter((line) => line.audio !== null),
    [run],
  )
  const pauses = playable.filter((line) => line.weak.length > 0).length
  const videoId = run.youtube_video_id

  const playerRef = useRef<YouTubePlayerHandle>(null)
  const [ready, setReady] = useState(false)
  const [status, setStatus] = useState<Status>('idle')
  // Which of the playable lines is being played, or was last.
  const [position, setPosition] = useState(0)
  const line = playable[position] ?? null

  const playLine = useCallback(
    (at: number) => {
      const audio = playable[at].audio
      if (!audio) return
      setPosition(at)
      setStatus('playing')
      playerRef.current?.playFrom(audio.start)
    },
    [playable],
  )

  // Moves on from the line `position` once it has ended: to the next, or to
  // the end of the song.
  const next = useCallback(
    (time: number) => {
      const following = playable[position + 1]
      if (!following?.audio) {
        playerRef.current?.pause()
        setStatus('done')
      } else if (following.audio.start - time > SKIPPED_GAP_SECONDS) {
        playLine(position + 1)
      } else {
        setPosition(position + 1)
      }
    },
    [playable, position, playLine],
  )

  useLineEndPolling(
    playerRef,
    status === 'playing' && line?.audio ? line.audio.end : null,
    (time) => {
      if (line && line.weak.length > 0) {
        playerRef.current?.pause()
        setStatus('paused')
      } else {
        next(time)
      }
    },
  )

  useEffect(() => {
    function handleKey(event: KeyboardEvent) {
      if (event.ctrlKey || event.metaKey || event.altKey) return
      if (status !== 'paused' || !line?.audio) return
      if (event.key === 'Enter') next(line.audio.end)
      else if (event.key === 'r') playLine(position)
      else return
      event.preventDefault()
    }

    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  })

  if (!videoId || playable.length === 0) {
    return (
      <p>
        This song needs a YouTube video and line timings to be run through. Link
        them on <Link to={`/documents/${documentId}`}>the song's page</Link>.
      </p>
    )
  }

  return (
    <div className="run-through">
      <p>
        Plays the song from start to finish and pauses after the{' '}
        {pauses === 1 ? 'line' : `${pauses} lines`} with a word you're
        forgetting. It's practice: nothing is rated or rescheduled.
      </p>

      <div className="study-toolbar">
        {status === 'idle' && (
          <button type="button" disabled={!ready} onClick={() => playLine(0)}>
            ▸ Start
          </button>
        )}
        {status === 'done' && (
          <button type="button" onClick={() => playLine(0)}>
            ▸ Again
          </button>
        )}
        {status === 'paused' && (
          <>
            <button
              type="button"
              onClick={() => line?.audio && next(line.audio.end)}
            >
              Continue (⏎)
            </button>
            <button type="button" onClick={() => playLine(position)}>
              ▸ Replay line (r)
            </button>
          </>
        )}
      </div>

      {status === 'paused' && line && (
        <div className="run-pause">
          <p className="study-line">
            <LineText line={line} />
          </p>
          <WeakWords line={line} />
        </div>
      )}

      {status === 'done' && (
        <p>
          That's the song.{' '}
          <Link to={`/documents/${documentId}/study`}>Study it</Link>
          {' · '}
          <Link to={`/documents/${documentId}`}>Back to the song</Link>
        </p>
      )}

      <ol className="run-lines">
        {run.lines.map((l) => (
          <li
            key={l.index}
            className={[
              l.weak.length > 0 && 'run-line-weak',
              status !== 'idle' && line?.index === l.index && 'run-line-now',
            ]
              .filter(Boolean)
              .join(' ')}
          >
            <LineText line={l} />
          </li>
        ))}
      </ol>

      {/* Hidden: the lines above follow the song. */}
      <YouTubePlayer
        ref={playerRef}
        videoId={videoId}
        onReady={() => setReady(true)}
      />
    </div>
  )
}

// A song played through at /documents/:id/run-through, pausing on the lines
// with words the user is forgetting.
export function RunThroughPage() {
  const { id } = useParams()
  const documentId = Number(id)

  const fetchRun = useCallback(() => fetchRunThrough(documentId), [documentId])
  const { data, loading, error } = useApiResource(
    fetchRun,
    [documentId],
    'Failed to load the run-through.',
  )

  return (
    <div className="study-page">
      <h1>Run through the song</h1>
      {loading && <p>Loading…</p>}
      {error && <p className="form-error">{error}</p>}
      {!loading && data && (
        <RunThroughPlayer key={documentId} run={data} documentId={documentId} />
      )}
    </div>
  )
}
