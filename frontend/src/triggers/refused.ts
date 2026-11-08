import type { ToolCall } from '../api/types'
import type { ConvState } from '../state/applyEvent'
import type { Allow } from './triggerText'

/** One thing a turn nobody was watching would have asked the user for, and was refused instead. */
export interface Refused {
  /** The tool call that was refused. */
  id: string
  /** What it wanted, in words. */
  what: string
  /** How its trigger could allow it; null for what no trigger allows. */
  allow: Allow | null
}

/** Every refusal for want of somebody to ask says this (app/agent.py). */
const NOBODY = 'nobody is here to ask'
/** "…which does not allow it to <what>. That is the user's standing decision…" */
const WANTED = /does not allow it to ([\s\S]+?)\. That is the user's standing decision/
/** "<provider> cannot work in a turn nobody is watching: it works with its own tools…" (UNATTENDED_NOT_THIS) */
const OWN_TOOLS = /^(?:error: )?(.+?) cannot work in a turn nobody is watching: it works with its own tools/
/** run "<the line, as JSON>"- and " in <folder>" when it was not the project folder. */
const RUN = /^run ("(?:[^"\\]|\\.)*")( in .+)?$/s

function pathOf(call: ToolCall): string {
  try {
    const given: unknown = JSON.parse(call.arguments || '{}')
    const path = given && typeof given === 'object' ? (given as { path?: unknown }).path : null
    return typeof path === 'string' ? path : ''
  } catch {
    return ''
  }
}

function refusal(call: ToolCall): Omit<Refused, 'id'> {
  const wanted = WANTED.exec(call.result ?? '')?.[1]
  if (!wanted) {
    // Refused in other words: a provider that works with its own tools, or a note put forward for the core.
    const provider = OWN_TOOLS.exec(call.result ?? '')?.[1]
    if (provider) return { what: `open an agent on ${provider}, which works with its own tools`, allow: null }
    return { what: call.name === 'remember' ? 'put a note forward for the core' : call.name, allow: null }
  }
  if (wanted === 'change files') {
    const path = pathOf(call)
    return { what: path ? `write ${path}` : 'change files', allow: { write: true } }
  }
  const ran = RUN.exec(wanted)
  if (ran) {
    try {
      const line: unknown = JSON.parse(ran[1])
      if (typeof line === 'string') {
        // The line the server compared, exactly: that is what a trigger would have to allow.
        // In another folder no trigger allows it.
        return { what: `run \`${line}\`${ran[2] ?? ''}`, allow: ran[2] ? null : { command: line } }
      }
    } catch {
      // not a line this page can read back: listed as it was said
    }
    return { what: wanted, allow: null }
  }
  if (/^open an? .+ (sub-agent|for a discussion)$/.test(wanted)) return { what: wanted, allow: { agents: 1 } }
  return { what: wanted, allow: null }
}

/**
 * What a turn would have asked the user, had somebody been there: its tool calls that were
 * refused with "nobody is here to ask", each request once, in the order they were made.
 */
export function refusedIn(state: ConvState, runId: string): Refused[] {
  const found: Refused[] = []
  const calls = state.toolCalls.filter(call => call.run_id === runId).sort((a, b) => a.seq - b.seq)
  for (const call of calls) {
    if ((call.status !== 'denied' && call.status !== 'failed') || !(call.result ?? '').includes(NOBODY)) continue
    const said = refusal(call)
    if (!found.some(other => other.what === said.what)) found.push({ id: call.id, ...said })
  }
  return found
}
