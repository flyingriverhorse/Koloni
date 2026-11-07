import { Check, PencilSimple, X } from '@phosphor-icons/react'
import { useRef, useState } from 'react'
import { errorText, overWhat } from '../api/client'
import type { Run } from '../api/types'
import { TERMINAL } from '../state/applyEvent'
import { plannedBy } from './planText'

interface Props {
  /** A plan turn (slice 49). */
  run: Run
  /** A later turn has started since: it can only be turned down (the server says the same). */
  stale?: boolean
  /** Approve (`text`: the plan as edited) or reject (`text`: why). `overBudget`: the user's word to start the work over the month's budget. */
  onDecide: (decision: 'approve' | 'reject', text?: string, overBudget?: boolean) => Promise<void>
}

/**
 * Under a plan turn: the plan it wrote (shown above, as the Lead's answer) put before the
 * user - approved as it is or edited, or turned down with why. Decided, it stays on record.
 */
export function PlanCard({ run, stale = false, onDecide }: Props) {
  const plan = run.plan
  const [editing, setEditing] = useState<string | null>(null)
  // Why it is turned down: asked once Reject is pressed; null until then.
  const [why, setWhy] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // The server held the work back over the month's budget: the user is asked to go on.
  const [over, setOver] = useState<string | null>(null)
  const approveButton = useRef<HTMLButtonElement>(null)

  if (!plan) {
    // (Queued, its message says so; ended with no plan, the turn's own notice says why.)
    if (run.status === 'queued' || TERMINAL.has(run.status)) return null
    return (
      <div role="note" className="msg-status mono">
        Writing a plan: this message’s work only reads, and nothing changes before you approve it.
      </div>
    )
  }
  if (plan.status !== 'proposed') {
    return (
      <div role="note" className="muted cmd-approval-note">
        {plan.status === 'approved' ? 'Plan approved: its work starts as a new turn.' : `Plan rejected${plan.why ? `: ${plan.why}` : '.'}`}
        <div className="mono">{plannedBy(plan)}</div>
      </div>
    )
  }

  async function decide(decision: 'approve' | 'reject', text?: string, overBudget = false) {
    setBusy(true)
    setError(null)
    setOver(null)
    try {
      await (overBudget ? onDecide(decision, text, true) : onDecide(decision, text))
    } catch (err) {
      const said = decision === 'approve' && !overBudget ? overWhat(err) : null
      if (said) setOver(said)
      else setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="cmd-approval">
      <div className="kicker cmd-approval-kicker">{stale ? 'This plan was not decided' : 'Approve this plan?'}</div>
      <div className="muted mono">{plannedBy(plan)}</div>
      <div className="muted cmd-approval-note">
        {stale ? 'A later message has started since this plan: reject it, or ask again.' : 'Approve here — a new message plans again.'}
      </div>
      {/* shortcut: a model's plan longer than the server takes (20000) is cut when edited; raise both if plans grow so. */}
      {editing !== null && !stale && (
        <textarea aria-label="Plan" className="input" rows={8} maxLength={20000} value={editing} disabled={busy} onChange={e => setEditing(e.target.value)} />
      )}
      {why !== null && (
        <input autoFocus className="input" aria-label="Why not (optional)" placeholder="Why not, in a sentence (optional)" maxLength={500} value={why} disabled={busy} onChange={e => setWhy(e.target.value)} />
      )}
      <div className="change-actions">
        {!stale && (
          <button
            ref={approveButton}
            type="button"
            className="btn btn-small btn-primary"
            disabled={busy || editing?.trim() === ''}
            onClick={() => decide('approve', editing ?? undefined)}
          >
            <Check size={13} />
            {editing !== null ? 'Approve edited plan' : 'Approve'}
          </button>
        )}
        {editing === null && !stale && (
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => setEditing(plan.text)}>
            <PencilSimple size={13} />
            Edit
          </button>
        )}
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => (why === null ? setWhy('') : decide('reject', why.trim() || undefined))}>
          <X size={13} />
          {why === null ? 'Reject' : 'Reject plan'}
        </button>
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {over && (
        <div role="group" aria-label={over} className="composer-warning composer-budget">
          <span role="alert">{over}. Start the work anyway?</span>
          <button type="button" className="btn btn-small" autoFocus onClick={() => void decide('approve', editing ?? undefined, true)}>
            Go on anyway
          </button>
          <button
            type="button"
            className="btn btn-small"
            onClick={() => {
              setOver(null)
              approveButton.current?.focus()
            }}
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  )
}
