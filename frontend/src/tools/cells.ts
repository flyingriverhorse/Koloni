import type { McpRead, McpServer, McpTool } from '../api/types'
import type { CellFill, CellTone } from '../shell/Cell'

/**
 * How a tool is let run, as the Tools page's cells say it (0.1.10): without asking, asking you first, off - given to
 * no agent -, or a server whose trust a reading took back.
 */
export type Runs = 'free' | 'ask' | 'off' | 'taken'

/** Each one's cell: green, Ready's "your word" honey rim, the empty cell, red-orange. */
export const RUNS_CELL: Record<Runs, { tone: CellTone; fill: CellFill }> = {
  free: { tone: 'ok', fill: 'full' },
  ask: { tone: 'honey', fill: 'soft' },
  off: { tone: 'plain', fill: 'none' },
  taken: { tone: 'warn', fill: 'full' },
}

/** Each one in words: the key's, and a cell's label where nothing more is said. */
export const RUNS_WORD: Record<Runs, string> = {
  free: 'runs without asking',
  ask: 'asks you first',
  off: 'off: given to no agent',
  taken: 'changed: trust taken back',
}

/** A `Cell`'s props for how something runs and its label. */
export const runsCell = ([runs, label]: [Runs, string]) => ({ ...RUNS_CELL[runs], label })

/** One of KOLONİ's own tools: off where it is switched off, else as its role's tile says (`RoleTool.asks`). */
export const builtinRuns = (asks: boolean, on: boolean): [Runs, string] =>
  !on ? ['off', RUNS_WORD.off] : asks ? ['ask', 'asks you first, on a card'] : ['free', RUNS_WORD.free]

/**
 * One tool of a server, as an agent's call of it goes (app/agent/outside_mixin.py): its server off, the tool not
 * offered or marked Off - none; a server not trusted yet asks at every level whatever the mark; trusted, its mark.
 */
export function toolRuns(server: McpServer, tool: McpTool): [Runs, string] {
  if (!server.enabled) return ['off', 'off: its server is off']
  if (tool.unusable) return ['off', 'not offered']
  if (tool.mark === 'off') return ['off', RUNS_WORD.off]
  if (!server.trusted) return ['ask', 'asks you: the server is not trusted yet']
  return tool.mark === 'free' ? ['free', RUNS_WORD.free] : ['ask', 'asks you first, at every level']
}

/**
 * A server, by the most any of its tools may do without you: off, not read, none on - the empty cell; watched - every
 * call asks; trusted - green where a tool runs without asking. `taken`: a reading on this page took its trust back.
 */
export function serverRuns(server: McpServer, taken: boolean): [Runs, string] {
  if (taken) return ['taken', 'trust taken back: a reading found new or changed tools']
  if (!server.enabled) return ['off', 'off: given to no agent']
  if (server.read_at === null) return ['off', 'not read yet: no agent is offered any']
  if (server.tools.length === 0 && server.read_error) return unshownRuns(server)
  const runs = server.tools.map(tool => toolRuns(server, tool)[0])
  if (!runs.includes('ask') && !runs.includes('free')) return ['off', 'none of its tools is on']
  if (!server.trusted) return ['ask', 'watching: every call asks you']
  return runs.includes('free')
    ? ['free', 'trusted: some of its tools run without asking']
    : ['ask', 'trusted: each of its tools asks you first']
}

/**
 * A server whose tools are not listed, its reading having failed: the tools kept from a reading before - which the page
 * is not shown where they cannot be (app/api/mcp_servers.py `shown`) - may still be offered (`mcp_client.usable`), so
 * the cell says the most they may do: every call asks while it is watched; trusted, one may run without asking.
 */
const unshownRuns = (server: McpServer): [Runs, string] =>
  server.trusted
    ? ['free', 'trusted: its tools cannot be shown - one may run without asking']
    : ['ask', 'watching: every call asks you']

/**
 * A reading kept by the page (`useTrust`) took this server's trust back, and it is not trusted again since - nor
 * changed: another command or other variables are watched for themselves, not for what that reading found.
 */
export const takenBack = (server: McpServer, read: McpRead | undefined) =>
  !!read &&
  !server.trusted &&
  read.new.length + read.changed.length > 0 &&
  JSON.stringify([read.server.command, read.server.env_names]) === JSON.stringify([server.command, server.env_names])

const both = (one: string[], other: string[]) => [...new Set([...one, ...other])]

/** A reading kept, with a later one merged in list by list: the later one's server, nothing named twice. */
export const mergedRead = (kept: McpRead | undefined, got: McpRead): McpRead =>
  kept
    ? {
        ...got,
        new: both(kept.new, got.new),
        changed: both(kept.changed, got.changed),
        gone: both(kept.gone, got.gone),
      }
    : got

/** What a reading found against the one before, in words; nothing that is not there is named. */
export function foundIn(read: McpRead): string {
  const parts = [
    read.new.length > 0 && `New: ${read.new.join(', ')}.`,
    read.changed.length > 0 &&
      `Changed: ${read.changed.join(', ')} - one that ran without asking is asked about again.`,
    read.gone.length > 0 && `Gone: ${read.gone.join(', ')}.`,
  ].filter(Boolean)
  return parts.length > 0 ? parts.join(' ') : 'Nothing is new, changed or gone since the reading before.'
}
