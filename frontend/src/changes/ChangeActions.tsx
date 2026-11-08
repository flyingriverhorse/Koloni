import { ArrowCounterClockwise, Check, X } from '@phosphor-icons/react'
import { useState } from 'react'
import { errorText } from '../api/client'
import type { FileChange } from '../api/types'
import { MADE_WITH_A_PLACE, NEVER_MADE, TAKEN_TOGETHER } from './changeLabel'

export type ChangeAction = 'approve' | 'reject' | 'revert'

interface Props {
  change: FileChange
  onDecide: (action: ChangeAction) => Promise<void>
}

const SETTLED: Partial<Record<FileChange['status'], [text: string, tag: string]>> = {
  // Decided, and not to be decided again: nothing to press until the agent has made it.
  approved: [`Approved — ${MADE_WITH_A_PLACE}`, 'tag'],
  rejected: ['Rejected', 'tag'],
  discarded: [NEVER_MADE, 'tag'],
  reverted: ['Reverted', 'tag'],
  conflict: ['Conflict — file changed on disk', 'tag tag-del'],
  failed: ['Not written — the disk refused the write', 'tag tag-del'],
  merged: [TAKEN_TOGETHER, 'tag'],
}

/** The decisions a change still allows: approve/reject while proposed, revert once applied. */
export function ChangeActions({ change, onDecide }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function decide(action: ChangeAction) {
    setBusy(true)
    setError(null)
    try {
      await onDecide(action)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const settled = SETTLED[change.status]
  return (
    <div className="change-actions">
      {change.status === 'proposed' && (
        <>
          <button type="button" className="btn btn-small btn-primary" disabled={busy} onClick={() => decide('approve')}>
            <Check size={13} />
            Approve
          </button>
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => decide('reject')}>
            <X size={13} />
            Reject
          </button>
        </>
      )}
      {change.status === 'applied' && (
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => decide('revert')}>
          <ArrowCounterClockwise size={13} />
          Revert
        </button>
      )}
      {settled && <span className={settled[1]}>{settled[0]}</span>}
      {/* A file outside the project is on record by its full path. */}
      {/^([a-z]:)?[\\/]/i.test(change.path) && <span className="tag tag-warn">outside the project</span>}
      {error && (
        <div role="alert" className="alert change-actions-error">
          {error}
        </div>
      )}
    </div>
  )
}
