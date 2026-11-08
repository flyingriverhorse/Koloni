import type { Agent, Command, Message, ToolCall } from '../api/types'
import { commandStatus } from '../commands/commandStatus'
import { toolName } from '../chat/toolSummary'
import type { ConvState } from '../state/applyEvent'
import { titleOf } from './agentStatus'
import { stepsOf } from './AgentSteps'

/**
 * What an agent did, told as a few plain phases (design A, "Report first"): a simple rule, no model. Its own calls are
 * walked in order and calls of one kind in a row are one phase - reads "Looked around", edits "Changed", commands "Ran" -
 * each with its result in words. Words of its own end a phase and are the next one's quote; a message handed to it,
 * a sub-agent it opened and an ask of the user are phases of their own. A command that waits for the user is not one:
 * the window shows it as its last step, with its card.
 */
export type PhaseKind = 'read' | 'change' | 'command' | 'opened' | 'own' | 'talked' | 'asked' | 'tool' | 'heard' | 'reminded' | 'said' | 'report'

export interface Phase {
  kind: PhaseKind
  /** When it began: its first call's step, or the message. */
  at: string
  /** The first sentence its step said before it, where it said one. */
  said: string | null
  calls: ToolCall[]
  /** A message handed to it, KOLONİ's reminder or its own words (`heard`, `reminded`, `said`). */
  message?: Message
  /** A reminder said the same several times in a row. */
  count?: number
}

/** [verb, one, more] of each tool that only looks: KOLONİ's and Claude Code's as KOLONİ records them (`app/handoff.py`). */
// shortcut: Codex reads with shell commands and Copilot's, agy's and Qoder's own read tools are not measured by name: they
// are "Used <tool>"; add their names here once a live run shows what KOLONİ records them as.
const [READ, SEARCH, LIST]: [string, string, string][] = [['read', 'file', 'files'], ['searched', 'time', 'times'], ['listed', 'folder', 'folders']]
const LOOKS: Record<string, [string, string, string]> = {
  read_file: READ,
  claude__Read: READ,
  claude__NotebookRead: READ,
  view_image: ['looked at', 'image', 'images'],
  search: SEARCH,
  claude__Grep: SEARCH,
  claude__Glob: SEARCH,
  list_dir: LIST,
  claude__LS: LIST,
  recall: ['recalled', 'memory', 'memories'],
}
/** Tools that write a file: a failed one has no change on record, and is a change phase all the same. */
const WRITES = new Set(['write_file', 'edit_file', 'claude__Write', 'claude__Edit', 'claude__MultiEdit', 'claude__NotebookEdit'])
const ASKS = new Set(['ask_user', 'create_role'])
/** Phases that take the next call of their kind; the others stand alone (each has a row to act on). */
const GROUPS = new Set<PhaseKind>(['read', 'change', 'command', 'talked', 'tool'])

const many = (n: number, one: string, more = `${one}s`) => `${n} ${n === 1 ? one : more}`

/** The first sentence of some words, on one line. */
export function firstSentence(words: string): string {
  const line = words.trim().split(/\n\s*\n|(?<=[.!?:])\s/)[0].replace(/\s+/g, ' ')
  return line.length > 160 ? `${line.slice(0, 159)}…` : line
}

function kindOf(state: ConvState, call: ToolCall, subAgents: Set<string>): PhaseKind {
  if (state.agents.some(a => a.tool_call_id === call.id)) return 'opened'
  if (subAgents.has(call.id)) return 'own'
  if (state.commands.some(c => c.tool_call_id === call.id) || call.name === 'run_command') return 'command'
  if (state.fileChanges.some(f => f.tool_call_id === call.id) || WRITES.has(call.name)) return 'change'
  if (call.name === 'message_agent') return 'talked'
  if (ASKS.has(call.name)) return 'asked'
  return Object.hasOwn(LOOKS, call.name) ? 'read' : 'tool'
}

/** A message handed to it or KOLONİ's reminder: a phase of its own. */
function heardOf(message: Message, count: number): Phase {
  return { kind: message.role === 'memory' ? 'reminded' : 'heard', at: message.created_at, said: null, calls: [], message, count }
}

