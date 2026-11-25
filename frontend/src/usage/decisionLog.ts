import { api } from '../api/client'
import type { Decision, DecisionLog } from '../api/types'

/** Who decided, as every place that shows a decision says it: the chat's Decided for you and Today's Decisions. */
export const WHO: Record<Decision['who'], string> = {
  orchestrator: 'Orchestrator',
  judge: "KOLONİ's judge",
  your_words: 'Check what I said first',
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

// The chat's "All decisions on Today": App opens Usage's Today, and Decisions there opens itself - once.
export const OPEN_DECISIONS = 'koloni:open-decisions'
let asked = false
export function openDecisions() {
  asked = true
  window.dispatchEvent(new CustomEvent(OPEN_DECISIONS))
}
/** Whether Decisions was asked to open, since it last looked. */
export function decisionsAsked(): boolean {
  const was = asked
  asked = false
  return was
}

/** An agent's or a model's words in Markdown, inert: on one line in a code span - no link, image, heading, HTML or
 *  @mention is made of them - fenced longer than any run of backticks in them. */
function inert(text: string): string {
  const line = text.replace(/\s+/g, ' ').trim()
  const fence = '`'.repeat(Math.max(0, ...(line.match(/`+/g) ?? []).map(run => run.length)) + 1)
  return `${fence} ${line} ${fence}`
}

/** One row as a line of Markdown: when, who, KOLONİ's sentence, then the words it is of, each inert. */
export function markdownRow(row: Decision, now = new Date()): string {
  const quote = row.quote ? `: ${inert(row.quote)}` : ''
  const answer = row.answer ? ` → ${inert(row.answer)}` : ''
  const why = row.why ? ` · why: ${inert(row.why)}` : ''
  return `- ${stamp(row.at, now)} · ${WHO[row.who]} · ${row.what}${quote}${answer}${why}`
}

/** Copy as Markdown: a plain list to paste into a PR's body, as masked as the screen shows it. */
export function markdown(log: DecisionLog, period: string, now = new Date()): string {
  return [
    `Decided for you (${period}):`,
    '',
    ...log.rows.map(row => markdownRow(row, now)),
    ...(log.judge_fine ? ['', fineLine(log.judge_fine)] : []),
  ].join('\n')
}

export const fineLine = (n: number) => `The judge let ${n} ${n === 1 ? 'command' : 'commands'} run.`
