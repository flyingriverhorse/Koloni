import { AGENT_STATUS, WAITS } from '../agents/agentStatus'
import type { Board, Run } from '../api/types'
import { TERMINAL } from '../state/applyEvent'

type BoardConversation = Board['conversations'][number]

/**
 * How many things of a conversation wait for the user, as its chat's cards do: each change to
 * approve and each question of an agent that asks, an agent that asks something else (a command,
 * to let a sub-agent start - its opener is the one that asks, so a proposed one is counted only
 * where nobody else asks), each set of changes to take in or discard, and a plan that waits for a yes.
 * shortcut: what an agent asks that the Board has no kind for (a command, a folder) counts once, and not
 * at all beside a change or a question of its; give it a kind on the server (app/api/board.py) if missed.
 */
export function waitCount(conversation: Pick<BoardConversation, 'agents' | 'merges_pending' | 'turn'>): number {
  // (`?? 0`: a server older than the page counts no kind)
  const asking = conversation.agents
    .filter(agent => agent.status === 'waiting_approval')
    .reduce((sum, agent) => sum + Math.max((agent.changes_to_approve ?? 0) + (agent.questions ?? 0), 1), 0)
  const proposed = conversation.agents.some(agent => agent.status === 'proposed')
  return conversation.merges_pending + Math.max(asking, proposed ? 1 : 0) + (conversation.turn?.plan_waits ? 1 : 0)
}

/** It waits for you, works, or how its last turn ended; null before its first turn or before the Board is read. */
export function standingOf(on?: BoardConversation): 'waits' | 'working' | Run['status'] | null {
  if (!on) return null
  if (waitCount(on) > 0) return 'waits'
  const turn = on.turn
  if (on.agents.length > 0 || (turn && !TERMINAL.has(turn.status))) return 'working'
  return turn?.status ?? null
}

/** How it stands, in the words and colour the rest of the app uses: its row in the list, its tab (slice 86d). */
export function standingSaid(on?: BoardConversation): readonly [label: string, color: string] | null {
  const standing = standingOf(on)
  if (!on || !standing) return null
  if (standing === 'waits') return [`${WAITS} · ${waitCount(on)}`, AGENT_STATUS.waiting_approval[1]]
  return AGENT_STATUS[standing === 'working' ? 'running' : standing]
}

/** What waits for the user in every conversation of the project, and on its backlog: the rail's badge. */
export const waitingTotal = (board: Board | null) => (board ? board.conversations.reduce((sum, c) => sum + waitCount(c), board.backlog_waiting) : 0)

/** What waits for the user in one conversation, as the Board says it: the Workspace button's number (slices 42c, 42d). */
export const waitingIn = (board: Board | null, conversationId: string | undefined) => {
  const row = board?.conversations.find(c => c.conversation_id === conversationId)
  return row ? waitCount(row) : null
}
