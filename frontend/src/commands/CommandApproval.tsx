import { Check, Checks, WarningCircle, X } from '@phosphor-icons/react'
import { useState } from 'react'
import { errorText } from '../api/client'
import type { Command } from '../api/types'
import { CardMore } from '../shell/CardMore'
import { useApp } from '../state/store'
import { placeLabel } from './commandStatus'

/** `disposable`: run once, and allow such deletes in the project from now on (coordination §4). `line`: run once, and
 *  on a card of Full auto's judge (0.1.9) not ask about this line again in the project. */
export type CommandDecision = 'once' | 'always' | 'disposable' | 'line' | 'reject'

/** How a card of Full auto's judge starts its line (`risk_judge.CARD`), as the server's `cards` knows it too. */
const JUDGE_SAYS = "KOLONİ's judge: "

interface Props {
  command: Command
  /** Why it is asked at every level, as its call's record says (one from a working copy that names the project, say). */
  why?: string | null
  onDecide: (decision: CommandDecision) => Promise<void>
}

/** K-yargıç: Full auto's check of the user's words found no line of theirs that covers it. Not its own sentence: a model's
 *  words, which a command's text may have steered, are no reason shown on the card (kept on the record). */
function NothingYouSaid({ judged }: { judged: Command['judged'] }) {
  if (judged?.verdict !== 'ask') return null
  return (
    <div role="note" className="cmd-approval-note">
      Nothing you said covers this.
    </div>
  )
}

/** Coordination §4: a delete KOLONİ found disposable, while its chat's project does not allow such deletes yet. */
function useOffersDisposable(command: Command): boolean {
  const allowed = useApp(s => s.projects.find(p => p.id === s.conv?.conversation.project_id)?.disposable_deletes)
  return command.disposable != null && !allowed
}

/** Full auto's judge's card (0.1.9): its box - ticked, Run once also keeps the line from being asked again here. None
 *  where the server keeps nothing for it (the judge did not look, or the line's folder is not known). */
function KeepLine({ command, keep, onKeep }: { command: Command; keep: boolean; onKeep: (on: boolean) => void }) {
  if (!command.keeps_line) return null
  return (
    <label className="choice cmd-approval-keep">
      <input type="checkbox" checked={keep} onChange={e => onKeep(e.target.checked)} />
      <span>Don’t ask about this line again here</span>
    </label>
  )
}

/** Why no rule is offered on a card: a judge's card's has none to pass it, one asked while web is off is asked each
 *  time, and so is any other. */
function noRule(command: Command): string {
  if (command.danger.startsWith(JUDGE_SAYS)) return 'No rule lets a command past Full auto’s judge, so none is offered.'
  return command.web_off ? 'This command is asked every time while web is off.' : 'This command is asked every time.'
}

/** Under Details: why no rule is offered, and what Allow such deletes turns on. */
function CardNotes({ command, rememberable, offers }: { command: Command; rememberable: boolean; offers: boolean }) {
  if (rememberable && !offers) return null
  return (
    <CardMore>
      {!rememberable && <div>{noRule(command)}</div>}
      {offers && (
        <div>
          KOLONİ checked {command.disposable?.what}: disposable. Allow such deletes in this project runs this one, and
          from now on, at Auto-edit and Full auto in a chat you watch, such deletes (clean worktrees and merged branches
          you no longer use, build and cache folders) go without a card. Settings › This project › Asking and away turns
          it off.
        </div>
      )}
    </CardMore>
  )
}

/** Asks before a command runs: what, where, and whether to remember the answer. */
export function CommandApproval({ command, why, onDecide }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [keep, setKeep] = useState(false)
  // The server offers a rule only for commands a rule can safely cover: none for one asked because web is off (K-web-komut).
  const rememberable = command.suggested_prefix !== ''
  const offers = useOffersDisposable(command)

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
      <NothingYouSaid judged={command.judged} />
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
      <KeepLine command={command} keep={keep} onKeep={setKeep} />
      <div className="change-actions">
        <button
          type="button"
          className="btn btn-small btn-primary"
          disabled={busy}
          onClick={() => decide(keep ? 'line' : 'once')}
        >
          <Check size={13} />
          Run once
        </button>
        {rememberable && (
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => decide('always')}>
            <Checks size={13} />
            Always run {command.suggested_prefix}
          </button>
        )}
        {offers && (
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => decide('disposable')}>
            <Checks size={13} />
            Allow such deletes in this project
          </button>
        )}
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => decide('reject')}>
          <X size={13} />
          Reject
        </button>
      </div>
      <CardNotes command={command} rememberable={rememberable} offers={offers} />
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}
