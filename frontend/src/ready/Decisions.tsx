import { useEffect, useId, useRef, useState } from 'react'
import { api, errorText } from '../api/client'
import type { BacklogTask, Decision, DecisionLog } from '../api/types'
import { OPEN_TODO } from '../chat/TodoCards'
import { decidedOf, judgedCommands } from '../chat/waiting'
import { useAsk } from '../memory/useAsk'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { since } from '../usage/period'
import { fineLine, markdown, newestLine, stamp, weekStart, whoOf } from './decisionLog'

type Chip = 'left' | 'today' | 'week' | 'unseen'
const CHIPS: [Chip, string][] = [
  ['left', 'Since I left'],
  ['today', 'Today'],
  ['week', 'Week'],
  ['unseen', 'Not seen'],
]
const EMPTY: Record<Chip, string> = {
  left: 'Nothing was decided for you since you left.',
  today: 'Nothing was decided for you today.',
  week: 'Nothing was decided for you this week.',
  unseen: 'Nothing waits for your OK.',
}
const MOST = 5 // rows shown before "Show all"
const LINK: Record<Decision['link']['kind'], string> = {
  question: 'The question',
  command: 'The command',
  task: 'The task',
  agent: 'The agent',
}

interface Props {
  /** Reads the project's decision log from a moment on - `unseen`: what waits for your OK, of any age. Throws
   *  ApiError. */
  onLoad: (since: string | null, unseen?: boolean) => Promise<DecisionLog>
  /** When the project's last ☾ Away started; null: it had none ("Since I left" is not offered). */
  leftAt: string | null
  /** Opens a chat: where a decision's card, command or agent is. */
  onOpenChat?: (conversationId: string) => void
  /** "Open in Ready for you" asked for it in view - "unseen": at Not seen; `onOpened` once it is. */
  asked?: 'unseen' | 'any' | null
  onOpened?: () => void
  /** How many were decided since you left, read with "Since I left" (the page's first line); null: more than the log
   *  gives. */
  onLeft?: (count: number | null) => void
}

/**
 * Ready for you's Decided for you (karar defteri): what was decided for you in the project in a period - by the
 * Orchestrator, KOLONİ's judge or a rule of yours - with why, from the record, and your OK and Change on it where they
 * still work. Copy as Markdown copies it as masked as shown.
 */
export function Decisions({ onLoad, leftAt, onOpenChat, asked = null, onOpened, onLeft }: Props) {
  const id = useId()
  // (Since I left first where there is a ☾ Away to have left by - known once it is read: so at the render.)
  const [picked, setPicked] = useState<Chip | null>(null)
  const chip = chipOf(picked, leftAt)
  const box = useRef<HTMLElement>(null)
  const { log, error, reread } = useLog(onLoad, chip, leftAt, onLeft)

  useEffect(() => {
    if (!asked) return
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (asked === 'unseen') setPicked('unseen')
    box.current?.scrollIntoView?.({ block: 'start' })
    box.current?.focus()
    onOpened?.()
  }, [asked, onOpened])

  return (
    <section ref={box} tabIndex={-1} aria-labelledby={id} className="decisions">
      <Head id={id} log={log} chip={chip} left={leftAt !== null} onPick={setPicked} />
      {error && (
        <div role="alert" className="alert">
          The decisions could not be read: {error}
        </div>
      )}
      {log && <Body key={chip} log={log} chip={chip} onOpenChat={onOpenChat} onDone={reread} />}
    </section>
  )
}

/** What the store hears that changes the log: the To-do list's tasks and, of the open chat, what was decided and waits
 *  for your OK - as one text, so that only a change of it reads the log again. */
const heardOf = (backlog: BacklogTask[] | null, conv: ConvState | null) =>
  [
    ...(backlog ?? []).map(task => `${task.id}:${task.status}:${task.po?.lead ?? ''}:${task.po?.seen ?? ''}`),
    ...(conv ? [...decidedOf(conv), ...judgedCommands(conv)].map(one => one.id) : []),
  ].join(',')

/**
 * The log as its chip asks it: read again after your OK or Change, on what the store hears change it (a task decided, a
 * card answered or changed, a command judged or seen) and when the window comes back. Another period - or another
 * project's reader - shows none of the last one's rows meanwhile, nor copies them as its.
 */
