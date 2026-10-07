import { useLayoutEffect, useRef } from 'react'

// A ref that always holds the value from the latest render, so a stable
// callback or listener can read it without being re-created.
export function useLatest<T>(value: T) {
  const ref = useRef(value)
  useLayoutEffect(() => {
    ref.current = value
  })
  return ref
}
