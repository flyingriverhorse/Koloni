import { AT_WORK } from '../agents/agentStatus'
import type { Agent, FileChange, Merge } from '../api/types'
import type { ConvState } from '../state/applyEvent'

/**
 * A sub-agent changes files in a working copy of the project of its own: the project gets
 * the changes when its work is over - asked for once per agent where you are asked. An agent
 * it opens works in the same copy. The lead, and a CLI with tools of its own, work in the
 * project itself.
 */

const nameOf = (agent: Agent) => agent.name || agent.role_name
/** A lead's copy is its turn's room's - or, in a side of a comparison (slice 54), the side's own. */
const roomsCopy = (state: Pick<ConvState, 'runs'>, lead: Agent) => !state.runs.some(r => r.id === lead.run_id && r.compare_id)
type Seen = Pick<ConvState, 'agents' | 'runs'> & Partial<Pick<ConvState, 'conversation'>>
/** Whose a lead's copy is said to be: its turn's recipe's (slice 84b-2: a chat team's agents work in one), its room's; null: a side's own. */
const leadsCopy = (state: Seen, lead: Agent) =>
  // (B-107: also once the chat's teams changed after its turn.)
  state.conversation?.teams.some(row => row.state?.run_id === lead.run_id) || state.runs.some(run => run.id === lead.run_id && run.teams?.length)
    ? 'the recipe’s'
    : roomsCopy(state, lead)
      ? 'the room’s'
      : null

/** The agent whose copy this agent changes files in: itself, or the one above it that has one. */
export function copyOwner(state: Pick<ConvState, 'agents'>, agent: Agent): Agent | null {
  let at: Agent | undefined = agent
  while (at?.copy?.state === 'parent') {
    const above: string | null = at.parent_agent_id
    at = state.agents.find(a => a.id === above)
  }
  return at?.copy?.state === 'own' ? at : null
}

/** What an agent's box says of where it changes files; null for one that works in the project like the lead. */
export function copyLine(state: Seen, agent: Agent): string | null {
  if (agent.copy?.state === 'too_big') return 'too big to copy — works in the project'
  if (agent.copy?.state === 'failed') return 'could not be copied — works in the project'
  const owner = copyOwner(state, agent)
  if (!owner) return null
  // A lead works in the project: a copy in its name is the one its turn's room, or recipe, works in.
  const whose = owner.depth === 0 ? leadsCopy(state, owner) : null
  if (whose) return owner.id === agent.id ? `holds ${whose} copy` : `works in ${whose} copy`
  if (owner.id !== agent.id) return `works in ${nameOf(owner)}'s copy`
  return owner.copy?.on_branch ? `works on branch ${owner.copy.on_branch}` : 'works in its own copy'
}

/**
 * Where a change is that was made in a working copy and is not in the project (yet):
 * "in Coder's copy". Null for every other change.
 */
export function inCopyOf(state: Seen, change: Pick<FileChange, 'status' | 'agent_id'>): string | null {
  if (change.status !== 'in_copy') return null
  const agent = state.agents.find(a => a.id === change.agent_id)
  const owner = agent && copyOwner(state, agent)
  const whose = owner?.depth === 0 ? leadsCopy(state, owner) : null
  if (whose) return `in ${whose} copy`
  return owner ? `in ${nameOf(owner)}'s copy` : 'in its copy'
}

/** The changes of an agent that wait for your decision, if any do. */
export function pendingMerge(state: Pick<ConvState, 'merges'>, agentId: string): Merge | null {
  return state.merges.find(m => m.agent_id === agentId && m.status === 'pending') ?? null
}

/**
 * Its working copy was kept on disk (its turn broke off, or it holds files that were not taken): still yours to decide -
 * take what it holds into the project, or delete the folder. Not a turn that waits for you.
 * ("kept" since B-359; "interrupted" with a folder from a server older than the page.)
 */
