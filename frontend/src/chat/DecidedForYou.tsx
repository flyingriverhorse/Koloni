import { useId, useState } from 'react'
import { errorText } from '../api/client'
import type { BacklogTask, Question } from '../api/types'
import { useAsk } from '../memory/useAsk'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { hearsNothing } from '../agents/agentStatus'
import { decidedOf, decidedTasks } from './waiting'
import { shownOption, shownQuestion } from '../agents/teamRun'

/** A time as this machine's clock says it: "02:10". */
const clock = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }) : '')
const OVER = new Set(['completed', 'failed', 'cancelled', 'rejected', 'interrupted'])

/**
 * "Decided for you" (K-vekil-karar): what the Lead answered for you while you were away, with its reason. OK takes one
 * off the list; Change sends your own choice to the agent that asked while it is still at work - a card of KOLONİ's
 * (Ask me, opening an agent) went on at once, and cannot be undone.
 */
export function DecidedForYou({ state }: { state: ConvState }) {
  const id = useId()
  // Whom the last Change went to: sent while it works, not yet read (its card is gone once said) -
  // said while it is at work in this chat.
  const [sent, setSent] = useState<{ id: string; name: string } | null>(null)
  const items = decidedOf(state)
  const backlog = useApp(s => s.backlog)
  const tasks = decidedTasks(backlog, state.conversation.id)
  const working = sent && state.agents.some(a => a.id === sent.id && !OVER.has(a.status))
  const said = working && (
    <p role="status" className="muted decided-note">
      Sent to {sent.name} while it works
    </p>
  )
  if (items.length === 0 && tasks.length === 0) return said || null
  // (By the time itself, not as the clock says it: a night goes past midnight.)
  const times = items.map(q => q.answered_at ?? '').sort()
  const [from, to] = [clock(times[0]), clock(times.at(-1) ?? null)]
  const span = from === to ? from : `${from}–${to}`
  return (
    <section aria-labelledby={id} className="cmd-approval card-tell decided">
      <h3 id={id} className="kicker cmd-approval-kicker decided-head">
        {/* shortcut: at Full auto the Lead decides in a watched turn too (K-fullauto-sorma); say
            "at Full auto" here by the chat's level if the heading is seen to mislead. */}
        Decided for you while you were away
        <span className="decided-count">
          {items.length + tasks.length}
          {span && ` · ${span}`}
        </span>
      </h3>
      {items.map(q => (
        <Decided key={q.id} question={q} state={state} onSent={setSent} />
      ))}
      {tasks.map(task => (
        <DecidedTask key={task.id} task={task} />
      ))}
      {said}
    </section>
  )
}

function Decided({ question, state, onSent }: { question: Question; state: ConvState; onSent: (to: { id: string; name: string }) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const asker = state.agents.find(a => a.id === question.agent_id)
  const kind = useApp(s => s.providers.find(p => p.name === asker?.provider_name)?.kind)
  const name = asker?.name || asker?.role_name || 'An agent'
  const cant = question.leave
    ? 'the next step ran'
    : !asker || OVER.has(asker.status)
      ? `${name} has finished`
      : hearsNothing(asker.provider_mode, kind)
        ? `${name} works on in its CLI, which hears nothing more`
        : null
  // shortcut: a free answer has no Change - only OK; give it a field of its own if one is wanted.
  const others = cant ? [] : question.options.filter(option => option !== question.answer)
  const act = async (what: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await what()
    } catch (err) {
      setError(errorText(err))
      setBusy(false)
    }
  }
  return (
    <div className="decided-item">
      <div className="decided-q">{question.leave ? shownQuestion(question) : `${name} asked: ${question.question}`}</div>
      <div>
        Orchestrator chose <b className="decided-a">{question.answer && shownOption(question.answer, question.leave)}</b>
      </div>
      <div className="decided-why">“{question.lead_why}”</div>
      <div className="decided-btns">
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => void act(() => useApp.getState().decidedOk(question.id))}>
          OK
        </button>
        {others.map(option => (
          <button key={option} type="button" className="btn btn-small" disabled={busy} onClick={() => void act(() => useApp.getState().decidedChange(question.id, option).then(() => onSent({ id: question.agent_id, name })))}>
            Change → {shownOption(option, question.leave)}
          </button>
        ))}
        {cant && <span className="muted decided-note">can't be undone: {cant}</span>}
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}

/** A follow-up task the Assistant PO proposed at a turn's end, and the Orchestrator's word on it at Full auto (6 Nov). OK keeps
 *  that word; Change undoes it - one added is taken off the To-do list while it is still todo, one said no to is added. */
function DecidedTask({ task }: { task: BacklogTask }) {
  const { busy, error, ask } = useAsk()
  const added = task.po?.lead === 'add'
  const s = useApp.getState()
  const cant = added && task.status !== 'todo' ? 'it has started' : null
  return (
    <div className="decided-item">
      <div className="decided-q">The Assistant PO proposed a To-do task: {task.title}</div>
      <div>
        Orchestrator chose <b className="decided-a">{added ? 'Add' : 'Reject'}</b>
      </div>
      <div className="decided-why">“{task.po?.lead_why}”</div>
      <div className="decided-btns">
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => void ask(() => (added ? s.seenTask(task.id) : s.decideTask(task.id, 'reject')))}>
          OK
        </button>
        {cant ? (
          <span className="muted decided-note">can't be undone: {cant}</span>
        ) : (
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => void ask(() => s.decideTask(task.id, added ? 'reject' : 'approve'))}>
            Change → {added ? 'Reject' : 'Add'}
          </button>
        )}
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}
