import { CaretDown, CaretRight, DotsThree, Play } from '@phosphor-icons/react'
import { useState } from 'react'
import { errorText } from '../api/client'
import { useConfirm } from '../shell/Confirm'
import type { Trigger } from '../api/types'
import { when } from '../canvas/turns'
import { Menu } from './Menu'
import { TriggerChanges } from './TriggerChanges'
import { budgetOf, endLine, leaveOf, offLine, outcomeOf, outcomeTone, slowedLine, whatOf, whenOf } from './triggerText'

interface Props {
  trigger: Trigger
  /** The title of the conversation its turns go into; null when that conversation is not among the project's. */
  conversation: string | null
  onSwitch: (enabled: boolean) => Promise<void>
  /** A schedule slowed down for finding nothing (93-B2): on its own times again. */
  onBack: () => Promise<void>
  /** Answers with the id of the turn it started. */
  onRun: () => Promise<string>
  onEdit: () => void
  onDelete: () => Promise<void>
  /** A webhook's: make its key anew (the old address stops). */
  onNewKey?: () => Promise<void>
  /** Draw one of its turns on the canvas. */
  onShowTurn: (runId: string) => void
}

/** One trigger as a sentence - when → what - with what it may do, its budget and its last run under it; the rest behind ⋯. */
export function TriggerCard({ trigger, conversation, onSwitch, onBack, onRun, onEdit, onDelete, onNewKey, onShowTurn }: Props) {
  const [open, setOpen] = useState(false)
  // A new key stops the old address at once: asked for twice.
  const [renewing, setRenewing] = useState(false)
  const [changesOpen, setChangesOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const off = offLine(trigger)
  const slowed = slowedLine(trigger)
  const leave = leaveOf(trigger)
  const last = trigger.runs[0]
  // A delete cannot be undone: asked first, as a To-do's is.
  const confirm = useConfirm()

  async function act(action: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className={`trigger-card${trigger.enabled ? '' : ' trigger-off'}`} aria-label={trigger.name}>
      <div className="trigger-line">
        <input type="checkbox" role="switch" className="switch" aria-label={`${trigger.name} is on`} checked={trigger.enabled} disabled={busy} onChange={event => void act(() => onSwitch(event.target.checked))} />
        <div className="trigger-text">
          <div className="trigger-sentence" title={trigger.message}>
            <strong>{whenOf(trigger)}</strong> → {whatOf(trigger.message)}
          </div>
          <div className="trigger-sub">
            {!trigger.enabled && 'off · '}
            <span className="trigger-name" title={trigger.name}>
              {trigger.name}
            </span>{' '}
            · in {conversation ?? 'a conversation that is gone'} · <span className={trigger.permissions.write || leave !== 'reads only' ? 'trigger-may' : undefined}>{leave}</span> · {budgetOf(trigger.budget)}
            {trigger.ends && <> · ends {endLine(trigger)}</>} ·{' '}
            {last ? (
              <>
                last run {when(last.at)} · <span className={outcomeTone(last)}>{outcomeOf(last)}</span>
              </>
            ) : (
              'has not run yet'
            )}
            {trigger.enabled && trigger.next_at && !slowed && <> · next {when(trigger.next_at)}</>}
            {trigger.runs.length > 0 && (
              <>
                {' '}
                <button type="button" className="link-btn" aria-expanded={open} onClick={() => setOpen(!open)}>
                  {open ? <CaretDown size={11} /> : <CaretRight size={11} />}
                  Recent runs ({trigger.runs.length})
                </button>
              </>
            )}
          </div>
          {/* Decision 2: the server never says its key again - only where the address begins. */}
          {trigger.kind === 'webhook' && (
            <div className="trigger-sub">
              <code className="mono">/api/hooks/…</code> · the key is shown once · New key in ⋯
            </div>
          )}
        </div>
        <button type="button" className="btn btn-small" disabled={busy} title="Run it now, with what it allows and nobody asked: what it would do by itself" onClick={() => void act(async () => onShowTurn(await onRun()))}>
          <Play size={12} />
          Run now
        </button>
        <Menu name={`More for ${trigger.name}`} className="icon-btn" title="Edit, new key, changes, delete" face={<DotsThree size={16} weight="bold" />}>
          <button type="button" role="menuitem" disabled={busy} onClick={onEdit}>
            Edit
          </button>
          {onNewKey && (
            <button type="button" role="menuitem" disabled={busy} title="For an address that got out: a new one is shown once" onClick={() => setRenewing(true)}>
              New key
            </button>
          )}
          {trigger.changes.length > 0 && (
            <button type="button" role="menuitem" onClick={() => setChangesOpen(!changesOpen)}>
              {changesOpen ? 'Hide changes' : `Changes (${trigger.changes.length})`}
            </button>
          )}
          <button type="button" role="menuitem" disabled={busy} onClick={() => confirm.ask(`Delete ${trigger.name}? It cannot be undone; what was done to it stays on the page.`, 'Delete', () => void act(onDelete), 'Keep it')}>
            Delete
          </button>
        </Menu>
      </div>
      {off && (
        <div role="alert" className="composer-warning trigger-off-why">
          {off}{' '}
          {off.startsWith('ended: its last day')
            ? 'To run it more, change its last day (Edit), then switch it on again.'
            : off.startsWith('ended:')
              ? 'Switch it on again for more: its runs are counted anew.'
              : 'Switch it on again when that is seen to.'}
        </div>
      )}
      {slowed && (
        <div role="status" className="composer-warning trigger-off-why">
          {slowed}{' '}
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => void act(onBack)}>
            Back to {whenOf(trigger)}
          </button>
        </div>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {onNewKey && renewing && (
        <div className="trigger-renew">
          <span className="muted">The old address stops at once.</span>
          <button
            type="button"
            className="btn btn-small"
            disabled={busy}
            onClick={() =>
              void act(async () => {
                await onNewKey()
                setRenewing(false)
              })
            }
          >
            Make a new key
          </button>
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => setRenewing(false)}>
            Cancel
          </button>
        </div>
      )}
      {open && (
        <ul className="trigger-runs" aria-label={`Recent runs of ${trigger.name}`}>
          {trigger.runs.map(run => {
            const line = (
              <>
                <span className="mono muted">{when(run.at)}</span> · {outcomeOf(run)}
              </>
            )
            return (
              <li key={run.id} title={run.note ?? undefined}>
                {run.run_id ? (
                  <button type="button" className="trigger-run" title="Show its work on the canvas" onClick={() => onShowTurn(run.run_id as string)}>
                    {line}
                  </button>
                ) : (
                  <span className="trigger-run">{line}</span>
                )}
              </li>
            )
          })}
        </ul>
      )}
      {confirm.shown()}
      {changesOpen && trigger.changes.length > 0 && <TriggerChanges changes={trigger.changes} label={`Changes to ${trigger.name}`} />}
    </article>
  )
}
