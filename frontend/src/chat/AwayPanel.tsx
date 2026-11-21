import { ArrowDown, ArrowUp, DotsSixVertical } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import type { Away, BacklogTask, PermissionMode } from '../api/types'
import { clock } from '../backlog/awayText'
import { useAsk } from '../memory/useAsk'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { LEVELS } from './levels'

/** The most To-do tasks one Go away takes. */
const MOST = 10
const DECIDES = ['its agents’ questions', 'a sub-agent to open on its own model', 'go on or stop at a step limit', 'a delete a line of yours allows (Check what I said first)']
const WAITS = ['outside the folder, your home, Windows', 'sending work off this machine, a git remote', '.git, .koloni, secrets, the main branch', 'another model that costs money', 'Take in, Discard, Commit']

/** A task Away may take: proposed or to do, and not one the Orchestrator turned down for you. */
const takes = (task: BacklogTask) => (task.status === 'proposed' || task.status === 'todo') && task.po?.lead !== 'no'
/** The lower of two levels: a task runs at no more than the chat's and the To-do page's. */
const lower = (one: PermissionMode, other: PermissionMode) => (MODES.indexOf(one) <= MODES.indexOf(other) ? one : other)
const MODES = Object.keys(LEVELS) as PermissionMode[]
const weekday = (iso: string) => new Date(iso).toLocaleDateString([], { weekday: 'short' })

interface Props {
  conv: ConvState
  /** The Orchestrator's offer it opens from: its places kept out and limits, as heard from you. */
  offer?: Away
  onClose: () => void
}

/**
 * ☾ Away (0.1.5): this chat's turn finishes, then the To-do tasks ticked here are worked through in this order - the
 * new ones from this chat ticked already; what the Orchestrator decides for you and what always waits; the limits; Go
 * away. Nothing starts before Go away.
 */
