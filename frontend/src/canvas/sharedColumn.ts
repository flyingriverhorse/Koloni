import type { BoardPost, Run, SharedFile, ToolCall, View } from '../api/types'
import { requestsOf } from '../agents/teamRequests'
import { writerOf } from '../notes/notesText'
import type { ConvState } from '../state/applyEvent'
import type { GraphEdge, GraphNode, TeamData } from './deriveGraph'

/** In a block, at most so many rows of each kind; the rest is "+N more notes" - a click unfolds the block (`foldGraph`). */
export const OF_A_KIND = 2

/** A row of a block: what it is, and what it says. */
export interface SharedRow {
  /** (K-belge-ciktilari: 'output', a file an agent made - `outputCards`.) */
  kind: 'file' | 'notebook' | 'memory' | 'more' | 'folder' | 'output'
  text: string
  /** A file's path in the shared folder; an output's in the project. */
  path?: string
  /** An output's kind of view: what its badge says. */
  what?: View['kind']
  /** A note's id, and on hover the note in full: who wrote it, in which turn and when; a memory row's, what was written to it. */
  note?: string
  title?: string
}

/** K-shared-bagli (mockup Z3): what one team - or, with no team, one agent - shared, noted and remembered in a turn. */
export interface SharedData {
  /** Whose: "Everyone" (the Lead's, contracts/, decisions/, the way to all the shared files), a team, an agent; null for
   * a request's contract. */
  who: string | null
  colour: string
  projectId: string | null
  runId: string
  rows: SharedRow[]
  /** K-belge-ciktilari: an output card's rows unfolded, where `rows` holds only the first of them (`foldGraph`). */
  all?: SharedRow[]
}

const add = <T>(map: Map<string, T[]>, key: string, value: T) => map.set(key, [...(map.get(key) ?? []), value])
const plural = (count: number, one: string) => `${count} ${one}${count === 1 ? '' : 's'}`
/** A `remember` call as its row's hover says it: "Lead: the words · notes.md:2-3 · put forward". */
function noted(state: ConvState, call: ToolCall): string {
  let args: Record<string, unknown> = {}
  try {
    const read: unknown = JSON.parse(call.arguments || '{}')
    if (read && typeof read === 'object' && !Array.isArray(read)) args = read as Record<string, unknown>
  } catch {
    // not readable: nothing is made up for it
  }
  const { text, file, start_line: start, end_line: end } = args
  const where = typeof file === 'string' && typeof start === 'number' ? `${file}:${start}-${typeof end === 'number' ? end : start}` : null
  const who = state.agents.find(a => a.id === call.agent_id)?.name || 'Agent'
  return [`${who}: ${typeof text === 'string' ? text : '(not readable)'}`, where, args.propose === true && 'put forward'].filter(Boolean).join(' · ')
}

const time = (at: string) => new Date(at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })

/**
 * What the turn's teams shared, noted and remembered (K-shared-bagli; cards, batch-26): a card for each team that wrote to
 * the shared folder, to the notebook or the project's memory - or read from it - joined to its frame by one line; with
 * no team, a card for each agent, joined to its box. What is everyone's - the Lead's, contracts/, decisions/ - is the
 * card beside the Lead, joined to it, and the way to all the shared files at its foot (with nothing else, that alone);
 * a request's contract is a card of its own, on an arm from the request's line. Nothing used, no card.
 * `nodes`, `edges`: the turn's, as drawn so far.
 */
