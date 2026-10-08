import { useEffect, useState } from 'react'
import { errorMessage, fetchLrclibLyrics } from './api'
import type { LrclibCandidate, LrclibLyrics } from './api'
import { useLatest } from './useLatest'

// The LRCLIB match chosen (null for none, undefined before a choice) and its
// lyrics, loaded as it's chosen: null until they have. A match whose lyrics
// fail to load is unchosen, with the reason in `error`, so it's never used
// unseen. `onLoaded` gets each chosen match's id once its lyrics load.
export function useLrclibChoice(onLoaded?: (id: number) => void) {
  const [choice, setChoice] = useState<LrclibCandidate | null>()
  // The last chosen match's lyrics, by its id, so they're never shown for
  // another choice.
  const [loaded, setLoaded] = useState<{
    id: number
    lyrics: LrclibLyrics
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const onLoadedRef = useLatest(onLoaded)

  const choiceId = choice?.id
  useEffect(() => {
    if (choiceId === undefined) return
    let cancelled = false

    fetchLrclibLyrics(choiceId)
      .then((lyrics) => {
        if (cancelled) return
        setLoaded({ id: choiceId, lyrics })
        onLoadedRef.current?.(choiceId)
      })
      .catch((err) => {
        if (cancelled) return
        setError(errorMessage(err, "Couldn't load the lyrics."))
        setChoice(undefined)
      })

    return () => {
      cancelled = true
    }
  }, [choiceId, onLoadedRef])

  const lyrics = choice && loaded?.id === choice.id ? loaded.lyrics : null

  function choose(candidate: LrclibCandidate | null | undefined) {
    setChoice(candidate)
    setError(null)
  }

  return {
    choice,
    choose,
    lyrics,
    loading: Boolean(choice) && lyrics === null,
    error,
  }
}
