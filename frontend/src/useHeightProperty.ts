import { useLayoutEffect } from 'react'

// Publishes the element's height, following it as it resizes, as the CSS
// property `name` on its enclosing `.content` scroll container, so the
// page's scroll padding and toasts can stay clear of it. Does nothing while
// `enabled` is false or there's no element yet. Written straight to the
// style, in a layout effect, so the value is in place before paint.
//
// Takes the element itself (held in state through a callback ref), not a
// ref object, so an element that mounts after this hook's component does
// is still picked up.
export function useHeightProperty(
  element: HTMLElement | null,
  name: string,
  enabled = true,
) {
  useLayoutEffect(() => {
    const container = element?.closest<HTMLElement>('.content')
    if (!enabled || !element || !container) return
    const publish = () =>
      container.style.setProperty(name, `${element.offsetHeight}px`)
    publish()
    const observer = new ResizeObserver(publish)
    observer.observe(element)
    return () => {
      observer.disconnect()
      container.style.removeProperty(name)
    }
  }, [element, name, enabled])
}
