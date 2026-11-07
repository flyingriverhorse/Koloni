import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { dayAndTime, failureText } from '../agents/failure'
import type { Limits, Provider } from '../api/types'
import { day } from '../memory/memoryText'
import { asOf, limitsLine, NO_PLAN, readAgo } from './limitsText'
import { PlanLimits } from './PlanLimits'

const provider = (id: string, name: string, kind: Provider['kind']) => ({ id, name, kind }) as Provider
const SOON = '2099-10-13T14:00:00Z'
const codex: Limits = {
  unknown: null,
  read_at: new Date(Date.now() - 3 * 60000).toISOString(),
  source: null,
  plan: 'pro',
  windows: [{ name: null, minutes: 10080, used_percent: 7, resets_at: SOON, stale: false }],
  credits: { balance: '49675.89', has_credits: true, unlimited: false },
}
const claude: Limits = {
  unknown: null,
  read_at: new Date().toISOString(),
  source: 'its last run',
  plan: null,
  windows: [
    { name: 'five_hour', minutes: 300, used_percent: 99, resets_at: SOON, stale: false },
    { name: 'another_window', minutes: null, used_percent: null, resets_at: '2020-01-01T00:00:00Z', stale: true },
  ],
  credits: null,
}
const unknown = (why: string): Limits => ({ unknown: why, read_at: null, source: null, plan: null, windows: [], credits: null })

test('a plan is read here and its own limit set on Models: "Limit in Models →" opens its provider there', async () => {
  const onModels = vi.fn()
  render(<PlanLimits providers={[provider('c', 'Codex', 'codex_cli')]} onLimits={vi.fn(async () => codex)} onModels={onModels} />)
  await userEvent.click(await screen.findByRole('button', { name: 'Limit Codex in Models' }))
  expect(onModels).toHaveBeenCalledWith('c')
})

