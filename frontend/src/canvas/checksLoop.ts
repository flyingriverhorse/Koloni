import { AGENT_STATUS, WAITS } from '../agents/agentStatus'
import { turnTeams } from '../agents/teamRun'
import type { Agent, Message, Run, ToolCall } from '../api/types'
import type { ConvState } from '../state/applyEvent'
import { type ChecksData, type Line, lineOf, linesOf, PROOF_CALL, roundsSaid, toolOf } from './checksNode'
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

/** The kinds of work KOLONİ checks by their files (S5a): one line each, as on the plain node. */
const KIND_ROWS = new Set(['docs', 'slides', 'diagram', 'data'])

/** The foot's test runs, short (the sketch's "✓ related 19 · ✓ pytest 36"): a runner by its tool and count; a kind of work as the plain node says it. */
function footOf(rows: Row[]): Line[] {
  return [...rows.filter(row => !KIND_ROWS.has(row.kind)).map(footLine), ...linesOf(rows.filter(row => KIND_ROWS.has(row.kind)))]
}

function footLine(row: Row): Line {
  const line = lineOf(row)
  const counts = row.counts
  if (!counts || !row.command || counts.passed + counts.failed === 0 || line.since) return line
  const step = /^Related tests/.test(row.text) ? 'related' : toolOf(row.command)
  return { ...line, text: `${step} ${counts.passed}${counts.failed ? ` · ${counts.failed} failed` : ''}` }
}

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

