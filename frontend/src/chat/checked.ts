import type { Message } from '../api/types'
import type { ConvState } from '../state/applyEvent'
import { isFrame } from './AgentSaid'

/** What Fix it sends: a new message of the user's, by their click - nothing starts by itself. */
export const FIX_IT = (command: string) =>
  `The tests KOLONİ ran at the end of the last turn failed: \`${command}\`. Fix what fails.`
/** R: what Fix it sends where no test failed but fewer ran, or more were skipped, than at the last green run (the row's code "removed"). */
export const FIX_FEWER = (command: string) =>
  `The tests KOLONİ ran at the end of the last turn (\`${command}\`): fewer of its tests run, or more are skipped, than at its last green run. Put back what was taken away, or say why.`
/** S3: what Fix it sends where the Reviewer still held the change after the Fix rounds: words of the user's own - the findings reach the Orchestrator as data (`review_held`), never as theirs. */
export const FIX_REVIEW =
  'The Reviewer KOLONİ opened at the end of the last turn still held its change. Fix its blocking findings.'

type Row = NonNullable<Message['checked']>[number]

/** S11 (decision 18): what Fix it sends on a "Not taken in" row - the user's answer to its question, their own words; why it was held by the row's reason code (P: a look still holding it), never by its text. */
const HELD_WHY: Partial<Record<NonNullable<Row['reason']>, string>> = {
  on_hold: "a look of KOLONİ's still held it",
  removed: 'fewer of its tests run, or more are skipped',
}
export const FIX_HELD = (question: string, reply: string, reason?: Row['reason']) =>
  `The last turn's work was not taken in: ${(reason && HELD_WHY[reason]) || 'its tests still fail'}. ${question} My answer: ${reply.trim()} Fix it.`

/**
 * S11: where a stronger model's rounds ended as no pass (its tests may pass), Fix it's words - the command and a fixed sentence by the row's
 * reason code, which KOLONİ sets. Never by the row's own text: it names files and a look's output a model chose, which are no words of the
 * user's (as FIX_REVIEW), and could steer which sentence is sent. A row kept before it had a code: "still".
 */
const NOT_DONE: Record<NonNullable<Row['reason']>, string> = {
  touched: 'a test, or what says which tests run, was changed without leave',
  held: 'the Reviewer held the test change',
  unread: 'the Reviewer did not pass the test change',
  no_verdict: 'the tests gave no verdict after a round',
  still: 'it still fails after the rounds',
  on_hold: 'a look still held it',
  removed: 'fewer tests ran, or more were skipped',
}
export const FIX_NOT_DONE = (command: string, reason: Row['reason']) =>
  `${FIX_IT(command)} The stronger model's rounds were no pass: ${NOT_DONE[reason ?? 'still']}.`

/** What Fix it asks for under a turn's Checked section: a failing test run first, else a stronger model's rounds that were no pass, else a Reviewer's hold; null: nothing to fix. */
export function fixOf(rows: Row[]): string | null {
  // (a test that fails first; where only fewer ran, or more were skipped - its code "removed" - that is what is said)
  const failing = rows.filter(row => row.kind === 'tests' && row.state === 'failed' && row.command)
  const failed = failing.find(row => row.reason !== 'removed')
  if (failed?.command) return FIX_IT(failed.command)
  if (failing[0]?.command) return FIX_FEWER(failing[0].command)
  const notDone = rows.find(
    row => (row.kind === 'stronger' || row.kind === 'rounds') && row.state === 'failed' && row.command,
  )
  if (notDone?.command) return FIX_NOT_DONE(notDone.command, notDone.reason)
  const held = rows.some(row => row.kind === 'review' && row.text.startsWith('Still on hold'))
  return held && rows.some(row => row.kind === 'finding' && row.text.startsWith('Blocking: ')) ? FIX_REVIEW : null
}

/** What the chat lists of a conversation's messages: the Lead's - not a sub-agent's, a discussion's, a note's -, no frame of a report, not what KOLONİ checked (`CheckedSection`). */
export function chatMessages(state: ConvState): Message[] {
  const subAgents = new Set(state.agents.filter(a => a.depth > 0).map(a => a.id))
  return state.messages.filter(
    m =>
      !m.discussion_id &&
      !m.board_post_id &&
      (!m.agent_id || !subAgents.has(m.agent_id)) &&
      !isFrame(m) &&
      m.role !== 'checked',
  )
}

/** The chat's newest turn, as the chat draws it: the turn of its last message that starts none - Fix it is offered under it alone (and in the Checks panel). */
export function newestTurn(state: ConvState): string | undefined {
  const turn = new Map(state.runs.map((r, index) => [r.id, index]))
  const at = (m: Message) => turn.get(m.run_id ?? '') ?? Infinity
  const said = chatMessages(state).filter(m => m.role !== 'user' && m.role !== 'trigger')
  return (
    said.reduce<Message | undefined>((last, m) => (!last || at(m) >= at(last) ? m : last), undefined)?.run_id ??
    undefined
  )
}

/** A turn's "checked" message: what KOLONİ checked at its end (kanıtlı bitiş), drawn by `CheckedSection`. */
export const checkedOf = (state: ConvState, runId: string): Message | undefined =>
  state.messages.find(m => m.run_id === runId && m.role === 'checked')

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
