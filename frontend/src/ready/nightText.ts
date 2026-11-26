import type { Away, AwayJob, Waiting } from '../api/types'
import { STATE_WORD, amount, clock } from '../backlog/awayText'
import { inert, markdownRow } from './decisionLog'

const HOUR = 3_600_000
const DAY = 24 * HOUR

/** The hour a time is in, on this machine's clock. */
function hourOf(time: number): number {
  const at = new Date(time)
  at.setMinutes(0, 0, 0)
  return at.getTime()
}

/** The night strip's time axis, in ms: `ticks`, its hours shown. */
export interface Axis {
  from: number
  to: number
  ticks: number[]
}

/**
 * The strip's axis: from the night's start to its end - or to a job's end or a decision on a lane, where one is past it
 * (a turn that ended after you were back) - on whole hours each side, a tick each hour (each few hours on a long night:
 * at most nine). Null where the record has no start or end of the night: nothing is drawn.
 */
export function axisOf(away: Away): Axis | null {
  if (!away.started_at || !away.ended_at) return null
  const ends = [away.ended_at, ...away.jobs.flatMap(job => [job.ended_at, ...job.decisions.map(one => one.at)])]
  const last = Math.max(...ends.flatMap(at => (at ? [Date.parse(at)] : [])))
  const from = hourOf(Date.parse(away.started_at))
  const to = Math.max(from + HOUR, hourOf(last) === last ? last : hourOf(last) + HOUR)
  const step = Math.ceil((to - from) / HOUR / 8) * HOUR
  return { from, to, ticks: Array.from({ length: Math.floor((to - from) / step) + 1 }, (_, i) => from + i * step) }
}

/** The day a night began, on this machine's calendar: "Tue 24 Nov". */
const dayOf = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' }) : ''

/** The night as the strip names it: "Last night, 02:10 to 06:40" within a day of its end, else by its day - "Night of
 *  Tue 24 Nov, …"; the Markdown, pasted later, always by its day. */
export function nightTitle(away: Away, now = new Date(), dated = false): string {
  const recent = !dated && away.ended_at != null && now.getTime() - Date.parse(away.ended_at) <= DAY
  const name = recent ? 'Last night' : `Night of ${dayOf(away.started_at)}`
  return `${name}, ${clock(away.started_at)} to ${clock(away.ended_at)}`
}

/** Where a time is on the axis, in % of it. */
export const place = (axis: Axis, at: string | number) =>
  (((typeof at === 'number' ? at : Date.parse(at)) - axis.from) / (axis.to - axis.from)) * 100

/** What KOLONİ's checks did not do, job by job - each started job's lines, `null` where no record says (never "none"). */
export const uncheckedOf = (away: Away): { job: AwayJob; lines: string[] | null }[] =>
  away.jobs.filter(job => job.conversation_id).map(job => ({ job, lines: job.not_checked ?? null }))

/** What the night spent against its limit: "Spent 1.40 USD of 5.00 USD"; not known where no record says. */
export function spentLine(away: Away): string {
  if (away.spent == null) return 'Spent: not known'
  const limit = away.money != null ? ` of ${amount(away.money, away.currency)}` : ''
  return `Spent ${away.at_least ? 'at least ' : ''}${amount(away.spent, away.currency)}${limit}`
}

/** A job as a line of the night's Markdown: its state, its title and - where the record has both - its span. */
function jobLine(job: AwayJob): string {
  const span = job.started_at && job.ended_at ? ` · ${clock(job.started_at)}–${clock(job.ended_at)}` : ''
  const decided = job.decisions.length ? ` · ${job.decisions.length} decided for you` : ''
  return `- ${inert(job.title)} · ${STATE_WORD[job.state] || 'planned'}${span}${decided}`
}

/**
 * Copy as Markdown, of the whole night: its span and sums, its jobs, what waits for you, what was decided for you on its
 * jobs, what was not checked and what it spent - each word a job's, an agent's or a model's inert (`inert`), masked as
 * the screen shows it.
 */
export function nightMarkdown(away: Away, parked: Waiting[], now = new Date()): string {
  const done = away.jobs.filter(job => job.state === 'done').length
  const waiting = parked
    .filter(row => !row.decision)
    .map(row => `- ${inert(row.task)} · ${row.kind}: ${inert(row.what_shown)}`)
  const decided = away.jobs
    .flatMap(job => job.decisions)
    .sort((a, b) => b.at.localeCompare(a.at))
    .map(row => markdownRow(row, now))
  const unchecked = uncheckedOf(away).flatMap(({ job, lines }) =>
    lines === null ? [`- ${inert(job.title)}: not known`] : lines.map(line => `- ${inert(job.title)}: ${inert(line)}`),
  )
  const part = (head: string, lines: string[]) => (lines.length ? ['', `${head}:`, ...lines] : [])
  return [
    `${nightTitle(away, now, true)}: ${done} of ${away.jobs.length} jobs done.`,
    '',
    'Jobs:',
    ...away.jobs.map(jobLine),
    ...part('Waiting for you', waiting),
    ...part('Decided for you', decided),
    ...part('Not checked', unchecked),
    '',
    `${spentLine(away)}.`,
  ].join('\n')
}

/** The page's greeting, by this machine's hour. */
export function greeting(now = new Date()): string {
  const hour = now.getHours()
  return hour >= 5 && hour < 12 ? 'Good morning' : hour >= 12 && hour < 18 ? 'Good afternoon' : 'Good evening'
}

const jobs = (n: number) => `${n} ${n === 1 ? 'job' : 'jobs'}`

/**
 * The report's one sentence, from the night's counts: how many of its jobs are done, then what waits for your word,
 * what could not be done and what was stopped - only those there are. One at work says so first.
 */
export function nightLede(away: Away): string {
  const count = (state: AwayJob['state']) => away.jobs.filter(job => job.state === state).length
  const [waits, failed, stopped] = [count('waits'), count('failed'), count('stopped')]
  const rest = [
    waits > 0 && `${waits} ${waits === 1 ? 'waits' : 'wait'} for your word`,
    failed > 0 && `${failed} could not be done`,
    stopped > 0 && `${stopped} ${stopped === 1 ? 'was' : 'were'} stopped`,
  ].filter(Boolean)
  const done = `${count('done')} of ${jobs(away.jobs.length)} done`
  const said = [away.status === 'running' ? `At work while you're away: ${done}` : done, ...rest].join(', ')
  return `${said}.`
}

/** Whether a night is news on Ready for you: at work, or ended and not looked at yet or within a day ("Last night"). */
export const isNews = (away: Away | null, now = new Date()): away is Away =>
  away !== null &&
  (away.status === 'running' ||
    (away.status === 'ended' &&
      (!away.seen_at || (away.ended_at != null && now.getTime() - Date.parse(away.ended_at) <= DAY))))
