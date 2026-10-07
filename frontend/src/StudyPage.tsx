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
import { CardCorrectionPanel } from './CardCorrectionPanel'
import { KanjiSidebar } from './KanjiSidebar'
import { ReadinessMeter } from './ReadinessMeter'
import { StudyCardView } from './StudyCardView'
import { useApiResource } from './useApiResource'
import { useLatest } from './useLatest'
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
  corrected: number
  // The soonest a card answered this session comes up again, an ISO time.
  nextDue: string | null
}

const EMPTY_TALLY: Tally = {
  answered: 0,
  correct: 0,
  pushedOut: 0,
  removed: 0,
  corrected: 0,
  nextDue: null,
}

// An answer to the card on screen, sent once the card is left (see
// commitAnswer).
type Answer = {
  cardId: number
  correct: boolean
  durationMs: number
  documentId: number | null
}

// The song's readiness, fetched once the session that changed it is over
// and `answersSaved`, the answers still being sent, have been.
function SummaryReadiness({
  documentId,
  answersSaved,
}: {
  documentId: number
  answersSaved: () => Promise<unknown>
}) {
  const { data, error } = useApiResource(
    () => answersSaved().then(() => fetchDocumentReadiness(documentId)),
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
  answersSaved,
}: {
  tally: Tally
  documentId: number | null
  answersSaved: () => Promise<unknown>
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
        {tally.corrected > 0 && <li>Corrected: {tally.corrected}</li>}
        {tally.nextDue && (
          <li>Next due: {new Date(tally.nextDue).toLocaleString()}</li>
        )}
        {documentId !== null && (
          <SummaryReadiness
            documentId={documentId}
            answersSaved={answersSaved}
          />
        )}
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
  // The push-out ladder or the correction panel, whichever is open.
  const [panel, setPanel] = useState<'ladder' | 'correct' | null>(null)
  // What the last correction did, said on the card after it.
  const [notice, setNotice] = useState<string | null>(null)
  const [tally, setTally] = useState(EMPTY_TALLY)
  const [error, setError] = useState<string | null>(null)
  const shownAt = useRef(performance.now())
  // The answer to the card on screen, sent only once the card is left: the
  // reveal is where a wrong reading first shows, and correcting it there
  // abandons the review rather than logging one against the wrong word.
  const pendingAnswer = useRef<Answer | null>(null)
  // Settles once every answer sent so far is saved or has failed.
  const answersSent = useRef<Promise<unknown>>(Promise.resolve())

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

  // Sends the answer held for the card on screen, if any. `keepalive` for
  // a page that's going away.
  function commitAnswer(keepalive = false) {
    const answer = pendingAnswer.current
    if (!answer) return
    pendingAnswer.current = null
    setTally((t) => ({
      ...t,
      answered: t.answered + 1,
      correct: t.correct + (answer.correct ? 1 : 0),
    }))
    const sent = reviewCard(answer.cardId, answer, keepalive)
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
    answersSent.current = Promise.all([answersSent.current, sent])
  }

  // An answer still held when the session is left is sent all the same.
  const commitAnswerRef = useLatest(commitAnswer)
  useEffect(() => {
    const flush = () => commitAnswerRef.current(true)
    window.addEventListener('pagehide', flush)
    return () => {
      window.removeEventListener('pagehide', flush)
      flush()
    }
  }, [commitAnswerRef])

  function advance() {
    commitAnswer()
    setIndex((i) => i + 1)
    setPicked(null)
    setPanel(null)
    setNotice(null)
    setError(null)
    shownAt.current = performance.now()
  }

  function pick(option: number) {
    if (!card || picked !== null) return
    setPicked(option)
    pendingAnswer.current = {
      cardId: card.id,
      correct: option === card.answer,
      durationMs: Math.round(performance.now() - shownAt.current),
      documentId: card.line?.document_id ?? null,
    }
  }

  // Takes the card out of today's queue without rating it, then moves on.
  function leave(
    request: () => Promise<unknown>,
    counted: 'pushedOut' | 'removed',
    failure: string,
  ) {
    // An answer already given is saved first, so that this lands after it.
    commitAnswer()
    answersSent.current
      .then(request)
      .then(() => {
        setTally((t) => ({ ...t, [counted]: t[counted] + 1 }))
        advance()
      })
      .catch((err) => setError(errorMessage(err, failure)))
  }

  function pushOut(months: PushOutMonths) {
    if (card)
      leave(
        () => pushOutCard(card.id, months),
        'pushedOut',
        'Failed to push it out.',
      )
  }

  function remove() {
    if (card)
      leave(() => suspendCard(card.id), 'removed', 'Failed to remove it.')
  }

  // The card asked about the wrong word, which is now corrected: its
  // answer, if any, is dropped unrated, and the session moves on.
  function handleCorrected(message: string) {
    pendingAnswer.current = null
    setTally((t) => ({ ...t, corrected: t.corrected + 1 }))
    advance()
    setNotice(message)
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
      // The correction panel handles its own keys.
      if (!card || panel === 'correct') return

      if (panel === 'ladder') {
        if (event.key in PUSH_OUT_KEYS) pushOut(PUSH_OUT_KEYS[event.key])
        else if (event.key === 'Escape') setPanel(null)
        else return
      } else if (event.key === '!') {
        setPanel('ladder')
      } else if (event.key === '-') {
        remove()
      } else if (event.key === 'w' && card.line?.correction) {
        setPanel('correct')
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
    return (
      <Summary
        tally={tally}
        documentId={documentId}
        answersSaved={() => answersSent.current}
      />
    )
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
        <button type="button" onClick={() => setPanel('ladder')}>
          I know this (!)
        </button>
        <button type="button" onClick={remove}>
          Remove (-)
        </button>
        {card.line?.correction && (
          <button type="button" onClick={() => setPanel('correct')}>
            Wrong {card.line.correction} (w)
          </button>
        )}
      </div>

      {panel === 'ladder' && (
        <div className="study-ladder" role="group" aria-label="Push out">
          Push it out:
          {Object.entries(PUSH_OUT_KEYS).map(([key, months]) => (
            <button key={key} type="button" onClick={() => pushOut(months)}>
              <kbd>{key}</kbd> {months} {months === 1 ? 'month' : 'months'}
            </button>
          ))}
          <button type="button" onClick={() => setPanel(null)}>
            Cancel
          </button>
        </div>
      )}

      {panel === 'correct' && card.line && (
        <CardCorrectionPanel
          card={card}
          line={card.line}
          onCorrected={handleCorrected}
          onCancel={() => setPanel(null)}
        />
      )}

      {notice && <p className="study-notice">{notice}</p>}
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
