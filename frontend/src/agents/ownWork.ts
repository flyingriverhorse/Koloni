import type { Agent, Project, Provider, ToolCall } from '../api/types'
import type { ConvState } from '../state/applyEvent'

/** What a CLI's own sub-agent is on record as: a call of this tool, by the CLI itself. */
const OWN_SUB_AGENT = 'claude__Agent'
// The CLIs whose own tools are recorded as <cli>__<tool>.
const CLIS = new Set(['claude', 'copilot', 'agy'])

/**
 * A sub-agent a CLI opened itself (not an agent of KOLONİ's): one tool call, with what
 * the sub-agent did hanging off it. One that was refused never worked.
 */
export function isOwnSubAgent(call: Pick<ToolCall, 'name' | 'origin' | 'status'>): boolean {
  return call.origin === 'cli' && call.name === OWN_SUB_AGENT && call.status !== 'denied'
}

/** The ids of the calls that are a CLI's own sub-agents. */
export function subAgentIds(calls: ToolCall[]): Set<string> {
  return new Set(calls.filter(isOwnSubAgent).map(c => c.id))
}

/**
 * Where a call was made: in one of the CLI's own sub-agents (that sub-agent's call id),
 * or by the agent itself (null). A record from before sub-agents were told apart, or one
 * whose sub-agent is not on record, is the agent's own.
 */
export function homeOf(call: Pick<ToolCall, 'parent_call_id'> | undefined, subAgents: Set<string>): string | null {
  return call?.parent_call_id && subAgents.has(call.parent_call_id) ? call.parent_call_id : null
}

/** K-native-not: the line said above what nobody watches (`notWatched`), under "works with its own tools". */
export const NOT_WATCHED = 'Some of KOLONİ’s rules are not watched here'

/**
 * K-native-not: which of KOLONİ's rules nobody watches for an agent whose CLI works with its own tools, as its
 * provider says for the way it ran (the backend's list) - and for the open project, where it runs its commands in
 * Docker: a CLI's own run on this machine. Null where nothing is skipped, and where that is not known (an API, a
 * provider renamed or gone).
 * shortcut: the provider by its name, as the agent's record keeps it (it has no provider id); a renamed one says nothing.
 */
export function notWatched(
  app: { providers: Pick<Provider, 'name' | 'not_watched' | 'not_watched_in_docker'>[]; projects: Pick<Project, 'id' | 'exec_location'>[]; projectId: string | null },
  agent: Pick<Agent, 'provider_name' | 'provider_mode'>,
): string[] | null {
  const mode = agent.provider_mode
  const provider = mode ? app.providers.find(p => p.name === agent.provider_name) : undefined
  const docker = app.projects.find(p => p.id === app.projectId)?.exec_location === 'docker'
  const rules = mode ? (docker ? provider?.not_watched_in_docker : provider?.not_watched)?.[mode] : undefined
  return rules?.length ? rules : null
}

/** What is added to "reads only" once something did get through. */
export const LET_THROUGH = ' (your agy settings let something through)'

/**
 * Whether a command or a change is on record for an agent. For one whose CLI was started
 * without leave to write or run, that shows the user's own settings for the CLI allowed
 * more: "reads only" is how it was started, not a promise.
 */
export function letThrough(state: Pick<ConvState, 'commands' | 'fileChanges'>, agentId: string): boolean {
  return state.commands.some(c => c.agent_id === agentId) || state.fileChanges.some(f => f.agent_id === agentId)
}

/** The calls made inside one of a CLI's own sub-agents, in order. */
export function innerCalls(state: ConvState, callId: string): ToolCall[] {
  return state.toolCalls.filter(t => t.parent_call_id === callId).sort((a, b) => a.seq - b.seq)
}

function given(call: Pick<ToolCall, 'arguments'>): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(call.arguments || '{}')
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : {}
  } catch {
    return {}
  }
}

/** One line for what the sub-agent was asked to do. */
export function ownSubAgentTask(call: Pick<ToolCall, 'arguments'>): string {
  const { description, prompt } = given(call)
  if (typeof description === 'string' && description.trim()) return description.trim()
  const lines = typeof prompt === 'string' ? prompt.split('\n').map(line => line.trim()) : []
  return lines.find(Boolean) ?? ''
}

/**
 * What is on record of how a finished sub-agent ended, and what that text is. The CLI's
 * report of it when it completed; the reason when it did not. A record that only says it
 * was launched (from before a sub-agent's work was followed) knows nothing of its ending.
 */
export function ownSubAgentEnding(call: Pick<ToolCall, 'status' | 'result'>): { label: string; text: string } | null {
  if (call.status === 'running' || call.status === 'pending') return null
  const text = (call.result ?? '').trim()
  if (call.status === 'succeeded' && /^Async agent launched/i.test(text)) {
    return { label: 'How it ended', text: 'It was launched. What it did and how it ended is not on record.' }
  }
  if (!text) return null
  return { label: call.status === 'succeeded' ? 'Its report' : 'How it ended', text }
}

/** Whose models a CLI's own sub-agent runs on: the only CLI whose sub-agents are on record is Claude Code. */
export const OWN_MODELS = 'uses Claude Code’s own models, not KOLONİ’s team guide'

/**
 * Everything it was asked, the kind of sub-agent the CLI opened, and the model the CLI named
 * for it when it opened it (each null when not said: the model is then the CLI's to choose,
 * and the record does not say which it was).
 */
export function ownSubAgentBrief(call: Pick<ToolCall, 'arguments'>): { prompt: string; kind: string | null; model: string | null; role: string | null } {
  const { prompt, subagent_type: kind, model, koloni_role: role } = given(call)
  return {
    prompt: typeof prompt === 'string' ? prompt : '',
    kind: typeof kind === 'string' ? kind : null,
    model: typeof model === 'string' && model.trim() ? model.trim() : null,
    // 89g: the role KOLONİ offered it as (`--agents`), as KOLONİ put it on the record.
    role: typeof role === 'string' && role ? role : null,
  }
}

/** The line said of a CLI's own sub-agent's model: whose models, and which one where the record has it. */
export function ownSubAgentModel(call: Pick<ToolCall, 'arguments'>): string {
  const { model } = ownSubAgentBrief(call)
  return `${OWN_MODELS}; ${model ? `model asked for: ${model}` : 'model not reported'}`
}

/**
 * The tool behind a recorded name of a CLI's own tool, and the MCP server it came from
 * (null for a tool of the CLI itself). Claude Code's are recorded as `claude__<tool>` and
 * it names an MCP server's tool `mcp__<server>__<tool>`; Codex's as `<server>__<tool>`.
 */
export function ownTool(name: string): { server: string | null; tool: string } {
  const [first, ...rest] = name.split('__')
  if (rest.length === 0) return { server: null, tool: name }
  if (!CLIS.has(first)) return { server: first, tool: rest.join('__') }
  if (rest[0] === 'mcp' && rest.length > 2) return { server: rest[1], tool: rest.slice(2).join('__') }
  return { server: null, tool: rest.join('__') }
}
