import type { Message, Run } from '../api/types'
import type { ConvState } from '../state/applyEvent'
import type { Loop } from './checksLoop'
import type { AgentData, GraphEdge, GraphNode } from './deriveGraph'

/** KOLONİ's own end-of-turn test run: its call on the Lead's answer (`ProofMixin.PROOF_CALL`). */
export const PROOF_CALL = 'koloni_proof_'
/** ...and S5b's live try's own runs (`try_mixin.TRY_CALL`): no test run. */
export const TRY_CALL = `${PROOF_CALL}try_`
/**
 * S10: a turn of a chat whose Check after a change was off - no node, only the Orchestrator's strip says so (a choice made for this
 * chat). One of a project whose After a change is Nothing has neither: its standing choice, which the Checked section already says.
 */
export const OFF_FOR_CHAT = 'not checked · off for this chat'
/** S5c: a recipe's turn whose Checks step checks nothing: no node either, the strip says so. */
export const OFF_IN_RECIPE = 'not checked · off in the recipe’s Checks step'

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
  /** k-canli-016: what failed is a look's hold (a Reviewer's, a Tester's), every check passed: "on hold", not "still failing". */
  held?: boolean
  /** tuval-kontrol-dongusu: the agents its checks opened, and the rounds - drawn in the box (`checksLoop.settleChecks`); null: none. */
  loop?: Loop | null
}

/** The Checked rows of a look - a review, its findings, the live try's Tester -: their failing is a hold. */
const LOOKS = new Set(['review', 'finding', 'try'])

/** Whether what failed in the Checked rows is only a look's hold. */
const heldOnly = (checked: Message | undefined, rows = checked?.checked ?? []) =>
  rows.some(row => row.state === 'failed') && rows.every(row => row.state !== 'failed' || LOOKS.has(row.kind))

/**
 * A command's tool, short: "pytest" of `python -m pytest -q`, "c8" of S9's `npx --no c8 …`, "python -c" of `python -c "…"`
 * (never its quoted code), else its first word.
 */
export function toolOf(command: string): string {
  const words = command.split(/\s+/).filter(Boolean)
  const after = words.indexOf('-m')
  const inline = inlineAt(words)
  if (inline > 0 && (after < 0 || inline < after)) return `${words[inline - 1].split(/[\\/]/).at(-1)} ${words[inline]}`
  return (
    (after >= 0
      ? words[after + 1]
      : words.find(word => !word.startsWith('-') && !/^(npx|uv|poetry|run|python[\d.]*|py)$/.test(word))) ?? command
  )
}

/** Where an interpreter is handed its code on the line - `python -c`, `node -e`, `bash -c` -; -1 for none. */
const inlineAt = (words: string[]) =>
  words.findIndex(
    (word, at) =>
      at > 0 &&
      /^-[ce]$/.test(word) &&
      /^(python[\d.]*|py|node|bash|sh|zsh|pwsh|ruby|perl)(\.exe)?$/i.test(words[at - 1].split(/[\\/]/).at(-1) ?? ''),
  )

export type Line = { state: Row['state']; text: string; since?: string | null }

/** S6's rows by their step: "Full tests running: cmd" is "full tests · running", "Related tests passed: cmd" "related tests · passed"; any other row as it is. */
function stepOf(row: Row): string | null {
  const own =
    row.command && row.text.endsWith(`: ${row.command}`) ? row.text.slice(0, -row.command.length - 2) : row.text
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
  if (!counts || !row.command || counts.passed + counts.failed === 0)
    return { state: row.state, text: step ?? row.text }
  if (step?.startsWith('related'))
    return {
      state: row.state,
      text: `related tests · ${counts.passed} passed${counts.failed ? ` · ${counts.failed} failed` : ''}`,
    }
  const unit = counts.unit === 'tests' ? '' : ` ${counts.unit}`
  const failed = counts.failed ? ` · ${counts.failed} ✗` : ''
  return { state: row.state, text: `${toolOf(row.command)} · ${counts.passed}${unit} ✓${failed}` }
}

/** S5a: the kinds of work KOLONİ checks after a turn wrote them (`app.proof_kinds.KINDS`), each one line on the node. */
const KINDS: Record<string, string> = {
  docs: 'documents',
  slides: 'slides',
  diagram: 'diagrams',
  data: 'data',
  config: 'config files',
  scripts: 'scripts',
  style: 'code style and types',
}

/** A kind's rows as one line, as a test run's: "documents · 2 ✓ · 1 ✗" - its files that passed and failed; "documents · not checked" where it was switched off. */
function kindLine(kind: string, rows: Row[]): Line {
  const passed = rows.filter(one => one.state === 'passed').length
  const failed = rows.filter(one => one.state === 'failed').length
  const state: Row['state'] = failed ? 'failed' : passed ? 'passed' : 'note'
  if (!passed && !failed)
    return {
      state,
      text: `${KINDS[kind]} · ${rows.some(one => one.text.startsWith('Not checked')) ? 'not checked' : 'noted'}`,
    }
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
      lines.push(
        kindLine(
          one.kind,
          rows.filter(other => other.kind === one.kind),
        ),
      )
    }
  }
  return lines
}

/** The end check's passes: a new one where a run of the pass so far comes again. Each after the first followed a fix round - or the ask for a test (`roundsOf`). */
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

/** Its fix rounds: at its end the Checked section's count (the tests run again on a test KOLONİ asked for are none), before it each pass again. */
const roundsOf = (checked: Message | undefined, said: number, calls: { arguments: string }[]) =>
  checked ? said : Math.max(passesOf(calls) - 1, 0)

