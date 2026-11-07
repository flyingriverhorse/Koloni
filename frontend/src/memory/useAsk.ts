import { useState } from 'react'
import { errorText } from '../api/client'

export const MAX_TEXT = 500
export const MAX_ABOUT = 80

/**
 * Ask the server for something about one record. A refusal is kept to show next to that
 * record; nothing on screen changes until the memory is read again after a success.
 */
export function useAsk() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function ask(action: () => Promise<void>): Promise<boolean> {
    setBusy(true)
    setError(null)
    try {
      await action()
      return true
    } catch (err) {
      setError(errorText(err))
      return false
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, ask }
}
