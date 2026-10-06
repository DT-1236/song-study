import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  errorMessage,
  fetchAllSongsQueue,
  fetchDocumentReadiness,
  pushOutCard,
  reviewCard,
  startSongSession,
  suspendCard,
} from './api'
import type { PushOutMonths, StudyQueue } from './api'
import { KanjiSidebar } from './KanjiSidebar'
import { ReadinessMeter } from './ReadinessMeter'
import { StudyCardView } from './StudyCardView'
import { useApiResource } from './useApiResource'
import { useLineEndPolling } from './useLineEndPolling'
import { usePersistentState } from './usePersistentState'
import { YouTubePlayer } from './YouTubePlayer'
import type { YouTubePlayerHandle } from './YouTubePlayer'

// The push-out ladder, by the key that picks each step.
const PUSH_OUT_KEYS: Record<string, PushOutMonths> = { '1': 1, '2': 3, '3': 6 }

type Tally = {
  answered: number
  correct: number
  pushedOut: number
  removed: number
  // The soonest a card answered this session comes up again, an ISO time.
  nextDue: string | null
}

const EMPTY_TALLY: Tally = {
  answered: 0,
  correct: 0,
  pushedOut: 0,
  removed: 0,
  nextDue: null,
}

// The song's readiness, fetched once the session that changed it is over.
function SummaryReadiness({ documentId }: { documentId: number }) {
  const { data, error } = useApiResource(
    () => fetchDocumentReadiness(documentId),
    [documentId],
    'Failed to load readiness.',
  )
  if (error) return <li className="form-error">{error}</li>
  if (!data) return null
  return (
    <li>
      Readiness: <ReadinessMeter readiness={data} />
    </li>
  )
}

function Summary({
  tally,
  documentId,
}: {
  tally: Tally
  documentId: number | null
}) {
  const accuracy =
    tally.answered === 0
      ? null
      : Math.round((tally.correct / tally.answered) * 100)

  return (
    <div className="study-summary">
      <h2>Session complete</h2>
      <ul>
        <li>Reviewed: {tally.answered}</li>
        {accuracy !== null && <li>Accuracy: {accuracy}%</li>}
        {tally.pushedOut > 0 && <li>Pushed out: {tally.pushedOut}</li>}
        {tally.removed > 0 && <li>Removed: {tally.removed}</li>}
        {tally.nextDue && (
          <li>Next due: {new Date(tally.nextDue).toLocaleString()}</li>
        )}
        {documentId !== null && <SummaryReadiness documentId={documentId} />}
      </ul>
      <p>
        {documentId !== null && (
          <Link to={`/documents/${documentId}`}>Back to the song</Link>
        )}
        {documentId !== null && ' · '}
        <Link to="/documents">Existing documents</Link>
      </p>
    </div>
  )
}

