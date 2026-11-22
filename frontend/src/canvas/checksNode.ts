import type { Message, Run } from '../api/types'
import type { ConvState } from '../state/applyEvent'
import type { AgentData, GraphEdge, GraphNode } from './deriveGraph'

/** KOLONİ's own end-of-turn test run: its call on the Lead's answer (`ProofMixin.PROOF_CALL`). */
export const PROOF_CALL = 'koloni_proof_'
/** How often the end check sends failing tests back, at most (`MAX_SENT_BACK`). */
export const MOST_ROUNDS = 2

type Row = NonNullable<Message['checked']>[number]

/** The Checks node (plan decision 12): KOLONİ's own checks after the Orchestrator's work - what runs now, then what came of it. */
export interface ChecksData extends Record<string, unknown> {
  runId: string
  leadId: string
  /** KOLONİ's test run at work now: its command and when it started; null: none (no time is made up). */
  running: { command: string; since: string | null } | null
  /** What was checked, short, each with its state - from the turn's Checked section; a row still running (S6) as it is. */
  lines: { state: Row['state']; text: string }[]
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

/** A Checked row on the node: "pytest · 214 ✓ · 2 ✗" (go's "3 packages ✓") where its runner counted some passed or failed, else its own words. */
export function lineOf(row: Row): { state: Row['state']; text: string } {
  const counts = row.counts
  if (!counts || !row.command || counts.passed + counts.failed === 0) return { state: row.state, text: row.text }
  const unit = counts.unit === 'tests' ? '' : ` ${counts.unit}`
  const failed = counts.failed ? ` · ${counts.failed} ✗` : ''
  return { state: row.state, text: `${toolOf(row.command)} · ${counts.passed}${unit} ✓${failed}` }
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

/** The Orchestrator's strip: "✓ checked · 1 round", "✗ still failing", "not checked" - or nothing before its end. */
export function stripOf(data: ChecksData): string | null {
  if (data.running) return '● checking…'
  const tests = data.lines.filter(line => line.state !== 'note')
  if (!tests.length) return null
  const rounds = data.rounds ? ` · ${data.rounds} round${data.rounds === 1 ? '' : 's'}` : ''
  if (tests.some(line => line.state === 'failed')) return `✗ still failing${rounds}`
  return tests.some(line => line.state === 'passed') ? `✓ checked${rounds}` : 'not checked'
}

/**
 * A turn's Checks node, after its Orchestrator: from KOLONİ's own test calls (live) and its Checked section (at its end).
 * Each fix round is a line back to the Orchestrator, "round 1 of 2: tests fail". None where nothing was checked.
 */
export function checksNode(state: ConvState, run: Run, nodes: GraphNode[], edges: GraphEdge[]): ChecksData | null {
  const lead = state.agents.find(a => a.run_id === run.id && a.depth === 0)
  const calls = state.toolCalls.filter(c => c.run_id === run.id && c.provider_call_id.startsWith(PROOF_CALL))
  const checked = state.messages.find(m => m.run_id === run.id && m.role === 'checked')
  if (!lead || (!calls.length && !checked)) return null
  const at = calls.find(c => c.status === 'running')
  // (Its clock: the command's own start - not its call's, which may wait for a free slot first.)
  const since = at ? (state.commands.find(c => c.tool_call_id === at.id)?.started_at ?? null) : null
  const rounds = Math.max(passesOf(calls) - 1, 0)
  const data: ChecksData = {
    runId: run.id,
    leadId: lead.id,
    running: at ? { command: commandOf(at.arguments), since } : null,
    lines: (checked?.checked ?? []).map(lineOf),
    rounds,
    recipe: Boolean(run.teams?.length),
  }
  const id = `checks:${run.id}`
  nodes.push({ id, kind: 'checks', runId: run.id, refId: run.id, data })
  edges.push({ id: `agent:${lead.id}>${id}`, source: `agent:${lead.id}`, target: id, active: Boolean(at), plan: true, po: true })
  for (let round = 1; round <= Math.min(rounds, MOST_ROUNDS); round++)
    edges.push({ id: `${id}>agent:${lead.id}:${round}`, source: id, target: `agent:${lead.id}`, active: false, round: `round ${round} of ${MOST_ROUNDS}: tests fail` })
  // (The Orchestrator's strip says it too.)
  const leadNode = nodes.find(node => node.id === `agent:${lead.id}`)
  if (leadNode) (leadNode.data as AgentData).checked = stripOf(data)
  return data
}

function commandOf(argumentsJson: string): string {
  try {
    const given = JSON.parse(argumentsJson) as { command?: unknown }
    return typeof given.command === 'string' ? given.command : ''
  } catch {
    return ''
  }
}
