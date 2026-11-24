import { AGENT_STATUS, WAITS } from '../agents/agentStatus'
import { turnTeams } from '../agents/teamRun'
import type { Agent, Message, Run, ToolCall } from '../api/types'
import type { ConvState } from '../state/applyEvent'
import { type ChecksData, KINDS, type Line, lineOf, linesOf, PROOF_CALL, stripOf, toolOf } from './checksNode'
import type { AgentData, GraphEdge, GraphNode } from './deriveGraph'

type Row = NonNullable<Message['checked']>[number]
/** One pass of KOLONİ's checks as the backend wrote it with the Checked section (`app.proof.new_pass`). */
type Pass = NonNullable<Message['passes']>[number]

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

/**
 * One pass of KOLONİ's checks (F), as its record says it: how its tests came out, who looked and what each said, the first
 * blocking finding, a stronger tier's diagnosis, who fixed it after - and why it went back, and how.
 */
export interface LoopRound {
  n: number
  /** "check": KOLONİ's steps; "stronger": a stronger tier's round (its diagnosis, its fixer, the tests again). */
  kind: Pass['kind']
  tier: string | null
  tests: Pass['tests']
  looks: { agentId: string; name: string; verdict: string | null }[]
  diagnosis: { agentId: string; name: string } | null
  finding: string | null
  fixed: { agentId: string; name: string; files: number }[]
  /** Why it went back ("tests fail", "2 blocking findings"); null: it did not, or for a test. */
  why: string | null
  /** "fix": a fix round - by the agents in `fixed`, or the Orchestrator itself where none; "ask": the ask for a test, no round. */
  sent: Pass['sent']
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
  /** A dot a round: held (it went back, or the last one ended so), passed, at work - or asked for a test (no fix round). */
  dots: ('held' | 'passed' | 'running' | 'asked')[]
  /** The footer: the test runs' lines, as the plain node says them. */
  tests: Line[]
  /** Why the last round was the last, as the Checked section says it; null: it passed, or nothing said. */
  stop: string | null
}

/** The kinds of work KOLONİ checks by their files (S5a, S5b's Pages, 0.1.7's Config, Scripts and Code style): one line each, as on the plain node. */
const KIND_ROWS = new Set(Object.keys(KINDS))

/** The Checked rows that are test runs - a runner's, the coverage, every kind of work's -: the footer and the panel's Tests. */
const TEST_KINDS = new Set(['tests', 'coverage', ...KIND_ROWS])
export const testRows = (rows: Row[]) => rows.filter(row => TEST_KINDS.has(row.kind))

