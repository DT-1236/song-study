import { useEffect, useRef, useState } from 'react'
import { lineToStamp, nudgedStart, overlapFor, roundedToMs } from './timing'
import type { LyricsLine } from './timing'
import { useLatest } from './useLatest'
import { useTransient } from './useTransient'
import { isTypingTarget } from './usePlayerShortcuts'

// What the timing editor's keys do, one for each of its bar buttons.
export type TimingKey = 'earlier' | 'later' | 'stamp'

// The timing editor's keys, by `KeyboardEvent.key`.
const KEYS: Record<string, TimingKey | 'up' | 'down'> = {
  ArrowUp: 'up',
  ArrowDown: 'down',
  ArrowLeft: 'earlier',
  ArrowRight: 'later',
  '/': 'stamp',
}

// What the timing editor's key `event` does, or null if it isn't one of
// them or is typed into a field or an open dialog.
function timingKeyOf(event: KeyboardEvent) {
  // / is typed with Shift on some layouts, so only the arrows rule it out.
  if (event.altKey || event.ctrlKey || event.metaKey) return null
  const key = KEYS[event.key] ?? null
  if (key === null || (key !== 'stamp' && event.shiftKey)) return null
  const active = document.activeElement
  // A slider doesn't count as typing here, so the keys still work once
  // one's been dragged; an open dialog's controls do. (A closed one's
  // button keeps focus for a moment after it closes.)
  if (active?.closest('dialog[open]')) return null
  if (
    isTypingTarget(active) &&
    !(active instanceof HTMLInputElement && active.type === 'range')
  )
    return null
  return key
}

// Calls `onPress` with each of the timing editor's keys that has a bar
// button, as it's pressed.
export function useTimingKeyPresses(onPress: (key: TimingKey) => void) {
  useEffect(() => {
    function listener(event: KeyboardEvent) {
      const key = timingKeyOf(event)
      // A held / times nothing more (see the editor's own listener).
      if (key === 'stamp' && event.repeat) return
      if (key !== null && key !== 'up' && key !== 'down') onPress(key)
    }
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  }, [onPress])
}

// How long a nudged line's time stays highlighted.
const NUDGE_FLASH_MS = 700

// A change to a line's timing that's confirmed first.
type TimingAction =
  | { kind: 'delete'; line: number }
  | { kind: 'overwrite'; line: number; start: number }

