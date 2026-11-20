import type { ToolCall } from '../api/types'

/**
 * How a web call was answered, from the first line of its result (app/web.py writes it):
 * which search answered - and that SearXNG did not, when the search fell back - or the
 * status and type a request came back with. Null for any other call, and for one that has
 * no answer: what is not known is not said.
 */
export function webNote(call: Pick<ToolCall, 'name' | 'result' | 'status'>): string | null {
  if (call.status !== 'succeeded' || !call.result) return null
  const head = call.result.split('\n', 1)[0]
  if (call.name === 'web_search') return /answered by .+$/.exec(head)?.[0] ?? null
  if (call.name === 'http_request') return /HTTP \d+.*$/.exec(head)?.[0] ?? null
  return null
}

/**
 * Slice 51: where a screenshot of the agent's browser was saved - named by KOLONİ from its agent's and its call's
 * ids, as app/agent.py `_shot` names it; never read from the result, whose lines a page can put words in. The
 * view beside the chat serves it under the call's own id. 28e: so is the copy of an image view_image looked at
 * (`_view_image`), read from the end of the result KOLONİ wrote and only in its call's own folder (B-346: by the
 * image's own name; `<name>.<type>` before it). Null for any other call.
 */
export function shotOf(call: Pick<ToolCall, 'name' | 'status' | 'id' | 'agent_id' | 'result'> & { origin?: ToolCall['origin'] }): string | null {
  if (call.status !== 'succeeded') return null
  const name = `${call.agent_id.slice(0, 8)}-${call.id.slice(0, 8)}`
  if (call.name === 'browser_screenshot') return `.koloni/tmp/browser/shots/${name}.png`
  if (call.name !== 'view_image' && call.origin !== 'cli') return null  // (B-347: or a CLI's own look at one)
  const copy = /\(the user sees it under the step: (\.koloni\/tmp\/images\/[^/]+(?:\/[^/]+)?\.(?:png|jpg|gif|webp))\)$/.exec(call.result ?? '')?.[1]
  return copy && [`.koloni/tmp/images/${name}/`, `.koloni/tmp/images/${name}.`].some(own => copy.startsWith(own)) ? copy : null
}

type Named = Pick<ToolCall, 'name'> & { origin?: ToolCall['origin'] }

/**
 * A call's tool as it is shown. A tool of an MCP server the user connected is on record as
 * `server__tool` (app/mcp_client.py) and shown as `server · tool`. A CLI's own tool (origin
 * "cli") has a name of that CLI's making: it is left as it is here.
 */
export function toolName(call: Named): string {
  const mcp = call.origin === 'cli' ? null : /^([a-z][a-z0-9-]{0,15})__(.+)$/.exec(call.name)
  return mcp ? `${mcp[1]} · ${mcp[2]}` : call.name
}

/** One line naming a tool call and its target, e.g. `read_file src/a.py`. */
export function toolSummary(call: Named & Pick<ToolCall, 'arguments'>): string {
  const name = toolName(call)
  const args = argsOf(call.arguments)
  if (!args) return name
  const said = agentCall(call.name, args) ?? lookupCall(call.name, args) ?? browserCall(call.name, args)
  if (said !== null) return said
  // A note is named by its subject; its words are in the call itself.
  if (call.name === 'remember') return typeof args.about === 'string' && args.about ? 'remember ' + args.about : 'remember'
  if (typeof args.path === 'string') return `${name} ${args.path}`
  if (call.name === 'list_dir' && args.path === undefined) return 'list_dir .'
  return name
}

type Args = Record<string, unknown>

/** A call's arguments; null where they are not an object. */
function argsOf(given: string): Args | null {
  try {
    const parsed: unknown = JSON.parse(given || '{}')
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null
    return parsed as Args
  } catch {
    return null
  }
}

/** A search, and the tools about agents and teams, by their target; null: not one of them, or its target is not as expected. */
function agentCall(tool: string, args: Args): string | null {
  if (tool === 'search' && typeof args.pattern === 'string') {
    return `search "${args.pattern}"`
  }
  if (tool === 'spawn_agent' && typeof args.role === 'string') return `spawn_agent ${args.role}`
  if (tool === 'message_agent' && typeof args.to === 'string') return `message_agent ${args.to}`
  if (tool === 'create_role' && typeof args.name === 'string') return `create_role ${args.name}`
  // The Lead's pick of the chat's teams (slice 84b), each with its reason: the chat's one line of it.
  if (tool === 'pick_teams' && Array.isArray(args.teams)) {
    const picks = (args.teams as Record<string, unknown>[]).filter(one => one && typeof one.team === 'string')
    return `pick_teams ${picks.map(one => (typeof one.why === 'string' ? `${one.team}: ${one.why}` : one.team)).join('; ')}`
  }
  return null
}

/** The memory, the web and a notice, by what was asked or said; null as `agentCall`'s. */
function lookupCall(tool: string, args: Args): string | null {
  if (tool === 'recall' && typeof args.query === 'string') return 'recall "' + args.query + '"'
  if (tool === 'web_search' && typeof args.query === 'string') return `web_search "${args.query}"`
  if (tool === 'http_request' && typeof args.url === 'string') {
    return `http_request ${typeof args.method === 'string' ? args.method.toUpperCase() : ''} ${args.url}`.replace('  ', ' ')
  }
  if (tool === 'notify' && typeof args.message === 'string') return `notify "${args.message}"`
  return null
}

// Slice 51: what the agent did in its browser, in words.
function browserCall(tool: string, args: Args): string | null {
  if (tool === 'browser_open') return typeof args.url === 'string' ? `opened ${args.url}` : 'opened a page'
  if (tool === 'browser_click') return clicked(args)
  if (tool === 'browser_type') return typeof args.selector === 'string' ? `typed into ${args.selector}` : 'typed'
  if (tool === 'browser_key') return typeof args.key === 'string' ? `pressed ${args.key}` : 'pressed a key'
  if (tool === 'browser_scroll') return scrolled(args)
  if (tool === 'browser_read') return 'read the page'
  if (tool === 'browser_screenshot') return 'took a screenshot'
  if (tool === 'browser_console') return 'read the console'
  return null
}

function clicked(args: Args): string {
  if (typeof args.text === 'string') return `clicked ${args.text}`
  if (typeof args.selector === 'string') return `clicked ${args.selector}`
  return typeof args.x === 'number' && typeof args.y === 'number' ? `clicked at ${args.x}, ${args.y}` : 'clicked'
}

const scrolled = (args: Args) => (typeof args.dy === 'number' ? `scrolled ${args.dy > 0 ? 'down' : 'up'} ${Math.abs(args.dy)}` : 'scrolled')

/**
 * Whether a call waits for leave to go outside the project: started, then put back to
 * waiting (a call of a batch that has not started yet has no start).
 */
export function asksOutside(call: ToolCall): boolean {
  return call.status === 'pending' && call.started_at !== null
}
