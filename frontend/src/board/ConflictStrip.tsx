import type { Board } from '../api/types'
import { conflictLine } from './conflicts'

/**
 * Above a conversation: the files one of its agents holds and an agent of another conversation
 * waits for, or the other way round. Nothing is asked of the user - the wait ends by itself
 * when the holder's work is over - but both conversations show it.
 */
export function ConflictStrip({ board, conversationId }: { board: Board | null; conversationId: string | null }) {
  const mine = (board?.conflicts ?? []).filter(
    c => c.holder.conversation_id === conversationId || c.waiting.some(w => w.conversation_id === conversationId),
  )
  if (!board || mine.length === 0) return null
  return (
    <div className="board-strip" role="status" aria-label="Another conversation wants the same file">
      {mine.map(conflict => (
        <div key={`${conflict.path} ${conflict.holder.conversation_id}`}>{conflictLine(board, conflict)}</div>
      ))}
    </div>
  )
}
