import { useEffect, type RefObject } from 'react'

// Sets `inert` on the element, so a hidden element is skipped by Tab and
// screen readers. React 18 has no `inert` prop, so it's set imperatively.
export function useInert(ref: RefObject<HTMLElement>, inert: boolean) {
  useEffect(() => {
    if (ref.current) ref.current.inert = inert
  }, [ref, inert])
}