function useLog(
  onLoad: Props['onLoad'],
  chip: Chip,
  leftAt: string | null,
  onLeft: Props['onLeft'],
): { log: DecisionLog | null; error: string | null; reread: () => void } {
  const [log, setLog] = useState<DecisionLog | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [again, setAgain] = useState(0)
  const heard = useApp(s => heardOf(s.backlog, s.conv))
  const shown = useRef<[string, Props['onLoad']] | null>(null)
  const from = chip === 'left' && leftAt ? leftAt : chip === 'week' ? weekStart() : since('today')!
  useEffect(() => {
    const back = () => setAgain(n => n + 1)
    window.addEventListener('focus', back)
    return () => window.removeEventListener('focus', back)
  }, [])
  useEffect(() => {
    let live = true
    const key = `${chip} ${from}`
    if (shown.current?.[0] !== key || shown.current[1] !== onLoad) {
      shown.current = [key, onLoad]
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLog(null)
    }
    ;(chip === 'unseen' ? onLoad(null, true) : onLoad(from)).then(
      read => {
        if (!live) return
        setLog(read)
        setError(null)
        if (chip === 'left') onLeft?.(read.more ? null : read.rows.length)
      },
      err => live && (setLog(null), setError(errorText(err))),
    )
    return () => {
      live = false
    }
  }, [onLoad, from, again, chip, onLeft, heard])
  return { log, error, reread: () => setAgain(n => n + 1) }
}

/** The period shown: the one picked - Since I left only where there is a ☾ Away to have left by -, else since you left
 *  where you did, else today. */
const chipOf = (picked: Chip | null, leftAt: string | null): Chip =>
  picked === 'left' && !leftAt ? 'today' : (picked ?? (leftAt ? 'left' : 'today'))

/** Its title - how many, how many not seen - and the period's chips. */
function Head(props: { id: string; log: DecisionLog | null; chip: Chip; left: boolean; onPick: (one: Chip) => void }) {
  const { id, log, chip, left, onPick } = props
  const unseen = log?.rows.filter(row => row.seen === false).length ?? 0
  return (
    <div className="decisions-head">
      <h2 id={id}>
        Decided for you{' '}
        <span className="muted">
          {log && `${log.rows.length}${log.more ? '+' : ''}`}
          {unseen > 0 && `, ${unseen} not seen`}
        </span>
      </h2>
      <div role="group" aria-label="Decisions since" className="chips decisions-chips">
        {CHIPS.filter(([one]) => one !== 'left' || left).map(([one, label]) => (
          <button key={one} type="button" className="chip" aria-pressed={chip === one} onClick={() => onPick(one)}>
            {label}
          </button>
        ))}
      </div>
    </div>
  )
}

type Done = (said?: string) => void

interface BodyProps {
  log: DecisionLog
  chip: Chip
  onOpenChat?: (id: string) => void
  onDone: () => void
}

function Body({ log, chip, onOpenChat, onDone }: BodyProps) {
  const [all, setAll] = useState(false)
  const [said, setSaid] = useState<string | null>(null)
  const fine = log.judge_fine > 0 && <p className="muted memory-hint">{fineLine(log.judge_fine)}</p>
  if (log.rows.length === 0)
    return (
      <>
        <p className="muted">{EMPTY[chip]}</p>
        {fine}
        {said && (
          <p role="status" className="muted">
            {said}
          </p>
        )}
      </>
    )
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(markdown(log, CHIPS.find(([one]) => one === chip)![1]))
      setSaid('Copied')
    } catch (err) {
      setSaid(`Not copied: ${errorText(err)}`)
    }
  }
  const done: Done = what => {
    setSaid(what ?? null)
    onDone()
  }
  return (
    <>
      <ol className="decisions-rows" aria-label="Decisions, newest first">
        {(all ? log.rows : log.rows.slice(0, MOST)).map(row => (
          <Row key={row.id} row={row} onOpenChat={onOpenChat} onDone={done} />
        ))}
      </ol>
      {log.more && <p className="muted memory-hint">{newestLine(log.rows.length)}</p>}
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
        {said && (
          <span role="status" className="muted">
            {said}
          </span>
        )}
      </p>
    </>
  )
}

/** Where a row is: its chat's title, or To-do. */
const whereOf = (row: Decision) => row.chat ?? (row.kind === 'task' ? 'To-do' : null)

