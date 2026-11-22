import type { Message, Run } from '../api/types'
import type { ConvState } from '../state/applyEvent'
import type { AgentData, GraphEdge, GraphNode } from './deriveGraph'

/** KOLONİ's own end-of-turn test run: its call on the Lead's answer (`ProofMixin.PROOF_CALL`). */
export const PROOF_CALL = 'koloni_proof_'
/** How often the end check sends work back, at most, where its Checked section does not say yet (the project's Fix rounds' default). */
export const MOST_ROUNDS = 2
/** S10: a turn of a chat whose Check after a change was off - no node, only the Orchestrator's strip says so. */
export const OFF_FOR_CHAT = 'not checked · off for this chat'

type Row = NonNullable<Message['checked']>[number]

/** The Checks node (plan decision 12): KOLONİ's own checks after the Orchestrator's work - what runs now, then what came of it. */
export interface ChecksData extends Record<string, unknown> {
  runId: string
  leadId: string
  /** KOLONİ's test run at work while the answer waits: its command and when it started; null: none (no time is made up). */
  running: { command: string; since: string | null } | null
  /** What was checked, short, each with its state - from the turn's Checked section; a whole suite still running after the answer (S6) with its start, its clock on the node. */
  lines: Line[]
  /** A check of the turn runs now: Stop this check stops it. */
  stoppable: boolean
  /** Fix rounds sent back so far. */
  rounds: number
  /** In a recipe's turn: the recipe's end. */
  recipe: boolean
}

/** A command's tool, short: "pytest" of `python -m pytest -q`, else its first word. */
export function toolOf(command: string): string {
  const words = command.split(/\s+/).filter(Boolean)
  const after = words.indexOf('-m')
  return (after >= 0 ? words[after + 1] : words.find(word => !/^(npx|uv|poetry|run|python[\d.]*|py)$/.test(word))) ?? command
}

export type Line = { state: Row['state']; text: string; since?: string | null }

/** S6's rows by their step: "Full tests running: cmd" is "full tests · running", "Related tests passed: cmd" "related tests · passed"; any other row as it is. */
function stepOf(row: Row): string | null {
  const own = row.command && row.text.endsWith(`: ${row.command}`) ? row.text.slice(0, -row.command.length - 2) : row.text
  const step = /^(Full|Related) tests (.*)$/.exec(own)
  return step ? `${step[1].toLowerCase()} tests · ${step[2]}` : null
}

/**
 * A Checked row on the node: "pytest · 214 ✓ · 2 ✗" (go's "3 packages ✓") where its runner counted some passed or failed, the related step's
 * "related tests · 12 passed"; a whole suite running after the answer "full tests" with its start (the node's clock), one waiting for the
 * machine "full tests · waiting for another test run to end"; else its own words.
 */
export function lineOf(row: Row): Line {
  if (row.state === 'running' && row.started_at) return { state: row.state, text: 'full tests', since: row.started_at }
  const step = stepOf(row)
  const counts = row.counts
  if (!counts || !row.command || counts.passed + counts.failed === 0) return { state: row.state, text: step ?? row.text }
  if (step?.startsWith('related')) return { state: row.state, text: `related tests · ${counts.passed} passed${counts.failed ? ` · ${counts.failed} failed` : ''}` }
  const unit = counts.unit === 'tests' ? '' : ` ${counts.unit}`
  const failed = counts.failed ? ` · ${counts.failed} ✗` : ''
  return { state: row.state, text: `${toolOf(row.command)} · ${counts.passed}${unit} ✓${failed}` }
}

/** S5a: the kinds of work KOLONİ checks after a turn wrote them (`app.proof_kinds.KINDS`), each one line on the node. */
const KINDS: Record<string, string> = { docs: 'documents', slides: 'slides', diagram: 'diagrams', data: 'data' }

/** A kind's rows as one line, as a test run's: "documents · 2 ✓ · 1 ✗" - its files that passed and failed; "documents · not checked" where it was switched off. */
function kindLine(kind: string, rows: Row[]): Line {
  const passed = rows.filter(one => one.state === 'passed').length
  const failed = rows.filter(one => one.state === 'failed').length
  const state: Row['state'] = failed ? 'failed' : passed ? 'passed' : 'note'
  if (!passed && !failed) return { state, text: `${KINDS[kind]} · ${rows.some(one => one.text.startsWith('Not checked')) ? 'not checked' : 'noted'}` }
  return { state, text: `${KINDS[kind]} · ${passed} ✓${failed ? ` · ${failed} ✗` : ''}` }
}

/** The node's lines: each Checked row as `lineOf` says it - but a kind's rows (S5a) one line, where its first row was. */
export function linesOf(rows: Row[]): Line[] {
  const lines: Line[] = []
  const seen = new Set<string>()
  for (const one of rows) {
    if (!(one.kind in KINDS)) lines.push(lineOf(one))
    else if (!seen.has(one.kind)) {
      seen.add(one.kind)
      lines.push(kindLine(one.kind, rows.filter(other => other.kind === one.kind)))
    }
  }
  return lines
}

/** The end check's passes: a new one where a run of the pass so far comes again. Each after the first followed a fix round (as `rounds` is counted on the server). */
function passesOf(calls: { arguments: string }[]): number {
  let passes = calls.length ? 1 : 0
  let seen = new Set<string>()
  for (const call of calls) {
    const key = call.arguments
    if (seen.has(key)) {
      passes++
      seen = new Set()
    }
    seen.add(key)
  }
  return passes
}

