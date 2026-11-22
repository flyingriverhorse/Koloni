import type { Message } from '../api/types'
import type { ConvState } from '../state/applyEvent'

/** What Fix it sends: a new message of the user's, by their click - nothing starts by itself. */
export const FIX_IT = (command: string) => `The tests KOLONİ ran at the end of the last turn failed: \`${command}\`. Fix what fails.`

/** A turn's "checked" message: what KOLONİ checked at its end (kanıtlı bitiş), drawn by `CheckedSection`. */
export const checkedOf = (state: ConvState, runId: string): Message | undefined => state.messages.find(m => m.run_id === runId && m.role === 'checked')

/**
 * S6: when the whole suite of the chat's newest checked turn started running, gone on after its answer (its row is
 * "running" with a start); null where none runs. The status line reads it - and a canvas Checks node can.
 */
export function testsRunningSince(state: ConvState): string | null {
  const note = state.messages.findLast(m => m.role === 'checked')
  return note?.checked?.find(row => row.state === 'running' && row.started_at)?.started_at ?? null
}

/** How long since `since`, as "2:14" - a running test run's clock. */
export function runClock(since: string, now: number): string {
  const seconds = Math.max(0, Math.floor((now - Date.parse(since)) / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}
