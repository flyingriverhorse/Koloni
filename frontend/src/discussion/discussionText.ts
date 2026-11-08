import type { Agent, Discussion } from '../api/types'
import type { ConvState } from '../state/applyEvent'

const OUTCOME: Record<NonNullable<Discussion['outcome']>, string> = {
  agreed: 'nothing left to say',
  round_limit: 'the round limit was reached',
  ended_by_user: 'you ended it',
  too_few: 'fewer than two were left to talk',
  budget: 'at its budget',
}

/** Where a discussion stands, in a few words. */
export function discussionLine(discussion: Discussion): string {
  if (discussion.status === 'running') {
    return discussion.round > 0 ? `Round ${discussion.round} of ${discussion.max_rounds}` : 'Starting'
  }
  if (discussion.status === 'ended') {
    return `Ended: ${discussion.outcome ? OUTCOME[discussion.outcome] : 'it is over'}`
  }
  return discussion.status === 'cancelled' ? 'Stopped' : 'Interrupted'
}

/** The member whose turn it is: the one at work while the discussion runs. */
export function speakerOf(state: ConvState, discussion: Discussion): Agent | undefined {
  if (discussion.status !== 'running') return undefined
  const members = new Set(discussion.members.filter(m => m.status === 'in').map(m => m.agent_id))
  return state.agents.find(a => members.has(a.id) && a.status === 'running')
}

export function nameIn(state: ConvState, agentId: string | null): string {
  if (agentId === null) return 'You'
  return state.agents.find(a => a.id === agentId)?.name || 'Agent'
}
