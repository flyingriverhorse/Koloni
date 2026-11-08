import { turnTeams } from '../agents/teamRun'
import type { Agent, BoardPost, Run } from '../api/types'
import { TERMINAL, activeRun, type ConvState } from '../state/applyEvent'
import { messageTime } from '../topics/topics'

/** Who wrote a note; a note with no agent is yours, or KOLONİ's own (the note it writes as a turn ends, G7). */
export function writerOf(state: ConvState, post: BoardPost): string {
  if (post.koloni) return 'KOLONİ'
  if (post.agent_id === null) return 'You'
  return state.agents.find(a => a.id === post.agent_id)?.name || 'Agent'
}

/** A note's element, by its id: where the canvas's notebook row opens the Notes tab (K-shared-bagli). */
export const noteId = (id: string) => `note-${id}`

/**
 * The turn whose notebook the Notes tab shows: the one at work, or else the last one
 * that started. A turn still in the queue has no notebook yet.
 */
export function notebookRun(state: ConvState): Run | null {
  return activeRun(state) ?? state.runs.findLast(r => r.started_at !== null) ?? null
}

/** The turns that have a notebook to show: every one that has started, oldest first. */
export function notebookRuns(state: ConvState): Run[] {
  return state.runs.filter(r => r.started_at !== null)
}

const ASKED_CHARS = 40

/** A message in the picker: its time, what was asked, how many notes. */
export function turnLabel(state: ConvState, run: Run): string {
  const asked = (state.messages.find(m => m.run_id === run.id && m.role === 'user')?.content ?? '').trim().replace(/\s+/g, ' ')
  const words = asked.length > ASKED_CHARS ? `${asked.slice(0, ASKED_CHARS)}…` : asked
  const notes = state.boardPosts.filter(p => p.run_id === run.id).length
  return `${messageTime(state, run.id)}${words ? ` · ${words}` : ''} · ${notes} ${notes === 1 ? 'note' : 'notes'}`
}

/** Why a turn's notebook cannot be written on; null while it can. */
export function closedReason(run: Run | null): string | null {
  if (!run) return 'Nothing is at work. A note can be written while something is.'
  return TERMINAL.has(run.status) ? 'This work is over: its notebook is closed.' : null
}

/** Not opened: one you declined, or one still waiting for you to approve it. */
const NOT_OPENED = new Set(['rejected', 'proposed'])

/**
 * Who a note is for, and who has it. It is for every agent of its turn but the one that
 * wrote it and those not opened: declined by you, or still waiting for your approval (one
 * you approve counts from then on). An agent has read it once the note was handed
 * to it: the server says so with the note, and each hand-over since is a message of that
 * agent's that carries the note. An agent that finished before, or never asks KOLONİ for
 * anything, was not handed it and stays unread.
 */
export function readersOf(state: ConvState, post: BoardPost): { read: Agent[]; unread: Agent[] } {
  const handed = new Set(post.read_by)
  for (const message of state.messages) {
    if (message.board_post_id === post.id && message.agent_id) handed.add(message.agent_id)
  }
  // K-not-oda: a team's own note is for its agents, where the turn's record of the team says who they are; else (a team
  // with no recipe, framed by roles on the canvas only) for those it was handed to.
  const team = post.team_id !== null && !post.everyone ? turnTeams(state, post.run_id).find(row => row.team_id === post.team_id) : undefined
  const meant = state.agents.filter(
    a =>
      a.run_id === post.run_id &&
      a.id !== post.agent_id &&
      !NOT_OPENED.has(a.status) &&
      (post.team_id === null || post.everyone || (team ? team.state.agents.includes(a.id) || a.depth === 0 : handed.has(a.id))),
  )
  return { read: meant.filter(a => handed.has(a.id)), unread: meant.filter(a => !handed.has(a.id)) }
}

/**
 * "handed to 2 of 3 · not yet to Tester": only what the records say. A note is on record
 * as handed over when it was put before the agent's next step; whether the model took it
 * in is not something KOLONİ knows.
 */
export function readLine(state: ConvState, post: BoardPost): string {
  const run = state.runs.find(r => r.id === post.run_id)
  if (post.koloni && run?.ended_at && Date.parse(post.created_at) >= Date.parse(run.ended_at)) return 'written as this work ended, for the next turn'
  const { read, unread } = readersOf(state, post)
  if (read.length + unread.length === 0) return post.team && !post.everyone ? `for ${post.team} only · handed to nobody yet` : 'no other agent at this work'
  const line = `handed to ${read.length} of ${read.length + unread.length}`
  return unread.length > 0 ? `${line} · not yet to ${unread.map(a => a.name || 'Agent').join(', ')}` : line
}