export function sharedColumn(state: ConvState, run: Run, turn: number | null, nodes: GraphNode[], edges: GraphEdge[], shared: SharedFile[]): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const own = nodes.filter(n => n.runId === run.id)
  const lead = state.agents.find(a => a.run_id === run.id && a.depth === 0)
  // Whose an agent's use is: its team's frame; the Lead's (or the user's) everyone's; with no frame, its own box.
  const anchorOf = (agentId: string | null): string => {
    const node = own.find(n => n.id === `agent:${agentId}`)
    return !agentId || agentId === lead?.id || !node ? 'top' : (node.team ?? node.id)
  }
  const [files, notes] = [new Map<string, string[]>(), new Map<string, BoardPost[]>()]
  const memory = new Map<string, { facts: Set<string>; lookups: number; written: string[] }>()
  const used = (anchor: string) => memory.get(anchor) ?? memory.set(anchor, { facts: new Set(), lookups: 0, written: [] }).get(anchor)!
  const calls = state.toolCalls.filter(t => t.run_id === run.id).sort((a, b) => a.seq - b.seq)

  // What its agents wrote to the shared folder, where write_shared says it went; contracts/ is every team's.
  for (const call of calls.filter(t => t.name === 'write_shared' && t.status === 'succeeded')) {
    const path = /^written: \.koloni\/shared\/(\S+)/.exec(call.result ?? '')?.[1]
    if (path) add(files, path.startsWith('contracts/') ? 'top' : anchorOf(call.agent_id), path)
  }
  // What a room between teams decided in the turn: no call names its file - the folder's own times do.
  // shortcut: a decision of another turn written while this one ran is shown with it; name its turn in the listing if met.
  const [from, to] = [Date.parse(run.started_at ?? ''), run.ended_at ? Date.parse(run.ended_at) : Infinity]
  for (const file of shared) if (file.path.startsWith('decisions/') && Date.parse(file.at) >= from && Date.parse(file.at) <= to) add(files, 'top', file.path)
  // A request's contract: on an arm from its line where that is drawn, else everyone's. Several requests on one line
  // (asked twice one way) have one card, a row for each contract: two cards of one id had the arm end short of it.
  const contracts = new Map<GraphEdge, Set<string>>()
  for (const request of requestsOf(state, run.id)) {
    // (N7: not the full stop after it.)
    const path = /contracts\/[\w.-]+/.exec(request.lead?.task ?? '')?.[0].replace(/\.$/, '')
    const line = edges.find(e => e.request?.calls.includes(request.call.id))
    if (path && line) contracts.set(line, (contracts.get(line) ?? new Set()).add(path))
    else if (path) add(files, 'top', path)
  }
  // The notebook: each note by whoever wrote it (KOLONİ's own are on the Notes tab).
  for (const post of state.boardPosts.filter(p => p.run_id === run.id && !p.koloni).sort((a, b) => a.seq - b.seq)) add(notes, anchorOf(post.agent_id), post)
  // The memory: the facts its agents were given as they started, what they looked up and wrote.
  for (const agent of state.agents.filter(a => a.run_id === run.id)) for (const fact of agent.facts_given ?? []) used(anchorOf(agent.id)).facts.add(fact)
  for (const call of calls) {
    if (call.name === 'recall') used(anchorOf(call.agent_id)).lookups++
    // What was written, as the removed inspector said it: who, the words, the lines they rest on, put forward. (A refused one is not.)
    if (call.name === 'remember' && call.status === 'succeeded') used(anchorOf(call.agent_id)).written.push(noted(state, call))
  }

  // (Folded: so many of a kind and "+N more files"; unfolded, `all`: every row.)
  const kept = (rows: SharedRow[], what: string, newest = false, all = false): SharedRow[] =>
    all || rows.length <= OF_A_KIND
      ? rows
      : [...(newest ? rows.slice(-OF_A_KIND) : rows.slice(0, OF_A_KIND)), { kind: 'more' as const, text: `+${plural(rows.length - OF_A_KIND, `more ${what}`)}` }]
  const rowsOf = (anchor: string, team: string | null, all = false): SharedRow[] => {
    const part = memory.get(anchor)
    const said = part && [part.facts.size && `${plural(part.facts.size, 'fact')} given`, part.lookups && plural(part.lookups, 'lookup'), part.written.length && `${part.written.length} written`].filter(Boolean).join(' · ')
    return [
      ...kept([...new Set(files.get(anchor))].map(path => ({ kind: 'file' as const, text: path, path })), 'file', false, all),
      ...kept(
        (notes.get(anchor) ?? []).map(post => {
          const who = writerOf(state, post)
          const head = [team, who, turn && `turn ${turn}`, time(post.created_at), 'to the notebook'].filter(Boolean).join(' · ')
          return { kind: 'notebook' as const, text: `${who}: “${post.content.split('\n')[0]}”`, note: post.id, title: `${head}\n${post.content}` }
        }),
        'note',
        true,
        all,
      ),
      ...(said ? [{ kind: 'memory' as const, text: said, ...(part.written.length && { title: part.written.join('\n') }) }] : []),
      // The whole shared folder, where it has files - written in this turn or before (the user: things gather there).
      ...(anchor === 'top' && shared.length ? [{ kind: 'folder' as const, text: `All shared files (${shared.length}) →` }] : []),
    ]
  }

  // (A block with rows left out unfolds in place, as an output card does: its "+N more" rows and "Fewer" fold it again.)
  const block = (anchor: string, who: string | null, colour: string, rows: SharedRow[], all?: SharedRow[]): GraphNode => ({
    id: `shared:${run.id}:${anchor}`,
    kind: 'shared',
    runId: run.id,
    refId: run.id,
    data: {
      who,
      colour,
      projectId: state.conversation.project_id,
      runId: run.id,
      rows,
      ...(all && rows.some(r => r.kind === 'more') && { all: [...all, { kind: 'more' as const, text: 'Fewer' }] }),
    } satisfies SharedData,
  })
  const added: GraphNode[] = []
  const lines: GraphEdge[] = []
  const top = rowsOf('top', null)
  if (top.length) {
    const one = block('top', 'Everyone', 'var(--accent)', top, rowsOf('top', null, true))
    added.push(one)
    // Joined to the Lead's box as a team's card to its frame (the user, 28 Oct: with no line it read as no one's).
    if (lead && own.some(n => n.id === `agent:${lead.id}`))
      lines.push({ id: `shared:${one.id}`, source: `agent:${lead.id}`, target: one.id, active: false, shared: { colour: 'var(--accent)', dotted: false } })
  }
  for (const node of own.filter(n => n.kind === 'team' || n.kind === 'agent')) {
    const who = node.kind === 'team' ? (node.data as TeamData).team : (state.agents.find(a => a.id === node.agentId)?.name ?? 'Agent')
    const rows = rowsOf(node.id, node.kind === 'team' ? who : null)
    if (!rows.length) continue
    const colour = node.kind === 'team' ? (node.data as TeamData).colour : 'var(--accent)'
    const one = block(node.id, who, colour, rows, rowsOf(node.id, node.kind === 'team' ? who : null, true))
    added.push(one)
    lines.push({ id: `shared:${one.id}`, source: node.id, target: one.id, active: false, shared: { colour, dotted: node.kind !== 'team' } })
  }
  for (const [request, paths] of contracts) {
    const one = block(request.id, null, 'var(--request)', [...paths].map(path => ({ kind: 'file' as const, text: path, path })))
    added.push(one)
    lines.push({ id: `shared:${one.id}`, source: request.source, target: one.id, active: false, shared: { colour: 'var(--request)', arm: request.id } })
  }
  return { nodes: added, edges: lines }
}
