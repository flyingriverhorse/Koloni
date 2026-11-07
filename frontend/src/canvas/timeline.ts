import { AGENT_STATUS, AT_WORK, titleOf } from '../agents/agentStatus'
import { homeOf, isOwnSubAgent, ownSubAgentTask, subAgentIds } from '../agents/ownWork'
import type { Run, ToolCall } from '../api/types'
import { TOOL_STATUS } from '../chat/ToolRow'
import { turnTokens } from '../shell/tokens'
import type { ConvState } from '../state/applyEvent'

/** A stretch of the turn, in ms since the epoch. */
export interface Span {
  from: number
  to: number
}

/** Something an agent waited for: whose word ("you", another agent's name; null: nobody on record) and on what. A time not on record is null. */
export interface Wait {
  from: number | null
  to: number | null
  who: string | null
  what: string
  /** It still waits: it runs to now. */
  open: boolean
  /** Of one that still waits for you: its row's key on Ready for you (`waitingOf`), where it is answered. */
  key?: string
}

export interface Mark {
  at: number
  what: string
}

/** One row of the timeline: an agent of KOLONİ's, or one of a CLI's own sub-agents (`cli`). */
export interface Lane {
  id: string
  /** Whose window a click opens: a CLI's own sub-agent shows in its agent's. */
  agentId: string
  name: string
  depth: number
  cli: boolean
  /** The lane that opened it, and when (the line between them is drawn there). */
  parent: string | null
  opened: number | null
  /** Its bar: started to ended; while at work, to now. Null where not on record (never started; ended with no time). */
  from: number | null
  to: number | null
  atWork: boolean
  status: [label: string, color: string]
  calls: (Span & { name: string; status: ToolCall['status'] })[]
  waits: Wait[]
  marks: Mark[]
}

export interface Timeline extends Span {
  /** The turn's own length: started to ended, or to now while at work; null where not known. */
  length: number | null
  /** Something in it is at work: what is drawn grows with the time. */
  atWork: boolean
  agents: number
  tokens: Pick<Run, 'input_tokens' | 'output_tokens'>
  lanes: Lane[]
  /** What happened to the turn itself, not to one agent: a room opened for it, its budget ran out. */
  marks: Mark[]
}

const time = (iso: string | null | undefined) => (iso ? Date.parse(iso) : null)
const RUN_AT_WORK: ReadonlySet<Run['status']> = new Set(['queued', 'running', 'waiting_approval'])
/** What ended within this of beginning did not wait: no wait is drawn for it (a change approved at once, a sub-agent started at once). */
const NO_WAIT_MS = 1000

/** Where a time lies on the turn's line, as a share in percent (0 to 100). */
export function place(at: number, line: Span): number {
  const length = line.to - line.from
  return length > 0 ? Math.min(100, Math.max(0, ((at - line.from) / length) * 100)) : 0
}