/** Its phases, in order (see `Phase`). */
export function phasesOf(state: ConvState, agent: Pick<Agent, 'id' | 'report' | 'ended_at'>): Phase[] {
  const { steps, said, callsOf, subAgents } = stepsOf(state, agent.id, agent.report)
  const waits = new Set(state.commands.filter(c => c.status === 'proposed').map(c => c.tool_call_id))
  const phases: Phase[] = []
  // A command it was warned of (it deletes, overwrites a remote, opens a secret) stands alone, with its own result.
  const alone = (call: ToolCall) => state.commands.some(c => c.tool_call_id === call.id && c.danger)
  const add = (call: ToolCall, kind: PhaseKind, quote: string | null, at: string) => {
    const last = phases[phases.length - 1]
    const joins = quote === null && last?.kind === kind && GROUPS.has(kind) && !alone(call) && !alone(last.calls[0]) && (kind !== 'tool' || last.calls[0].name === call.name)
    if (joins) last.calls.push(call)
    else phases.push({ kind, at, said: quote, calls: [call] })
  }
  for (const [message, count] of steps) {
    if (message.role !== 'assistant') {
      phases.push(heardOf(message, count))
      continue
    }
    const words = said(message).trim()
    let quote: string | null = words ? firstSentence(words) : null
    for (const call of callsOf(message.id).filter(c => !waits.has(c.id))) {
      add(call, kindOf(state, call, subAgents), quote, message.created_at)
      quote = null
    }
    // Words with no call after them: what it said, a phase of its own.
    if (quote !== null) phases.push({ kind: 'said', at: message.created_at, said: quote, calls: [], message })
  }
  // Its report: the last phase, once written (the report itself is on top of the window, not said again).
  if (agent.report !== null) phases.push({ kind: 'report', at: agent.ended_at ?? phases[phases.length - 1]?.at ?? '', said: null, calls: [] })
  return phases
}

/** How a call that did not end well ended, in a word: "failed", "refused", "interrupted"; null for one that went. */
const MISHAP: Partial<Record<ToolCall['status'], string>> = { failed: 'failed', denied: 'refused', interrupted: 'interrupted' }

/** Words counted, in the order first seen: "2 failed, 1 refused"; each count with its noun where one is given. */
function counted(words: string[], noun = ''): string {
  const counts = new Map<string, number>()
  for (const word of words) counts.set(word, (counts.get(word) ?? 0) + 1)
  return [...counts].map(([word, n]) => `${noun ? many(n, noun) : n} ${word}`).join(', ')
}

/** The calls of a phase that did not end well, in words: "1 failed", "2 refused", "1 interrupted". */
function callMarks(calls: ToolCall[]): string | null {
  return counted(calls.flatMap(c => MISHAP[c.status] ?? [])) || null
}

const working = (calls: ToolCall[]) => calls.some(c => c.status === 'running' || c.status === 'pending')

/** "read 6 files, searched 1 time": what a look-around did, by kind, in the order it did it. */
function looked(calls: ToolCall[]): string {
  const counts = new Map<[string, string, string], number>()
  for (const call of calls) counts.set(LOOKS[call.name], (counts.get(LOOKS[call.name]) ?? 0) + 1)
  return [...counts].map(([[verb, one, more], n]) => `${verb} ${many(n, one, more)}`).join(', ')
}

/** A test run: it is "the tests", and it "passed".
 * shortcut: known test runners by name only; a project's own test script ("make check") is "Ran make check". */
export const isTest = (command: string) => /\b(pytest|vitest|jest|unittest|npm (run )?test|pnpm test|yarn test|go test|cargo test|playwright test)\b/.test(command)

/** How one command came out, in a word or two: every state has its own, so none is lost from a count. */
const WORDS: Partial<Record<Command['status'], string>> = {
  running: 'running…',
  approved: 'approved, not started',
  timed_out: 'timed out',
  killed: 'stopped',
  rejected: 'rejected',
  failed_to_start: 'did not start',
  blocked: 'blocked by its sandbox',
  interrupted: 'interrupted',
}
// A CLI's own command that failed is on record as ended with no exit code, its call as failed (`callFailed`).
function outcome(command: Command, fine: string, callFailed = false): string {
  if (command.status === 'exited') return command.exit_code === 0 ? fine : command.exit_code !== null || callFailed ? 'failed' : 'exit not reported'
  if (command.status === 'interrupted' && command.started_at === null) return 'approved, never ran'
  return WORDS[command.status] ?? command.status
}

