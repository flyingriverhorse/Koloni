import type { Agent, Run } from '../api/types'
import { activeRun, type ConvState } from '../state/applyEvent'
import { money } from '../usage/cost'
import { waitingCards } from './chatLine'

/** What a turn cost so far (`GET /api/runs/{id}/spent`): null where nothing of it is priced. */
export interface Spent {
  spent: number | null
  currency: string | null
  at_least: boolean
}

/** An agent below the Orchestrator still at work, for the line over the chat: not one that waits for your yes - that is
 *  a card, counted with what waits for you. */
const WORKING: ReadonlySet<Agent['status']> = new Set(['queued', 'running', 'waiting', 'blocked'])

/** The turn at work in the chat - also while it waits for your answer on a card: its agents work on. */
export const runningTurn = (conv: ConvState): Run | null => activeRun(conv)

/** The agents of the turn at work below its Orchestrator, oldest first. */
export const agentsAtWork = (conv: ConvState, run: Run): Agent[] =>
  conv.agents.filter(one => one.run_id === run.id && one.depth > 0 && WORKING.has(one.status))

/** The plan its Orchestrator shows (update_plan, or its CLI's own), as it says it. */
export const leadPlan = (conv: ConvState, run: Run) => {
  const lead = conv.agents.find(one => one.run_id === run.id && one.depth === 0)
  return (lead && conv.live[lead.id]?.plan) || null
}

/** "step 3 of 6": the step after those done, at most the last. */
export function stepOf(plan: NonNullable<ReturnType<typeof leadPlan>>): string {
  const done = plan.filter(step => step.status === 'completed').length
  return `step ${Math.min(done + 1, plan.length)} of ${plan.length}`
}

const counted = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/**
 * Task 6 (0.1.11): the line over the chat while its turn runs - "3 agents at work · step 3 of 6 · 1 waits for you ·
 * ≈ 0.40 USD": its agents at work, its Orchestrator's step, what waits for you, what it cost so far (where priced).
 * Null where the turn runs with none of the first three, or no turn runs.
 */
export function atWorkLine(conv: ConvState, spent: Spent | null): string | null {
  const run = runningTurn(conv)
  if (!run) return null
  const agents = agentsAtWork(conv, run).length
  const plan = leadPlan(conv, run)
  const waits = waitingCards(conv)
  if (!agents && !plan?.length && !waits) return null
  return [
    agents > 0 && counted(agents, 'agent at work', 'agents at work'),
    plan?.length && stepOf(plan),
    waits > 0 && `${waits} ${waits === 1 ? 'waits' : 'wait'} for you`,
    spent?.spent != null &&
      spent.currency &&
      money({ amount: spent.spent, currency: spent.currency, at_least: spent.at_least }),
  ]
    .filter(Boolean)
    .join(' · ')
}

/** "09:41": when an agent started, as this machine's clock says it. */
export const sinceOf = (agent: Agent) =>
  new Date(agent.started_at ?? agent.created_at).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })

/** An agent's words in what is said of its wait: on one line, cut, in quotes. */
const waitWords = (text: string) => {
  const line = text.split(/\s+/).join(' ').trim()
  return `“${line.length <= 80 ? line : `${line.slice(0, 79)}…`}”`
}

/**
 * explain_wait (28 Nov): what an agent at work waits for, read only from the records the chat holds - as agents_at_work
 * says it (`app/waits.py`): its card for you, its question, its command running, another agent, a place. Null where the
 * records say nothing: never a reason made up.
 */
export function waitsFor(conv: ConvState, agent: Agent): string | null {
  const commands = conv.commands.filter(one => one.agent_id === agent.id)
  const asked = commands.find(one => one.status === 'proposed')
  if (asked) return `your yes on its command ${waitWords(asked.command)}`
  const change = conv.fileChanges.find(one => one.agent_id === agent.id && one.status === 'proposed')
  if (change) return `your yes on its change to ${waitWords(change.path)}`
  const question = conv.questions.findLast(one => one.agent_id === agent.id && one.status === 'pending')
  if (question)
    return question.leave
      ? `an answer on a card of KOLONİ’s: ${waitWords(question.question)}`
      : `an answer to its question ${waitWords(question.question)}`
  const running = commands.find(one => one.status === 'running')
  if (running) {
    const since = running.started_at ? ` since ${sinceOf({ ...agent, started_at: running.started_at })}` : ''
    return `its command ${waitWords(running.command)}, running${since}`
  }
  return waitsOther(conv, agent)
}

/** `waitsFor`'s part with no record of its own calls: another agent, or a place. */
function waitsOther(conv: ConvState, agent: Agent): string | null {
  if (agent.waiting_for?.agent_name)
    return `${agent.waiting_for.agent_name}, which holds ${waitWords(agent.waiting_for.path)}`
  if (agent.status === 'queued')
    return agent.queued_on
      ? `a place at ${agent.queued_on.provider} (${agent.queued_on.at_work} of ${agent.queued_on.most} at work there)`
      : 'a place among the turn’s agents at work'
  if (agent.status === 'proposed') return 'your yes to open it'
  if (agent.status === 'waiting') {
    const own = conv.agents.filter(one => one.parent_agent_id === agent.id && WORKING.has(one.status))
    if (own.length) return `its own agents at work: ${own.map(one => one.name).join(', ')}`
  }
  return null
}
