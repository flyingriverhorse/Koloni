import { render, screen, within } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import type { Budget, DecisionLog, Limits, Project, Provider, Usage } from '../api/types'
import { DecidedToday } from '../ready/DecidedToday'
import { Days } from './Days'
import { daysLeft } from './budgetText'
import { since } from './period'
import { TopChats, WhoStarted } from './Spenders'
import { UsagePage } from './UsagePage'
import { fullestPlan, summarySentence } from './usageText'

// 0.1.10's Usage page in the honeycomb cells: the summary in a sentence, the strip of days, the chats that spent most,
// who started it, "plan" for a subscription's cost and Copilot's AI credits.

const sums = { cache_read_tokens: null, cache_write_tokens: null, unknown_agents: 0 }
const row = (over: Partial<Usage['by_model'][number]>): Usage['by_model'][number] => ({
  provider_name: 'Paid',
  model_id: 'm',
  runs: 1,
  agents: 1,
  input_tokens: 100,
  output_tokens: 10,
  cost: null,
  ...sums,
  ...over,
})
const usage = (by_model: Usage['by_model']): Usage => ({ by_model, by_conversation: [], by_start: [], by_day: [] })
const budget = (over: Partial<Budget> = {}): Budget => ({
  budget: 50,
  currency: 'USD',
  spent: 23.4,
  share: 0.468,
  warn: false,
  over: false,
  at_least: false,
  unpriced_runs: 0,
  ...over,
})

test('the summary says what the period cost, in words; with nothing priced it says no money was counted', () => {
  const said = (over: Partial<Parameters<typeof summarySentence>[0]>) =>
    summarySentence({ period: 'month', usage: usage([row({})]), cost: '≈ 23.4 USD', ...over })
  expect(said({})).toBe('This month about 23.4 USD was spent.')
  expect(said({ cost: '≥ 1.5 USD', period: '7' })).toBe('In the last 7 days at least 1.5 USD was spent.')
  // amounts in two currencies are never added: each is said
  expect(said({ cost: '≈ 1 USD + ≈ 2 EUR', period: 'all' })).toBe('So far about 1 USD + about 2 EUR was spent.')
  expect(said({ cost: '–', period: 'today' })).toBe(
    'Today no money was counted: what ran was on a plan, had no price or reported nothing.',
  )
  // nothing ran: what the page said before
  expect(said({ usage: usage([]), period: 'today' })).toBe('No agent reported usage today.')
  expect(said({ usage: usage([]), period: '30' })).toBe('No agent ran in this period.')
})

test('the summary adds this month’s budget where the project has one - unenforced or over said so - and the plan used most', () => {
  const said = (over: Partial<Parameters<typeof summarySentence>[0]>) =>
    summarySentence({ period: 'today', usage: usage([row({})]), cost: '–', ...over }).replace(/^Today .*?\. /, '')
  expect(said({ budget: budget() })).toBe('This month’s budget is 46% used.')
  expect(said({ budget: budget({ at_least: true }) })).toBe('This month’s budget is at least 46% used.')
  expect(said({ budget: budget({ spent: 51, share: 1.02, over: true, warn: true }) })).toBe(
    'This month’s budget is 102% used: a new message asks before its work starts.',
  )
  expect(said({ budget: budget({ spent: null, share: null, currency: null }) })).toBe(
    'This budget is not enforced: prices are in more than one currency.',
  )
  // no budget set, or every project's: not a word of it
  expect(said({ budget: budget({ budget: null, share: null }) })).toMatch(/^Today no money/)
  expect(said({ budget: null, plan: 'Claude Code has used 62% of the week.' })).toBe(
    'Claude Code has used 62% of the week.',
  )
})

test('the plan used most is the window most used of what the plans last said; a stale or unknown one is not', () => {
  const cli = (id: string, name: string) => ({ id, name, kind: 'codex_cli' }) as Provider
  const window = (used: number | null, stale = false) => ({
    name: null,
    minutes: 10080,
    used_percent: used,
    resets_at: null,
    stale,
  })
  const limits = (windows: Limits['windows'], unknown: string | null = null) =>
    ({ unknown, read_at: null, source: null, plan: null, windows, credits: null }) as Limits
  const providers = [cli('a', 'Codex'), cli('b', 'Claude Code'), cli('c', 'agy')]
  expect(
    fullestPlan(providers, {
      a: limits([window(18), window(null)]),
      b: limits([window(62.4), window(95, true)]),
      c: 'could not be read',
    }),
  ).toBe('Claude Code has used 62% of the week.')
  expect(fullestPlan(providers, { a: limits([window(99)], 'not read yet') })).toBeNull()
  expect(fullestPlan(providers, {})).toBeNull()
})

