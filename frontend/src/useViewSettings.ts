import { useHighlightSettings } from './useHighlightSettings'
import { usePersistentState } from './usePersistentState'
import { useSeekSeconds } from './usePlayerShortcuts'
import { useStickyVideo } from './useStickyVideo'

// The viewing settings: the same for every document, and kept across reloads.
export function useViewSettings() {
  const [fontSize, setFontSize] = usePersistentState('fontSize', 18)
  const [furiganaSize, setFuriganaSize] = usePersistentState('furiganaSize', 11)
  const [seekSeconds, setSeekSeconds] = useSeekSeconds()
  const [nudgeMs, setNudgeMs] = usePersistentState('nudgeMs', 50)
  const [stickyVideo, setStickyVideo] = useStickyVideo()
  const highlight = useHighlightSettings()
  return {
    fontSize,
    setFontSize,
    furiganaSize,
    setFuriganaSize,
    seekSeconds,
    setSeekSeconds,
    nudgeMs,
    setNudgeMs,
    stickyVideo,
    setStickyVideo,
    highlight,
  }
}

type ViewSettingsState = ReturnType<typeof useViewSettings>

// The custom properties the lyrics' rules in App.css read, for the element
// holding them.
export function displayStyle(settings: ViewSettingsState) {
  return {
    ...settings.highlight.style,
    '--lyrics-font-size': `${settings.fontSize}px`,
    '--furigana-font-size': `${settings.furiganaSize}px`,
  } as React.CSSProperties
}
