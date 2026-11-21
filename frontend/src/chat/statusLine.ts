import { titleOf } from '../agents/agentStatus'
import { liveKind } from '../agents/liveLine'
import type { Team } from '../api/types'
import { activityOf } from '../canvas/deriveGraph'
import { turnTokens } from '../shell/tokens'
import { activeRun, type ConvState } from '../state/applyEvent'
import { leadQuestion } from './chatLine'

export type ChatStatus =
  | { tone: 'ready'; who: string; queued: number }
  | { tone: 'running'; what: string; since: string | null; wrote: number | null; kind: string | null; queued: number }
  | { tone: 'asks'; who: string; queued: number }

/**
 * Where the chat stands, for the line over its message box (0.1.5): ready; at work - what its Orchestrator does now (as
 * its box on the canvas says it), since its turn began, the turn's tokens written and its tier; or waiting for your
 * answer. `queued`: messages that wait for after this turn.
 */
export function statusOf(conv: ConvState | null, teams: Team[]): ChatStatus {
  const queued = conv?.runs.filter(r => r.status === 'queued').length ?? 0
  const run = conv && activeRun(conv)
  const lead = conv?.agents.findLast(a => a.depth === 0 && (!run || a.run_id === run.id))
  const who = titleOf(lead?.name || 'Lead', teams)
  if (conv && leadQuestion(conv)) return { tone: 'asks', who, queued }
  if (!conv || !run) return { tone: 'ready', who, queued }
  // (Before its Orchestrator is on record, the turn waits for its model.)
  const what = lead?.run_id === run.id ? activityOf(lead, run, conv, teams) : 'Waiting for the model…'
  return { tone: 'running', what, since: run.started_at, wrote: turnTokens(conv, run).output_tokens, kind: lead ? liveKind(lead, run.model_id) : null, queued }
}
