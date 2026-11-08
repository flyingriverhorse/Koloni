import type { Agent, Team } from '../api/types'

/** K-isimler: what the screen calls the chat's top agent; its role and record stay "Lead" (app/roles.py `title_of`). */
export const ORCHESTRATOR = 'Orchestrator'

/**
 * What the screen calls an agent or role by its name: the Lead is the Orchestrator, a team's lead (given `teams`) its
 * team's coordinator, anyone else its name.
 * shortcut: without `teams` a team's lead keeps its name ("Docs lead"); pass the store's teams where that is seen.
 */
export function titleOf(name: string, teams: Pick<Team, 'name' | 'lead'>[] = []): string {
  if (name === 'Lead') return ORCHESTRATOR
  const team = teams.find(team => team.lead.name === name)
  return team ? `${team.name} coordinator` : name
}

/** What waits for the user's word, wherever it is said: an agent, a command, a turn, a conversation. */
export const WAITS = 'waits for you'

/** An agent whose own model summarises its older history before its next step (slice 59b). */
export const SUMMARISING = 'Summarising its earlier work…'

/**
 * How an agent's state reads, and the colour that goes with it: in the chat's rows, on the
 * Board and - the colour - on its node. `waiting_approval` is a lead whose turn waits for you;
 * `proposed`, a sub-agent that waits to be let start.
 */
export const AGENT_STATUS: Record<Agent['status'] | 'waiting_approval', [label: string, color: string]> = {
  proposed: [WAITS, 'var(--warn)'],
  waiting_approval: [WAITS, 'var(--warn)'],
  queued: ['waiting for a slot', 'var(--muted)'],
  running: ['working', 'var(--accent)'],
  waiting: ['waiting', 'var(--accent)'],
  // For a file another agent holds: it asks nothing of the user.
  blocked: ['waiting for a file', 'var(--muted)'],
  completed: ['done', 'var(--ok)'],
  failed: ['failed', 'var(--del)'],
  cancelled: ['stopped', 'var(--muted)'],
  rejected: ['rejected', 'var(--warn)'],
  interrupted: ['interrupted', 'var(--warn)'],
}

export const AT_WORK: ReadonlySet<Agent['status']> = new Set(['proposed', 'queued', 'running', 'waiting', 'blocked'])

// 89d: words go into Claude Code's and Codex's own turn while they work; Copilot's and agy's own hear none (B-164).
const STEERED = new Set(['claude_cli', 'codex_cli'])
/** Whether an agent's CLI hears nothing more while it works (`mode`: how its provider ran; `kind`: the provider's). */
export const hearsNothing = (mode: string | null | undefined, kind: string | undefined) =>
  mode === 'reads' || (mode === 'native' && !STEERED.has(kind ?? ''))
