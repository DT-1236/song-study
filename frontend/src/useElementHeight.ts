import { useEffect, useState } from 'react'

// The element's height in pixels, following it as it resizes: 0 while
// there's no element.
export function useElementHeight(element: HTMLElement | null) {
  const [height, setHeight] = useState(0)
  useEffect(() => {
    if (!element) {
      setHeight(0)
      return
    }
    const observer = new ResizeObserver(() => setHeight(element.offsetHeight))
    observer.observe(element)
    return () => observer.disconnect()
  }, [element])
  return height
}
