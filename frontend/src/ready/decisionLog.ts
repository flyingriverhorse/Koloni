import { api } from '../api/client'
import type { Decision, DecisionLog } from '../api/types'

/** Who decided, as every place that shows a decision says it: Ready for you's Decided for you, and a plain chat's box. */
export const WHO: Record<Decision['who'], string> = {
  orchestrator: 'Orchestrator',
  judge: "KOLONİ's judge",
  your_words: 'Your rule',
}

/** The project's decision log from a moment on (read only: nothing adds, changes or deletes a row). Throws ApiError. */
export const readDecisions = (projectId: string, since: string) =>
  api.get<DecisionLog>(`/projects/${projectId}/decisions?since=${encodeURIComponent(since)}`)

/** Monday's midnight here, of the week `now` is in. */
export const weekStart = (now = new Date()) =>
  new Date(now.getFullYear(), now.getMonth(), now.getDate() - ((now.getDay() + 6) % 7)).toISOString()

/** When a row was decided, as this machine's clock says it: "04:40" today, "Mon 04:40" before. */
export function stamp(iso: string, now = new Date()): string {
  const at = new Date(iso)
  const time = { hour: '2-digit', minute: '2-digit', hour12: false } as const
  return at.toDateString() === now.toDateString()
    ? at.toLocaleTimeString([], time)
    : at.toLocaleString([], { weekday: 'short', ...time })
}

// "Open in Ready for you" (the chat's line, Usage's Today): App opens the Ready for you page with Decided for you in view -
// its own state, cleared once it is in view, or the page left.
export const OPEN_DECISIONS = 'koloni:open-decisions'
export const openDecisions = () => window.dispatchEvent(new CustomEvent(OPEN_DECISIONS))

/** An agent's or a model's words in Markdown, inert: on one line in a code span - no link, image, heading, HTML or
 *  @mention is made of them - fenced longer than any run of backticks in them. */
function inert(text: string): string {
  const line = text.replace(/\s+/g, ' ').trim()
  const fence = '`'.repeat(Math.max(0, ...(line.match(/`+/g) ?? []).map(run => run.length)) + 1)
  return `${fence} ${line} ${fence}`
}

/** `before`, then the words inert - or nothing, where there are none to show. */
const said = (before: string, text: string | null | undefined) => (text?.trim() ? `${before}${inert(text)}` : '')

/** One row as a line of Markdown: when, who, KOLONİ's sentence, then the words it is of, each inert. */
export function markdownRow(row: Decision, now = new Date()): string {
  const words = said(': ', row.quote) + said(' → ', row.answer) + said(' · why: ', row.why)
  return `- ${stamp(row.at, now)} · ${WHO[row.who]} · ${row.what}${words}`
}

/** Copy as Markdown: a plain list to paste into a PR's body, as masked as the screen shows it. */
export function markdown(log: DecisionLog, period: string, now = new Date()): string {
  return [
    `Decided for you (${period}):`,
    '',
    ...log.rows.map(row => markdownRow(row, now)),
    ...(log.more ? ['', newestLine(log.rows.length)] : []),
    ...(log.judge_fine ? ['', fineLine(log.judge_fine)] : []),
  ].join('\n')
}

export const fineLine = (n: number) => `The judge let ${n} ${n === 1 ? 'command' : 'commands'} run.`
/** Where the period had more than the log gives (`DecisionLog.more`). */
export const newestLine = (n: number) => `Showing the newest ${n}.`

/** The Ready for you page's first line, from the record alone: what waits, and - where it is known - how much was decided
 *  since you left (a part not known is left out). */
export function readySentence(waiting: number, decidedSinceLeft: number | null): string {
  const waits =
    waiting === 0
      ? 'Nothing waits for your word.'
      : `${waiting} ${waiting === 1 ? 'thing waits' : 'things wait'} for your word.`
  if (decidedSinceLeft === null) return waits
  const made = decidedSinceLeft === 1 ? '1 decision was' : `${decidedSinceLeft} decisions were`
  return `${waits} ${made} made for you since you left.`
}

/** "3 things were decided" / "1 thing was decided". */
const things = (n: number, done: string, many: string) => (n === 1 ? `1 thing ${done}` : `${n} things ${many}`)

/** What a chat's line says: what was decided for you in it and waits for your OK, and what waits for your word. */
export function decidedSentence(decided: number, waiting: number): string {
  const parts = [
    decided > 0 && things(decided, 'was decided for you', 'were decided for you'),
    waiting > 0 && (waiting === 1 ? '1 waits for you' : `${waiting} wait for you`),
  ].filter(Boolean)
  return `While you were away, ${parts.join(' and ')}.`
}

/** What Usage's Today says of the day's decisions, from the log: how many, and how many you have not seen. */
export function todaySentence(log: DecisionLog): string {
  const n = log.rows.length
  // (More than the log gives: how many is not known here, so not said.)
  if (log.more) return 'Decisions were made for you today.'
  if (n === 0) return 'No decisions were made for you today.'
  const unseen = log.rows.filter(row => row.seen === false).length
  const made = n === 1 ? '1 decision was made for you today' : `${n} decisions were made for you today`
  return unseen > 0 ? `${made}, ${unseen} of them you haven't seen.` : `${made}.`
}
