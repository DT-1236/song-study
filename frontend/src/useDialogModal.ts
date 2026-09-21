import {
  useEffect,
  useRef,
  useState,
  type MouseEvent,
  type SyntheticEvent,
} from 'react'

// Shared wiring for every reference modal built on a native <dialog>: syncs
// showModal()/close() to the `open` prop, and returns the Escape/backdrop
// handlers every one of them needs (both call onClose).
//
// Also tracks `hasOpened`, which starts matching `open` and then latches
// true forever the first time the dialog opens. Callers use it to skip
// building their (often sizeable, hand-authored) content until it's needed
// at least once, without unmounting it again afterward — unmounting on
// every close would mean re-building it, and briefly racing the dialog's
// own close() with React removing its children.
export function useDialogModal(open: boolean, onClose: () => void) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [hasOpened, setHasOpened] = useState(open)

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) {
      dialog.showModal()
    } else if (!open && dialog.open) {
      dialog.close()
    }
    if (open) setHasOpened(true)
  }, [open])

  return {
    dialogRef,
    hasOpened,
    onCancel: (e: SyntheticEvent<HTMLDialogElement>) => {
      e.preventDefault()
      onClose()
    },
    onClick: (e: MouseEvent<HTMLDialogElement>) => {
      // The dialog element covers the whole viewport, so a click landing on
      // it directly (not on a descendant) means it hit the backdrop.
      if (e.target === dialogRef.current) onClose()
    },
  }
}