/** The Orchestrator's strip: "✓ checked · 1 round", "✓ checked · related only" (the whole suite stopped or not run), "✗ still failing", "not checked" - or nothing before its end. */
export function stripOf(data: ChecksData): string | null {
  if (data.running || data.lines.some(line => line.state === 'running')) return '● checking…'
  const tests = data.lines.filter(line => line.state !== 'note')
  if (!tests.length) return null
  const rounds = data.rounds ? ` · ${data.rounds} round${data.rounds === 1 ? '' : 's'}` : ''
  if (tests.some(line => line.state === 'failed')) return `✗ still failing${rounds}`
  const passed = tests.filter(line => line.state === 'passed')
  if (!passed.length) return 'not checked'
  return `✓ checked${passed.every(line => line.text.startsWith('related tests')) ? ' · related only' : ''}${rounds}`
}

/**
 * A turn's Checks node, after its Orchestrator: from KOLONİ's own test calls (live) and its Checked section (at its end).
 * Each fix round is a line back to the Orchestrator, "round 1 of 2: tests fail" - "2 blocking findings" for a Reviewer's
 * (S3), whose agents KOLONİ opened come after the node. None where nothing was checked.
 */
export function checksNode(state: ConvState, run: Run, nodes: GraphNode[], edges: GraphEdge[]): ChecksData | null {
  const lead = state.agents.find(a => a.run_id === run.id && a.depth === 0)
  const own = state.toolCalls.filter(c => c.run_id === run.id && c.provider_call_id.startsWith(PROOF_CALL))
  // (Its test runs; its spawns are S3's Reviewers.)
  const calls = own.filter(c => c.name === 'run_command')
  const checked = state.messages.find(m => m.run_id === run.id && m.role === 'checked')
  if (!lead || (!own.length && !checked)) return null
  if (checked?.checked?.some(row => row.kind === 'chat_off')) return offForChat(nodes, lead.id)
  const at = calls.find(c => c.status === 'running')
  const said = roundsSaid(checked)
  const rounds = Math.max(passesOf(calls) - 1, said.n)
  const lines = linesOf(checked?.checked ?? [])
  const data: ChecksData = {
    runId: run.id,
    leadId: lead.id,
    // (Once the Checked section is written, a suite still running is its row: said once.)
    running: at && !checked ? { command: commandOf(at.arguments), since: sinceOf(state, at.id) } : null,
    lines,
    stoppable: Boolean(at) || lines.some(line => line.state === 'running'),
    rounds,
    recipe: Boolean(run.teams?.length),
  }
  const id = `checks:${run.id}`
  nodes.push({ id, kind: 'checks', runId: run.id, refId: run.id, data })
  edges.push({ id: `agent:${lead.id}>${id}`, source: `agent:${lead.id}`, target: id, active: Boolean(at), plan: true, po: true })
  for (let round = 1; round <= Math.min(rounds, said.most); round++)
    edges.push({ id: `${id}>agent:${lead.id}:${round}`, source: id, target: `agent:${lead.id}`, active: false, round: roundLine(round, said) })
  reviewersAfter(state, own, `agent:${lead.id}`, id, edges)
  // (The Orchestrator's strip says it too.)
  const leadNode = nodes.find(node => node.id === `agent:${lead.id}`)
  if (leadNode) (leadNode.data as AgentData).checked = stripOf(data)
  return data
}

/** Off for this chat: no Checks node is drawn - the Orchestrator's strip says it, so nobody takes the turn as checked. */
function offForChat(nodes: GraphNode[], leadId: string): null {
  const leadNode = nodes.find(node => node.id === `agent:${leadId}`)
  if (leadNode) (leadNode.data as AgentData).checked = OFF_FOR_CHAT
  return null
}

/** A test run's clock: its command's own start - not its call's, which may wait for a free slot first; null before it starts. */
function sinceOf(state: ConvState, callId: string): string | null {
  return state.commands.find(c => c.tool_call_id === callId)?.started_at ?? null
}

/**
 * What the Checked section says of its fix rounds at its end: how many, of how many (the project's Fix rounds), and why each
 * went back where a Reviewer's findings did - "Sent back to fix: 2 of 3 rounds (tests fail; 2 blocking findings)". Before
 * its end, none (a pass after a round may run nothing: the Orchestrator's own run stood - counted here then).
 */
function roundsSaid(checked: Message | undefined): { n: number; most: number; why: string[] } {
  const text = checked?.checked?.find(row => row.kind === 'rounds')?.text ?? ''
  const [, n, most, why] = /(\d+) of (\d+) rounds?(?: \((.*)\))?/.exec(text) ?? []
  return { n: Number(n ?? 0), most: most ? Number(most) : MOST_ROUNDS, why: why ? why.split('; ') : [] }
}

/** A round's line back: "round 1 of 2: tests fail" once the Checked section says its rounds; before that only "round 1" - the Fix rounds and what sent it back are not known yet. */
function roundLine(round: number, said: { n: number; most: number; why: string[] }): string {
  return said.n ? `round ${round} of ${said.most}: ${said.why[round - 1] ?? 'tests fail'}` : `round ${round}`
}

/** S3: the Reviewers KOLONİ opened at the turn's end are drawn after its Checks node - their spawn line from it, not the Orchestrator. */
function reviewersAfter(state: ConvState, own: { id: string; name: string }[], from: string, to: string, edges: GraphEdge[]) {
  const looks = new Set(own.filter(c => c.name === 'spawn_agent').map(c => c.id))
  const mine = new Set(state.agents.filter(a => looks.has(a.tool_call_id ?? '')).map(a => `agent:${a.id}`))
  for (const edge of edges)
    if (edge.source === from && mine.has(edge.target)) Object.assign(edge, { id: `${to}>${edge.target}`, source: to })
}

function commandOf(argumentsJson: string): string {
  try {
    const given = JSON.parse(argumentsJson) as { command?: unknown }
    return typeof given.command === 'string' ? given.command : ''
  } catch {
    return ''
  }
}
