import { Check, Checks, WarningCircle, X } from '@phosphor-icons/react'
import { useState } from 'react'
import { errorText } from '../api/client'
import type { Command } from '../api/types'
import { CardMore } from '../shell/CardMore'
import { placeLabel } from './commandStatus'

export type CommandDecision = 'once' | 'always' | 'reject'

interface Props {
  command: Command
  /** Why it is asked at every level, as its call's record says (one from a working copy that names the project, say). */
  why?: string | null
  onDecide: (decision: CommandDecision) => Promise<void>
}

/** Asks before a command runs: what, where, and whether to remember the answer. */
export function CommandApproval({ command, why, onDecide }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // The server offers a rule only for commands a rule can safely cover: none for one asked because web is off (K-web-komut).
  const rememberable = command.suggested_prefix !== ''

  async function decide(decision: CommandDecision) {
    setBusy(true)
    setError(null)
    try {
      await onDecide(decision)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="cmd-approval">
      <div className="kicker cmd-approval-kicker">Run this command?</div>
      <pre className="mono cmd-approval-command">{command.command}</pre>
      {command.danger && (
        // (Deletes, overwrites a git remote or opens a secret file: no rule covers it.)
        <div role="note" className="cmd-approval-danger">
          <WarningCircle size={14} color="var(--warn)" aria-hidden="true" />
          {command.danger}
        </div>
      )}
      {why && why !== command.danger && (
        <div role="note" className="cmd-approval-danger">
          <WarningCircle size={14} color="var(--warn)" aria-hidden="true" />
          {why}
        </div>
      )}
      <div className="cmd-approval-where">
        <span className="tag">{placeLabel(command)}</span>
        {command.cwd && command.cwd !== '.' && <span className="mono muted">in {command.cwd}</span>}
        {command.origin === 'cli' ? (
          <span className="mono muted">run by the CLI itself, with its own shell</span>
        ) : command.keep_running ? (
          // (Not in a sandbox: it runs with this command's rights, and serves its page on this machine.)
          <span className="mono muted">keeps running, serves a page</span>
        ) : (
          <span className="mono muted">stops after {command.timeout_seconds}s</span>
        )}
      </div>
      <div className="change-actions">
        <button type="button" className="btn btn-small btn-primary" disabled={busy} onClick={() => decide('once')}>
          <Check size={13} />
          Run once
        </button>
        {rememberable && (
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => decide('always')}>
            <Checks size={13} />
            Always run {command.suggested_prefix}
          </button>
        )}
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => decide('reject')}>
          <X size={13} />
          Reject
        </button>
      </div>
      {!rememberable && <CardMore>{command.web_off ? 'This command is asked every time while web is off.' : 'This command is asked every time.'}</CardMore>}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}
