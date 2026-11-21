import { Stop } from '@phosphor-icons/react'
import type { ReactNode } from 'react'
import { LiveFacts } from '../agents/LiveFacts'
import { useAsk } from '../memory/useAsk'
import { usePanel } from '../shell/usePanel'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { AwayPanel } from './AwayPanel'
import { type ChatStatus, statusOf } from './statusLine'

interface Props {
  conv: ConvState | null
  /** The closed chat's small box: no line. */
  compact: boolean
  running: boolean
  onStop: () => void
  /** The conversation's model: chosen there, whatever the chat does.  */
  model?: ReactNode
}

/**
 * The line over the message box (0.1.5, "Kovan konsolu"): "● Orchestrator is ready", or while a turn runs what it does,
 * for how long, the tokens written and the tier, with Stop; or that it waits for your answer; and how many messages are
 * queued. Its clock ticks every second, so it is no live region: a screen reader reads it when it comes to it.
 */
export function ComposerStatus({ conv, compact, running, onStop, model }: Props) {
  const teams = useApp(s => s.teams)
  const away = useApp(s => s.away)
  if (compact) return null
  const status = statusOf(conv, teams, away)
  return (
    <div className={`composer-status composer-status-${status.tone}`}>
      <span className="composer-status-dot" aria-hidden />
      <Said status={status} />
      {status.queued > 0 && <span className="composer-status-queued"> · {status.queued} queued</span>}
      <AwayChip conv={conv} />
      {/* (In every tone, in one place: a model's window open as a turn starts stays open, and /model always finds it.) */}
      {model}
      {running && (
        <button type="button" className="icon-btn composer-stop" aria-label="Stop" title="Stop the work" onClick={onStop}>
          <Stop size={12} weight="fill" />
        </button>
      )}
    </div>
  )
}

/**
 * ☾ Away on the line (0.1.5): opens the Away panel - this chat's turn finishes, then the To-do tasks ticked there; while
 * its project is away, I'm back. None in a plain chat; in a chat with no turn yet it says why it waits.
 */
function AwayChip({ conv }: { conv: ConvState | null }) {
  const away = useApp(s => s.away)
  const { open, setOpen, close, button, panel } = usePanel()
  const { busy, ask } = useAsk()
  if (!conv?.conversation.project_id) return null
  if (away?.status === 'running' && away.project_id === conv.conversation.project_id)
    return (
      <button type="button" className="away-chip on" disabled={busy} onClick={() => void ask(() => useApp.getState().comeBack(away.id))}>
        <span aria-hidden>☾</span> I’m back
      </button>
    )
  const none = conv.runs.length === 0
  return (
    <div className="allow-list away-chip-wrap">
      <button
        ref={button}
        type="button"
        className="away-chip"
        aria-haspopup="dialog"
        aria-expanded={open}
        disabled={none}
        title={none ? 'Write to the Orchestrator first: Away finishes this chat’s turn' : 'Go away: this chat’s turn finishes, then To-do is worked through'}
        onClick={() => (open ? close() : setOpen(true))}
      >
        <span aria-hidden>☾</span> Away
      </button>
      {open && (
        <div ref={panel} tabIndex={-1} role="dialog" aria-label="Away" className="allow-list-panel away-panel">
          <AwayPanel conv={conv} onClose={close} />
        </div>
      )}
    </div>
  )
}

/** The line's words: where the line is too narrow its facts go first, the last first, and only then is what it does cut. */
function Said({ status }: { status: ChatStatus }) {
  if (status.tone === 'running')
    return (
      <>
        <b className="composer-status-what">{status.what}</b>
        <LiveFacts since={status.since} wrote={status.wrote} kind={status.kind} />
      </>
    )
  if (status.tone === 'away') return <span className="composer-status-what">{status.what}</span>
  return status.tone === 'asks' ? (
    <span className="composer-status-what">
      {status.who} <b>waits for your answer</b>
    </span>
  ) : (
    <span className="composer-status-what">
      <b>{status.who}</b> is ready
    </span>
  )
}
