import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Away, AwayJob, Decision, Waiting } from '../api/types'
import { NightStrip } from './NightStrip'
import { axisOf, nightMarkdown, nightTitle, place } from './nightText'

/** Ready for you's night (Part B): a lane per job on one time axis, the decisions on their jobs' lanes, what was not
 *  checked and spent, the whole report and Copy as Markdown - nothing drawn that the record does not hold. */

// (Today's hours: the night ended within a day - "Last night".)
const TODAY = new Date()
const on = (hour: number, minute = 0) => new Date(TODAY.getFullYear(), TODAY.getMonth(), TODAY.getDate(), hour, minute)
const at = (hour: number, minute = 0) => on(hour, minute).toISOString()

const decision = (id: string, when: string, seen: boolean | null, over: Partial<Decision> = {}): Decision => ({
  id,
  at: when,
  kind: 'answer',
  who: 'orchestrator',
  what: 'Answered a question for you',
  quote: 'Which database?',
  answer: 'SQLite',
  options: ['Postgres'],
  why: 'the tests make one',
  conversation_id: 'c1',
  chat: 'Fix login',
  link: { kind: 'question', id: id },
  undo: 'change_and_redo',
  undo_reason: null,
  seen,
  ...over,
})

const job = (over: Partial<AwayJob>): AwayJob => ({
  title: 'job',
  line: null,
  team: null,
  recipe: null,
  task_id: null,
  conversation_id: null,
  state: 'done',
  why: null,
  assessment: null,
  kept: [],
  files: [],
  taken: [],
  shared: [],
  kept_out: [],
  asks: [],
  checks: [],
  decisions: [],
  now: null,
  spent: null,
  ...over,
})

const night = (jobs: AwayJob[], over: Partial<Away> = {}): Away =>
  ({
    id: 'a1',
    project_id: 'p1',
    conversation_id: 'c0',
    run_id: 'r0',
    status: 'ended',
    jobs,
    kept_out: [],
    until: null,
    money: 5,
    started_at: at(2, 10),
    ended_at: at(6, 40),
    why: null,
    seen_at: null,
    tried: [],
    slipped: [],
    spent: 1.4,
    currency: 'USD',
    job_minutes: null,
    at_least: false,
    counts: {},
    proposed: [],
    decided: [],
    ...over,
  }) as Away

const push: Waiting = {
  id: 'p1',
  kind: 'push',
  task_id: 't1',
  task: 'Fix the login',
  conversation_id: 'c1',
  what: 'Push koloni/fix-login',
  what_shown: 'Push koloni/fix-login',
  cwd: null,
  why: 'Waits for you',
  warn: null,
  options: [],
  decision: null,
  answer: null,
  result: null,
  closed: null,
  held: false,
  seq: 1,
  tip: 'abc',
  place: null,
  danger: null,
  wrote: null,
}

const JOBS = [
  job({
    title: 'Fix the login',
    task_id: 't1',
    conversation_id: 'c1',
    started_at: at(2, 20),
    ended_at: at(3, 40),
    decisions: [decision('answer:q1', at(2, 30), false), decision('answer:q2', at(3, 10), true)],
    not_checked: ['Tests not run: a guessed command, you were away'],
  }),
  job({
    title: 'Clean old fixtures',
    task_id: 't2',
    conversation_id: 'c2',
    state: 'waits',
    started_at: at(5, 30),
    ended_at: at(6, 20),
    not_checked: [],
  }),
  // (its turn still open: its start alone - no bar, still listed; no Checked note: not known)
  job({ title: 'Docs pass', task_id: 't3', conversation_id: 'c3', state: 'stopped', started_at: at(4) }),
  job({ title: 'Never started', task_id: 't4', state: 'next' }),
]

test('the axis: from the night’s start to its end on whole hours, a tick an hour; none without both times', () => {
  const axis = axisOf(night(JOBS))!
  expect(new Date(axis.from).getHours()).toBe(2)
  expect(new Date(axis.to).getHours()).toBe(7)
  expect(axis.ticks.map(tick => new Date(tick).getHours())).toEqual([2, 3, 4, 5, 6, 7])
  expect(place(axis, at(4, 30))).toBe(50)
  // (a turn that ended past the night: the axis reaches it)
  const late = axisOf(night([job({ started_at: at(6), ended_at: at(7, 30) })]))!
  expect(new Date(late.to).getHours()).toBe(8)
  expect(axisOf(night(JOBS, { ended_at: null }))).toBeNull()
})