/** A row: when, who, where, KOLONİ's sentence and the words it is of - an agent's or a model's, shown as quotes, never
 *  as markup - why, and what you can still do about it. */
function Row({ row, onOpenChat, onDone }: { row: Decision; onOpenChat?: (id: string) => void; onDone: Done }) {
  const where = whereOf(row)
  return (
    <li className="decision">
      <span className="muted decision-time">{stamp(row.at)}</span>
      <div className="decision-body">
        <span className="decision-head">
          <b className={`decision-who who-${row.who}`}>{whoOf(row)}</b>
          {where && <span className="muted decision-where">{where}</span>}
          {row.seen === false && <span className="decision-unseen">not seen</span>}
        </span>
        <span>
          {row.what}
          {row.quote && (
            <>
              {': '}
              {row.kind === 'command' ? <code>{row.quote}</code> : <q>{row.quote}</q>}
            </>
          )}
          {row.answer && (
            <>
              {' → '}
              <b className="decided-a">{row.answer}</b>
            </>
          )}
        </span>
        {row.why && <q className="muted decision-why">{row.why}</q>}
        <RowActions row={row} onOpenChat={onOpenChat} onDone={onDone} />
      </div>
    </li>
  )
}

/** The record a row is of, by its id ("answer:<question id>"). */
const recordOf = (row: Decision) => row.id.slice(row.id.indexOf(':') + 1)
/** Whether a row is of the open chat: its store is told at once, as its own box told it. */
const here = (row: Decision) =>
  row.conversation_id !== null && useApp.getState().conv?.conversation.id === row.conversation_id

/** Your OK on a row: it stays, seen. On a To-do task it decides nothing - the Orchestrator's word seen, the task as it is. */
async function ok(row: Decision): Promise<void> {
  const s = useApp.getState()
  const id = recordOf(row)
  if (row.kind === 'task') return s.seenTask(id)
  if (row.kind === 'command') return here(row) ? s.commandSeen(id) : void (await api.post(`/commands/${id}/seen`))
  return here(row) ? s.decidedOk(id) : void (await api.post(`/questions/${id}/ok`))
}

/** Your Change: another answer, to the agent that asked while it works; a To-do choice the other way - only in the state
 *  its row showed (`expect`): one moved on since is refused, never an agent's change dropped or applied by it. */
async function change(row: Decision, answer: string): Promise<void> {
  const s = useApp.getState()
  const id = recordOf(row)
  if (row.kind === 'task') {
    const added = row.answer === 'Add'
    await api.post(`/backlog/${id}/decide`, {
      decision: added ? 'reject' : 'approve',
      expect: added ? 'added' : 'proposed',
    })
    await Promise.all([s.loadBacklog(), s.loadBoard()])
    return
  }
  if (here(row)) return s.decidedChange(id, answer)
  await api.post(`/questions/${id}/change`, { answer })
}

/** The other answers Change can give a row: a card's, as kept; a To-do choice's, the other way. */
const choicesOf = (row: Decision) =>
  row.undo !== 'change' ? [] : row.kind === 'task' ? [row.answer === 'Add' ? 'Reject' : 'Add'] : (row.options ?? [])

/** What can still be done about a row: where it is, your OK while it is not seen, and Change while it works - or why it
 *  can't be undone. */
function RowActions({ row, onOpenChat, onDone }: { row: Decision; onOpenChat?: (id: string) => void; onDone: Done }) {
  const { busy, error, ask } = useAsk()
  // (read again either way: refused, it may have moved on since the row was read - its row says so)
  const act = (what: () => Promise<void>, said?: string) => void ask(what).then(fine => onDone(fine ? said : undefined))
  const sent = row.kind === 'task' ? undefined : 'Sent to the agent that asked, while it works'
  return (
    <div className="decision-actions">
      <RowLink row={row} onOpenChat={onOpenChat} />
      {row.seen === false && (
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => act(() => ok(row))}>
          OK
        </button>
      )}
      {choicesOf(row).map(choice => (
        <button
          key={choice}
          type="button"
          className="btn btn-small"
          disabled={busy}
          onClick={() => act(() => change(row, choice), sent)}
        >
          Change → {choice}
        </button>
      ))}
      {row.undo === 'none' && row.undo_reason && (
        <span className="muted decided-note">can't be undone: {row.undo_reason}</span>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
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
