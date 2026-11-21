import { useState } from 'react'
import { errorText, overWhat } from '../api/client'
import type { Run } from '../api/types'
import { useApp } from '../state/store'

/** A message still queued when KOLONİ restarted: never given to the Orchestrator, and nothing sends it by itself - Send does, as the newest. */
export function NotSent({ run }: { run?: Run }) {
  const sendAgain = useApp(s => s.sendAgain)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // The server held it back over the month's budget: the user is asked to go on, as for a plan.
  const [over, setOver] = useState<string | null>(null)

  if (run?.status !== 'interrupted' || run.started_at || !run.by_user || run.unattended) return null
  const runId = run.id

  async function send(overBudget: boolean) {
    setBusy(true)
    setError(null)
    setOver(null)
    try {
      await sendAgain(runId, overBudget)
    } catch (err) {
      const said = overBudget ? null : overWhat(err)
      if (said) setOver(said)
      else setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="msg-meta">
        <span className="tag">Not sent: KOLONİ restarted</span>
        {/* (Not one side of a comparison: alone it would compare nothing - the server refuses it.) */}
        {!run.compare_id && (
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => void send(false)}>
            Send
          </button>
        )}
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {over && (
        <div role="group" aria-label={over} className="composer-warning composer-budget">
          <span role="alert">{over}. Send it anyway?</span>
          <button type="button" className="btn btn-small" autoFocus onClick={() => void send(true)}>
            Go on anyway
          </button>
          <button type="button" className="btn btn-small" onClick={() => setOver(null)}>
            Cancel
          </button>
        </div>
      )}
    </>
  )
}
