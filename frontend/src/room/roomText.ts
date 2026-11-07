import { titleOf } from '../agents/agentStatus'
import type { Agent, Room, RoomItem, RoomPost } from '../api/types'
import { asksOutside } from '../chat/toolSummary'
import { foldRepeats } from '../shell/repeats'
import type { ConvState } from '../state/applyEvent'

const OUTCOME: Record<NonNullable<Room['outcome']>, string> = {
  agreed: 'everybody’s work is over',
  budget: 'its budget was reached',
  ended_by_user: 'you ended it',
  ended_by_opener: 'the agent that opened it ended it',
  too_few: 'fewer than two members were still working',
}

/** Whether a room still runs: it can be written into, ended and given more. */
export const isRunning = (room: Room) => room.status === 'sharing' || room.status === 'working'

/** Where a room stands, in a few words. */
export function roomLine(room: Room): string {
  if (isRunning(room) && room.paused) return 'Paused: nothing is posted or spent until you resume it'
  if (room.status === 'sharing') return 'Sharing the work out'
  if (room.status === 'working') return 'At work'
  if (room.status === 'ended') {
    // Its own reason, where there is more to say than the outcome.
    if (room.outcome === 'budget' && room.why && room.why !== 'unanswered') return `Ended: its budget of ${room.why} was reached`
    if (room.outcome === 'too_few' && room.why === 'unanswered') return 'Ended: everybody’s work is over, and a question was left unanswered'
    if (room.outcome === 'ended_by_opener' && !room.agent_id) return 'Ended: the Orchestrator ended it' // (K-oda-izle: your room, followed)
    return `Ended: ${room.outcome ? OUTCOME[room.outcome] : 'it is over'}`
  }
  return room.status === 'cancelled' ? 'Stopped' : 'Interrupted'
}

/** Where a room stands, as its window's head, its tab and its line in the chat say it: "at work", "done · 1 of 2" (items done of all). */
export function roomTag(state: Pick<ConvState, 'roomItems'>, room: Room): string {
  if (isRunning(room) && room.paused) return 'paused'
  if (room.status === 'sharing') return 'sharing the work out'
  if (room.status === 'working') return 'at work'
  if (room.status !== 'ended') return room.status === 'cancelled' ? 'stopped' : 'interrupted'
  const items = state.roomItems.filter(i => i.room_id === room.id)
  const of = items.length ? ` · ${items.filter(i => i.status === 'done').length} of ${items.length}` : ''
  const why =
    room.outcome === 'agreed' ? 'done'
    : room.outcome === 'ended_by_user' ? 'you ended it'
    : room.outcome === 'ended_by_opener' ? (room.agent_id ? 'its opener ended it' : 'the Orchestrator ended it')
    : room.outcome === 'budget' ? `out of ${room.why && room.why !== 'unanswered' ? room.why : 'budget'}`
    : room.outcome === 'too_few' ? (room.why === 'unanswered' ? 'a question was left' : 'fewer than two working')
    : 'over'
  return why + of
}

/** Whether a room came to its own end with every item done: its tag is drawn as good news. */
export const allDone = (state: Pick<ConvState, 'roomItems'>, room: Room) =>
  room.outcome === 'agreed' && state.roomItems.every(i => i.room_id !== room.id || i.status === 'done')

export const MEMBER: Record<Room['members'][number]['status'], string> = {
  in: 'at work',
  waiting: 'waiting for a post',
  done: 'done',
  left: 'left',
}

export const ITEM: Record<RoomItem['status'], string> = { open: 'open', taken: 'taken', done: 'done', dropped: 'dropped' }

/**
 * A member in the room's tags: "Coder · at work" - "Coder · paused" once a Pause holds it, its step over (B-167: it
 * said "at work" while it waited for the Resume).
 */
export function memberTag(state: Pick<ConvState, 'agents'>, room: Room, member: Room['members'][number]): string {
  const held = isRunning(room) && room.paused && member.status === 'in' && state.agents.find(a => a.id === member.agent_id)?.status === 'waiting'
  return `${memberName(state, member)} · ${held ? 'paused' : MEMBER[member.status]}`
}

/** What an agent of the room is called: "You" for nobody (your own post). */
export function nameIn(state: Pick<ConvState, 'agents'>, agentId: string | null): string {
  if (agentId === null) return 'You'
  return titleOf(state.agents.find(a => a.id === agentId)?.name || 'Agent')
}

/** A member by its name - or, in the moment before its agent is opened, by its role. */
export function memberName(state: Pick<ConvState, 'agents'>, member: Room['members'][number]): string {
  return state.agents.find(a => a.id === member.agent_id)?.name || member.role
}

/** Who waits for a room - the agent that opened it, else its turn's lead: the room's one working copy is kept in its name. */
export function leadOf(state: Pick<ConvState, 'agents'>, room: Room): Agent | undefined {
  return state.agents.find(a => (room.agent_id ? a.id === room.agent_id : a.run_id === room.run_id && a.depth === 0))
}

/** R178: the one who watches a running room though no member - its opener, or the Lead you let follow it - on a
 * line of its own: "Watched by Orchestrator · can post, invite, end"; '' where nobody does. */