/** The Orchestrator's strip: "✓ checked · 1 round", "✓ checked · related only" (the whole suite stopped or not run), "✗ still failing", "✗ on hold" (a look holds, every check passed), "not checked" - or nothing before its end. */
export function stripOf(data: ChecksData): string | null {
  if (data.running || data.lines.some(line => line.state === 'running')) return '● checking…'
  const tests = data.lines.filter(line => line.state !== 'note')
  if (!tests.length) return null
  const rounds = data.rounds ? ` · ${data.rounds} round${data.rounds === 1 ? '' : 's'}` : ''
  if (tests.some(line => line.state === 'failed')) return `✗ ${data.held ? 'on hold' : 'still failing'}${rounds}`
  const passed = tests.filter(line => line.state === 'passed')
  if (!passed.length) return 'not checked'
  return `✓ checked${passed.every(line => line.text.startsWith('related tests')) ? ' · related only' : ''}${rounds}`
}

/**
 * A turn's Checks node, after its Orchestrator: from KOLONİ's own test calls (live) and its Checked section (at its end). Its
 * rounds are in it, not lines back to the Orchestrator: the agents KOLONİ opened, and those it sent work back to, are drawn in
 * it (`checksLoop`). None where nothing was checked.
 */
export function checksNode(state: ConvState, run: Run, nodes: GraphNode[], edges: GraphEdge[]): ChecksData | null {
  const lead = state.agents.find(a => a.run_id === run.id && a.depth === 0)
  const own = state.toolCalls.filter(c => c.run_id === run.id && c.provider_call_id.startsWith(PROOF_CALL))
  // (Its test runs - not S5b's live try's (`TRY_CALL`): a tool's --help, a preview; its spawns are S3's Reviewers and S5b's Tester.)
  const calls = own.filter(c => c.name === 'run_command' && !c.provider_call_id.startsWith(TRY_CALL))
  const checked = state.messages.find(m => m.run_id === run.id && m.role === 'checked')
  if (!lead || (!own.length && !checked)) return null
  // (Off for this chat, or After a change at Nothing: KOLONİ checked nothing - no node, as no check ran.)
  const off = checked?.checked?.find(row => row.kind in OFF_STRIPS)
  if (off) return notChecked(nodes, lead.id, OFF_STRIPS[off.kind])
  const at = calls.find(c => c.status === 'running')
  const said = roundsSaid(checked)
  const rounds = roundsOf(checked, said.n, calls)
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
    held: heldOnly(checked),
  }
  const id = `checks:${run.id}`
  const { team, from } = recipeEnd(run, nodes, lead.id)
  nodes.push({ id, kind: 'checks', runId: run.id, refId: run.id, data, ...(team && { team }) })
  edges.push({ id: `${from}>${id}`, source: from, target: id, active: Boolean(at), plan: true, po: true })
  // (The Orchestrator's strip says it too.)
  const leadNode = nodes.find(node => node.id === `agent:${lead.id}`)
  if (leadNode) (leadNode.data as AgentData).checked = stripOf(data)
  return data
}

/**
 * S5c: in a recipe's turn the Checks node is the recipe's last step - inside its frame (the turn's last), joined from its last
 * pass's agent, under which the layout puts it; else after the Orchestrator.
 */
function recipeEnd(run: Run, nodes: GraphNode[], leadId: string): { team?: string; from: string } {
  const frame = nodes.filter(node => node.kind === 'team' && node.runId === run.id).at(-1)
  if (!frame) return { from: `agent:${leadId}` }
  const last = run.teams
    ?.find(row => row.team_id === frame.refId)
    ?.state?.passes.at(-1)
    ?.agents.at(-1)
  return {
    team: frame.id,
    from: last && nodes.some(node => node.id === `agent:${last}`) ? `agent:${last}` : `agent:${leadId}`,
  }
}

/** The Checked rows that say nothing was checked, each with the strip's words (none at Nothing: the project's standing choice). */
const OFF_STRIPS: Record<string, string | null> = {
  chat_off: OFF_FOR_CHAT,
  not_checked: null,
  recipe_off: OFF_IN_RECIPE,
}

/** Off for this chat, or set to Nothing: no Checks node is drawn - the Orchestrator's strip says it, so nobody takes the turn as checked. */
function notChecked(nodes: GraphNode[], leadId: string, said: string | null): null {
  const leadNode = nodes.find(node => node.id === `agent:${leadId}`)
  if (leadNode && said) (leadNode.data as AgentData).checked = said
  return null
}

/** A test run's clock: its command's own start - not its call's, which may wait for a free slot first; null before it starts. */
function sinceOf(state: ConvState, callId: string): string | null {
  return state.commands.find(c => c.tool_call_id === callId)?.started_at ?? null
}

/**
 * What the Checked section says of its fix rounds at its end: how many, and why each went back where a Reviewer's findings
 * did - "Sent back to fix: 2 of 3 rounds (tests fail; 2 blocking findings)". Before its end, none (a pass after a round may
 * run nothing: the Orchestrator's own run stood - counted here then).
 */
export function roundsSaid(checked: Message | undefined): { n: number; why: string[] } {
  const text = checked?.checked?.find(row => row.kind === 'rounds')?.text ?? ''
  // (k-canli-016: "Sent back to fix: round 3 (until it passes, 3 failing → 1)" - no count of rounds, no why each)
  const until = /round (\d+) \(until it passes/.exec(text)
  if (until) return { n: Number(until[1]), why: [] }
  const [, n, why] = /(\d+) of \d+ rounds?(?: \((.*)\))?/.exec(text) ?? []
  return { n: Number(n ?? 0), why: why ? why.split('; ') : [] }
}

function commandOf(argumentsJson: string): string {
  try {
    const given = JSON.parse(argumentsJson) as { command?: unknown }
    return typeof given.command === 'string' ? given.command : ''
  } catch {
    return ''
  }
}