test('each CLI has a row with what it says of its plan, and what is not known says so', async () => {
  const told: Record<string, Limits> = { l: unknown(NO_PLAN), c: codex, k: claude, a: unknown('this CLI does not say what is left of its plan') }
  const onLimits = vi.fn((id: string, _afresh: boolean) => Promise.resolve(told[id]))
  const providers = [provider('l', 'Local', 'openai_compat'), provider('c', 'Codex', 'codex_cli'), provider('k', 'Claude Code', 'claude_cli'), provider('a', 'agy', 'agy_cli')]
  render(<PlanLimits providers={providers} onLimits={onLimits} />)
  const rows = within(screen.getByRole('table', { name: 'Plan limits by provider' }))
  expect(await rows.findByRole('row', { name: /^Codex/ })).toHaveTextContent(`pro · 7% of the week used, resets ${dayAndTime(SOON)} · credits 49,675.89`)
  expect(rows.getByRole('row', { name: /^Codex/ })).toHaveTextContent('read 3 min ago')
  // A window that has reset since is not shown as it was, nor as a zero; one without a measured length goes by its name.
  const own = rows.getByRole('row', { name: /^Claude Code/ })
  expect(own).toHaveTextContent(`99% of 5 hours used, resets ${dayAndTime(SOON)} · the another_window window: stale — it says again in its next run`)
  // and the time of day it was read (89l)
  expect(own).toHaveTextContent(`read just now (${asOf(claude.read_at!)}), from its last run`)
  // the time of day within a day; past that, the day too
  const at = '2026-10-11T10:05:00Z'
  const clock = new Date(at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  expect(asOf(at, Date.parse('2026-10-12T10:04:00Z'))).toBe(`as of ${clock}`)
  expect(asOf(at, Date.parse('2026-10-12T10:05:00Z'))).toBe(`as of ${dayAndTime(at)}`)
  // at 90% or more, the row says it is near its limit; a stale window or a quiet plan is not
  expect(own).toHaveTextContent(`Claude Code is near its limit: 99% of 5 hours used, resets ${dayAndTime(SOON)}`)
  expect(rows.getByRole('row', { name: /^Codex/ })).not.toHaveTextContent('near its limit')
  // A bar for each window whose used share is known now: none for the stale one, none where nothing was read.
  expect(within(own).getAllByRole('meter').map(m => [m.getAttribute('aria-label'), m.getAttribute('value')])).toEqual([['Claude Code: 5 hours used', '99']])
  expect(within(rows.getByRole('row', { name: /^Codex/ })).getByRole('meter', { name: 'Codex: the week used' })).toHaveAttribute('value', '7')
  expect(within(rows.getByRole('row', { name: /^agy/ })).queryByRole('meter')).not.toBeInTheDocument()
  expect(rows.getByRole('row', { name: /^agy/ })).toHaveTextContent('not known — this CLI does not say what is left of its plan')
  // A model server that says nothing of its limits has no row (73: an API's answers may say them). Opening the page asks nobody afresh.
  expect(rows.queryByRole('row', { name: /^Local/ })).not.toBeInTheDocument()
  expect(onLimits.mock.calls).toEqual([
    ['l', false],
    ['c', false],
    ['k', false],
    ['a', false],
  ])
  expect(screen.getByText(/These are the limits of the account the CLI on this machine is signed in to\./)).toBeInTheDocument()
  expect(screen.getByText(/Claude Code is not asked here: its limits are read from its own runs/)).toBeInTheDocument()
})

test('opening the page reads nothing afresh; "Check now" does, and a reading that fails says why in its row', async () => {
  const onLimits = vi
    .fn()
    .mockResolvedValueOnce(unknown('not read yet'))
    .mockResolvedValueOnce(unknown('Codex did not answer within 15 seconds'))
    .mockRejectedValueOnce({ detail: 'the server is away' })
    .mockResolvedValueOnce({ ...codex, windows: [{ ...codex.windows[0], stale: true, used_percent: null }] })
    .mockResolvedValueOnce({ ...codex, failed: 'Codex did not answer within 15 seconds' })
  render(<PlanLimits providers={[provider('c', 'Codex', 'codex_cli')]} onLimits={onLimits} />)
  const row = () => screen.getByRole('row', { name: /^Codex/ })
  const check = () => userEvent.click(screen.getByRole('button', { name: 'Check now' }))
  // A row never read says so, and how to have it read: the page does not start Codex by itself.
  expect(await screen.findByText('not read yet — Check now')).toBeInTheDocument()
  expect(onLimits.mock.calls).toEqual([['c', false]])
  await check()
  expect(row()).toHaveTextContent('not known — Codex did not answer within 15 seconds')
  await check()
  expect(row()).toHaveTextContent('could not be read: the server is away')
  await check()
  expect(row()).toHaveTextContent('pro · the week: stale — check again · credits 49,675.89')
  // A reading that fails after a good one leaves the good one, with its time, and says so beside it.
  await check()
  expect(row()).toHaveTextContent('pro · 7% of the week used')
  expect(row()).toHaveTextContent('could not be read just now: Codex did not answer within 15 seconds; last read 3 min ago')
  expect(onLimits.mock.calls.map(([, afresh]) => afresh)).toEqual([false, true, true, true, true])
})

test('"Check now" never reads Claude Code afresh: that runs a turn, which only its own Read now on the Models page does (87)', async () => {
  const onLimits = vi.fn((_id: string, _afresh: boolean) => Promise.resolve(unknown('not read yet')))
  render(<PlanLimits providers={[provider('c', 'Codex', 'codex_cli'), provider('k', 'Claude Code', 'claude_cli')]} onLimits={onLimits} />)
  await userEvent.click(await screen.findByRole('button', { name: 'Check now' }))
  await waitFor(() => expect(onLimits).toHaveBeenCalledTimes(4))
  expect(onLimits.mock.calls.slice(2)).toEqual([
    ['c', true],
    ['k', false],
  ])
  // ...and its row says why, in sight: no Read now on Usage is deliberate
  const why = 'Check now does not read it: that takes a Claude Code turn. Read now on its Models card does.'
  expect(await screen.findByRole('row', { name: /^Claude Code/ })).toHaveTextContent(why)
  expect(screen.getByRole('row', { name: /^Codex/ })).not.toHaveTextContent(why)
})

test('a row being read and a check under way say so in plain characters', async () => {
  let answer = (_limits: Limits) => {}
  const onLimits = vi.fn(() => new Promise<Limits>(resolve => (answer = resolve)))
  render(<PlanLimits providers={[provider('c', 'Codex', 'codex_cli')]} onLimits={onLimits} />)
  expect(screen.getByRole('row', { name: /^Codex/ })).toHaveTextContent('reading…')
  expect(screen.getByRole('button', { name: 'Checking…' })).toBeDisabled()
  answer(unknown('not read yet'))
  expect(await screen.findByRole('button', { name: 'Check now' })).toBeEnabled()
  // (the hint's words as written: curly quotes, KOLONİ's dotted İ - no mojibake)
  const hint = document.querySelector('.memory-hint')!.textContent!
  expect(hint).toContain('“Check now” asks Codex')
  expect(hint).toContain('after KOLONİ restarts')
  expect(hint).not.toMatch(/â€|Ä|Å/)
})

test('without a CLI, or an API that says anything, there is no section', async () => {
  const onLimits = vi.fn(() => Promise.resolve(unknown(NO_PLAN)))
  const { container } = render(<PlanLimits providers={[provider('l', 'Local', 'openai_compat')]} onLimits={onLimits} />)
  await waitFor(() => expect(onLimits).toHaveBeenCalledWith('l', false))
  expect(container).toBeEmptyDOMElement()
})

test('an API says its rate limits in its answers, and DeepSeek its balance when checked (73)', async () => {
  const window = { name: 'requests', minutes: 1, used_percent: null, resets_at: SOON, stale: false, limit: 50, remaining: 48 }
  const api: Limits = { ...unknown(''), unknown: null, read_at: new Date().toISOString(), source: 'its last answer', windows: [window, { ...window, name: 'tokens', limit: 8000, stale: true }] }
  const balance: Limits = { ...unknown(''), unknown: null, read_at: new Date().toISOString(), credits: { balance: '110.00 CNY', has_credits: true, unlimited: null } }
  const told: Record<string, Limits> = { a: api, d: balance, l: unknown(NO_PLAN) }
  const onLimits = vi.fn((id: string, _afresh: boolean) => Promise.resolve(told[id]))
  render(<PlanLimits providers={[provider('a', 'Claude API', 'anthropic'), provider('d', 'DeepSeek', 'openai_compat'), provider('l', 'Local', 'openai_compat')]} onLimits={onLimits} />)
  const at = new Date(SOON).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  expect(await screen.findByRole('row', { name: /^Claude API/ })).toHaveTextContent(
    `requests 48/50 left this minute, resets ${at} · tokens: 8000 a minute, stale — it says again in its next run`,
  )
  expect(screen.getByRole('row', { name: /^DeepSeek/ })).toHaveTextContent('credits 110.00 CNY')
  // a model server that says nothing of itself has no row
  expect(screen.queryByRole('row', { name: /^Local/ })).toBeNull()
  // "Check now" asks the server for each: it asks DeepSeek, and no API a turn
  await userEvent.click(screen.getByRole('button', { name: 'Check now' }))
  await waitFor(() => expect(onLimits).toHaveBeenCalledTimes(6))
  expect(onLimits.mock.calls.slice(3).map(([, afresh]) => afresh)).toEqual([true, true, true])
  // only what was said: no limit said, no "of"
  expect(limitsLine({ ...api, windows: [{ ...window, limit: null, minutes: null }] })).toBe(`requests 48 left now, resets ${at}`)
})

test('a line says only what was said', () => {
  expect(limitsLine({ ...codex, plan: null, credits: { balance: null, has_credits: null, unlimited: true }, windows: [] })).toBe('credits unlimited')
  expect(limitsLine({ ...codex, credits: { balance: 'a lot', has_credits: true, unlimited: false }, windows: [{ name: null, minutes: 90, used_percent: 12.5, resets_at: null, stale: false }] })).toBe(
    'pro · 12.5% of 90 minutes used · credits a lot',
  )
  expect(limitsLine({ ...codex, plan: null, credits: null, windows: [] })).toBe('not known')
  // A window that has not reset, with when it does but not how much of it is used: not "stale".
  expect(limitsLine({ ...codex, plan: null, credits: null, windows: [{ ...codex.windows[0], used_percent: null }] })).toBe(`the week: resets ${dayAndTime(SOON)}; how much is used was not said`)
  // B-74: a window the last reading did not name says when it was read itself
  const earlier = new Date(Date.now() - 6 * 60000).toISOString()
  expect(limitsLine({ ...codex, plan: null, credits: null, windows: [{ ...codex.windows[0], read_at: earlier }] })).toMatch(/, read 6 min ago$/)
  expect(readAgo('2026-10-11T10:00:00Z', Date.parse('2026-10-11T12:30:00Z'))).toBe('read 2 h ago')
  // A reading kept across restarts can be old: days, and past a week the day it was.
  expect(readAgo('2026-10-11T10:00:00Z', Date.parse('2026-10-12T09:59:00Z'))).toBe('read 23 h ago')
  expect(readAgo('2026-10-11T10:00:00Z', Date.parse('2026-10-12T10:00:00Z'))).toBe('read 1 day ago')
  expect(readAgo('2026-10-11T10:00:00Z', Date.parse('2026-10-17T12:00:00Z'))).toBe('read 6 days ago')
  expect(readAgo('2026-10-11T10:00:00Z', Date.parse('2026-10-18T10:00:00Z'))).toBe(`read on ${day('2026-10-11T10:00:00Z')}`)
})

test('why an agent failed is said in plain words only where its provider said why', () => {
  const failed = { provider_name: 'Codex', failure: 'rate_limited', failure_resets_at: SOON } as const
  expect(failureText(failed)).toBe(`Codex: limit reached, resets ${dayAndTime(SOON)}`)
  expect(failureText({ ...failed, failure_resets_at: null })).toBe('Codex: limit reached')
  expect(failureText({ provider_name: 'Paid', failure: 'credits_exhausted', failure_resets_at: null })).toBe('Paid: out of credits')
  expect(failureText({ provider_name: null, failure: 'cli_crashed', failure_resets_at: null })).toBe('Its provider: the CLI stopped without finishing')
  expect(failureText({ provider_name: 'Codex', failure: 'empty_output', failure_resets_at: null })).toBe('Codex: it ended without an answer')
  expect(failureText({ provider_name: 'Codex', failure: 'other', failure_resets_at: null })).toBeNull()
  expect(failureText({ provider_name: 'Codex', failure: null, failure_resets_at: null })).toBeNull()
})
