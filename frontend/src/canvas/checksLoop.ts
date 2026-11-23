import type { Agent, Message, Run, ToolCall } from '../api/types'
import type { ConvState } from '../state/applyEvent'
import { type ChecksData, type Line, linesOf, PROOF_CALL, roundsSaid } from './checksNode'
import type { AgentData, GraphEdge, GraphNode } from './deriveGraph'

type Row = NonNullable<Message['checked']>[number]

/** How a card or the box's line reads: held or failing, passed, at work, or neither. */
export type Tone = 'bad' | 'ok' | 'run' | 'note'

/** A role in KOLONİ's checks, drawn once (tuval-kontrol-dongusu D): its latest agent, the earlier ones shadows behind it (×count). */
export interface LoopCard {
  agentId: string
  name: string
  count: number
  said: string
  tone: Tone
}

/** One pass of KOLONİ's checks (F): who looked and what each said, the first blocking finding, who fixed it after - and why it went back. */
export interface LoopRound {
  n: number
  looks: { agentId: string; name: string; verdict: string | null }[]
  finding: string | null
  fixed: { agentId: string; name: string; files: number }[]
  /** What the Checked section says sent it back ("tests fail", "2 blocking findings"); null: not said. */
  why: string | null
}

/** KOLONİ's checks of a turn as one box: its looks and fixes, round by round. */
export interface Loop {
  /** Sent back at least once: the dashed frame, the shadows and the ×N; else a plain Checks box. */
  loop: boolean
  /** The agents drawn in the box, none of them a node of their own. */
  agents: string[]
  looks: LoopCard[]
  fixes: LoopCard[]
  rounds: LoopRound[]
  /** The header's line: "⟲ 3 looks · 2 fix rounds · on hold", "● round 2 · looking…". */
  status: string
  tone: Tone
  /** A dot a round: held (it went back, or the last one ended so), passed, at work. */
  dots: ('held' | 'passed' | 'running')[]
  /** The footer: the test runs' lines, as the plain node says them. */
  tests: Line[]
  /** Why the last round was the last, as the Checked section says it; null: it passed, or nothing said. */
  stop: string | null
}

/** The Checked rows that are test runs - a runner's, the coverage, a kind of work's (S5a) -: the footer and the panel's Tests. */
const TEST_KINDS = new Set(['tests', 'coverage', 'docs', 'slides', 'diagram', 'data'])
export const testRows = (rows: Row[]) => rows.filter(row => TEST_KINDS.has(row.kind))

/** A look's verdict line, as KOLONİ asks for it: "Verdict: MERGE", "Verdict: HOLD". */
const VERDICT = /^\W*(?:final\s+)?verdict\W+(MERGE|HOLD)\b/im

/**
 * What a look of KOLONİ's said: "HOLD · 3 blocking" where its findings block, else its verdict line; null: neither.
 * shortcut: its own verdict line only - KOLONİ reads more ways of saying it (`review_mixin.verdict_of`: a negated MERGE holds);
 * have the backend put its reading on the agent if a card is seen to say MERGE where the Checked section held.
 */
export function verdictOf(agent: Agent): string | null {
  const blocking = agent.findings?.filter(one => one.blocking !== false).length ?? 0
  if (blocking) return `HOLD · ${blocking} blocking`
  return VERDICT.exec(agent.report ?? '')?.[1]?.toUpperCase() ?? null
}

