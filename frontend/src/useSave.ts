import { useState } from 'react'
import { errorMessage } from './api'

// State for a control that saves with one request: whether it's saving, and
// the message its last attempt failed with, `failure` if the error carries
// none. save() runs `request`, then `onSaved` with its result, or records why
// it failed.
export function useSave(failure = 'Failed to save — try again.') {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save<T>(
    request: () => Promise<T>,
    onSaved: (result: T) => void,
  ) {
    setSaving(true)
    setError(null)
    try {
      onSaved(await request())
    } catch (err) {
      setError(errorMessage(err, failure))
    } finally {
      setSaving(false)
    }
  }

  return { saving, error, setError, save }
}