// The state and keys of the timing editor for `lines`, whose starts are
// `starts` (null once a line's timing is deleted), new for each editing
// session.
//
// The picked line follows playback; ↑/↓ or a click pick another and play from
// it; ←/→ move the picked line's start by `nudgeMs` and play from there; /
// starts the line after the one being sung at the current playback time (the
// first line, before any is) and scrolls down a line.
export function useTimingEditor({
  lines,
  starts,
  onStartChange,
  playingLine,
  onPlayLine,
  getTime,
  nudgeMs,
  onToast,
}: {
  lines: LyricsLine[]
  starts: (number | null)[]
  // Sets `line`'s start, null to leave it untimed.
  onStartChange: (line: number, start: number | null) => void
  playingLine: number | null
  onPlayLine: (start: number) => void
  // The current playback time, or null until the player is ready.
  getTime: () => number | null
  nudgeMs: number
  // Shows why a key did nothing.
  onToast: (message: string) => void
}) {
  const [selected, setSelected] = useState(() => playingLine ?? 0)
  // A change waiting on its confirmation.
  const [pending, setPending] = useState<TimingAction | null>(null)
  // Set by "don't ask again": that kind of change skips its confirmation
  // until editing ends.
  const [skipConfirm, setSkipConfirm] = useState({
    delete: false,
    overwrite: false,
  })
  // The line whose start was just nudged.
  const [nudgedLine, flashNudge] = useTransient<number>(NUDGE_FLASH_MS)
  const selectedRowRef = useRef<HTMLDivElement>(null)
  // The rows' container: row i is its child i.
  const rowsRef = useRef<HTMLDivElement>(null)

  // The picked line follows the one being sung. Picking a line plays from
  // it, so the two only part when an untimed line is picked.
  useEffect(() => {
    if (playingLine !== null) setSelected(playingLine)
  }, [playingLine])

  // Scrolls the picked line onto the screen when it moves off it, as little
  // as possible.
  useEffect(() => {
    selectedRowRef.current?.scrollIntoView({ block: 'nearest' })
  }, [selected])

  // Picks `line` and plays from its start, if it has one.
  function pick(line: number) {
    setSelected(line)
    const start = starts[line] ?? null
    if (start !== null) onPlayLine(start)
  }

  // Sets `line`'s start and picks it.
  function setStart(line: number, start: number) {
    onStartChange(line, start)
    setSelected(line)
  }

  // Sets `line`'s start from /, and scrolls the page down by the line and
  // the space after it, so the next line to time sits where this one was
  // and timing along needs no scrolling by hand.
  function stamp(line: number, start: number) {
    setStart(line, start)
    const rows = rowsRef.current?.children
    const row = rows?.[line]
    if (!rows || !row) return
    const next = rows[line + 1]
    const { top, height } = row.getBoundingClientRect()
    row
      .closest('.content')
      ?.scrollBy(0, next ? next.getBoundingClientRect().top - top : height)
    // Timing that began with the next line off screen brings it on.
    next?.scrollIntoView({ block: 'nearest' })
  }

  function apply(action: TimingAction) {
    if (action.kind === 'delete') onStartChange(action.line, null)
    // Only / overwrites a start.
    else stamp(action.line, action.start)
  }

  // Applies `action`, asking first unless "don't ask again" was checked for
  // its kind.
  function confirmThen(action: TimingAction) {
    if (skipConfirm[action.kind]) return apply(action)
    setPending(action)
  }

  function nudge(direction: number) {
    const start = starts[selected] ?? null
    if (start === null) return onToast('This line has no timing to nudge.')
    const moved = nudgedStart(start, direction * nudgeMs)
    const overlap = overlapFor(starts, selected, moved)
    if (overlap) return onToast(overlap)
    setStart(selected, moved)
    flashNudge(selected)
    onPlayLine(moved)
  }

  // Starts the line after the one being sung at the current playback time
  // then, or the first line before any is, asking first if that replaces a
  // time it already has.
  function timeNextLine() {
    const time = getTime()
    if (time === null) return onToast("The video isn't ready yet.")
    const start = roundedToMs(time)
    const line = lineToStamp(starts, start)
    if (line >= lines.length) return onToast('There are no more lines to time.')
    const overlap = overlapFor(starts, line, start)
    if (overlap) return onToast(overlap)
    if ((starts[line] ?? null) === null) return stamp(line, start)
    confirmThen({ kind: 'overwrite', line, start })
  }

  function handleKeyDown(event: KeyboardEvent) {
    const key = timingKeyOf(event)
    if (key === null) return
    event.preventDefault()
    if (key === 'stamp') {
      // Held down, it would time line after line at almost the same moment.
      if (!event.repeat) timeNextLine()
    } else if (key === 'earlier' || key === 'later') {
      nudge(key === 'earlier' ? -1 : 1)
    } else {
      const line = selected + (key === 'up' ? -1 : 1)
      if (line >= 0 && line < lines.length) pick(line)
    }
  }

  // Kept current by an effect, so the listener can be added once and still
  // see the latest state.
  const handleKeyDownRef = useLatest(handleKeyDown)
  useEffect(() => {
    const listener = (event: KeyboardEvent) => handleKeyDownRef.current(event)
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  }, [handleKeyDownRef])

  return {
    selected,
    nudgedLine,
    // Whether a nudge has a start to move.
    canNudge: (starts[selected] ?? null) !== null,
    selectedRowRef,
    rowsRef,
    pick,
    nudge,
    timeNextLine,
    // Asks before deleting `line`'s timing.
    confirmDelete: (line: number) => confirmThen({ kind: 'delete', line }),
    pending,
    // Applies the change waiting on its confirmation, and with `dontAskAgain`
    // skips asking for that kind of change until editing ends.
    confirmPending(dontAskAgain: boolean) {
      if (!pending) return
      if (dontAskAgain) setSkipConfirm({ ...skipConfirm, [pending.kind]: true })
      apply(pending)
      setPending(null)
    },
    cancelPending: () => setPending(null),
  }
}
