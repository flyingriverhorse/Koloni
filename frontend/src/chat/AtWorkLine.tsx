import { useEffect, useId, useRef, useState } from 'react'
import { api } from '../api/client'
import { AGENT_STATUS, titleOf } from '../agents/agentStatus'
import { STEP_MARK } from '../agents/livePlan'
import { StopAndMessage } from '../canvas/agentStop'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { agentsAtWork, atWorkLine, leadPlan, runningTurn, sinceOf, type Spent } from './atWork'

/** How often, at most, what the turn cost is read again as its agents' tokens change. */
export const SPENT_EVERY_MS = 5000

/** What the turn cost so far, read as it starts and again - at most every SPENT_EVERY_MS - as its agents report tokens;
 *  null until read, for another turn, or where it could not be. */
function useSpent(runId: string | null, tokens: number): Spent | null {
  const [read, setRead] = useState<[string, Spent] | null>(null)
  const last = useRef(0)
  useEffect(() => {
    if (!runId) return
    let live = true
    const timer = setTimeout(
      () => {
        last.current = Date.now()
        api.get<Spent>(`/runs/${runId}/spent`).then(
          spent => live && setRead([runId, spent]),
          () => {},
        )
      },
      Math.max(0, last.current + SPENT_EVERY_MS - Date.now()),
    )
    return () => {
      live = false
      clearTimeout(timer)
    }
  }, [runId, tokens])
  return read && read[0] === runId ? read[1] : null
}

/**
 * Task 6 (0.1.11): the line over the chat, under its tabs, while its turn runs with agents at work, a plan or something
 * waiting for you - "3 agents at work · step 3 of 6 · 1 waits for you · ≈ 0.40 USD". It opens "At work in this turn":
 * each agent with Stop and Message, the Orchestrator's plan, and Ready for you.
 */
export function AtWorkLine({ conv }: { conv: ConvState | null }) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const run = conv && runningTurn(conv)
  const tokens = conv && run ? spentKey(conv, run.id) : 0
  // (read only while the line shows: a turn with nothing at work asks nothing)
  const spent = useSpent(run && atWorkLine(conv, null) ? run.id : null, tokens)
  const line = conv && atWorkLine(conv, spent)
  if (!conv || !run || !line) return null
  return (
    <div className="at-work">
      <button
        type="button"
        className="at-work-line"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
      >
        {line}
      </button>
      {open && <AtWorkPanel id={id} conv={conv} />}
    </div>
  )
}

/** What its agents reported so far: a change reads the cost again. */
const spentKey = (conv: ConvState, runId: string) =>
  conv.agents
    .filter(one => one.run_id === runId)
    .reduce((sum, one) => sum + (one.input_tokens ?? 0) + (one.output_tokens ?? 0), 0)

function AtWorkPanel({ id, conv }: { id: string; conv: ConvState }) {
  const run = runningTurn(conv)
  if (!run) return null
  const agents = agentsAtWork(conv, run)
  const plan = leadPlan(conv, run)
  return (
    <section id={id} className="at-work-panel" aria-label="At work in this turn">
      <h3 className="kicker">At work in this turn</h3>
      {agents.length > 0 && (
        <ul className="at-work-agents">
          {agents.map(one => {
            const name = titleOf(one.name || one.role_name)
            return (
              <li key={one.id} className="at-work-agent">
                <span>
                  {name} · {AGENT_STATUS[one.status][0]} · since {sinceOf(one)}
                </span>
                <StopAndMessage agentId={one.id} name={name} />
              </li>
            )
          })}
        </ul>
      )}
      {plan?.length ? (
        <ol className="agent-plan" aria-label="The Orchestrator's plan (its own words)">
          {plan.map((step, index) => (
            <li key={index} className={`agent-plan-${step.status}`}>
              {STEP_MARK[step.status]} {step.step}
            </li>
          ))}
        </ol>
      ) : null}
      <button type="button" className="btn btn-small" onClick={() => useApp.getState().showReady(true)}>
        Open Ready for you
      </button>
    </section>
  )
}