const day = (date: Date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
const NOW = new Date(2026, 10, 27, 15, 0)
const back = (days: number) => day(new Date(2026, 10, 27 - days))
const dayRow = (on: string, over: Partial<Usage['by_day'][number]> = {}): Usage['by_day'][number] => ({
  day: on,
  runs: 1,
  agents: 1,
  input_tokens: 1000,
  output_tokens: 100,
  cost: null,
  ...sums,
  ...over,
})

test('the strip has the last 30 days by money: a bar a day said in words, the most and today under it', () => {
  render(
    <Days
      read={{
        at: NOW,
        rows: [
          dayRow(back(29), { cost: { amount: 1, currency: 'USD' } }),
          dayRow(back(2), { cost: { amount: 3.1, currency: 'USD' } }),
          // ran on a plan: no money - a stub, not a zero
          dayRow(back(1)),
          dayRow(back(0), { cost: { amount: 1.62, currency: 'USD', at_least: true } }),
        ],
      }}
    />,
  )
  const strip = screen.getByRole('list', { name: 'Each day' })
  const days = within(strip).getAllByRole('listitem')
  expect(days).toHaveLength(30)
  expect(days[0]).toHaveTextContent('29 Oct: ≈ 1.00 USD')
  expect(days[1]).toHaveTextContent('30 Oct: nothing ran')
  // (no cost: on a plan, unpriced, or its models' costs in two currencies)
  expect(days[28]).toHaveTextContent('26 Nov: no cost in one currency')
  expect(days[28].querySelector('i')).toHaveClass('usage-strip-unknown')
  expect(days[27].querySelector('i')).toHaveStyle({ height: '100%' })
  expect(days[1].querySelector('i')).toBeNull()
  expect(screen.getByText('the money spent, the last 30 days')).toBeInTheDocument()
  expect(screen.getByText('Most: 25 Nov: ≈ 3.10 USD')).toBeInTheDocument()
  expect(screen.getByText('Today, 27 Nov: ≥ 1.62 USD')).toBeInTheDocument()
})

test('with costs in two currencies the strip is the tokens reported, and says why; a part is "≥"; with nothing, it says so', () => {
  const { rerender } = render(
    <Days
      read={{
        at: NOW,
        rows: [
          dayRow(back(3), { cost: { amount: 1, currency: 'USD' } }),
          dayRow(back(1), { cost: { amount: 1, currency: 'EUR' } }),
          dayRow(back(0), { input_tokens: null, output_tokens: null }),
          // an agent of it reported nothing: what is said is only the least
          dayRow(back(5), { input_tokens: 2000, output_tokens: 100, unknown_agents: 1 }),
        ],
      }}
    />,
  )
  expect(screen.getByText('the tokens reported, the last 30 days: costs are in more than one currency')).toBeVisible()
  expect(screen.getByText('Most: 22 Nov: ≥ 2,100 tokens')).toBeInTheDocument()
  expect(screen.getByRole('list', { name: 'Each day' })).toHaveTextContent('24 Nov: 1,100 tokens')
  expect(screen.getByText('Today, 27 Nov: nothing reported')).toBeInTheDocument()
  // with no cost at all: said so
  rerender(<Days read={{ at: NOW, rows: [dayRow(back(0))] }} />)
  expect(screen.getByText('the tokens the models reported, the last 30 days: nothing in them has a cost')).toBeVisible()
  rerender(<Days read={{ at: NOW, rows: [] }} />)
  expect(screen.getByText('Nothing ran in the last 30 days.')).toBeInTheDocument()
  expect(screen.queryByRole('list')).toBeNull()
})

const talk = (id: string, title: string, over: Partial<Usage['by_conversation'][number]> = {}) => ({
  conversation_id: id,
  project_id: 'p',
  title,
  runs: 1,
  agents: 1,
  input_tokens: 10,
  output_tokens: 1,
  ...sums,
  ...over,
})

test('the chats that spent most come by their money, three of them, each opening its chat; all of them in numbers', async () => {
  const onOpen = vi.fn()
  render(
    <TopChats
      rows={[
        talk('a', 'Login', { cost: { amount: 6.15, currency: 'USD' } }),
        talk('b', 'Plan only'),
        talk('c', 'Report export', { cost: { amount: 9.4, currency: 'USD' } }),
        talk('d', 'Reset', { cost: { amount: 4.02, currency: 'USD' } }),
      ]}
      here={{ id: 'p' } as Project}
      nameOf={() => 'demo'}
      onOpen={onOpen}
    />,
  )
  const top = within(screen.getByRole('region', { name: 'Chats that spent most' })).getAllByRole('listitem')
  expect(top.map(item => item.textContent)).toEqual(['Report export≈ 9.40 USD', 'Login≈ 6.15 USD', 'Reset≈ 4.02 USD'])
  within(top[0]).getByRole('button', { name: 'Report export' }).click()
  expect(onOpen).toHaveBeenCalledWith('c')
  expect(screen.getByText('All 4 chats, in numbers')).toBeInTheDocument()
  expect(
    within(screen.getByRole('table', { name: 'Usage by conversation' })).getByRole('row', { name: /^Plan only/ }),
  ).toHaveTextContent('–')
})

test('who started it is a bar each, by its money; its numbers folded under', () => {
  const start = (started_by: 'user' | 'koloni', amount: number | null, runs: number, agents: number) => ({
    started_by,
    runs,
    agents,
    input_tokens: 10,
    output_tokens: 1,
    ...sums,
    cost: amount === null ? null : { amount, currency: 'USD' },
  })
  render(<WhoStarted rows={[start('user', 15.9, 3, 5), start('koloni', 0.6, 0, 2)]} />)
  const who = screen.getByRole('region', { name: 'Who started it' })
  const [you, itself] = within(who).getAllByRole('listitem')
  expect(you).toHaveTextContent('You≈ 15.90 USD')
  expect(itself).toHaveTextContent('KOLONİ itself≈ 0.60 USD')
  expect(you.querySelector('.usage-share i')).toHaveStyle({ width: '100%' })
  expect(within(who).getByText('3 messages by you · 2 requests by KOLONİ itself')).toBeInTheDocument()
  expect(within(who).getByRole('table', { name: 'Usage by who sent the message' })).toBeInTheDocument()
})

test('a subscription’s model costs "plan", not a dash; Copilot’s AI credits are beside its cost', async () => {
  const cli = { id: 'cc', name: 'Claude Code', kind: 'claude_cli', plan: false } as Provider
  const copilot = { id: 'gh', name: 'Copilot', kind: 'copilot_cli', plan: false } as Provider
  const keyAPlan = { id: 'k', name: 'Key', kind: 'anthropic', plan: true } as Provider
  const read = usage([
    row({ provider_name: 'Claude Code', provider_id: 'cc', model_id: 'sonnet' }),
    row({
      provider_name: 'Copilot',
      provider_id: 'gh',
      model_id: 'auto',
      nano_aiu: 41_000_000_000,
      premium_requests: 2,
    }),
    row({ provider_name: 'Key', provider_id: 'k', model_id: 'opus' }),
    row({ provider_name: 'Gone', provider_id: null, model_id: 'x' }),
  ])
  render(
    <UsagePage
      project={{ id: 'p', name: 'demo' } as Project}
      projects={[]}
      providers={[cli, copilot, keyAPlan]}
      onLoad={vi.fn().mockResolvedValue(read)}
      onOpen={vi.fn()}
    />,
  )
  const models = within(await screen.findByRole('table', { name: 'Usage by provider and model' }))
  const cost = (name: RegExp) => within(models.getByRole('row', { name })).getAllByRole('cell').at(-1)!.textContent
  expect(cost(/^Claude Code/)).toBe('plan')
  expect(cost(/^Copilot/)).toBe('plan · 41 AI credits · 2 premium requests')
  expect(cost(/^Key/)).toBe('plan')
  // a provider deleted since, or one with no price: not known
  expect(cost(/^Gone/)).toBe('–')
})

test('the decisions line follows the period: this month’s from its first day, all of them from the first', async () => {
  const log = (rows: number, unseen: number) =>
    ({
      rows: Array.from({ length: rows }, (_, at) => ({ seen: at >= unseen })),
      judge_fine: 0,
      more: false,
    }) as DecisionLog
  const onLoad = vi.fn().mockResolvedValue(log(41, 2))
  const { rerender } = render(<DecidedToday onLoad={onLoad} period="month" />)
  expect(
    await screen.findByText("41 decisions were made for you this month, 2 of them you haven't seen."),
  ).toBeVisible()
  expect(onLoad).toHaveBeenLastCalledWith(since('month'))
  onLoad.mockResolvedValue(log(1, 0))
  rerender(<DecidedToday onLoad={onLoad} period="all" />)
  expect(await screen.findByText('1 decision was made for you so far.')).toBeVisible()
  expect(onLoad).toHaveBeenLastCalledWith(new Date(0).toISOString())
  // (read once for a period: "7 days" back is another moment each render); the last period's line is gone meanwhile
  onLoad.mockClear()
  let answer: (log: DecisionLog) => void = () => {}
  onLoad.mockReturnValue(new Promise<DecisionLog>(resolve => (answer = resolve)))
  rerender(<DecidedToday onLoad={onLoad} period="7" />)
  expect(screen.queryByText('1 decision was made for you so far.')).toBeNull()
  rerender(<DecidedToday onLoad={onLoad} period="7" />)
  answer(log(1, 0))
  await screen.findByText('1 decision was made for you in the last 7 days.')
  expect(onLoad).toHaveBeenCalledTimes(1)
})

test('the days left of the month do not count today; on its last day none are left', () => {
  expect(daysLeft(new Date(2026, 10, 27, 15))).toBe(3)
  expect(daysLeft(new Date(2026, 10, 30, 23))).toBe(0)
  expect(daysLeft(new Date(2026, 1, 1))).toBe(27)
})