/** Not over yet: at work, or waiting - to be let start, for a slot, a file, an agent, or for you. */
const AT_WORK: ReadonlySet<Agent['status']> = new Set(['proposed', 'queued', 'running', 'waiting', 'blocked'])
const atWork = (agent: Agent) => AT_WORK.has(agent.status)
const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`

/** The agents KOLONİ's checks take in: its own (looks, and a stronger model's fixer) and what the Orchestrator opened after it sent work back. */
interface Box {
  looks: Agent[]
  fixes: Agent[]
  /** Each in the order it was opened. */
  ordered: Agent[]
  /** How many of KOLONİ's calls came before an agent was opened: where nothing looked, which round it fixed in. */
  before: (agent: Agent) => number
}

/** The call that opened each agent, by its id. */
const callsById = (state: ConvState, run: Run) => new Map(state.toolCalls.filter(c => c.run_id === run.id).map(c => [c.id, c]))

/**
 * Who is in the box: an agent a call of KOLONİ's opened (`PROOF_CALL`: a review, a look again, a try's Tester, a diagnosis - and
 * a stronger model's fixer, `…fix_`); and one opened after KOLONİ's first check - only work sent back opens one then: the
 * Orchestrator's, or in a recipe's turn anyone's (its frame keeps the recipe's own steps, KOLONİ's send-back rounds are the box's).
 * shortcut: in a recipe's turn every agent opened after KOLONİ's first check is a fix of the box - a Tester its send-back reran
 * too ("Tester · fix"); tell them apart by the recipe's step if that is seen.
 */
function boxOf(state: ConvState, run: Run, lead: Agent): Box {
  const calls = callsById(state, run)
  const own = state.toolCalls.filter(c => c.run_id === run.id && c.provider_call_id.startsWith(PROOF_CALL))
  const first = Math.min(...own.map(c => c.seq))
  const seqOf = (agent: Agent) => calls.get(agent.tool_call_id ?? '')?.seq ?? Number.MAX_SAFE_INTEGER
  const mine = (agent: Agent) => calls.get(agent.tool_call_id ?? '')?.provider_call_id.startsWith(PROOF_CALL) ?? false
  // (In a recipe's turn, only one whose opening call is known: the recipe's own steps are the frame's.)
  const opener = (agent: Agent) => (run.teams?.length ? agent.depth > 0 && calls.has(agent.tool_call_id ?? '') : agent.parent_agent_id === lead.id)
  const sentBack = (agent: Agent) => opener(agent) && !mine(agent) && seqOf(agent) > first
  const kolonis = state.agents.filter(a => a.run_id === run.id && a.depth > 0 && mine(a))
  const fixer = (agent: Agent) => calls.get(agent.tool_call_id ?? '')?.provider_call_id.startsWith(`${PROOF_CALL}fix_`) ?? false
  const fixes = [...kolonis.filter(fixer), ...state.agents.filter(a => a.run_id === run.id && sentBack(a))]
  const looks = kolonis.filter(a => !fixer(a))
  const ordered = [...looks, ...fixes].sort((a, b) => seqOf(a) - seqOf(b) || a.created_at.localeCompare(b.created_at))
  return { looks, fixes, ordered, before: agent => own.filter(c => c.seq < seqOf(agent)).length }
}

/** Its looks and fixes in rounds, each but the last with why it went back (as the Checked section says). */
function roundsOf(box: Box, state: ConvState, why: string[]): LoopRound[] {
  const rounds = box.looks.length ? lookedRounds(box, state) : testedRounds(box, state)
  for (const round of rounds.slice(0, -1)) round.why = why[round.n - 1] ?? null
  return rounds
}

const roundOf = (n: number): LoopRound => ({ n, looks: [], finding: null, fixed: [], why: null })
const fixOf = (state: ConvState, agent: Agent) => ({ agentId: agent.id, name: agent.name, files: filesOf(state, agent.id) })

/** A new round after a fix, or where a role looks again (the Orchestrator fixed it itself). */
function lookedRounds(box: Box, state: ConvState): LoopRound[] {
  const rounds = [roundOf(1)]
  const looks = new Set(box.looks.map(a => a.id))
  const roleOf = new Map(box.looks.map(a => [a.id, a.role_name]))
  for (const agent of box.ordered) {
    const now = rounds.at(-1)!
    if (!looks.has(agent.id)) {
      now.fixed.push(fixOf(state, agent))
      continue
    }
    const again = now.fixed.length > 0 || now.looks.some(one => roleOf.get(one.agentId) === agent.role_name)
    if (again) rounds.push(roundOf(rounds.length + 1))
    const into = rounds.at(-1)!
    into.looks.push({ agentId: agent.id, name: agent.name, verdict: verdictOf(agent) })
    into.finding ??= agent.findings?.find(one => one.blocking !== false)?.what ?? null
  }
  return rounds
}

/**
 * Where nothing looked (sent back for the tests alone), KOLONİ's test run is each round's look: the agents opened between two of
 * its runs one round (a Coder and a Tester a send-back reran), and the run after the last - once those are over - the last.
 */
function testedRounds(box: Box, state: ConvState): LoopRound[] {
  const rounds: LoopRound[] = []
  for (const [at, agent] of box.ordered.entries()) {
    if (!at || box.before(agent) !== box.before(box.ordered[at - 1])) rounds.push(roundOf(rounds.length + 1))
    rounds.at(-1)!.fixed.push(fixOf(state, agent))
  }
  if (!box.ordered.some(atWork)) rounds.push(roundOf(rounds.length + 1))
  return rounds
}

/** How many files an agent changed. */
const filesOf = (state: ConvState, agentId: string) => new Set(state.fileChanges.filter(f => f.agent_id === agentId).map(f => f.path)).size

/** A role's card: its latest agent, with how many there were - "Reviewer ×3, last: HOLD · 1 blocking", "Coder · fix ×2, last: 4 files". */
function cardsOf(agents: Agent[], fix: boolean, state: ConvState, asking: ReadonlySet<string>): LoopCard[] {
  const byRole = new Map<string, Agent[]>()
  for (const agent of agents) byRole.set(agent.role_name, [...(byRole.get(agent.role_name) ?? []), agent])
  return [...byRole.values()].map(all => {
    const latest = all.at(-1)!
    const name = `${all.length > 1 ? latest.role_name : latest.name}${fix ? ' · fix' : ''}`
    const [said, tone] = cardSaid(latest, fix, state, asking)
    return { agentId: latest.id, name, count: all.length, said: all.length > 1 && tone !== 'run' ? `last: ${said}` : said, tone }
  })
}

/** A card's line: what waits for you as its node said it, a wait in the agent's own words, at work, how it ended. */
function cardSaid(agent: Agent, fix: boolean, state: ConvState, asking: ReadonlySet<string>): [string, Tone] {
  if (asking.has(agent.id) || agent.status === 'proposed') return [WAITS, 'note']
  if (agent.status === 'running') return [fix ? '● at work' : '● reading', 'run']
  if (atWork(agent)) return [AGENT_STATUS[agent.status][0], 'note']
  return endedSaid(agent, fix, state)
}

/** How an agent of the box ended: a fix by its files, a look by its verdict; else as its state reads (stopped, failed, rejected). */
function endedSaid(agent: Agent, fix: boolean, state: ConvState): [string, Tone] {
  if (agent.status !== 'completed') return [AGENT_STATUS[agent.status][0], 'bad']
  if (fix) return [plural(filesOf(state, agent.id), 'file'), 'note']
  const verdict = verdictOf(agent)
  return [verdict ?? 'done', verdict?.startsWith('HOLD') ? 'bad' : verdict === 'MERGE' ? 'ok' : 'note']
}

/**
 * The box's line: at work "● round 2 · looking…"; over "⟲ 3 looks · 2 fix rounds · on hold" (looks and rounds said where there
 * were) - "not taken in" where the work stays in its copy for it.
 */
function statusOf(box: Box, rounds: LoopRound[], data: ChecksData, running: number, asking: ReadonlySet<string>, rows: Row[]): [string, Tone] {
  if (running) return [`● round ${running} · ${doing(box, asking)}`, 'run']
  const failed = data.lines.some(line => line.state === 'failed')
  const kept = rows.some(row => row.kind === 'not_taken' && row.state === 'failed')
  const end = failed ? (kept ? 'not taken in' : data.held ? 'on hold' : 'still failing') : '✓ checked'
  const looked = rounds.filter(round => round.looks.length).length
  const parts = [looked && plural(looked, 'look'), data.rounds && plural(data.rounds, 'fix round')].filter(Boolean)
  return [`${failed ? '⟲ ' : ''}${[...parts, end].join(' · ')}`, failed ? 'bad' : 'ok']
}

/** What the round at work does now: waits for you (an agent of it asks), looks, fixes - else KOLONİ's test run. */
function doing(box: Box, asking: ReadonlySet<string>): string {
  const now = box.ordered.filter(atWork)
  if (now.some(a => asking.has(a.id) || a.status === 'proposed')) return WAITS
  const running = now.filter(a => a.status === 'running')
  return running.some(a => box.looks.includes(a)) ? 'looking…' : running.length ? 'fixing…' : now.length ? 'waiting…' : 'testing…'
}

/** A drop against the last green run, short: "Tests went from 48 to 45 (3 removed)" is "48 → 45 (3 removed)". */
const DROP = /^Tests went from (\d+) to (\d+) (\(.*?\))/

/**
 * Where nothing looked and work went back for the tests alone, the loop's left end is the tests (the approved sketch's case 3):
 * "48 → 45 (3 removed)" where fewer ran, else the failing run as the node says it.
 */
function testsCard(rows: Row[], data: ChecksData): LoopCard {
  const drop = rows.map(row => DROP.exec(row.text)).find(Boolean)
  const failing = data.lines.find(line => line.state === 'failed')
  const said = drop ? `${drop[1]} → ${drop[2]} ${drop[3]}` : (failing?.text ?? data.lines.at(-1)?.text ?? 'tests')
  return { agentId: `tests:${data.runId}`, name: 'Tests', count: 1, said, tone: drop || failing ? 'bad' : 'note' }
}

/** Why the checks stopped where a round held: the Checked section's own line ("Still on hold after 2 fix rounds: …", "Stopped after round 3: …"). */
const stopOf = (rows: Row[]) => rows.find(row => row.state === 'failed' && /^(Still|Stopped)/.test(row.text) && ['review', 'rounds', 'stronger'].includes(row.kind))?.text ?? null

/**
 * KOLONİ's checks of a turn as one box (tuval-kontrol-dongusu, D + F): the agents its checks opened, and those the Orchestrator
 * opened for the work it sent back, each role drawn once with how many there were, round by round for the panel. Null where
 * none was opened: the plain Checks node of its lines.
 */
export function loopOf(state: ConvState, run: Run, data: ChecksData, asking: ReadonlySet<string> = new Set()): Loop | null {
  const lead = state.agents.find(a => a.run_id === run.id && a.depth === 0)
  if (!lead) return null
  const box = boxOf(state, run, lead)
  if (!box.ordered.length) return null
  const checked = state.messages.find(m => m.run_id === run.id && m.role === 'checked')
  const rows = checked?.checked ?? []
  const rounds = roundsOf(box, state, roundsSaid(checked).why)
  const running = passAtWork(state, run, data, box, rounds)
  const [status, tone] = statusOf(box, rounds, data, running, asking, rows)
  const last: Loop['dots'][number] = running ? 'running' : tone === 'ok' ? 'passed' : 'held'
  const passes = Math.max(running, rounds.length)
  return {
    // (A fix agent in it: work went back already - before KOLONİ's next pass counts the round.)
    loop: data.rounds > 0 || rounds.length > 1 || box.fixes.length > 0,
    agents: box.ordered.map(a => a.id),
    looks: box.looks.length || !box.fixes.length ? cardsOf(box.looks, false, state, asking) : [testsCard(rows, data)],
    fixes: cardsOf(box.fixes, true, state, asking),
    rounds,
    status,
    tone,
    dots: Array.from({ length: passes }, (_, n) => (n === passes - 1 ? last : 'held')),
    tests: footOf(testRows(rows)),
    stop: running ? null : stopOf(rows),
  }
}

/**
 * The round at work now, by its number; 0: none. A round fixed, its fixes over: KOLONİ checks again - the next round, before a
 * look of it is opened.
 */
function passAtWork(state: ConvState, run: Run, data: ChecksData, box: Box, rounds: LoopRound[]): number {
  const working = Boolean(data.running) || data.lines.some(line => line.state === 'running') || box.ordered.some(atWork) || ownRunning(state, run)
  if (!working) return 0
  return rounds.at(-1)!.fixed.length > 0 && !box.fixes.some(atWork) ? rounds.length + 1 : rounds.length
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
  // (What waits for you as each agent's node had it, before the box takes their place: `asks`.)
  const asking = new Set(nodes.filter(n => n.runId === run.id && n.kind === 'agent' && (n.data as AgentData).attention).map(n => n.agentId ?? ''))
  data.loop = loopOf(state, run, data, asking)
  const gone = takeOut(nodes, new Set((data.loop?.agents ?? []).map(id => `agent:${id}`)))
  const own = nodes.filter(n => n.kind === 'agent' && (n.data as AgentData).parentId === data.leadId)
  // (The plain node of lines with the Orchestrator's agents beside it: no long line down past them; the box: its arrow.)
  const drop = !checks.team && (data.loop || own.length) ? `agent:${data.leadId}>${checks.id}` : null
  for (let at = edges.length - 1; at >= 0; at--) if (gone.has(edges[at].source) || gone.has(edges[at].target) || edges[at].id === drop) edges.splice(at, 1)
  if (data.loop && !checks.team) edges.push(arrowInto(checks, own, data.loop))
  if (checks.team) intoFrameBox(state, run, checks, nodes, edges)
  return gone
}

/**
 * In a recipe's turn the box is its frame's last part: one arrow into it, from the last agent of the recipe's own steps still
 * drawn there - never the Orchestrator's straight in (the Orchestrator reaches the frame at its door), nor one gone into the box.
 */
function intoFrameBox(state: ConvState, run: Run, checks: GraphNode, nodes: GraphNode[], edges: GraphEdge[]) {
  for (let at = edges.length - 1; at >= 0; at--) if (edges[at].target === checks.id) edges.splice(at, 1)
  const team = nodes.find(n => n.id === checks.team)?.refId
  const passes = turnTeams(state, run.id).find(row => row.team_id === team)?.state.passes ?? []
  const last = passes.flatMap(pass => pass.agents).findLast(id => nodes.some(n => n.id === `agent:${id}`))
  const data = checks.data as ChecksData
  if (last) edges.push({ id: `agent:${last}>${checks.id}`, source: `agent:${last}`, target: checks.id, active: Boolean(data.running) || data.loop?.tone === 'run' })
}

/** The box right of the Orchestrator's work, an arrow into it from that work: its middle agent, else the Orchestrator. */
function arrowInto(checks: GraphNode, own: GraphNode[], loop: Loop): GraphEdge {
  const data = checks.data as ChecksData
  const from = own.length ? own[Math.floor((own.length - 1) / 2)].id : `agent:${data.leadId}`
  return { id: `${from}>${checks.id}`, source: from, target: checks.id, active: Boolean(data.running) || loop.tone === 'run' }
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
 * The box's measures (its CSS draws to them, `.node-checks-box`): a card a role as big as an agent's - its name and one line -
 * with room for its shadows, in two columns (its looks, ⇄, its fixes), under its tag on the frame's top edge, over its foot.
 * One column where nothing was fixed.
 */
export const LOOP = { card: 200, cardH: 56, shadow: 6, gap: 12, way: 24, top: 22, foot: 30, pad: 16 }

/** How big the Checks node is drawn with its loop; null: as any node (its lines alone). */
export function checksSize(data: ChecksData): { width: number; height: number } | null {
  const loop = data.loop
  if (!loop) return null
  const rows = Math.max(loop.looks.length, loop.fixes.length, 1)
  const column = LOOP.card + LOOP.shadow
  const width = 2 * LOOP.pad + (loop.fixes.length ? 2 * column + 2 * LOOP.gap + LOOP.way : column)
  return { width, height: LOOP.top + rows * (LOOP.cardH + LOOP.shadow) + (rows - 1) * LOOP.gap + LOOP.foot + LOOP.pad }
}
