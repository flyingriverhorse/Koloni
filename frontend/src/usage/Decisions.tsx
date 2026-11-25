import { useEffect, useRef, useState } from 'react'
import { errorText } from '../api/client'
import type { Decision, DecisionLog } from '../api/types'
import { OPEN_TODO } from '../chat/TodoCards'
import { WHO, decisionsAsked, fineLine, markdown, stamp, weekStart } from './decisionLog'
import { since } from './period'

type Chip = 'today' | 'week' | 'left'
const CHIPS: [Chip, string][] = [
  ['today', 'Today'],
  ['week', 'This week'],
  ['left', 'Since I left'],
]
const EMPTY: Record<Chip, string> = {
  today: 'Nothing was decided for you today.',
  week: 'Nothing was decided for you this week.',
  left: 'Nothing was decided for you since you left.',
}
const MOST = 5 // rows shown before "Show all"
const LINK: Record<Decision['link']['kind'], string> = {
  question: 'The question',
  command: 'The command',
  task: 'The task',
  agent: 'The agent',
}

interface Props {
  /** Reads the project's decision log from a moment on. Throws ApiError. */
  onLoad: (since: string) => Promise<DecisionLog>
  /** When the project's last ☾ Away started; null: it had none ("Since I left" is not offered). */
  leftAt: string | null
  /** Opens a chat: where a decision's card, command or agent is. */
  onOpenChat?: (conversationId: string) => void
}

/**
 * Today's Decisions (karar defteri): what was decided for you in the project in a period - by the Orchestrator, KOLONİ's
 * judge or Check what I said first - with why, from the record; folded, and open when the chat's "All decisions on
 * Today" asked. Read only: OK and Change are the chat's Decided for you. Copy as Markdown copies it as masked as shown.
 */
export function Decisions({ onLoad, leftAt, onOpenChat }: Props) {
  const [chip, setChip] = useState<Chip>('today')
  const [log, setLog] = useState<DecisionLog | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDetailsElement>(null)
  const from = chip === 'left' && leftAt ? leftAt : chip === 'week' ? weekStart() : since('today')!

  useEffect(() => {
    if (!decisionsAsked()) return
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOpen(true)
    box.current?.scrollIntoView?.({ block: 'start' })
  }, [])
  useEffect(() => {
    let live = true
    onLoad(from).then(
      read => live && (setLog(read), setError(null)),
      err => live && (setLog(null), setError(errorText(err))),
    )
    return () => {
      live = false
    }
  }, [onLoad, from])

  const unseen = log?.rows.filter(row => row.seen === false).length ?? 0
  return (
    <section aria-label="Decisions" className="decisions">
      <details ref={box} className="usage-fold" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
        <summary>
          <h3>Decisions</h3>
          <span className="muted">
            {log && `· ${log.rows.length}`}
            {unseen > 0 && ` (${unseen} not seen)`}
          </span>
        </summary>
        <div role="group" aria-label="Period of the decisions" className="chips decisions-chips">
          {CHIPS.filter(([one]) => one !== 'left' || leftAt).map(([one, label]) => (
            <button key={one} type="button" className="chip" aria-pressed={chip === one} onClick={() => setChip(one)}>
              {label}
            </button>
          ))}
        </div>
        {error && (
          <div role="alert" className="alert">
            The decisions could not be read: {error}
          </div>
        )}
        {log && <Body key={chip} log={log} chip={chip} onOpenChat={onOpenChat} />}
      </details>
    </section>
  )
}

function Body({ log, chip, onOpenChat }: { log: DecisionLog; chip: Chip; onOpenChat?: (id: string) => void }) {
  const [all, setAll] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)
  const fine = log.judge_fine > 0 && <p className="muted memory-hint">{fineLine(log.judge_fine)}</p>
  if (log.rows.length === 0)
    return (
      <>
        <p className="muted">{EMPTY[chip]}</p>
        {fine}
      </>
    )
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(markdown(log, CHIPS.find(([one]) => one === chip)![1]))
      setCopied('Copied')
    } catch (err) {
      setCopied(`Not copied: ${errorText(err)}`)
    }
  }
  return (
    <>
      <ul className="decisions-rows" aria-label="Decisions in the period">
        {(all ? log.rows : log.rows.slice(0, MOST)).map(row => (
          <Row key={row.id} row={row} onOpenChat={onOpenChat} />
        ))}
      </ul>
      {fine}
      <p className="decisions-foot">
        {!all && log.rows.length > MOST && (
          <button type="button" className="usage-open" onClick={() => setAll(true)}>
            Show all {log.rows.length}
          </button>
        )}
        <button type="button" className="btn btn-small" onClick={() => void copy()}>
          Copy as Markdown
        </button>
        {copied && (
          <span role="status" className="muted">
            {copied}
          </span>
        )}
      </p>
    </>
  )
}

/** A row: when, who, KOLONİ's sentence and the words it is of - an agent's or a model's, shown as quotes, never as
 *  markup - and where it is. */
function Row({ row, onOpenChat }: { row: Decision; onOpenChat?: (id: string) => void }) {
  return (
    <li className="decision">
      <span className="muted mono">{stamp(row.at)}</span>
      <span>
        <b>{WHO[row.who]}</b> · {row.what}
        {row.quote && (
          <>
            : <q>{row.quote}</q>
          </>
        )}
        {row.answer && (
          <>
            {' → '}
            <b className="decided-a">{row.answer}</b>
          </>
        )}
        {row.why && <span className="muted"> · “{row.why}”</span>}
        {row.seen === false && <span className="tag decision-unseen">not seen</span>}
      </span>
      <RowLink row={row} onOpenChat={onOpenChat} />
    </li>
  )
}

/** Where a row's decision is: its task on To-do; the chat of its card, command or agent. */
function RowLink({ row, onOpenChat }: { row: Decision; onOpenChat?: (id: string) => void }) {
  const cid = row.conversation_id
  const open =
    row.link.kind === 'task'
      ? () => window.dispatchEvent(new CustomEvent(OPEN_TODO, { detail: row.link.id }))
      : cid && onOpenChat
        ? () => onOpenChat(cid)
        : null
  if (!open) return null
  const where = row.link.kind === 'task' ? 'on To-do' : 'in its chat'
  return (
    <button
      type="button"
      className="usage-open"
      aria-label={`${LINK[row.link.kind]} ${where}: ${row.what}`}
      onClick={open}
    >
      {LINK[row.link.kind]}
    </button>
  )
}
