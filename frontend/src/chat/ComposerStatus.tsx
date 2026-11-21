import { Stop } from '@phosphor-icons/react'
import type { ReactNode } from 'react'
import { LiveFacts } from '../agents/LiveFacts'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
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
  if (compact) return null
  const status = statusOf(conv, teams)
  return (
    <div className={`composer-status composer-status-${status.tone}`}>
      <span className="composer-status-dot" aria-hidden />
      <Said status={status} />
      {status.queued > 0 && <span className="composer-status-queued"> · {status.queued} queued</span>}
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

/** The line's words: what it does is cut first where the line is too narrow; its facts stay. */
function Said({ status }: { status: ChatStatus }) {
  if (status.tone === 'running')
    return (
      <>
        <b className="composer-status-what">{status.what}</b>
        <LiveFacts since={status.since} wrote={status.wrote} kind={status.kind} />
      </>
    )
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