/** Each command's outcome, its call's failure read too. */
const wordsOf = (state: ConvState, commands: Command[], fine: string) =>
  commands.map(c => outcome(c, fine, state.toolCalls.find(t => t.id === c.tool_call_id)?.status === 'failed'))

/** How a phase of commands came out, in words: each outcome counted, nothing left out ("1 OK, 1 rejected"). */
function ran(state: ConvState, commands: Command[]): string | null {
  if (commands.length === 0) return null
  const fine = commands.every(c => isTest(c.command)) ? 'passed' : 'OK'
  const words = wordsOf(state, commands, fine)
  const code = commands[0].exit_code
  if (commands.length === 1) return words[0] === 'failed' ? `failed (${code === null ? 'its CLI said so' : `exit ${code}`})` : words[0]
  if (fixed(commands, words, fine)) return `failed ${words.length === 2 ? 'once' : `${words.length - 1} times`}, then ${fine}`
  return counted(words)
}

/** One command run again until it went: every run before the last failed with an exit code, and the last exited 0. */
// shortcut: only reruns in a row are seen; a rerun with an edit between them is two phases (NOTLAR's rule 3 joins them).
const fixed = (commands: Command[], words: string[], fine: string) =>
  words[words.length - 1] === fine && words.slice(0, -1).every(word => word === 'failed') && new Set(commands.map(c => c.command)).size === 1

/** What a command that never ran was, as its line starts: not "Ran". */
const NOT_RAN: Record<string, string> = {
  rejected: 'Asked you to run',
  'did not start': 'Tried to run',
  'approved, not started': 'About to run',
  'approved, never ran': 'Did not run',
}

const commandsOf = (state: ConvState, calls: ToolCall[]) => calls.flatMap(call => state.commands.filter(c => c.tool_call_id === call.id))

/** A run_command call with no command on record: how it stands, in a word. */
const bareWord = (call: ToolCall) => MISHAP[call.status] ?? (call.status === 'succeeded' ? 'done' : 'now…')
/** What calls with no command on record were, as their line starts. */
const BARE: Record<string, string> = { refused: 'Asked to run', failed: 'Tried to run', 'now…': 'Running', done: 'Ran' }

/** A phase of commands: "Ran the tests", "Ran 3 commands", or what it was where none of them ran; and every result. */
function commandLine(state: ConvState, calls: ToolCall[]) {
  const commands = commandsOf(state, calls)
  // A call with no command on record (refused before one was made, say) is said apart, never as one of those that ran.
  const bare = calls.filter(call => !commands.some(c => c.tool_call_id === call.id)).map(bareWord)
  if (commands.length === 0) {
    const verb = bare.every(word => word === bare[0]) ? (BARE[bare[0]] ?? 'Tried to run') : 'Tried to run'
    return { title: `${verb} ${bare.length === 1 ? 'a command' : many(bare.length, 'command')}`, result: bare.length === 1 ? bare[0] : counted(bare) }
  }
  const names = [...new Set(commands.map(c => c.command))]
  const never = commands.every(c => NOT_RAN[outcome(c, 'OK')]) ? NOT_RAN[outcome(commands[0], 'OK')] : null
  const what = names.length === 1 ? (never || !isTest(names[0]) ? names[0] : 'the tests') : many(commands.length, 'command')
  const more = bare.length > 0 ? `; ${counted(bare, 'more command')}` : ''
  return { title: `${never ?? 'Ran'} ${what}`, result: `${ran(state, commands)}${more}` }
}

export type Tone = 'ok' | 'now' | 'warn' | 'bad'

/**
 * How a phase stands, for its mark: at work; something in it failed (anywhere, not only its last); something did not
 * end well or is not known (refused, stopped, interrupted, no exit code); or all went. Its line says which in words.
 */
