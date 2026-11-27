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

/** The turn at work in the chat - only one that runs: a turn that waits for your approval has nobody at work. */
export const runningTurn = (conv: ConvState): Run | null => {
  const run = activeRun(conv)
  return run?.status === 'running' ? run : null
}

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
