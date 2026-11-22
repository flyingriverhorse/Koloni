import { titleOf } from '../agents/agentStatus'
import { liveKind } from '../agents/liveLine'
import type { Away, Team } from '../api/types'
import { activityOf } from '../canvas/deriveGraph'
import { turnTokens } from '../shell/tokens'
import { activeRun, type ConvState } from '../state/applyEvent'
import { leadQuestion } from './chatLine'
import { testsRunningSince } from './checked'

export type ChatStatus =
  /** `tests`: since when a whole suite gone on after the last answer runs (S6); null: none. */
  | { tone: 'ready'; who: string; queued: number; tests: string | null }
  | { tone: 'running'; what: string; since: string | null; wrote: number | null; kind: string | null; queued: number }
  | { tone: 'asks'; who: string; queued: number }
  | { tone: 'away'; what: string; queued: number }

/** Where ☾ Away stands: "Away · To-do 1 of 2: Add a bye line · 3 decided for you · 1 waits", or every task looked at. */
export function awayLine(away: Away): string {
  const m = away.jobs.length
  const working = away.jobs.findIndex(job => job.state === 'working')
  const at = working >= 0 ? working : away.jobs.findIndex(job => job.state === 'next')
  const where = !m ? 'nothing on To-do' : at < 0 ? `To-do ${m} of ${m} looked at` : `To-do ${at + 1} of ${m}: ${away.jobs[at].title}`
  const waits = away.counts.waits ?? 0
  return ['Away', where, ...(away.decided.length ? [`${away.decided.length} decided for you`] : []), ...(waits ? [`${waits} waits`] : [])].join(' · ')
}

/**
 * Where the chat stands, for the line over its message box (0.1.5): ready; at work - what its Orchestrator does now (as
 * its box on the canvas says it), since its turn began, the turn's tokens written and its tier; or waiting for your
 * answer; or, its project away (☾ Away), where that stands. `queued`: messages that wait for after this turn.
 */
export function statusOf(conv: ConvState | null, teams: Team[], away: Away | null = null): ChatStatus {
  const queued = conv?.runs.filter(r => r.status === 'queued').length ?? 0
  const run = conv && activeRun(conv)
  // (☾ Away of its project: said while nothing of this chat is at work.)
  const gone = away?.status === 'running' && away.project_id === conv?.conversation.project_id && run?.status !== 'running'
  return gone ? { tone: 'away', what: awayLine(away), queued } : chatStatus(conv, teams, run, queued)
}

function chatStatus(conv: ConvState | null, teams: Team[], run: ReturnType<typeof activeRun> | null, queued: number): ChatStatus {
  const lead = conv?.agents.findLast(a => a.depth === 0 && (!run || a.run_id === run.id))
  const who = titleOf(lead?.name || 'Lead', teams)
  if (conv && leadQuestion(conv)) return { tone: 'asks', who, queued }
  if (!conv || !run) return { tone: 'ready', who, queued, tests: conv && testsRunningSince(conv) }
  // (Before its Orchestrator is on record, the turn waits for its model.)
  const what = lead?.run_id === run.id ? activityOf(lead, run, conv, teams) : 'Waiting for the model…'
  return { tone: 'running', what, since: run.started_at, wrote: turnTokens(conv, run).output_tokens, kind: lead ? liveKind(lead, run.model_id) : null, queued }
}
