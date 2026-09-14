import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'

// A modal asking to confirm `message`, shown while `open`. Its Cancel button
// and Escape both call onCancel.
export function ConfirmDialog({
  open,
  message,
  confirmLabel,
  onConfirm,
  onCancel,
  children,
}: {
  open: boolean
  message: string
  confirmLabel: string
  onConfirm: () => void
  onCancel: () => void
  // Options shown between the message and the buttons.
  children?: ReactNode
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) {
      dialog.showModal()
      // Rather than the first control, so a stray Enter or Space doesn't
      // confirm.
      cancelRef.current?.focus()
    } else if (!open && dialog.open) {
      dialog.close()
    }
  }, [open])

  return (
    <dialog
      ref={dialogRef}
      className="confirm-dialog"
      onCancel={(e) => {
        // Left to `open` to close, like the buttons.
        e.preventDefault()
        onCancel()
      }}
    >
      <p>{message}</p>
      {children}
      <div className="confirm-dialog-actions">
        <button type="button" className="danger" onClick={onConfirm}>
          {confirmLabel}
        </button>
        <button type="button" ref={cancelRef} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </dialog>
  )
}
