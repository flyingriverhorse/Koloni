import { useState } from 'react'
import { errorText } from '../api/client'
import type { ConvState } from '../state/applyEvent'
import { TURNS_PAGE } from '../state/earlier'
import { useApp } from '../state/store'

/**
 * Over the oldest turn shown of a long chat, which opens on its newest (`TURNS_PAGE`): its older turns, a page at a time,
 * on your click. What needs the whole chat - search, the decision log, the night's report - reads it on the server.
 */
export function Earlier({ conv }: { conv: ConvState }) {
  const loadEarlier = useApp(s => s.loadEarlier)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  if (!conv.older) return null
  const next = Math.min(conv.older, TURNS_PAGE)
  const read = () => {
    setBusy(true)
    setError(null)
    loadEarlier()
      .catch(err => setError(errorText(err)))
      .finally(() => setBusy(false))
  }
  return (
    <div className="msg-earlier">
      <button type="button" className="btn btn-small" disabled={busy} onClick={read}>
        Show {next} earlier {next === 1 ? 'turn' : 'turns'}
      </button>{' '}
      <span className="muted">
        {conv.older} older {conv.older === 1 ? 'turn is' : 'turns are'} not shown
      </span>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}
