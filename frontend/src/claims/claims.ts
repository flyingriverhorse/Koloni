import { titleOf } from '../agents/agentStatus'
import type { Agent, Team, ToolCall } from '../api/types'
import type { ConvState } from '../state/applyEvent'

/**
 * Two agents do not change one file at a time: an agent about to change a file holds it
 * until its work is done, and another that wants the same file waits for it. Waiting for a
 * file asks nothing of the user.
 */

/** The agent that holds a file may be one of another conversation of the project. */
const ELSEWHERE = 'an agent of another conversation'

/** What an agent that waits for a file says on its box: "waits for Coder · cart.py" (`teams`: a team's lead is its coordinator). */
export function waitLine(agent: Pick<Agent, 'status' | 'waiting_for'>, cid?: string, teams: Team[] = []): string | null {
  const wait = agent.status === 'blocked' ? agent.waiting_for : null
  return wait ? `waits for ${holder(wait, cid, teams)} · ${wait.path}` : null
}

/** B-140: who holds it, as the screen calls it - in another chat, named by it (a Coder waited 9 minutes, its chat said nothing of where). */
const holder = (wait: NonNullable<Agent['waiting_for']>, cid?: string, teams: Team[] = []) =>
  `${titleOf(wait.agent_name, teams) || ELSEWHERE}${wait.conversation_id && cid && wait.conversation_id !== cid ? ` in «${wait.conversation_title ?? 'another chat'}»` : ''}`

const sameFile = (a: string, b: string) => a.toLowerCase() === b.toLowerCase()

/**
 * What a call that waits for a file says in the chat: "waiting for Coder to finish with
 * cart.py". Null for every call that does not: the call is one that changes a file, it has
 * not returned, and its agent waits for a file - which is then the file of this call, as an
 * agent that waits does nothing else. (The path is the one the agent waits for: the call
 * may have written it another way.)
 */
export function callWaits(state: Pick<ConvState, 'agents'> & Partial<Pick<ConvState, 'conversation'>>, call: ToolCall): string | null {
  if (call.status !== 'running') return null
  if (call.name !== 'write_file' && call.name !== 'edit_file') return null
  const agent = state.agents.find(a => a.id === call.agent_id)
  const wait = agent?.status === 'blocked' ? agent.waiting_for : null
  if (!wait) return null
  // (Its holder's turn waits for your answer there - its Ready for you, say: answered, the file is free.)
  const frees = wait.asks_you ? ': that chat waits for your answer there' : ''
  return `waiting for ${holder(wait, state.conversation?.id)} to finish with ${wait.path}${frees}`
}

/** The files an agent holds now, by their paths. */
export function heldBy(state: Pick<ConvState, 'claims'>, agentId: string): string[] {
  return state.claims.filter(claim => claim.agent_id === agentId).map(claim => claim.path)
}

/** Who holds a file now, by name; null when nobody does. */
export function holderOf(state: Pick<ConvState, 'claims' | 'agents'>, path: string): string | null {
  const claim = state.claims.find(c => sameFile(c.path, path))
  if (!claim) return null
  const agent = state.agents.find(a => a.id === claim.agent_id)
  return agent ? agent.name || agent.role_name : ELSEWHERE
}