test('a lane per job: a bar only where the record has its start and end, its decisions filled while not seen', () => {
  const { container } = render(<NightStrip away={night(JOBS)} parked={[push]} />)
  const strip = screen.getByRole('region', { name: /^Last night, / })
  const lanes = within(strip).getAllByRole('listitem')
  expect(lanes.map(lane => lane.getAttribute('aria-label'))).toEqual([
    `Fix the login: Done, ${hm(2, 20)} to ${hm(3, 40)}, 2 decided for you, 1 not seen, its push waits for you`,
    `Clean old fixtures: Waits for you, ${hm(5, 30)} to ${hm(6, 20)}`,
    'Docs pass: Stopped',
    'Never started: Next',
  ])
  expect(lanes[0].querySelector('.night-bar.night-done')).not.toBeNull()
  expect(lanes[1].querySelector('.night-bar.night-waits')).not.toBeNull()
  expect(lanes[2].querySelector('.night-bar')).toBeNull()
  expect(lanes[3].querySelector('.night-bar')).toBeNull()
  expect(lanes[0].querySelectorAll('.night-hex')).toHaveLength(2)
  expect(lanes[0].querySelectorAll('.night-hex .night-unseen')).toHaveLength(1)
  expect(within(lanes[0]).getByText('push waits for you')).toBeInTheDocument()
  // (no bar of a kind not drawn in its legend)
  expect(container.querySelector('.night-foot')).toHaveTextContent('FinishedWaits for youDecision you haven’t seenSeen')
  expect(strip).toHaveTextContent('Spent 1.40 USD of 5.00 USD')
})

test('Not checked: its count opens on its lines, job by job - a job no record says of, not known', async () => {
  render(<NightStrip away={night(JOBS)} parked={[]} />)
  const open = screen.getByRole('button', { name: '1 thing, 1 job not known' })
  expect(open).toHaveAttribute('aria-expanded', 'false')
  await userEvent.click(open)
  const lines = Array.from(document.querySelectorAll('.night-unchecked-list li'), li => li.textContent)
  expect(lines).toEqual([
    'Fix the login: Tests not run: a guessed command, you were away',
    'Docs pass: not known: no record of its checks',
  ])
})

test('spent not known says so; a night at work, or one with no end, draws nothing', () => {
  render(<NightStrip away={night(JOBS, { spent: null, money: null })} parked={[]} />)
  expect(screen.getByText('Spent: not known')).toBeInTheDocument()
  const { container } = render(<NightStrip away={night(JOBS, { status: 'running', ended_at: null })} parked={[]} />)
  expect(container).toBeEmptyDOMElement()
})

test('the whole report, and Copy as Markdown of it: every word of a job’s, an agent’s or a model’s inert', async () => {
  const user = userEvent.setup()
  const onReport = vi.fn()
  const hostile = 'Fix [it](https://evil.example) `now` <img src=x>'
  const jobs = [{ ...JOBS[0], title: hostile }, ...JOBS.slice(1)]
  render(<NightStrip away={night(jobs)} parked={[push]} onReport={onReport} />)
  await user.click(screen.getByRole('button', { name: 'The whole report' }))
  expect(onReport).toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: 'Copy as Markdown' }))
  expect(await screen.findByRole('status')).toHaveTextContent('Copied')
  const copied = await navigator.clipboard.readText()
  expect(copied).toBe(nightMarkdown(night(jobs), [push]))
  const lines = copied.split('\n')
  // (pasted later: by its day, never "last night")
  expect(lines[0]).toBe(`Night of ${day(2, 10)}, ${hm(2, 10)} to ${hm(6, 40)}: 1 of 4 jobs done.`)
  expect(lines).toContain(`- \`\` ${hostile} \`\` · Done · ${hm(2, 20)}–${hm(3, 40)} · 2 decided for you`)
  expect(lines).toContain('- ` Fix the login ` · push: ` Push koloni/fix-login `')
  expect(lines).toContain('- ` Docs pass `: not known')
  expect(lines.filter(line => line.includes('Answered a question for you'))).toHaveLength(2)
  expect(lines.at(-1)).toBe('Spent 1.40 USD of 5.00 USD.')
})

/** A time as the strip says it, and its day. */
const DAY_SAID = { weekday: 'short', day: 'numeric', month: 'short' } as const
function day(hour: number, minute = 0) {
  return on(hour, minute).toLocaleDateString([], DAY_SAID)
}

test('a night is "last night" within a day of its end, else named by its day', () => {
  const ended = night([], { started_at: '2026-11-20T23:10:00Z', ended_at: '2026-11-21T06:40:00Z' })
  const said = (now: string) => nightTitle(ended, new Date(now))
  expect(said('2026-11-21T20:00:00Z').startsWith('Last night, ')).toBe(true)
  const named = `Night of ${new Date('2026-11-20T23:10:00Z').toLocaleDateString([], DAY_SAID)}, `
  expect(said('2026-11-25T09:00:00Z').startsWith(named)).toBe(true)
})

function hm(hour: number, minute = 0) {
  return on(hour, minute).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

test('the night’s Markdown copies a parked line as the page shows it - masked, never as recorded', () => {
  const secret = 'curl -H "Authorization: Bearer ghp_0123456789abcdef" https://me:hunter2@example.com'
  const line = {
    ...push,
    kind: 'command',
    what: secret,
    what_shown: 'curl -H "Authorization: ***" https://***@example.com',
  }
  const copied = nightMarkdown(night(JOBS), [line])
  expect(copied).toContain('curl -H "Authorization: ***" https://***@example.com')
  for (const word of ['ghp_0123456789abcdef', 'hunter2']) expect(copied).not.toContain(word)
})