function StudySession({
  queue,
  documentId,
}: {
  queue: StudyQueue
  documentId: number | null
}) {
  // A word with no dictionary entry any more has nothing to ask.
  const [cards] = useState(() =>
    queue.cards.filter((c) => c.answer !== null && c.options.length > 0),
  )
  const [index, setIndex] = useState(0)
  const [picked, setPicked] = useState<number | null>(null)
  const [laddering, setLaddering] = useState(false)
  const [tally, setTally] = useState(EMPTY_TALLY)
  const [error, setError] = useState<string | null>(null)
  const shownAt = useRef(performance.now())

  const [muted, setMuted] = usePersistentState('study-muted', false)
  const playerRef = useRef<YouTubePlayerHandle>(null)
  // The video the player was made for, kept through cards with no audio so
  // that it isn't reloaded for the next one.
  const [videoId, setVideoId] = useState<string | null>(null)
  const [readyVideoId, setReadyVideoId] = useState<string | null>(null)
  // Bumped to play the line again.
  const [replays, setReplays] = useState(0)

  const card = cards[index] ?? null
  const audio = card?.line?.audio ?? null

  useEffect(() => {
    if (audio && audio.youtube_video_id !== videoId) {
      setVideoId(audio.youtube_video_id)
      setReadyVideoId(null)
    }
  }, [audio, videoId])

  // The card's line, while it's unmuted and the player has its video.
  const playing =
    audio && !muted && readyVideoId === audio.youtube_video_id ? audio : null

  // Plays the line from its start to its end, and stops it if the card goes
  // first.
  useEffect(() => {
    if (!playing) return
    const player = playerRef.current
    if (!player) return
    player.playFrom(playing.start)
    return () => player.pause()
  }, [playing, replays])

  useLineEndPolling(playerRef, playing?.end ?? null, () =>
    playerRef.current?.pause(),
  )

  function advance() {
    setIndex((i) => i + 1)
    setPicked(null)
    setLaddering(false)
    setError(null)
    shownAt.current = performance.now()
  }

  function pick(option: number) {
    if (!card || picked !== null) return
    const correct = option === card.answer
    const durationMs = Math.round(performance.now() - shownAt.current)
    setPicked(option)
    setTally((t) => ({
      ...t,
      answered: t.answered + 1,
      correct: t.correct + (correct ? 1 : 0),
    }))
    reviewCard(card.id, {
      correct,
      durationMs,
      documentId: card.line?.document_id ?? null,
    })
      .then(({ card: scheduled }) =>
        setTally((t) => ({
          ...t,
          nextDue:
            t.nextDue === null || scheduled.due < t.nextDue
              ? scheduled.due
              : t.nextDue,
        })),
      )
      .catch((err) =>
        setError(errorMessage(err, 'Failed to save your answer.')),
      )
  }

  // Takes the card out of today's queue without rating it, then moves on.
  function leave(
    request: Promise<unknown>,
    counted: 'pushedOut' | 'removed',
    failure: string,
  ) {
    request
      .then(() => {
        setTally((t) => ({ ...t, [counted]: t[counted] + 1 }))
        advance()
      })
      .catch((err) => setError(errorMessage(err, failure)))
  }

  function pushOut(months: PushOutMonths) {
    if (card)
      leave(pushOutCard(card.id, months), 'pushedOut', 'Failed to push it out.')
  }

  function remove() {
    if (card) leave(suspendCard(card.id), 'removed', 'Failed to remove it.')
  }

  useEffect(() => {
    function handleKey(event: KeyboardEvent) {
      if (event.ctrlKey || event.metaKey || event.altKey) return
      const target = event.target
      if (
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement
      )
        return
      if (!card) return

      if (laddering) {
        if (event.key in PUSH_OUT_KEYS) pushOut(PUSH_OUT_KEYS[event.key])
        else if (event.key === 'Escape') setLaddering(false)
        else return
      } else if (event.key === '!') {
        setLaddering(true)
      } else if (event.key === '-') {
        remove()
      } else if (event.key === ' ') {
        setReplays((n) => n + 1)
      } else if (event.key === 'Enter' && picked !== null) {
        advance()
      } else if (picked === null && /^[1-9]$/.test(event.key)) {
        const option = Number(event.key) - 1
        if (option >= card.options.length) return
        pick(option)
      } else {
        return
      }
      event.preventDefault()
    }

    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  })

  if (!card) {
    if (cards.length === 0) {
      return <p>Nothing is due right now.</p>
    }
    return <Summary tally={tally} documentId={documentId} />
  }

  return (
    <div className="study-session">
      <div className="study-toolbar">
        <span>
          {index + 1} / {cards.length}
        </span>
        <button
          type="button"
          onClick={() => setMuted(!muted)}
          aria-pressed={muted}
        >
          {muted ? 'Unmute' : 'Mute'}
        </button>
        {audio && (
          <button
            type="button"
            disabled={muted}
            onClick={() => setReplays((n) => n + 1)}
          >
            ▸ Replay (space)
          </button>
        )}
        <button type="button" onClick={() => setLaddering(true)}>
          I know this (!)
        </button>
        <button type="button" onClick={remove}>
          Remove (-)
        </button>
      </div>

      {laddering && (
        <div className="study-ladder" role="group" aria-label="Push out">
          Push it out:
          {Object.entries(PUSH_OUT_KEYS).map(([key, months]) => (
            <button key={key} type="button" onClick={() => pushOut(months)}>
              <kbd>{key}</kbd> {months} {months === 1 ? 'month' : 'months'}
            </button>
          ))}
          <button type="button" onClick={() => setLaddering(false)}>
            Cancel
          </button>
        </div>
      )}

      {error && <p className="form-error">{error}</p>}

      <div className="study-layout">
        <StudyCardView card={card} picked={picked} onPick={pick} />
        {picked !== null && (
          <KanjiSidebar
            kanji={card.kanji}
            entries={queue.kanji}
            cardId={card.id}
            maxDeckWords={queue.max_deck_words}
          />
        )}
      </div>

      {picked !== null && (
        <button type="button" className="study-next" onClick={advance}>
          {index + 1 === cards.length ? 'Finish' : 'Next'} (⏎)
        </button>
      )}

      {videoId && (
        <div className="study-player">
          <YouTubePlayer
            key={videoId}
            ref={playerRef}
            videoId={videoId}
            onReady={() => setReadyVideoId(videoId)}
          />
        </div>
      )}
    </div>
  )
}

// The study queue of one song at /documents/:id/study, or of every song at
// /study.
export function StudyPage() {
  const { id } = useParams()
  const documentId = id === undefined ? null : Number(id)

  const fetchQueue = useCallback(
    () =>
      documentId === null ? fetchAllSongsQueue() : startSongSession(documentId),
    [documentId],
  )
  const { data, loading, error } = useApiResource(
    fetchQueue,
    [documentId],
    'Failed to load the study queue.',
  )

  return (
    <div className="study-page">
      <h1>{documentId === null ? 'Study' : 'Study this song'}</h1>
      {loading && <p>Loading…</p>}
      {error && <p className="form-error">{error}</p>}
      {!loading && data && (
        <StudySession key={documentId} queue={data} documentId={documentId} />
      )}
    </div>
  )
}
