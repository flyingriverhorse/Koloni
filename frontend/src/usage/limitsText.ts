import { dayAndTime } from '../agents/failure'
import { day } from '../memory/memoryText'
import type { Limits } from '../api/types'

type Window = Limits['windows'][number]

/** Near a plan's limit from this share of a window used (slice 37: said, nothing waits).
 *  shortcut: fixed at 90%, no setting; add one on the Usage page if a user asks for another. */
export const NEAR_AT = 90

/** A plan's window at NEAR_AT% or more as last read: one to say so of, once for each time it resets. */
export interface Near {
  /** The provider and the window, the same across readings. */
  key: string
  resets_at: string | null
  text: string
}

/** The windows used to NEAR_AT% or more now; one whose share is not known, or is stale, never is. */
export const nearOf = (limits: Limits): Window[] => limits.windows.filter(w => !w.stale && w.used_percent !== null && w.used_percent >= NEAR_AT)

/** What the toast and Usage say of a window near its limit. */
export const nearWords = (provider: string, w: Window) =>
  `${provider} is near its limit: ${Math.round(w.used_percent!)}% of ${windowName(w)} used${w.resets_at ? `, resets ${dayAndTime(w.resets_at)}` : ''}`

// A name in words, as agy names its groups and Copilot its premium requests; not an id like Claude Code's `five_hour`.
const worded = (name: string | null) => (name && !/^[a-z0-9_]+$/.test(name) ? name : null)

/** A window by its length, where that is known; else by the name its CLI gives it. A name in words is said too. */
export function windowName({ minutes, name }: Window): string {
  if (minutes === 10080) return worded(name) ? `${name} this week` : 'the week'
  if (minutes && minutes % 60 === 0) return `${minutes / 60} hours`
  if (minutes) return `${minutes} minutes`
  return worded(name) ?? (name ? `the ${name} window` : 'its window')
}

/**
 * A window as a plan's gauge says what is left of it - "this week", "this session", "of 5 hours" - and as the line
 * under it names it ("This week", "Session"): Claude Code calls its 5 hours `five_hour`, Codex names none.
 */
export function windowWords(w: Window): [gauge: string, line: string] {
  // shortcut: a window of one model's week is read from a name like `seven_day_fable`, not seen from the real CLI
  // yet; another name is shown as it is written.
  const up = (words: string) => words[0].toUpperCase() + words.slice(1)
  const model = /^seven_day_([a-z]+)$/.exec(w.name ?? '')?.[1]
  if (w.name === 'five_hour') return ['this session', 'Session']
  if (model) return [`of ${up(model)} this week`, `${up(model)} this week`]
  if (w.minutes === 10080 && !worded(w.name)) return ['this week', 'This week']
  return [`of ${windowName(w)}`, up(windowName(w))]
}

/** A balance as the CLI wrote it, with thousands set apart and two decimals where it is a plain number. */
export function balance(written: string): string {
  if (!/^\d+(\.\d+)?$/.test(written)) return written
  const [whole, rest] = written.split('.')
  return whole.replace(/\B(?=(\d{3})+$)/g, ',') + (rest ? `.${rest.slice(0, 2)}` : '')
}

/** What an OpenAI-compatible server says of itself where it says nothing of its limits (app/limits.py NO_PLAN): no row. */
export const NO_PLAN = 'a model server does not say what is left of a plan'

const clock = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })

/** An API's window as its last answer's headers said it (slice 73): "requests 48/50 left this minute, resets 12:03". */
function apiWindow(w: Window, again: string): string {
  const minute = w.minutes === 1
  if (w.stale || typeof w.remaining !== 'number')
    return `${w.name}: ${typeof w.limit === 'number' ? `${w.limit}${minute ? ' a minute' : ''}` : 'how many are left was not said'}${w.stale ? `, stale — ${again}` : ''}`
  return `${w.name} ${w.remaining}${typeof w.limit === 'number' ? `/${w.limit}` : ''} left ${minute ? 'this minute' : 'now'}${w.resets_at ? `, resets ${clock(w.resets_at)}` : ''}`
}

/** What is known of a plan, in one line. Nothing is made up: what is not known says so. */
export function limitsLine(limits: Limits): string {
  // Codex's, before the user has had it read: nothing is started just to show the page.
  if (limits.unknown === 'not read yet') return 'not read yet — Check now'
  if (limits.unknown) return `not known — ${limits.unknown}`
  // A window that has reset since it was read is not shown as it was then - nor as a zero.
  const again = limits.source ? 'it says again in its next run' : 'check again'
  const windows = limits.windows.map(w =>
    typeof w.limit === 'number' || typeof w.remaining === 'number'
      ? apiWindow(w, again)
      : w.stale
      ? `${windowName(w)}: stale — ${again}`
      : w.used_percent === null
        ? `${windowName(w)}: ${w.resets_at ? `resets ${dayAndTime(w.resets_at)}; ` : ''}how much is used was not said`
        : `${w.used_percent}% of ${windowName(w)} used${w.resets_at ? `, resets ${dayAndTime(w.resets_at)}` : ''}${
            // (one the last reading did not name: when it was read itself, B-74)
            w.read_at ? `, ${readAgo(w.read_at)}` : ''
          }`,
  )
  const credits = limits.credits?.unlimited ? ['credits unlimited'] : limits.credits?.balance ? [`credits ${balance(limits.credits.balance)}`] : []
  return [...(limits.plan ? [limits.plan] : []), ...windows, ...credits].join(' · ') || 'not known'
}

/** How long ago a reading was made; past a week, the day it was. */
export function readAgo(iso: string, now = Date.now()): string {
  const minutes = Math.floor((now - new Date(iso).getTime()) / 60000)
  const days = Math.floor(minutes / 1440)
  if (minutes < 1) return 'read just now'
  if (minutes < 60) return `read ${minutes} min ago`
  if (days < 1) return `read ${Math.floor(minutes / 60)} h ago`
  return days < 7 ? `read ${days === 1 ? '1 day' : `${days} days`} ago` : `read on ${day(iso)}`
}

/** When a reading was made, as the clock says it here: "as of 14:05" within a day, else with its day too. */
export const asOf = (iso: string, now = Date.now()) =>
  `as of ${now - new Date(iso).getTime() < 86400000 ? new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : dayAndTime(iso)}`
