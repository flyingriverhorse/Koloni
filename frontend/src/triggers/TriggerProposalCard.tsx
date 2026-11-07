import { Check, Clock, PencilSimple, X } from '@phosphor-icons/react'
import type { TriggerProposal } from '../api/types'
import { useAsk } from '../memory/useAsk'
import { CardMore } from '../shell/CardMore'
import { blank, budgetOf, endOf, whenOf } from './triggerText'

interface Props {
  proposal: TriggerProposal
  /** Throws ApiError with the server's reason. */
  onDecide: (decision: 'approve' | 'reject') => Promise<void>
  /** Open the Triggers form with it filled in: what more it may do is yours to give there. */
  onEdit: () => void
}

// What a proposed trigger may do once approved: nothing an agent can raise (app/api/triggers.py).
const fresh = blank('')
const SAFEST = `reads only · no sub-agents · ${budgetOf({ steps: Number(fresh.steps), minutes: Number(fresh.minutes), per_day: Number(fresh.perDay) })}`

/**
 * A trigger an agent proposed (slice 69): when it runs, what it does and what it may do, with Approve,
 * Edit and Reject. Only your Approve, here, makes it - reading only, whatever the agent asked for.
 */
export function TriggerProposalCard({ proposal, onDecide, onEdit }: Props) {
  const { busy, error, ask } = useAsk()
  if (proposal.status !== 'proposed') {
    return (
      <p className="muted away-said" role="note">
        <Clock size={13} /> {proposal.status === 'approved' ? `The trigger “${proposal.name}” was made: it is on the Triggers page.` : `The trigger “${proposal.name}” was rejected: nothing was made.`}
      </p>
    )
  }
  return (
    <section className="cmd-approval" aria-label={`Proposed trigger: ${proposal.name}`}>
      <div className="kicker cmd-approval-kicker">Make this trigger?</div>
      <dl className="trigger-facts">
        <dt>Name</dt>
        <dd>{proposal.name}</dd>
        <dt>When</dt>
        <dd>
          {whenOf(proposal)} · ends {endOf(proposal.ends)}
        </dd>
        <dt>May</dt>
        <dd>{SAFEST}</dd>
      </dl>
      <div>
        <span className="muted">Each run is told (written by the agent):</span>
        <p className="trigger-proposal-message">{proposal.message}</p>
      </div>
      <p className="card-said">Its runs start by themselves in this chat, with nobody watching.</p>
      <div className="change-actions">
        <button type="button" className="btn btn-small btn-primary" disabled={busy} onClick={() => void ask(() => onDecide('approve'))}>
          <Check size={13} />
          Approve
        </button>
        <button type="button" className="btn btn-small" disabled={busy} onClick={onEdit}>
          <PencilSimple size={13} />
          Edit
        </button>
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => void ask(() => onDecide('reject'))}>
          <X size={13} />
          Reject
        </button>
      </div>
      <CardMore>Approve makes it as shown; to let it do more, or change anything, Edit.</CardMore>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </section>
  )
}
