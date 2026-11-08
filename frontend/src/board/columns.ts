import type { Board } from '../api/types'

type BoardConversation = Board['conversations'][number]

/** The Board's two sections, and the folded "older" under the second. */
export type Column = 'work' | 'today' | 'older'

// A turn that ended without its work done: labelled so on its row.
export const BROKE = new Set(['failed', 'cancelled', 'interrupted'])
export const GOING = new Set(['queued', 'running', 'waiting_approval'])

export const count = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/**
 * Where a conversation's row goes. Work going on (an agent that waits for your word too: Ready for you lists what it
 * asks); a last turn that ended on `now`'s local day, failed or stopped too, is today's; the rest - one that never
 * ran too - are older.
 */
export function columnOf(conversation: BoardConversation, now = new Date()): Column {
  const turn = conversation.turn
  if (conversation.agents.length > 0 || (turn && GOING.has(turn.status))) return 'work'
  const at = turn?.ended_at ?? turn?.started_at
  return turn && at && new Date(at).toDateString() === now.toDateString() ? 'today' : 'older'
}

/** The earliest or the latest of some times, as they were given; null for none. */
const pick = (times: (string | null | undefined)[], latest: boolean) =>
  times
    .filter((at): at is string => Boolean(at))
    .reduce<string | null>((best, at) => (best === null || (new Date(at) > new Date(best)) === latest ? at : best), null)

/** When anything of a conversation last happened: its agents' last step, or its last turn's end. */
export const lastAt = (conversation: BoardConversation) =>
  pick([...conversation.agents.map(agent => agent.last_event_at), conversation.turn?.ended_at ?? conversation.turn?.started_at], true)

/** How long since `iso`, in the largest whole unit: "<1 min", "5 min", "3 h", "2 d". */
export function since(iso: string, now = Date.now()): string {
  const minutes = Math.floor((now - new Date(iso).getTime()) / 60_000)
  if (minutes < 1) return '<1 min'
  if (minutes < 60) return `${minutes} min`
  return minutes < 24 * 60 ? `${Math.floor(minutes / 60)} h` : `${Math.floor(minutes / (24 * 60))} d`
}
