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

/** How a command's state reads to a person, and the colour it takes; a server's (slice 42b) as a page's would. */
export function commandStatus(command: Pick<Command, 'status' | 'exit_code' | 'started_at'> & Partial<Pick<Command, 'keep_running' | 'preview_url'>>): {
  label: string
  tone: Tone
} {
  if (command.keep_running) {
    if (command.status === 'running') return { label: command.preview_url ? 'running' : 'starting…', tone: 'accent' }
    if (command.status === 'killed') return { label: 'stopped', tone: 'muted' }
    if (command.status === 'exited' && command.exit_code !== null) return { label: `exited ${command.exit_code}`, tone: command.exit_code === 0 ? 'muted' : 'del' }
    if (command.status === 'interrupted' && command.started_at !== null) return { label: 'stopped when KOLONİ closed', tone: 'muted' }
  }
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
      // A CLI that ran the command itself may not say how it exited: that is not a failure.
      if (command.exit_code === null) return { label: 'ended · exit code not reported', tone: 'muted' }
      return { label: `exit ${command.exit_code}`, tone: command.exit_code === 0 ? 'ok' : 'del' }
    case 'timed_out':
      return { label: 'timed out', tone: 'del' }
    case 'killed':
      return { label: 'killed', tone: 'muted' }
    case 'rejected':
      return { label: 'rejected', tone: 'muted' }
    case 'failed_to_start':
      return { label: 'did not start', tone: 'del' }
    case 'blocked':
      // K-48: its CLI called it done (exit 0), and its sandbox had refused the write.
      return { label: 'blocked: its read-only sandbox refused a write', tone: 'del' }
    case 'interrupted':
      // One that never started was approved, and its agent never got its place: not your no.
      if (command.started_at === null) return { label: 'approved — the work ended before it ran', tone: 'muted' }
      return { label: 'interrupted', tone: 'warn' }
  }
}

/** Whole seconds a command ran, or null while it has not both started and ended. */
export function commandSeconds(command: Pick<Command, 'started_at' | 'ended_at'>): number | null {
  if (!command.started_at || !command.ended_at) return null
  return Math.round((Date.parse(command.ended_at) - Date.parse(command.started_at)) / 1000)
}

export function placeLabel(command: Pick<Command, 'location' | 'image'>): string {
  return command.location === 'docker' ? `Docker · ${command.image ?? 'no image'}` : 'This machine'
}
