import type { Agent, ToolCall } from '../api/types'
import type { ConvState } from '../state/applyEvent'

/**
 * K-takimlar-arasi: one agent's request_work - another team asked for work - and the lead of that team KOLONİ opened
 * for it (the spawn call whose `parent_call_id` is the request's: app/team_requests.py).
 */
export interface TeamRequest {
  call: ToolCall
  from: Agent | undefined
  /** The team that asked (the asker's), as KOLONİ told the lead; null before it reached one. */
  fromTeam: string | null
  to: string
  what: string
  /** It came with a contract, which KOLONİ wrote into the shared folder's contracts/. */
  contract: boolean
  lead: Agent | undefined
  /** How it stands: its lead at work while the asker waits for it, or not; its answer; or it never reached the team. */
  stands: 'waits' | 'at work' | 'answered' | 'declined' | 'failed' | 'not delivered' | 'refused'
}

const OPEN: ReadonlySet<Agent['status']> = new Set(['proposed', 'queued', 'running', 'waiting', 'blocked'])

const parsed = (text: string | null | undefined): Record<string, unknown> => {
  try {
    const found: unknown = JSON.parse(text || '{}')
    return found && typeof found === 'object' ? (found as Record<string, unknown>) : {}
  } catch {
    return {} // (not JSON: shown with what is known)
  }
}
const str = (value: unknown) => (typeof value === 'string' ? value : '')

/** The requests between teams of a turn (or of the chat), oldest first. */
export function requestsOf(state: ConvState, runId?: string): TeamRequest[] {
  return state.toolCalls
    .filter(t => t.name === 'request_work' && (!runId || t.run_id === runId))
    .sort((a, b) => a.seq - b.seq)
    .map(call => {
      const args = parsed(call.arguments)
      const opening = state.toolCalls.find(t => t.parent_call_id === call.id && t.name === 'spawn_agent')
      const lead = opening && state.agents.find(a => a.tool_call_id === opening.id)
      const stands: TeamRequest['stands'] = lead
        ? OPEN.has(lead.status)
          ? call.status === 'running'
            ? 'waits'
            : 'at work'
          : lead.status !== 'completed'
            ? 'failed'
            : /^\s*declined/i.test(lead.report ?? '')
              ? 'declined'
              : 'answered'
        : call.status === 'running' || call.status === 'pending'
          ? 'waits'
          : call.result?.startsWith('queued for the ')
            ? 'not delivered'
            : 'refused'
      return {
        call,
        from: state.agents.find(a => a.id === call.agent_id),
        fromTeam: str(parsed(opening?.arguments).asked_by) || null,
        to: str(args.to),
        what: str(args.what).trim(),
        contract: !!str(args.contract).trim(),
        lead,
        stands,
      }
    })
}

/** Its work in a few words, for a line or a badge. */
export function shortWhat(what: string, most = 32): string {
  const first = what.split('\n')[0].trim()
  return first.length > most ? `${first.slice(0, most - 1)}…` : first
}

/** Who asked, as the asked team's lead's badge and the chat's card say it: "Web app's Coder". */
export function askerOf(request: TeamRequest): string {
  const role = request.from?.role_name ?? 'an agent'
  return request.fromTeam ? `${request.fromTeam}'s ${role}` : role
}

/** The line's label between the two frames: the same line, waiting and then answered. */
export function lineLabel(request: TeamRequest): string {
  if (request.stands === 'answered') return 'answered ✓'
  if (request.stands === 'declined') return `request declined by ${request.to}`
  if (request.stands === 'failed') return 'failed'
  return `request · ${shortWhat(request.what)}${request.stands === 'waits' ? ' · waits' : ''}`
}

/** How it stands, as the chat's card says it: "Backend / API lead gave it to its Coder · at work · Web app's Coder waits". */
export function standsLine(request: TeamRequest, member?: Agent): string {
  const lead = request.lead ? request.lead.name || request.lead.role_name : `${request.to}'s lead`
  switch (request.stands) {
    case 'answered':
      return `${lead} answered ✓`
    case 'declined':
      return `${lead} declined: ${(request.lead?.report ?? '').replace(/^\s*declined:?\s*/i, '').split('\n')[0]}`
    case 'failed':
      return `${lead} ${request.lead?.status ?? 'failed'}`
    case 'not delivered':
      return 'not delivered: the Orchestrator has it'
    case 'refused':
      return 'refused'
  }
  if (request.lead?.status === 'proposed') return `${lead} waits for your approval`
  const at = member ? `${lead} gave it to its ${member.role_name} · at work` : `${lead} has it · at work`
  return request.stands === 'waits' ? `${at} · ${askerOf(request)} waits` : at
}