/** How long something took, as it is read: "12s", "3m 05s", "1h 02m"; not known, a dash. */
export function took(ms: number | null): string {
  if (ms === null || ms < 0) return '–'
  if (ms < 1000) return ms > 0 ? '<1s' : '0s'
  const s = Math.round(ms / 1000)
  const two = (n: number) => String(n).padStart(2, '0')
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${two(s % 60)}s`
  return `${Math.floor(s / 3600)}h ${two(Math.floor(s / 60) % 60)}m`
}

/**
 * One turn as time: its agents as lanes (each sub-agent under the one that opened it), their
 * bars, the calls in them, what they waited for and what happened to them; and the turn's
 * totals. All of it from the records the conversation already has; `now` ends what is at work.
 */
export function timeline(state: ConvState, runId: string, now: number): Timeline | null {
  const run = state.runs.find(r => r.id === runId)
  if (!run) return null
  const here = <T extends { run_id: string }>(records: T[]) => records.filter(r => r.run_id === runId)
  const agents = here(state.agents)
  const calls = here(state.toolCalls)
  const subs = subAgentIds(calls)
  const callOf = new Map(calls.map(c => [c.id, c]))
  // A record made by a call inside a CLI's own sub-agent is that sub-agent's.
  const laneOf = (agentId: string, callId: string | null) => homeOf(callId ? callOf.get(callId) : undefined, subs) ?? agentId
  // An end on record; else now, for what still waits or works; else not known.
  const until = (end: string | null, open: boolean) => time(end) ?? (open ? now : null)
  // What is left at work on a turn that is over is not drawn growing.
  const runAtWork = RUN_AT_WORK.has(run.status)

  const lanes: Lane[] = []
  const add = (lane: Omit<Lane, 'calls' | 'waits' | 'marks'>) => {
    const own = calls.filter(c => !isOwnSubAgent(c) && c.agent_id === lane.agentId && homeOf(c, subs) === (lane.cli ? lane.id : null))
    lanes.push({
      ...lane,
      calls: own.flatMap(c => {
        const [from, to] = [time(c.started_at), until(c.ended_at, runAtWork && c.status === 'running')]
        return from !== null && to !== null ? [{ from, to, name: c.name, status: c.status }] : []
      }),
      waits: [],
      marks: [],
    })
    // The CLI's own sub-agents opened here, then the agents this one opened, each under it.
    for (const sub of calls.filter(c => subs.has(c.id) && c.agent_id === lane.agentId && homeOf(c, subs) === (lane.cli ? lane.id : null))) {
      const at = runAtWork && (sub.status === 'running' || sub.status === 'pending')
      add({
        id: sub.id, agentId: sub.agent_id, name: ownSubAgentTask(sub) || 'sub-agent', depth: lane.depth + 1, cli: true,
        parent: lane.id, opened: time(sub.started_at), from: time(sub.started_at), to: until(sub.ended_at, at), atWork: at,
        status: TOOL_STATUS[sub.status],
      })
    }
    if (lane.cli) return
    for (const kid of agents.filter(a => a.parent_agent_id === lane.id)) addAgent(kid, lane)
  }
  const addAgent = (a: (typeof agents)[number], parent: Pick<Lane, 'id' | 'depth'> | null) => {
    const at = runAtWork && AT_WORK.has(a.status)
    add({
      id: a.id, agentId: a.id, name: titleOf(a.name || a.role_name), depth: parent ? parent.depth + 1 : 0, cli: false,
      parent: parent?.id ?? null, opened: parent ? time(a.created_at) : null,
      from: time(a.started_at), to: a.started_at ? until(a.ended_at, at) : null, atWork: at,
      status: AGENT_STATUS[a.status],
    })
  }
  const known = new Set(agents.map(a => a.id))
  for (const a of agents.filter(a => !a.parent_agent_id || !known.has(a.parent_agent_id))) addAgent(a, null)

  const lane = new Map(lanes.map(l => [l.id, l]))
  /**
   * A wait from `begun` to `end`; while `open`, to now. One that ended within NO_WAIT_MS never was.
   * One `asked` (a record that always asks you) and left with no end is said with no length; any
   * other with no end was never asked: your settings let it through.
   */
  // `key`: the record's, as Ready for you keys its row - one that still waits for you leads there.
  const wait = (laneId: string, begun: string | null | undefined, end: string | null, open: boolean, who: string | null, what: string, asked = false, key?: string) => {
    const [from, to] = [time(begun), time(end)]
    if (from === null || (to !== null && to - from < NO_WAIT_MS) || (to === null && !open && !asked)) return
    const still = to === null && open
    lane.get(laneId)?.waits.push({ from, to: to ?? (open ? now : null), who, what, open: still, ...(still && who === you && key ? { key } : {}) })
  }
  const you = 'you'
  for (const q of here(state.questions)) wait(laneOf(q.agent_id, q.tool_call_id), q.created_at, q.answered_at, q.status === 'pending', you, 'question', true, q.id)
  // A change the CLI made was not asked about; one made in a working copy is asked about through its merge.
  const copied = new Set(here(state.merges).map(m => m.agent_id))
  for (const f of here(state.fileChanges).filter(f => f.origin !== 'cli' && !copied.has(f.agent_id)))
    wait(laneOf(f.agent_id, f.tool_call_id), f.created_at, f.decided_at, f.status === 'proposed', you, f.path, false, f.id)
  // B-316: at Full auto a command runs on no card, and what it waited for was its start - its working copy made, a place.
  // shortcut: a command has no decision time; its start stands for it, and one is taken as asked where it waits now, or its
  // card is one at every level (`danger`, its call's `why_asked`), or below Full auto - so one approved and then queued
  // counts that queue as waiting for you too, and one a rule ran unasked as well - upgrade if commands get a decided_at.
  // shortcut: a search's card (its `danger` said only while it waits) is read, once decided, as no card at Full auto; and the
  // level is the chat's now, not the one it ran at (a command keeps no level) - record both on the command if that misleads.
  const fullAuto = state.conversation.permission_mode === 'full_auto'
  for (const c of here(state.commands).filter(c => c.origin !== 'cli')) {
    const asked = c.status === 'proposed' || !fullAuto || !!c.danger || !!callOf.get(c.tool_call_id)?.why_asked
    wait(laneOf(c.agent_id, c.tool_call_id), c.created_at, c.started_at, c.status === 'proposed', asked ? you : null, c.command, false, c.id)
  }
  for (const m of here(state.merges)) wait(m.agent_id, m.created_at, m.decided_at, m.status === 'pending', you, 'changes to take in', true, m.id)
  for (const w of here(state.webRequests)) wait(laneOf(w.agent_id, w.tool_call_id), w.created_at, w.decided_at, w.status === 'proposed', you, 'web request', true, w.id)
  // (A command's why_asked - run_command's, run_skill_script's - is its card's reason: its wait is its command's, above.)
  const commanded = new Set(state.commands.map(c => c.tool_call_id))
  for (const c of calls.filter(c => c.outside_folder || (c.why_asked && !commanded.has(c.id)))) {
    // shortcut: an approval to reach outside the folder has no record of its own; it is taken to start with the call's message, which may be a little earlier - upgrade if the call gets an asked_at.
    const asked = state.messages.find(m => m.id === c.message_id)
    wait(laneOf(c.agent_id, c.id), asked?.created_at, c.started_at, c.status === 'pending', you, c.outside_folder ?? 'a secret file', true, c.id)
  }
  for (const a of agents) {
    // Asked about, it waits for you. shortcut: once started, whether it waited for your word or for a slot is not on record, so the wait is said for nobody - upgrade if an agent gets a decided_at.
    if (a.status === 'proposed' || a.status === 'rejected') wait(a.id, a.created_at, a.started_at ?? a.ended_at, a.status === 'proposed', you, 'to start', false, a.id)
    else if (a.started_at) wait(a.id, a.created_at, a.started_at, false, null, 'to start')
    // shortcut: a file another agent holds is on record only while it is held, with no time it began; its length is not known - upgrade if claims get a time.
    if (a.status === 'blocked' && a.waiting_for) lane.get(a.id)?.waits.push({ from: null, to: null, who: a.waiting_for.agent_name, what: a.waiting_for.path, open: true })
  }

  const turnMarks: Mark[] = []
  const mark = (laneId: string | null, at: number | null, what: string) => {
    if (at !== null) (laneId && lane.get(laneId) ? lane.get(laneId)!.marks : turnMarks).push({ at, what })
  }
  for (const d of here(state.discussions)) {
    mark(d.agent_id, time(d.created_at), 'discussion started')
    mark(d.agent_id, time(d.ended_at), 'discussion ended')
  }
  for (const r of here(state.rooms)) {
    mark(r.agent_id, time(r.created_at), 'room opened')
    mark(r.agent_id, time(r.ended_at), 'room ended')
  }
  for (const a of agents) {
    const limited = a.failure === 'rate_limited' || a.failure === 'credits_exhausted'
    if (a.status === 'failed') mark(a.id, time(a.ended_at), limited ? 'limit reached' : 'failed')
    if (a.status === 'cancelled') mark(a.id, time(a.ended_at), 'stopped')
  }
  if ((run.error ?? '').startsWith('budget:')) mark(null, time(run.ended_at), 'limit reached')

  const byId = new Map(agents.map(a => [a.id, a]))
  for (const l of lanes) {
    // What it waits on now, told apart (B-316): your word - a card of its, which its wait leads to - or the agents it opened.
    const kids = l.cli || byId.get(l.id)?.status !== 'waiting' ? [] : agents.filter(a => a.parent_agent_id === l.id && AT_WORK.has(a.status))
    if (l.waits.some(w => w.open && w.who === you)) l.status = AGENT_STATUS.waiting_approval
    else if (kids.length > 0) l.status = [`waits for ${kids.map(a => a.name || a.role_name).join(', ')}`, l.status[1]]
    l.waits.sort((a, b) => (a.from ?? Infinity) - (b.from ?? Infinity))
    l.marks.sort((a, b) => a.at - b.at)
    // The line from the agent that opened it meets the first of it that is drawn: what it waited for before it started, or its bar.
    const first = Math.min(l.from ?? Infinity, ...l.waits.map(w => w.from ?? Infinity))
    if (l.parent !== null && Number.isFinite(first)) l.opened = first
  }
  turnMarks.sort((a, b) => a.at - b.at)

  const started = time(run.started_at)
  const times = [
    started, time(run.ended_at), runAtWork ? now : null,
    ...lanes.flatMap(l => [l.from, l.to, l.opened, ...l.waits.flatMap(w => [w.from, w.to]), ...l.marks.map(m => m.at)]),
    ...turnMarks.map(m => m.at),
  ].filter((t): t is number => t !== null)
  const from = Math.min(...times)
  const ended = until(run.ended_at, runAtWork)
  return {
    from: Number.isFinite(from) ? from : (time(run.created_at) ?? now),
    to: times.length > 0 ? Math.max(...times) : (time(run.created_at) ?? now),
    length: started !== null && ended !== null ? ended - started : null,
    atWork: runAtWork || lanes.some(l => l.atWork || l.waits.some(w => w.open && w.to !== null)),
    agents: agents.filter(a => a.started_at).length,
    tokens: turnTokens(state, run),
    lanes,
    marks: turnMarks,
  }
}