export const isKept = (merge: Merge) => (merge.status === 'kept' || merge.status === 'interrupted') && merge.kept_in != null

/**
 * How an agent's own working copy stands, by what you have to do about it: its work is finished and waits for your Take
 * in, it was kept, or the agent is still at work in it. Null: no copy of its own, or nothing left to do with it. One answer
 * for the Workspace's Changes and for Where the work is, so the two never disagree.
 */
export function copyStands(state: Pick<ConvState, 'merges'>, agent: Agent): 'waits' | 'kept' | 'at work' | null {
  if (agent.copy?.state !== 'own') return null
  if (pendingMerge(state, agent.id)) return 'waits'
  if (state.merges.some(m => m.agent_id === agent.id && isKept(m))) return 'kept'
  return AT_WORK.has(agent.status) ? 'at work' : null
}

/**
 * B-156: a kept copy that holds a file - one that holds none is no copy to take in (its card still offers Discard).
 * shortcut: a kept copy whose folder could not be looked at shows only the files on record, maybe none; upgrade if
 * such a copy is seen left uncounted.
 */
export const keptToTake = (merge: Merge) => isKept(merge) && merge.files.length > 0

/** An agent stopped at the end of the steps it was given (K-devam-butce): "stopped after the N steps it was given". */
export const atGivenSteps = (error: string | null) => error?.startsWith('stopped after the ') ?? false

/** An agent's error is a step limit's: the app's, its role's ("stopped at its role's limit of N steps"), or its budget's. */
export const atAStepLimit = (error: string | null) => error === 'step_limit' || (error?.startsWith("stopped at its role's limit of") && error.includes('step')) || atGivenSteps(error)

/**
 * K-devam-butce: a kept card whose agent stopped at a step limit while its turn still runs: Continue gives it more
 * steps, and it goes on in its kept copy. (After the turn: a message to the Lead opens it again.)
 */
export const canContinue = (state: Pick<ConvState, 'agents' | 'runs'>, merge: Merge) => {
  const agent = state.agents.find(a => a.id === merge.agent_id)
  return isKept(merge) && agent?.status === 'failed' && atAStepLimit(agent.error) && state.runs.some(r => r.id === merge.run_id && (r.status === 'running' || r.status === 'waiting_approval'))
}

/** A merge that has a card to show: its changes wait for you, its copy was kept, or what was taken of it has a commit on record - offered or made. */
export const hasCard = (merge: Merge) => merge.status === 'pending' || isKept(merge) || merge.commit != null

/** What is shown as a card for an agent (`hasCard`). */
export function cardMerges(state: Pick<ConvState, 'merges'>, agentId: string): Merge[] {
  return state.merges.filter(m => m.agent_id === agentId && hasCard(m))
}

/** The agents' scratch, `.koloni/tmp/` (K-koloni-klasor): its changes stay on record for their card and undo, but no list of what changed shows them. */
export const inScratch = (path: string) => path.replace(/\\/g, '/').replace(/^\.\//, '').toLowerCase().startsWith('.koloni/tmp/')

/** The changes that are in the project, or were: what "Changes" counts. One still in a copy is not. */
export function inProject(changes: FileChange[]): FileChange[] {
  return changes.filter(c => c.status !== 'in_copy')
}

/** How many files an agent's own working copy changed so far, from its record (slice 70): the "± N files" of its node; null for one with no copy of its own, or none changed yet. */
export function copyFiles(state: Pick<ConvState, 'agents' | 'fileChanges'>, agent: Agent): number | null {
  if (agent.copy?.state !== 'own') return null
  const mine = (id: string) => {
    const by = state.agents.find(a => a.id === id)
    return !!by && copyOwner(state, by)?.id === agent.id
  }
  return new Set(state.fileChanges.filter(f => f.status === 'in_copy' && mine(f.agent_id) && !inScratch(f.path)).map(f => f.path)).size || null
}