/** The foot's test runs, short (the sketch's "✓ related 19 · ✓ pytest 36"): a runner by its tool and count; a kind of work as the plain node says it. */
function footOf(rows: Row[]): Line[] {
  return [
    ...rows.filter(row => !KIND_ROWS.has(row.kind)).map(footLine),
    ...linesOf(rows.filter(row => KIND_ROWS.has(row.kind))),
  ]
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

/** How an agent stands in the box: one of its looks, a stronger tier's diagnosis (its own kind, no look), a fixer. */
type As = 'look' | 'diagnosis' | 'fix'
const AS_NAME: Record<As, string> = { look: '', diagnosis: ' · diagnosis', fix: ' · fix' }

/**
 * The agents in the box: as KOLONİ's passes name them (`Message.passes`, written with its Checked section) - each pass's looks,
 * a stronger tier's diagnosis, the fixers its send-back had the Lead open or the tier's own -, with what a fixer opened under it.
 * Never read off the order agents were opened in. Before that section (a live turn), only the agents KOLONİ's own calls opened.
 * shortcut: live, the Orchestrator's fixers are its own nodes until the section names them - send the passes live (an event of
 * their own) if that is felt.
 */
interface Box {
  looks: Agent[]
  diagnoses: Agent[]
  fixes: Agent[]
  /** What a fixer opened under it: in the box with its fixer, no node of its own. */
  under: string[]
  /** The passes as written; null: none yet (a live turn). */
  passes: Pass[] | null
}

function boxOf(state: ConvState, run: Run, passes: Pass[] | null): Box {
  const mine = state.agents.filter(a => a.run_id === run.id)
  const byId = new Map(mine.map(a => [a.id, a]))
  const named = (ids: (string | null | undefined)[]) =>
    [...new Set(ids)].flatMap(id => (id && byId.get(id) ? [byId.get(id)!] : []))
  if (passes) {
    const fixes = named(passes.flatMap(pass => pass.fixers))
    return {
      looks: named(passes.flatMap(pass => pass.looks.map(look => look.agent_id))),
      diagnoses: named(passes.map(pass => pass.diagnosis)),
      fixes,
      under: underOf(mine, fixes),
      passes,
    }
  }
  const calls = new Map(state.toolCalls.filter(c => c.run_id === run.id).map(c => [c.id, c.provider_call_id]))
  const kind = (agent: Agent) => /^koloni_proof_([a-z]+)_/.exec(calls.get(agent.tool_call_id ?? '') ?? '')?.[1] ?? null
  const kolonis = mine.filter(a => (calls.get(a.tool_call_id ?? '') ?? '').startsWith(PROOF_CALL))
  const fixes = kolonis.filter(a => kind(a) === 'fix')
  return {
    looks: kolonis.filter(a => kind(a) !== 'fix' && kind(a) !== 'diagnose'),
    diagnoses: kolonis.filter(a => kind(a) === 'diagnose'),
    fixes,
    under: underOf(mine, fixes),
    passes: null,
  }
}

/** Every agent opened under a fixer, however deep (a Coder's own sub-agent). */
function underOf(agents: Agent[], fixes: Agent[]): string[] {
  const inside = new Set(fixes.map(a => a.id))
  for (let size = -1; size !== inside.size;) {
    size = inside.size
    for (const agent of agents) if (agent.parent_agent_id && inside.has(agent.parent_agent_id)) inside.add(agent.id)
  }
  return [...inside].filter(id => !fixes.some(a => a.id === id))
}

/**
 * A look's verdict as its pass recorded it - the one KOLONİ acted on: "HOLD · 3 blocking" where its findings block; with `said`,
 * its report's own word where that was another ("HOLD · 1 blocking - its report said MERGE", as the Checked row says it).
 */
function saidVerdict(verdict: string | null, agent: Agent | undefined, said?: string | null): string | null {
  const blocking = agent?.findings?.filter(one => one.blocking !== false).length ?? 0
  const shown = verdict === 'HOLD' && blocking ? `HOLD · ${blocking} blocking` : verdict
  return shown && said && said !== verdict ? `${shown} - its report said ${said}` : shown
}

/** The rounds of the panel: a pass each, as written. */
function roundsOf(box: Box, state: ConvState): LoopRound[] {
  const byId = new Map(state.agents.map(a => [a.id, a]))
  const name = (id: string, or: string) => byId.get(id)?.name ?? or
  return (box.passes ?? []).map(pass => ({
    n: pass.n,
    kind: pass.kind,
    tier: pass.tier ?? null,
    tests: pass.tests,
    looks: pass.looks.map(look => ({
      agentId: look.agent_id,
      name: name(look.agent_id, look.role),
      verdict: saidVerdict(look.verdict, byId.get(look.agent_id), look.said),
    })),
    diagnosis: pass.diagnosis ? { agentId: pass.diagnosis, name: name(pass.diagnosis, 'Diagnosis') } : null,
    finding:
      pass.looks
        .map(look => byId.get(look.agent_id)?.findings?.find(one => one.blocking !== false)?.what)
        .find(Boolean) ?? null,
    fixed: pass.fixers.map(id => ({ agentId: id, name: name(id, 'Agent'), files: filesOf(state, id) })),
    why: pass.why,
    sent: pass.sent,
  }))
}

/** How many files an agent changed. */
const filesOf = (state: ConvState, agentId: string) =>
  new Set(state.fileChanges.filter(f => f.agent_id === agentId).map(f => f.path)).size

/** A role's card: its latest agent, with how many there were - "Reviewer ×3, last: HOLD · 1 blocking", "Coder · fix ×2, last: 4 files". */
function cardsOf(
  agents: Agent[],
  as: As,
  state: ConvState,
  asking: ReadonlySet<string>,
  verdicts: ReadonlyMap<string, string | null>,
): LoopCard[] {
  const byRole = new Map<string, Agent[]>()
  for (const agent of agents) byRole.set(agent.role_name, [...(byRole.get(agent.role_name) ?? []), agent])
  return [...byRole.values()].map(all => {
    const latest = all.at(-1)!
    const name = `${all.length > 1 ? latest.role_name : latest.name}${AS_NAME[as]}`
    const [said, tone] = cardSaid(latest, as, state, asking, verdicts)
    return {
      agentId: latest.id,
      name,
      count: all.length,
      said: all.length > 1 && tone !== 'run' ? `last: ${said}` : said,
      tone,
    }
  })
}

/** A card's line: what waits for you as its node said it, a wait in the agent's own words, at work, how it ended. */
function cardSaid(
  agent: Agent,
  as: As,
  state: ConvState,
  asking: ReadonlySet<string>,
  verdicts: ReadonlyMap<string, string | null>,
): [string, Tone] {
  if (asking.has(agent.id) || agent.status === 'proposed') return [WAITS, 'note']
  if (agent.status === 'running') return [as === 'fix' ? '● at work' : '● reading', 'run']
  if (atWork(agent)) return [AGENT_STATUS[agent.status][0], 'note']
  return endedSaid(agent, as, state, verdicts)
}

/** How an agent of the box ended: a fix by its files, a diagnosis by its verdict word, a look by its pass's verdict; else as its state reads. */
function endedSaid(
  agent: Agent,
  as: As,
  state: ConvState,
  verdicts: ReadonlyMap<string, string | null>,
): [string, Tone] {
  if (agent.status !== 'completed') return [AGENT_STATUS[agent.status][0], 'bad']
  if (as === 'fix') return [plural(filesOf(state, agent.id), 'file'), 'note']
  if (as === 'diagnosis') return [/Diagnosis:\s*([\w-]+)/i.exec(agent.report ?? '')?.[1] ?? 'done', 'note']
  const verdict = verdicts.has(agent.id) ? saidVerdict(verdicts.get(agent.id) ?? null, agent) : verdictOf(agent)
  return [verdict ?? 'done', verdict?.startsWith('HOLD') ? 'bad' : verdict === 'MERGE' ? 'ok' : 'note']
}

/**
 * The box's line: at work "● round 2 · looking…"; over "⟲ 3 looks · 2 fix rounds · on hold" (looks and rounds said where there
 * were, from the passes) - "not taken in" where the work stays in its copy for it; "not checked" where no test line passed (a
 * turn stopped mid-round is never "✓ checked": as the Orchestrator's strip says, `stripOf`).
 */
function statusOf(
  box: Box,
  data: ChecksData,
  rows: Row[],
  running: boolean,
  asking: ReadonlySet<string>,
): [string, Tone] {
  const passes = box.passes ?? []
  if (running) return [`● ${passes.length ? `round ${passes.length} · ` : ''}${doing(box, asking)}`, 'run']
  const failed = data.lines.some(line => line.state === 'failed')
  const checked = Boolean(stripOf(data)?.startsWith('✓'))
  return [
    `${failed ? '⟲ ' : ''}${[...countsOf(passes), endOf(data, rows, failed, checked)].join(' · ')}`,
    failed ? 'bad' : checked ? 'ok' : 'note',
  ]
}

/** How it ended: "not taken in" where the work stays in its copy for it, "on hold", "still failing" - else checked or not. */
function endOf(data: ChecksData, rows: Row[], failed: boolean, checked: boolean): string {
  if (!failed) return checked ? '✓ checked' : 'not checked'
  return rows.some(row => row.kind === 'not_taken' && row.state === 'failed')
    ? 'not taken in'
    : data.held
      ? 'on hold'
      : 'still failing'
}

/** The passes, counted where there were: "3 looks", "2 fix rounds", "1 stronger round". */
function countsOf(passes: Pass[]): string[] {
  const looked = passes.filter(pass => pass.looks.length).length
  const fixed = passes.filter(pass => pass.kind === 'check' && pass.sent === 'fix').length
  const stronger = passes.filter(pass => pass.kind === 'stronger').length
  return [
    looked && plural(looked, 'look'),
    fixed && plural(fixed, 'fix round'),
    stronger && plural(stronger, 'stronger round'),
  ].filter((one): one is string => Boolean(one))
}

/** What the round at work does now: waits for you (an agent of it asks), looks, fixes - else KOLONİ's test run. */
function doing(box: Box, asking: ReadonlySet<string>): string {
  const now = [...box.looks, ...box.diagnoses, ...box.fixes].filter(atWork)
  if (now.some(a => asking.has(a.id) || a.status === 'proposed')) return WAITS
  const running = now.filter(a => a.status === 'running')
  return running.some(a => !box.fixes.includes(a))
    ? 'looking…'
    : running.length
      ? 'fixing…'
      : now.length
        ? 'waiting…'
        : 'checking…'
}

/** A drop against the last green run, short: "Tests went from 48 to 45 (3 removed)" is "48 → 45 (3 removed)". */
const DROP = /^Tests went from (\d+) to (\d+) (\(.*?\))/

/**
 * Where nothing looked and work went back for the tests alone, the loop's left end is the tests (the approved sketch's case 3):
 * "48 → 45 (3 removed)" where fewer ran, else a test run's line - the failing one - as the node says it; never another kind of
 * row (the section's last line may be the rounds').
 */
function testsCard(rows: Row[], data: ChecksData): LoopCard {
  const drop = rows.map(row => DROP.exec(row.text)).find(Boolean)
  const tests = linesOf(rows.filter(row => row.kind === 'tests')).filter(line => line.state !== 'note')
  const failing = tests.find(line => line.state === 'failed')
  const said = drop ? `${drop[1]} → ${drop[2]} ${drop[3]}` : ((failing ?? tests[0])?.text ?? 'tests')
  return {
    agentId: `tests:${data.runId}`,
    name: 'Tests',
    count: 1,
    said,
    tone: drop || failing ? 'bad' : tests.length ? 'ok' : 'note',
  }
}

/** Why the checks stopped where a round held: the Checked section's own line ("Still on hold after 2 fix rounds: …", "Stopped after round 3: …"). */
const stopOf = (rows: Row[]) =>
  rows.find(
    row =>
      row.state === 'failed' &&
      /^(Still|Stopped)/.test(row.text) &&
      ['review', 'rounds', 'stronger'].includes(row.kind),
  )?.text ?? null

/** A dot a pass: each but the last went back (or was handed up) - a neutral one where it only asked for a test -; the last as the box ends, or at work. */
function dotsOf(box: Box, running: boolean, tone: Tone): Loop['dots'] {
  const last: Loop['dots'][number] = running ? 'running' : tone === 'ok' ? 'passed' : 'held'
  if (!box.passes) return running ? [last] : []
  return box.passes.map((pass, at) => (at === box.passes!.length - 1 ? last : pass.sent === 'ask' ? 'asked' : 'held'))
}

/** Whether the box says its rounds - its status in its tag, a dot a pass at its foot: sent back at least once, or at work. */
export const saysRounds = (loop: Loop) => loop.loop || loop.tone === 'run'

/** Each dot in words, for its title and the dots' label. */
export const DOT_WORDS: Record<Loop['dots'][number], string> = {
  held: 'held',
  passed: 'passed',
  running: 'at work',
  asked: 'asked for a test',
}

/**
 * KOLONİ's checks of a turn as one box (tuval-kontrol-dongusu, D + F): the agents its passes name (`boxOf`), each role drawn
 * once with how many there were, a pass a round for the panel. Null where none was opened, and for a turn checked before the
 * passes were written: the plain Checks node of its lines.
 */
export function loopOf(
  state: ConvState,
  run: Run,
  data: ChecksData,
  asking: ReadonlySet<string> = new Set(),
): Loop | null {
  const checked = state.messages.find(m => m.run_id === run.id && m.role === 'checked')
  if (checked && !checked.passes) return null
  const box = boxOf(state, run, checked?.passes ?? null)
  const all = [...box.looks, ...box.diagnoses, ...box.fixes]
  if (!all.length) return null
  const rows = checked?.checked ?? []
  // (Before its section, a turn at work is still being checked: nothing of how it ends is said.)
  const running = atWorkNow(state, run, data, all) || (!checked && run.status === 'running')
  const [status, tone] = statusOf(box, data, rows, running, asking)
  return {
    // (Sent back to fix at least once - an ask for a test is no round.)
    loop: Boolean(box.passes?.some(pass => pass.sent === 'fix')) || box.fixes.length > 0,
    agents: [...all.map(a => a.id), ...box.under],
    ...columnsOf(box, state, asking, rows, data),
    rounds: roundsOf(box, state),
    status,
    tone,
    dots: dotsOf(box, running, tone),
    tests: footOf(testRows(rows)),
    stop: running ? null : stopOf(rows),
  }
}

/**
 * The box's two columns: its looks (or, sent back for the tests alone, the Tests) and a stronger tier's diagnoses ⇄ its fixes -
 * each look's card by the verdict its pass recorded.
 */
function columnsOf(
  box: Box,
  state: ConvState,
  asking: ReadonlySet<string>,
  rows: Row[],
  data: ChecksData,
): Pick<Loop, 'looks' | 'fixes'> {
  const verdicts = new Map(
    (box.passes ?? []).flatMap(pass => pass.looks.map(look => [look.agent_id, look.verdict] as const)),
  )
  const left =
    box.looks.length || !box.fixes.length
      ? cardsOf(box.looks, 'look', state, asking, verdicts)
      : [testsCard(rows, data)]
  return {
    looks: [...left, ...cardsOf(box.diagnoses, 'diagnosis', state, asking, verdicts)],
    fixes: cardsOf(box.fixes, 'fix', state, asking, verdicts),
  }
}

/** KOLONİ's checks at work now: a test run, a suite gone on after the answer, an agent of the box. */
const atWorkNow = (state: ConvState, run: Run, data: ChecksData, all: Agent[]) =>
  Boolean(data.running) ||
  data.lines.some(line => line.state === 'running') ||
  all.some(atWork) ||
  ownRunning(state, run)

/** A call of KOLONİ's at work: a test run, a look being opened. */
const ownRunning = (state: ConvState, run: Run) =>
  state.toolCalls.some(
    (c: ToolCall) => c.run_id === run.id && c.provider_call_id.startsWith(PROOF_CALL) && c.status === 'running',
  )

/**
 * The Checks node's box, once its turn's agents are drawn: its loop (`loopOf`), whose agents are no nodes of their own - nor
 * what hangs in them, nor their lines; and where the Orchestrator's own agents stand right of it, no long line down to the box
 * under them (in a recipe's turn the box joins its frame's last pass). Returns the ids of the nodes taken out.
 */
export function settleChecks(
  state: ConvState,
  run: Run,
  checks: GraphNode,
  nodes: GraphNode[],
  edges: GraphEdge[],
): Set<string> {
  const data = checks.data as ChecksData
  // (What waits for you as each agent's node had it, before the box takes their place: `asks`.)
  const asking = new Set(
    nodes
      .filter(n => n.runId === run.id && n.kind === 'agent' && (n.data as AgentData).attention)
      .map(n => n.agentId ?? ''),
  )
  data.loop = loopOf(state, run, data, asking)
  const gone = takeOut(nodes, new Set((data.loop?.agents ?? []).map(id => `agent:${id}`)))
  const own = nodes.filter(n => n.kind === 'agent' && (n.data as AgentData).parentId === data.leadId)
  // (The plain node of lines with the Orchestrator's agents beside it: no long line down past them; the box: its arrow.)
  const drop = !checks.team && (data.loop || own.length) ? `agent:${data.leadId}>${checks.id}` : null
  for (let at = edges.length - 1; at >= 0; at--)
    if (gone.has(edges[at].source) || gone.has(edges[at].target) || edges[at].id === drop) edges.splice(at, 1)
  if (data.loop && !checks.team) edges.push(arrowInto(checks, own, data.loop))
  if (checks.team) intoFrameBox(state, run, checks, nodes, edges)
  return gone
}

/**
 * In a recipe's turn the box is its frame's last part: an arrow into it from the last agent of that recipe's own steps still drawn
 * there - and from each other frame of the turn, its frame itself (KOLONİ checks once, at the end, all their work) -; never the
 * Orchestrator's straight in (the Orchestrator reaches a frame at its door), nor one gone into the box.
 */
function intoFrameBox(state: ConvState, run: Run, checks: GraphNode, nodes: GraphNode[], edges: GraphEdge[]) {
  for (let at = edges.length - 1; at >= 0; at--) if (edges[at].target === checks.id) edges.splice(at, 1)
  const active = Boolean((checks.data as ChecksData).running) || (checks.data as ChecksData).loop?.tone === 'run'
  const rows = turnTeams(state, run.id)
  for (const frame of nodes.filter(n => n.kind === 'team' && n.runId === run.id)) {
    const passes = rows.find(row => row.team_id === frame.refId)?.state.passes ?? []
    const last = passes.flatMap(pass => pass.agents).findLast(id => nodes.some(n => n.id === `agent:${id}`))
    const from = frame.id === checks.team ? last && `agent:${last}` : frame.id
    if (from) edges.push({ id: `${from}>${checks.id}`, source: from, target: checks.id, active })
  }
}

/** The box right of the Orchestrator's work, an arrow into it from that work: its middle agent, else the Orchestrator. */
function arrowInto(checks: GraphNode, own: GraphNode[], loop: Loop): GraphEdge {
  const data = checks.data as ChecksData
  const from = own.length ? own[Math.floor((own.length - 1) / 2)].id : `agent:${data.leadId}`
  return {
    id: `${from}>${checks.id}`,
    source: from,
    target: checks.id,
    active: Boolean(data.running) || loop.tone === 'run',
  }
}

/** The nodes `gone` names, and what sits in them, taken out of `nodes`; returns all their ids. */
function takeOut(nodes: GraphNode[], gone: Set<string>): Set<string> {
  for (let size = -1; size !== gone.size;) {
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
  return {
    width,
    height:
      LOOP.top +
      rows * (LOOP.cardH + LOOP.shadow) +
      (rows - 1) * LOOP.gap +
      LOOP.foot +
      LOOP.pad +
      wrapped(loop, width),
  }
}

/**
 * Room for what wraps rather than being cut: the tag's status under itself (its tag holds the frame's width less 64 px), the
 * dots on lines of their own past half the foot.
 * shortcut: lines counted at ~6.5 px a character of the tag's text, 10 px a dot - measure the text if a box is seen cut.
 */
function wrapped(loop: Loop, width: number): number {
  const tag = (`Checks · KOLONİ  ${saysRounds(loop) ? loop.status : ''}`.length * 6.5) / (width - 64 - 12)
  const foot = width - 2 * LOOP.pad
  const dots = saysRounds(loop) && loop.dots.length * 10 > foot / 2 ? Math.ceil((loop.dots.length * 10) / foot) * 11 : 0
  return (Math.ceil(tag) - 1) * 15 + dots
}