export function AwayPanel({ conv, offer, onClose }: Props) {
  const cid = conv.conversation.id
  const backlog = useApp(s => s.backlog)
  const todoLevel = useApp(s => s.backlogAuto?.permission_mode)
  useEffect(() => {
    if (!backlog) void useApp.getState().loadBacklog()
  }, [backlog])
  const tasks = (backlog ?? []).filter(takes)
  const [order, setOrder] = useState<string[] | null>(null)
  const [ticked, setTicked] = useState<Set<string> | null>(null)
  const [limits, setLimits] = useState<Limits>({ until: clock(offer?.until), money: offer?.money == null ? '' : String(offer.money), kept: (offer?.kept_out ?? []).join(', ') })
  const { busy, error, ask } = useAsk()
  const ids = [...(order ?? []).filter(id => tasks.some(t => t.id === id)), ...tasks.map(t => t.id).filter(id => !order?.includes(id))]
  const on = ticked ?? new Set(tasks.filter(t => t.proposed_in === cid).slice(0, MOST).map(t => t.id))
  const tick = (id: string) => setTicked(new Set(on.has(id) ? [...on].filter(one => one !== id) : [...on, id]))
  const move = (at: number, by: number) => setOrder(ids.map((id, i) => (i === at ? ids[at + by] : i === at + by ? ids[at] : id)))
  const go = () =>
    void ask(() =>
      useApp.getState().goAway(cid, {
        task_ids: ids.filter(id => on.has(id)),
        order: ids,
        until: limits.until || null,
        money: limits.money === '' ? null : Number(limits.money),
        kept_out: limits.kept.split(/[,\n]/).map(one => one.trim()).filter(Boolean),
      }),
    ).then(done => done && onClose())
  return (
    <div className="away-panel-body">
      <h3 className="away-panel-head">
        <span aria-hidden>☾</span> You’re away
      </h3>
      <p className="muted">The Orchestrator finishes this chat, then works through To-do in order. It decides for you where it safely can.</p>
      <p className="muted">
        The tasks run at <b>{LEVELS[lower(conv.conversation.permission_mode, todoLevel ?? conv.conversation.permission_mode)].name}</b> - the lower of this chat’s level and the To-do
        page’s.
      </p>
      {ids.length > 0 && <AwayTasks tasks={ids.map(id => tasks.find(t => t.id === id)!)} cid={cid} on={on} onTick={tick} onMove={move} />}
      <AwayColumns />
      <AwayLimits limits={limits} currency={offer?.currency ?? 'USD'} onChange={setLimits} />
      <div className="memory-actions">
        <button type="button" className="btn btn-small btn-primary" disabled={busy} onClick={go}>
          Go away
        </button>
        <button type="button" className="btn btn-small" onClick={onClose}>
          Cancel
        </button>
      </div>
      <details className="more">
        <summary>How it works</summary>
        <p className="muted">
          Each To-do task works in its own copy; your project does not change while you’re away, and you take the work in when you’re back. What always waits does not stop the work: the
          agent goes on with the rest. Away lasts until you’re back - press I’m back, or write in a chat.
        </p>
      </details>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}

interface TasksProps {
  tasks: BacklogTask[]
  cid: string
  on: Set<string>
  onTick: (id: string) => void
  onMove: (at: number, by: number) => void
}

/** The open To-do tasks in the order Away takes them: ticked ones only, at most ten; moved up or down. */
function AwayTasks({ tasks, cid, on, onTick, onMove }: TasksProps) {
  return (
    <section aria-label="Then from To-do">
      <div className="kicker">Then from To-do, in this order</div>
      <ol className="away-tasks">
        {tasks.map((task, i) => (
          <li key={task.id} className="away-task">
            <DotsSixVertical size={12} aria-hidden />
            <label className="away-grow">
              <input type="checkbox" checked={on.has(task.id)} disabled={!on.has(task.id) && on.size >= MOST} onChange={() => onTick(task.id)} /> {task.title}
            </label>
            <span className="tag">{task.proposed_in === cid ? 'new · from this chat' : `on To-do since ${weekday(task.created_at)}`}</span>
            <button type="button" className="icon-btn" aria-label={`Move ${task.title} up`} disabled={i === 0} onClick={() => onMove(i, -1)}>
              <ArrowUp size={12} />
            </button>
            <button type="button" className="icon-btn" aria-label={`Move ${task.title} down`} disabled={i === tasks.length - 1} onClick={() => onMove(i, 1)}>
              <ArrowDown size={12} />
            </button>
          </li>
        ))}
      </ol>
    </section>
  )
}

/** What the Orchestrator decides for you while you're away, and what always waits for you. */
function AwayColumns() {
  return (
    <div className="away-cols">
      {(
        [
          ['Decides for you', DECIDES],
          ['Always waits for you', WAITS],
        ] as const
      ).map(([title, said]) => (
        <div key={title} className="away-col">
          <div className="kicker">{title}</div>
          <ul>
            {said.map(one => (
              <li key={one}>{one}</li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

interface Limits {
  until: string
  money: string
  kept: string
}

/** The limits: none unless you set one (the user, 6 Nov) - a stop time, a spend limit, the places kept out. */
function AwayLimits({ limits, currency, onChange }: { limits: Limits; currency: string; onChange: (limits: Limits) => void }) {
  return (
    <div className="away-limits">
      <label>
        Until <input type="time" className="input away-inline" value={limits.until} onChange={e => onChange({ ...limits, until: e.target.value })} />
      </label>
      <label>
        spend at most{' '}
        <input type="number" className="input away-inline" min={0} step={0.5} value={limits.money} onChange={e => onChange({ ...limits, money: e.target.value })} /> {currency}
      </label>
      <label>
        kept out <input className="input away-inline mono" placeholder="files or folders, commas between" value={limits.kept} onChange={e => onChange({ ...limits, kept: e.target.value })} />
      </label>
    </div>
  )
}
