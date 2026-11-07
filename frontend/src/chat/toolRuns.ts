import type { Command, FileChange, Message, ToolCall } from '../api/types'
import { toolName, toolSummary } from './toolSummary'

/** Each message's calls, in the order they were made. */
export function callsByMessage(calls: ToolCall[]): Map<string, ToolCall[]> {
  const of = new Map<string, ToolCall[]>()
  for (const call of [...calls].sort((a, b) => a.seq - b.seq)) {
    const mine = of.get(call.message_id)
    if (mine) mine.push(call)
    else of.set(call.message_id, [call])
  }
  return of
}

/**
 * An agent's calls in a row, in the order the chat shows them, with no words of its between
 * them (K-ozet-satiri): two or more are one line. A step of the model is a message of its
 * own, so a run goes on across empty messages of the same agent and turn; words, anybody
 * else's message, or a call that stands alone (a card, a row that waits for you) end it.
 */
export function toolRuns(messages: Message[], callsOf: Map<string, ToolCall[]>, stands: (call: ToolCall) => boolean): ToolCall[][] {
  const runs: ToolCall[][] = [[]]
  let before: Message | undefined
  for (const message of messages) {
    if (message.role !== 'assistant' || message.content || message.run_id !== before?.run_id || message.agent_id !== before.agent_id) runs.push([])
    before = message
    for (const call of callsOf.get(message.id) ?? []) {
      if (stands(call)) runs.push([])
      else runs[runs.length - 1].push(call)
    }
  }
  return runs.filter(run => run.length > 1)
}

/** What a run's line counts, by kind and in this order: [verb, one, more than one]. */
const KINDS: Record<string, [string, string, string]> = {
  read_file: ['read', 'file', 'files'],
  list_dir: ['listed', 'folder', 'folders'],
  search: ['searched', 'time', 'times'],
  recall: ['recalled', 'memory', 'memories'],
  run_command: ['ran', 'command', 'commands'],
  edit_file: ['edited', 'file', 'files'],
  // Slice 51: every call on the agent's own browser, as one kind.
  browser: ['tried the page in', 'step', 'steps'],
}
const ORDER = Object.keys(KINDS)
const rank = (kind: string) => (ORDER.includes(kind) ? ORDER.indexOf(kind) : ORDER.length)

/**
 * A run's line: what was done, counted by kind ("Read 4 files, listed 4 folders"; any other
 * tool as the canvas counts it, "notify ×2"), and what runs now; how many failed, were
 * refused or were cut off (`marks`); its state. Only what was done is counted: what did not
 * end well is in its mark, and what still runs is the one named.
 */
export function runHead(calls: ToolCall[], { commands, fileChanges }: { commands: Command[]; fileChanges: FileChange[] }) {
  const kinds = new Map<string, ToolCall[]>()
  for (const call of calls.filter(c => c.status === 'succeeded')) {
    const changes = fileChanges.some(f => f.tool_call_id === call.id) || call.name === 'write_file' || call.name === 'edit_file'
    const ran = commands.some(c => c.tool_call_id === call.id) || call.name === 'run_command'
    const kind = changes ? 'edit_file' : ran ? 'run_command' : call.name.startsWith('browser_') ? 'browser' : Object.hasOwn(KINDS, call.name) ? call.name : toolName(call)
    kinds.set(kind, [...(kinds.get(kind) ?? []), call])
  }
  const done = [...kinds]
    .sort(([a], [b]) => rank(a) - rank(b))
    .map(([kind, of]) => {
      if (!Object.hasOwn(KINDS, kind)) return `${kind} ×${of.length}`
      const [verb, one, more] = KINDS[kind]
      const said = `${verb} ${of.length} ${of.length === 1 ? one : more}`
      if (kind !== 'edit_file') return said
      // (Lines made, in the project or the agent's copy: not those of a change turned down or undone.)
      const made = fileChanges.filter(f => MADE.has(f.status) && of.some(call => call.id === f.tool_call_id))
      return made.length ? `${said} (+${made.reduce((n, f) => n + f.additions, 0)} −${made.reduce((n, f) => n + f.deletions, 0)})` : said
    })
  const now = calls.find(call => call.status === 'running')
  const what = [done.join(', '), now && `now: ${toolSummary(now)}`].filter(Boolean).join(' · ')
  const count = (status: ToolCall['status']) => calls.filter(call => call.status === status).length
  // Done if any was; else the worst there is.
  const status: ToolCall['status'] = calls.some(call => call.status === 'running' || call.status === 'pending')
    ? 'running'
    : ENDS.find(end => count(end) > 0) ?? 'succeeded'
  const marks = ENDS.slice(1).filter(end => count(end) > 0).map(end => [end, count(end)] as [ToolCall['status'], number])
  return { what: what.charAt(0).toUpperCase() + what.slice(1), marks, status }
}

const ENDS: ToolCall['status'][] = ['succeeded', 'failed', 'denied', 'interrupted']
const MADE = new Set<FileChange['status']>(['applied', 'merged', 'in_copy'])
