import type { Message } from '../api/types'
import type { ConvState } from '../state/applyEvent'

/** What Fix it sends: a new message of the user's, by their click - nothing starts by itself. */
export const FIX_IT = (command: string) => `The tests KOLONİ ran at the end of the last turn failed: \`${command}\`. Fix what fails.`
/** S3: what Fix it sends where the Reviewer still held the change after the Fix rounds: words of the user's own - the findings reach the Orchestrator as data (`review_held`), never as theirs. */
export const FIX_REVIEW = 'The Reviewer KOLONİ opened at the end of the last turn still held its change. Fix its blocking findings.'

/** S11 (decision 18): what Fix it sends on a "Not taken in" row - the user's answer to the stronger model's question, their own words. */
export const FIX_HELD = (question: string, reply: string) => `The last turn's work was not taken in: its tests still fail. ${question} My answer: ${reply.trim()} Fix it.`

type Row = NonNullable<Message['checked']>[number]

/** S11: what Fix it sends where a stronger model's rounds ended as no pass (the tests may pass): the command and KOLONİ's own line why, quoted. */
export const FIX_NOT_DONE = (command: string, why: string) => `${FIX_IT(command)} KOLONİ's end check says it is not done: "${why}"`

/** What Fix it asks for under a turn's Checked section: a failing test run first, else a stronger model's rounds that were no pass, else a Reviewer's hold; null: nothing to fix. */
export function fixOf(rows: Row[]): string | null {
  const failed = rows.find(row => row.kind === 'tests' && row.state === 'failed' && row.command)
  if (failed?.command) return FIX_IT(failed.command)
  const notDone = rows.find(row => (row.kind === 'stronger' || row.kind === 'rounds') && row.state === 'failed' && row.command)
  if (notDone?.command) return FIX_NOT_DONE(notDone.command, notDone.text)
  const held = rows.some(row => row.kind === 'review' && row.text.startsWith('Still on hold'))
  return held && rows.some(row => row.kind === 'finding' && row.text.startsWith('Blocking: ')) ? FIX_REVIEW : null
}

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
