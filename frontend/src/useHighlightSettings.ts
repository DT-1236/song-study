import { usePersistentState } from './usePersistentState'

// The playing line's highlight color and opacity (a percentage), as the
// person set them on any page and kept across reloads, and `style`, the
// custom properties the highlight rules in App.css read, for the element
// holding the lyrics.
export function useHighlightSettings() {
  // Defaults to the theme's accent, which is hex, as a color input needs.
  const [color, setColor] = usePersistentState('highlightColor', () =>
    getComputedStyle(document.documentElement)
      .getPropertyValue('--accent')
      .trim(),
  )
  const [opacity, setOpacity] = usePersistentState('highlightOpacity', 25)

  const style = {
    '--highlight-color': color,
    '--highlight-opacity': `${opacity}%`,
  } as React.CSSProperties

  return { color, setColor, opacity, setOpacity, style }
}