const AT_WORK: ReadonlySet<Agent['status']> = new Set(['proposed', 'queued', 'running', 'waiting', 'blocked'])
const atWork = (agent: Agent) => AT_WORK.has(agent.status)
const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`

/** The agents KOLONİ's checks take in: its own (looks, and a stronger model's fixer) and what the Orchestrator opened after it sent work back. */
interface Box {
  looks: Agent[]
  fixes: Agent[]
  /** Each in the order it was opened. */
  ordered: Agent[]
}

/** The call that opened each agent, by its id. */
const callsById = (state: ConvState, run: Run) => new Map(state.toolCalls.filter(c => c.run_id === run.id).map(c => [c.id, c]))

/**
 * Who is in the box: an agent a call of KOLONİ's opened (`PROOF_CALL`: a review, a look again, a try's Tester, a diagnosis - and
 * a stronger model's fixer, `…fix_`); and one the Orchestrator opened after KOLONİ's first check - only work sent back opens one
 * then. Not in a recipe's turn: there its roles fix, in their frame.
 */
function boxOf(state: ConvState, run: Run, lead: Agent): Box {
  const calls = callsById(state, run)
  const own = state.toolCalls.filter(c => c.run_id === run.id && c.provider_call_id.startsWith(PROOF_CALL))
  const first = Math.min(...own.map(c => c.seq))
  const seqOf = (agent: Agent) => calls.get(agent.tool_call_id ?? '')?.seq ?? Number.MAX_SAFE_INTEGER
  const mine = (agent: Agent) => calls.get(agent.tool_call_id ?? '')?.provider_call_id.startsWith(PROOF_CALL) ?? false
  const sentBack = (agent: Agent) => !run.teams?.length && agent.parent_agent_id === lead.id && !mine(agent) && seqOf(agent) > first
  const kolonis = state.agents.filter(a => a.run_id === run.id && a.depth > 0 && mine(a))
  const fixer = (agent: Agent) => calls.get(agent.tool_call_id ?? '')?.provider_call_id.startsWith(`${PROOF_CALL}fix_`) ?? false
  const fixes = [...kolonis.filter(fixer), ...state.agents.filter(a => a.run_id === run.id && sentBack(a))]
  const looks = kolonis.filter(a => !fixer(a))
  const ordered = [...looks, ...fixes].sort((a, b) => seqOf(a) - seqOf(b) || a.created_at.localeCompare(b.created_at))
  return { looks, fixes, ordered }
}

/** Its looks and fixes in rounds: a new one after a fix, or where a role looks again (the Orchestrator fixed it itself). */
function roundsOf(box: Box, state: ConvState, why: string[]): LoopRound[] {
  const rounds: LoopRound[] = [{ n: 1, looks: [], finding: null, fixed: [], why: null }]
  const looks = new Set(box.looks.map(a => a.id))
  const roleOf = new Map(box.looks.map(a => [a.id, a.role_name]))
  for (const agent of box.ordered) {
    const now = rounds.at(-1)!
    if (!looks.has(agent.id)) {
      now.fixed.push({ agentId: agent.id, name: agent.name, files: filesOf(state, agent.id) })
      continue
    }
    const again = now.fixed.length > 0 || now.looks.some(one => roleOf.get(one.agentId) === agent.role_name)
    if (again) rounds.push({ n: rounds.length + 1, looks: [], finding: null, fixed: [], why: null })
    const into = rounds.at(-1)!
    into.looks.push({ agentId: agent.id, name: agent.name, verdict: verdictOf(agent) })
    into.finding ??= agent.findings?.find(one => one.blocking !== false)?.what ?? null
  }
  // (A round went back for what the Checked section says - each but the last.)
  for (const round of rounds.slice(0, -1)) round.why = why[round.n - 1] ?? null
  return rounds
}

/** How many files an agent changed. */
const filesOf = (state: ConvState, agentId: string) => new Set(state.fileChanges.filter(f => f.agent_id === agentId).map(f => f.path)).size

/** A role's card: its latest agent, with how many there were - "Reviewer ×3, last: HOLD · 1 blocking", "Coder · fix ×2, last: 4 files". */
function cardsOf(agents: Agent[], fix: boolean, state: ConvState): LoopCard[] {
  const byRole = new Map<string, Agent[]>()
  for (const agent of agents) byRole.set(agent.role_name, [...(byRole.get(agent.role_name) ?? []), agent])
  return [...byRole.values()].map(all => {
    const latest = all.at(-1)!
    const name = `${all.length > 1 ? latest.role_name : latest.name}${fix ? ' · fix' : ''}`
    const [said, tone] = cardSaid(latest, fix, state)
    return { agentId: latest.id, name, count: all.length, said: all.length > 1 && tone !== 'run' ? `last: ${said}` : said, tone }
  })
}

function cardSaid(agent: Agent, fix: boolean, state: ConvState): [string, Tone] {
  if (atWork(agent)) return [fix ? '● at work' : '● reading', 'run']
  if (agent.status === 'failed' || agent.status === 'cancelled' || agent.status === 'interrupted') return [agent.status, 'bad']
  if (fix) return [plural(filesOf(state, agent.id), 'file'), 'note']
  const verdict = verdictOf(agent)
  return [verdict ?? 'done', verdict?.startsWith('HOLD') ? 'bad' : verdict === 'MERGE' ? 'ok' : 'note']
}

/** The box's line: at work "● round 2 · looking…"; over "⟲ 3 looks · 2 fix rounds · on hold" (looks and rounds said where there were). */
function statusOf(box: Box, rounds: LoopRound[], data: ChecksData, running: boolean): [string, Tone] {
  if (running) {
    const what = box.looks.some(atWork) ? 'looking…' : box.fixes.some(atWork) ? 'fixing…' : 'testing…'
    return [`● round ${rounds.length} · ${what}`, 'run']
  }
  const failed = data.lines.some(line => line.state === 'failed')
  const end = failed ? (data.held ? 'on hold' : 'still failing') : '✓ checked'
  const looked = rounds.filter(round => round.looks.length).length
  const parts = [looked && plural(looked, 'look'), data.rounds && plural(data.rounds, 'fix round')].filter(Boolean)
  return [`${failed ? '⟲ ' : ''}${[...parts, end].join(' · ')}`, failed ? 'bad' : 'ok']
}

/** Why the checks stopped where a round held: the Checked section's own line ("Still on hold after 2 fix rounds: …", "Stopped after round 3: …"). */
const stopOf = (rows: Row[]) => rows.find(row => row.state === 'failed' && /^(Still|Stopped)/.test(row.text) && ['review', 'rounds', 'stronger'].includes(row.kind))?.text ?? null

/**
 * KOLONİ's checks of a turn as one box (tuval-kontrol-dongusu, D + F): the agents its checks opened, and those the Orchestrator
 * opened for the work it sent back, each role drawn once with how many there were, round by round for the panel. Null where
 * none was opened: the plain Checks node of its lines.
 */
export function loopOf(state: ConvState, run: Run, data: ChecksData): Loop | null {
  const lead = state.agents.find(a => a.run_id === run.id && a.depth === 0)
  if (!lead) return null
  const box = boxOf(state, run, lead)
  if (!box.ordered.length) return null
  const checked = state.messages.find(m => m.run_id === run.id && m.role === 'checked')
  const rows = checked?.checked ?? []
  const rounds = roundsOf(box, state, roundsSaid(checked).why)
  const running = Boolean(data.running) || data.lines.some(line => line.state === 'running') || box.ordered.some(atWork) || ownRunning(state, run)
  const [status, tone] = statusOf(box, rounds, data, running)
  const last: Loop['dots'][number] = running ? 'running' : tone === 'ok' ? 'passed' : 'held'
  return {
    loop: data.rounds > 0 || rounds.length > 1,
    agents: box.ordered.map(a => a.id),
    looks: cardsOf(box.looks, false, state),
    fixes: cardsOf(box.fixes, true, state),
    rounds,
    status,
    tone,
    dots: rounds.map((_, n) => (n === rounds.length - 1 ? last : 'held')),
    tests: linesOf(testRows(rows)),
    stop: running ? null : stopOf(rows),
  }
}

/** A call of KOLONİ's at work: a test run, a look being opened. */
const ownRunning = (state: ConvState, run: Run) => state.toolCalls.some((c: ToolCall) => c.run_id === run.id && c.provider_call_id.startsWith(PROOF_CALL) && c.status === 'running')

/**
 * The Checks node's box, once its turn's agents are drawn: its loop (`loopOf`), whose agents are no nodes of their own - nor
 * what hangs in them, nor their lines; and where the Orchestrator's own agents stand right of it, no long line down to the box
 * under them (in a recipe's turn the box joins its frame's last pass). Returns the ids of the nodes taken out.
 */
export function settleChecks(state: ConvState, run: Run, checks: GraphNode, nodes: GraphNode[], edges: GraphEdge[]): Set<string> {
  const data = checks.data as ChecksData
  data.loop = loopOf(state, run, data)
  const gone = takeOut(nodes, new Set((data.loop?.agents ?? []).map(id => `agent:${id}`)))
  const beside = nodes.some(n => n.kind === 'agent' && (n.data as AgentData).parentId === data.leadId)
  const long = beside && !checks.team ? `agent:${data.leadId}>${checks.id}` : null
  for (let at = edges.length - 1; at >= 0; at--) if (gone.has(edges[at].source) || gone.has(edges[at].target) || edges[at].id === long) edges.splice(at, 1)
  return gone
}

/** The nodes `gone` names, and what sits in them, taken out of `nodes`; returns all their ids. */
function takeOut(nodes: GraphNode[], gone: Set<string>): Set<string> {
  for (let size = -1; size !== gone.size; ) {
    size = gone.size
    for (const node of nodes) if (node.parent && gone.has(node.parent)) gone.add(node.id)
  }
  for (let at = nodes.length - 1; at >= 0; at--) if (gone.has(nodes[at].id)) nodes.splice(at, 1)
  return gone
}

/**
 * The box's measures (its CSS draws to them): a card a role, in two columns - its looks, ⇄, its fixes - under a head with its
 * rounds, over a foot; with neither (one look, nothing sent back) as wide as a node.
 */
export const LOOP = { width: 440, narrow: 220, head: 34, card: 42, gap: 8, foot: 28, pad: 12 }

/** How big the Checks node is drawn with its loop; null: as any node (its lines alone). */
export function checksSize(data: ChecksData): { width: number; height: number } | null {
  const loop = data.loop
  if (!loop) return null
  const rows = Math.max(loop.looks.length, loop.fixes.length, 1)
  const width = loop.loop || loop.fixes.length ? LOOP.width : LOOP.narrow
  return { width, height: LOOP.head + rows * LOOP.card + (rows - 1) * LOOP.gap + LOOP.foot + 2 * LOOP.pad }
}