export function watchedBy(state: Pick<ConvState, 'agents'>, room: Room): string {
  const watcher = isRunning(room) && room.lead_follows === 'on' ? leadOf(state, room) : undefined
  return watcher ? `Watched by ${nameIn(state, watcher.id)} · can post, invite, end` : ''
}

/** Whether a post is the watcher's own - its opener's or the Lead's, never a member's. */
export const byWatcher = (state: Pick<ConvState, 'agents'>, room: Room, agentId: string | null) =>
  agentId !== null && agentId === leadOf(state, room)?.id && !room.members.some(m => m.agent_id === agentId)

/** A room's goal, saying who opened it where an agent did: "Lead opened a room: …". */
export function roomGoal(state: Pick<ConvState, 'agents'>, room: Room): string {
  return room.agent_id ? `${nameIn(state, room.agent_id)} opened a room: ${room.goal}` : room.goal
}

/** The agents a member - or its opener, following it - asked into the room that wait for your word: the room's opener opens them, not the member. */
export function invitedTo(state: Pick<ConvState, 'agents' | 'toolCalls'>, room: Room): Agent[] {
  const members = new Set([...room.members.map(m => m.agent_id), room.agent_id])
  return state.agents.filter(
    a => a.status === 'proposed' && state.toolCalls.some(t => t.id === a.tool_call_id && t.name === 'invite_to_room' && members.has(t.agent_id)),
  )
}

const whole = (value: number) => (Number.isInteger(value) ? String(value) : value.toFixed(1))

/**
 * How much of what a room may spend is used, one line for each: "3 of 40 posts". A limit
 * it does not have says so; tokens no member's model reported are said to be none
 * reported, not a zero. Its tokens are billed ones (B-390): all its members' steps sent and wrote,
 * more than an agent's box beside it, which shows how much its context holds now.
 */
export function spentLines(room: Room): string[] {
  return (['posts', 'tokens', 'minutes'] as const).map(key => {
    const [used, limit] = [room.spent[key], room.budget[key]]
    const of = limit === null ? ' (no limit)' : ` of ${limit}`
    if (used === null) return `no ${key} reported${of}`
    const noun = key === 'tokens' ? 'tokens sent and written' : key
    const line = limit === null ? `${whole(used)} ${noun}${of}` : `${whole(used)} of ${limit} ${noun}`
    return key === 'tokens' ? `${line} - each step resends its context` : line
  })
}

/**
 * A room's posts in order, a line of KOLONİ's ("done": a member's report, "left") said again word for
 * word by the same member folded into its first, with how many times it was said (AC) - also with
 * others' posts between them.
 */
export function once(posts: RoomPost[]): [post: RoomPost, times: number][] {
  return foldRepeats(posts, p => (p.type === 'done' || p.type === 'left' ? `${p.agent_id} ${p.type} ${p.text}` : null), true)
}

/** What a post is, said before its text: its type, whom it is for and what it replies to. (A member's report - "done" - is under Reports: the room's head says how it stands.) */
export function postHead(state: Pick<ConvState, 'agents'>, post: RoomPost): string {
  // (B-156: its last words answer the question it was woken for.)
  if (post.type === 'done') return post.reply_to !== null ? `reply to ${post.reply_to}` : ''
  if (post.type === 'left') return 'left the room'
  if (post.type === 'ended') return 'ended the room' // (K-oda-lead: its opener's last word)
  return [
    post.type === 'said' ? null : post.type,
    post.to_agent_id && `to ${nameIn(state, post.to_agent_id)}`,
    post.reply_to !== null && `reply to ${post.reply_to}`,
  ]
    .filter(Boolean)
    .join(' · ')
}

/** The agents at work in a room: its members, and whoever works for one of them. */
export function inRoom(state: Pick<ConvState, 'agents'>, room: Room): Map<string, Agent> {
  const members = new Set(room.members.map(m => m.agent_id))
  const inside = new Map<string, Agent>()
  // (Agents are stored parents first, so one pass collects every sub-tree.)
  for (const agent of state.agents) {
    if (members.has(agent.id) || (agent.parent_agent_id && inside.has(agent.parent_agent_id))) inside.set(agent.id, agent)
  }
  return inside
}

/** Whether something of a room waits for your word: a card of one of its agents, or its changes. */
export function waitsForYou(state: ConvState, room: Room): boolean {
  const inside = inRoom(state, room)
  return (
    state.questions.some(q => q.status === 'pending' && inside.has(q.agent_id)) ||
    state.commands.some(c => c.status === 'proposed' && inside.has(c.agent_id)) ||
    state.fileChanges.some(f => f.status === 'proposed' && inside.has(f.agent_id)) ||
    state.webRequests.some(w => w.status === 'proposed' && inside.has(w.agent_id)) ||
    state.toolCalls.some(t => asksOutside(t) && inside.has(t.agent_id)) ||
    state.pendingRoles.some(r => inside.has(r.agent_id)) ||
    state.pendingSkills.some(r => inside.has(r.agent_id)) ||
    state.agents.some(a => a.status === 'proposed' && a.parent_agent_id !== null && inside.has(a.parent_agent_id)) ||
    invitedTo(state, room).length > 0 ||
    state.merges.some(m => m.status === 'pending' && (inside.has(m.agent_id) || m.room_id === room.id))
  )
}
