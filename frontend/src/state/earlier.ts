import { api } from '../api/client'
import type { Run, Snapshot } from '../api/types'
import { fromSnapshot, type ConvState } from './applyEvent'

/** The turns a long chat opens on, and reads at a time on "Show earlier turns" (~600 turns were ~15 MB at once). */
export const TURNS_PAGE = 40

// The most turns one read asks for (the server's own most: `api.conversations.snapshot`).
const MOST_TURNS = 1000

/** How many turns a chat is read with: its newest page - or, read again (a dropped stream), as many as are shown, at
 *  most `MOST_TURNS` (asked more, the server refuses, and a reconnect would ask again for ever). */
export const turnsOf = (conv: ConvState | null, again: boolean) =>
  Math.min(MOST_TURNS, Math.max(TURNS_PAGE, again ? (conv?.runs.length ?? 0) : 0))

/**
 * A turn asked for by its id - a job's, a night's - in the chat open now: its older pages are read until it is there,
 * or none is left. Whether that chat is the one open.
 */
export async function reachTurn(
  get: () => { conv: ConvState | null; loadEarlier(): Promise<void> },
  conversationId: string,
  runId: string,
): Promise<boolean> {
  const here = () => get().conv?.conversation.id === conversationId
  while (here() && get().conv?.olderFrom && !get().conv?.runs.some(run => run.id === runId)) await get().loadEarlier()
  return here()
}

/** The page of turns before those shown (`ConvState.olderFrom`). Throws ApiError. */
export const earlierPage = (conv: ConvState) =>
  api.get<Snapshot>(`/conversations/${conv.conversation.id}?turns=${TURNS_PAGE}&before=${conv.olderFrom}`)

// What of a chat is of its turns: an older page's rows go before the ones shown, each row once.
const TURNS_KEYS = [
  'messages',
  'runs',
  'toolCalls',
  'fileChanges',
  'commands',
  'webRequests',
  'agents',
  'channelMessages',
  'questions',
  'discussions',
  'discussionPosts',
  'boardPosts',
  'merges',
] as const

/**
 * A page of older turns (`?turns=&before=`) put before those shown, each row once (the older page's copy: the newer
 * read). An older turn that still waited came with the first page: every row of a turn goes back to its turn's place.
 */
export function withEarlier(state: ConvState, page: Snapshot): ConvState {
  const older = fromSnapshot(page)
  const next = { ...state, older: older.older, olderFrom: older.olderFrom } as unknown as Record<
    string,
    { id: string }[]
  >
  for (const key of TURNS_KEYS) {
    const seen = new Set<string>()
    next[key] = [...older[key], ...state[key]].filter(row => !seen.has(row.id) && !!seen.add(row.id))
  }
  // (Stable: a turn's rows keep their own order.)
  const runs = (next.runs as Run[]).sort((a, b) => a.created_at.localeCompare(b.created_at))
  const place = new Map(runs.map((run, n) => [run.id, n]))
  const at = (row: object) => ('run_id' in row ? (place.get(String(row.run_id)) ?? -1) : -1)
  for (const key of TURNS_KEYS) next[key].sort((a, b) => at(a) - at(b))
  return next as unknown as ConvState
}
