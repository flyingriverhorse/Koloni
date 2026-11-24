import { WAITS } from '../agents/agentStatus'
import type { Command } from '../api/types'

export type Tone = 'accent' | 'ok' | 'warn' | 'del' | 'muted'

export const TONE_COLOR: Record<Tone, string> = {
  accent: 'var(--accent)',
  ok: 'var(--ok)',
  warn: 'var(--warn)',
  del: 'var(--del)',
  muted: 'var(--muted)',
}

/** K-yargıç: where the line of the user's that a command ran on with no card, or was not run by, stands. */
export const JUDGED_FROM = {
  preferences: 'Your preferences',
  rules: 'This project’s rules',
  message: 'your message',
} as const

/** How a command's state reads to a person, and the colour it takes; a server's (slice 42b) as a page's would. */
export function commandStatus(
  command: Pick<Command, 'status' | 'exit_code' | 'started_at'> &
    Partial<Pick<Command, 'keep_running' | 'preview_url'>>,
): {
  label: string
  tone: Tone
} {
  const kept = keptStatus(command)
  if (kept) return kept
  switch (command.status) {
    case 'proposed':
      return { label: WAITS, tone: 'warn' }
    case 'approved':
      // It has the user's yes - to this command, or given before (a rule, the level) - and has
      // not started: its agent waits for a place among the agents at work, or where it runs
      // (a container, a working copy) is not ready yet.
      return { label: 'approved — not started yet', tone: 'muted' }
    case 'running':
      return { label: 'working', tone: 'accent' }
    case 'exited':
      return exitedStatus(command.exit_code)
    case 'interrupted':
      return interruptedStatus(command.started_at)
    default:
      return ENDED[command.status]
  }
}

type Status = { label: string; tone: Tone }

/** The words of a command that ended with no exit code of its own (a state missing here fails the type check). */
const ENDED: Record<'timed_out' | 'killed' | 'rejected' | 'refused' | 'failed_to_start' | 'blocked', Status> = {
  timed_out: { label: 'timed out', tone: 'del' },
  killed: { label: 'killed', tone: 'muted' },
  rejected: { label: 'rejected', tone: 'muted' },
  // K-yargıç: a line of the user's forbids it - not run, and its agent was told that line.
  refused: { label: 'refused', tone: 'muted' },
  failed_to_start: { label: 'did not start', tone: 'del' },
  // K-48: its CLI called it done (exit 0), and its sandbox had refused the write.
  blocked: { label: 'blocked: its read-only sandbox refused a write', tone: 'del' },
}

/** A server's own words for its state (`keep_running`); null where it reads as any command's, and for a command that is none. */
function keptStatus(command: Parameters<typeof commandStatus>[0]): Status | null {
  if (!command.keep_running) return null
  if (command.status === 'running') return { label: command.preview_url ? 'running' : 'starting…', tone: 'accent' }
  if (command.status === 'killed') return { label: 'stopped', tone: 'muted' }
  if (command.status === 'exited' && command.exit_code !== null)
    return { label: `exited ${command.exit_code}`, tone: command.exit_code === 0 ? 'muted' : 'del' }
  if (command.status === 'interrupted' && command.started_at !== null)
    return { label: 'stopped when KOLONİ closed', tone: 'muted' }
  return null
}

function exitedStatus(exitCode: Command['exit_code']): Status {
  // A CLI that ran the command itself may not say how it exited: that is not a failure.
  if (exitCode === null) return { label: 'ended · exit code not reported', tone: 'muted' }
  return { label: `exit ${exitCode}`, tone: exitCode === 0 ? 'ok' : 'del' }
}

function interruptedStatus(startedAt: Command['started_at']): Status {
  // One that never started was approved, and its agent never got its place: not your no.
  if (startedAt === null) return { label: 'approved — the work ended before it ran', tone: 'muted' }
  return { label: 'interrupted', tone: 'warn' }
}

/** Whole seconds a command ran, or null while it has not both started and ended. */
export function commandSeconds(command: Pick<Command, 'started_at' | 'ended_at'>): number | null {
  if (!command.started_at || !command.ended_at) return null
  return Math.round((Date.parse(command.ended_at) - Date.parse(command.started_at)) / 1000)
}

export function placeLabel(command: Pick<Command, 'location' | 'image'>): string {
  return command.location === 'docker' ? `Docker · ${command.image ?? 'no image'}` : 'This machine'
}
