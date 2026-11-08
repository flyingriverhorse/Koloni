import { titleOf as agentTitle } from '../agents/agentStatus'
import type { Board } from '../api/types'

type Conflict = Board['conflicts'][number]

const titleOf = (board: Board, conversationId: string) =>
  board.conversations.find(c => c.conversation_id === conversationId)?.title ?? 'another conversation'

/** "a.txt: held by Lead in «A», waited for by Lead in «B»" - one file two conversations want. */
export function conflictLine(board: Board, conflict: Conflict): string {
  const who = (one: Conflict['holder']) => `${agentTitle(one.agent_name)} in «${titleOf(board, one.conversation_id)}»`
  return `${conflict.path}: held by ${who(conflict.holder)}, waited for by ${conflict.waiting.map(who).join(' and ')}`
}