export function phaseTone(state: ConvState, phase: Phase): Tone {
  const commands = commandsOf(state, phase.calls)
  const bare = phase.calls.filter(call => !commands.some(c => c.tool_call_id === call.id))
  const words = wordsOf(state, commands, 'OK')
  if (working(bare) || words.includes('running…')) return 'now'
  if (bare.some(c => c.status === 'failed') || words.includes('failed') || commands.some(c => commandStatus(c).tone === 'del')) return 'bad'
  if (bare.some(c => c.status === 'denied' || c.status === 'interrupted') || words.some(word => word !== 'OK')) return 'warn'
  return 'ok'
}

/** A phase's line: what it was, and how it came out - in words, a tool's own name only for a tool nothing else names. */
export function phaseLine(state: ConvState, phase: Phase): { title: string; result: string | null } {
  return LINES[phase.kind](state, phase)
}

const argOf = (call: ToolCall, key: string): string | null => {
  try {
    const value: unknown = (JSON.parse(call.arguments || '{}') as Record<string, unknown>)[key]
    return typeof value === 'string' ? value : null
  } catch {
    return null
  }
}

/** Where a call looked: its file, folder or pattern, else its own line. */
export const targetOf = (call: ToolCall) => argOf(call, 'file_path') ?? argOf(call, 'path') ?? argOf(call, 'pattern') ?? argOf(call, 'query') ?? toolName(call)

const LINES: Record<PhaseKind, (state: ConvState, phase: Phase) => { title: string; result: string | null }> = {
  read: (_, { calls }) => ({ title: 'Looked around', result: [looked(calls), working(calls) && 'now…', callMarks(calls)].filter(Boolean).join(' · ') }),
  change: (state, { calls }) => {
    const changes = state.fileChanges.filter(f => calls.some(c => c.id === f.tool_call_id))
    // (A write with no change on record - it failed, or waits for a file - by the path it was given.)
    const paths = [...new Set(calls.map(c => changes.find(f => f.tool_call_id === c.id)?.path ?? targetOf(c)))]
    const lines = changes.length ? `+${changes.reduce((n, f) => n + f.additions, 0)} −${changes.reduce((n, f) => n + f.deletions, 0)}` : null
    return { title: paths.length === 1 ? `Changed ${paths[0]}` : `Changed ${many(paths.length, 'file')}`, result: [lines, working(calls) && 'now…', callMarks(calls)].filter(Boolean).join(' · ') || null }
  },
  command: (state, { calls }) => commandLine(state, calls),
  opened: (state, { calls }) => {
    const child = state.agents.find(a => a.tool_call_id === calls[0].id)
    return { title: `Opened ${titleOf(child?.name || child?.role_name || 'an agent')}`, result: null }
  },
  own: () => ({ title: 'Opened a sub-agent of its CLI', result: null }),
  talked: (_, { calls }) => ({ title: `Talked to ${[...new Set(calls.map(c => titleOf(argOf(c, 'to') ?? 'an agent')))].join(', ')}`, result: callMarks(calls) }),
  asked: (_, { calls }) => ({ title: calls[0].name === 'create_role' ? 'Asked you for a new role' : 'Asked you a question', result: working(calls) ? 'waits for you' : callMarks(calls) }),
  tool: (_, { calls }) => ({ title: `Used ${toolName(calls[0])}${calls.length > 1 ? ` ×${calls.length}` : ''}`, result: [working(calls) && 'now…', callMarks(calls)].filter(Boolean).join(' · ') || null }),
  heard: (state, { message }) => ({ title: heardFrom(state, message!), result: null }),
  reminded: (_, { count = 1 }) => ({ title: `KOLONİ reminded it${count > 1 ? ` ×${count}` : ''}`, result: null }),
  said: () => ({ title: 'Said', result: null }),
  report: () => ({ title: 'Wrote its report', result: null }),
}

function heardFrom(state: ConvState, message: Message): string {
  const from = message.from_agent_id ? titleOf(state.agents.find(a => a.id === message.from_agent_id)?.name || 'an agent') : null
  if (message.board_post_id) return `Got a note from the notebook, by ${from ?? 'you'}`
  if (message.room_post_id) return 'Got a message from its room'
  return `Got a message from ${from ?? 'KOLONİ'}`
}
