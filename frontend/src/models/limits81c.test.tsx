import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { dayAndTime } from '../agents/failure'
import { ApiError } from '../api/client'
import type { Limits, Provider } from '../api/types'
import { Composer } from '../chat/Composer'
import { readingOf } from './cards'
import { ModelsPage } from './ModelsPage'

// Slice 81c: plan gauges in "left" words, the provider window's Limits tab, Copilot's model server folded away,
// and a provider past its limit asking before a turn.

const provider = (over: Partial<Provider>): Provider => ({
  id: 'p1',
  name: 'DeepSeek',
  kind: 'openai_compat',
  base_url: 'https://api.deepseek.com',
  default_model: null,
  executable: null,
  mode: null,
  options: null,
  for_agents: false,
  note: null,
  models: [],
  only_listed: false,
  max_running: null,
  plan: false,
  step_down_at: null,
  day_limit: null,
  month_limit: null,
  has_key: true,
  position: 0,
  created_at: 't',
  updated_at: 't',
  ...over,
})
const claude = provider({ id: 'cc', name: 'Claude Code', kind: 'claude_cli', base_url: null, has_key: false })
const codex = provider({ id: 'cx', name: 'Codex', kind: 'codex_cli', base_url: null, has_key: false })
const handlers = () => ({
  onCreate: vi.fn().mockResolvedValue(undefined),
  onSave: vi.fn().mockResolvedValue(undefined),
  onDelete: vi.fn().mockResolvedValue(undefined),
  onTest: vi.fn().mockResolvedValue({ ok: true, model_id: 'x', tools_supported: true, error: null }),
})
const RESETS = '2026-10-23T15:09:00Z'
const reading = (windows: Partial<Limits['windows'][number]>[], credits: Limits['credits'] = null): Limits => ({
  unknown: null,
  read_at: null,
  source: null,
  plan: null,
  credits,
  windows: windows.map(w => ({ name: null, minutes: null, used_percent: null, resets_at: null, stale: false, ...w })),
})

test('a plan’s gauge says what is left of its narrowest window, and the others and its credits under it', () => {
  // As Claude Code says it (23 Oct): session 67% used, the week 84%, Fable's week 3%.
  const told = reading([
    { name: 'five_hour', minutes: 300, used_percent: 67, resets_at: RESETS },
    { name: 'seven_day', minutes: 10080, used_percent: 84 },
    { name: 'seven_day_fable', used_percent: 3 },
  ])
  expect(readingOf(claude, { limits: told })).toEqual({
    share: 0.16,
    value: '16%',
    label: 'left this week',
    more: `Session 33% left · resets ${dayAndTime(RESETS)} · Fable this week 97% left`,
  })
  // As Codex says it: "5h 100% left, weekly 100% left, 42558 credits" - nothing of its account.
  const fresh = reading(
    [
      { minutes: 300, used_percent: 0 },
      { minutes: 10080, used_percent: 0 },
    ],
    { balance: '42558', has_credits: true, unlimited: false },
  )
  expect(readingOf(codex, { limits: fresh })).toEqual({ share: 1, value: '100%', label: 'left of 5 hours', more: 'This week 100% left · 42,558 credits' })
})

test('a plan’s gauge says how old its reading is: Claude Code’s comes from its last run here, and its use elsewhere since is not in it', () => {
  // As on 23 Oct: read at 11:34 with the week 83% used; by 15:23 the week was 93% used, in other sessions.
  const old = { ...reading([{ name: 'seven_day', minutes: 10080, used_percent: 83 }]), read_at: new Date(Date.now() - 4 * 3600_000).toISOString(), source: 'its last run' }
  expect(readingOf(claude, { limits: old })).toMatchObject({ value: '17%', more: 'read 4 h ago, in its last run here' })
  const asked = { ...reading([{ minutes: 300, used_percent: 10 }]), read_at: new Date(Date.now() - 5 * 60_000).toISOString(), source: 'account/rateLimits/read' }
  expect(readingOf(codex, { limits: asked })).toMatchObject({ more: 'read 5 min ago' })
})

test('the Limits tab: a plan switch and a day’s and month’s most for an API key, a step down for a subscription', async () => {
  const h = handlers()
  const { unmount } = render(<ModelsPage providers={[provider({ day_limit: 5 })]} picked="p1" {...h} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Limits' }))
  const panel = screen.getByRole('tabpanel', { name: 'Limits' })
  expect(within(panel).queryByLabelText(/Step down/)).toBeNull()
  const day = within(panel).getByLabelText(/At most \$ … a day/)
  expect(day).toHaveValue('5')
  const save = within(panel).getByRole('button', { name: 'Save limits' })
  expect(save).toBeDisabled() // nothing changed
  await userEvent.clear(day)
  await userEvent.type(within(panel).getByLabelText(/a month/), '0')
  expect(within(panel).getByText(/As written it is no limit/)).toBeInTheDocument()
  expect(save).toBeDisabled()
  // The note that says so is the box's description; only plain decimals are amounts.
  expect(within(panel).getByLabelText(/a month/)).toHaveAccessibleDescription(/As written it is no limit/)
  await userEvent.clear(within(panel).getByLabelText(/a month/))
  await userEvent.type(within(panel).getByLabelText(/a month/), '1e3')
  expect(save).toBeDisabled()
  await userEvent.clear(within(panel).getByLabelText(/a month/))
  await userEvent.type(within(panel).getByLabelText(/a month/), '50')
  await userEvent.click(save)
  expect(h.onSave).toHaveBeenLastCalledWith('p1', { day_limit: null, month_limit: 50 })
  expect(await within(panel).findByRole('status')).toHaveTextContent('Saved.')
  // A new edit is not what was saved.
  await userEvent.type(within(panel).getByLabelText(/a month/), '0')
  expect(within(panel).queryByRole('status')).toBeNull()
  await userEvent.type(within(panel).getByLabelText(/a month/), '{Backspace}')
  // A plan counts no money: there is no money to limit. The box is named by all of its note, not by the hint's button.
  const plan = within(panel).getByLabelText(/This key is a plan: count no money/)
  expect(plan).toHaveAccessibleName(
    'This key is a plan: count no money Its runs then show no cost on Usage and count nothing in a project’s budget. For a key paid in credits or a plan. Its runs are counted apart, as runs with no price are.',
  )
  await userEvent.click(plan)
  expect(within(panel).queryByLabelText(/a day/)).toBeNull()
  await userEvent.click(save)
  expect(h.onSave).toHaveBeenLastCalledWith('p1', expect.objectContaining({ plan: true }))
  unmount()

  const sub = handlers()
  render(<ModelsPage providers={[claude, provider({})]} picked="cc" {...sub} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Limits' }))
  const its = screen.getByRole('tabpanel', { name: 'Limits' })
  expect(within(its).queryByLabelText(/This key is a plan/)).toBeNull()
  await userEvent.type(within(its).getByLabelText(/Step down a tier at … % of the plan/), '40')
  expect(within(its).getByRole('button', { name: 'Save limits' })).toBeDisabled()
  await userEvent.clear(within(its).getByLabelText(/Step down/))
  await userEvent.type(within(its).getByLabelText(/Step down/), '80')
  await userEvent.click(within(its).getByRole('button', { name: 'Save limits' }))
  expect(sub.onSave).toHaveBeenLastCalledWith('cc', { step_down_at: 80 })
})

test('Copilot’s own model server is folded away; the key stays outside the fold', async () => {
  const { unmount } = render(<ModelsPage providers={[provider({})]} {...handlers()} />)
  await userEvent.click(screen.getByRole('button', { name: /Add a provider/ }))
  await userEvent.type(screen.getByLabelText('Name'), 'Copilot')
  await userEvent.selectOptions(screen.getByLabelText('Kind'), 'copilot_cli')
  const fold = screen.getByText('Use a model server of your own instead (optional)').closest('details')!
  expect(fold).not.toHaveAttribute('open')
  expect(within(fold).queryByLabelText('API key')).toBeNull()
  expect(screen.getByLabelText('API key')).toBeVisible()
  await userEvent.click(screen.getByText('Use a model server of your own instead (optional)'))
  expect(fold).toHaveAttribute('open')
  unmount()

  // One saved with a server of its own shows it open.
  const saved = provider({ id: 'cp', name: 'Copilot', kind: 'copilot_cli', base_url: 'http://localhost:8080/v1', mode: 'session' })
  render(<ModelsPage providers={[saved]} picked="cp" {...handlers()} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  expect(screen.getByText('Use a model server of your own instead (optional)').closest('details')).toHaveAttribute('open')
})

test('a provider past its limit asks before the turn, in its own words', async () => {
  const onSend = vi
    .fn()
    .mockRejectedValueOnce(new ApiError(409, "this project is over DeepSeek's limit of 5.00 USD a day (10.50 spent today): say to go on over it"))
    .mockResolvedValueOnce(undefined)
  render(<Composer running={false} permissionMode="ask" onSend={onSend} onStop={vi.fn()} onPermissionMode={vi.fn()} />)
  await userEvent.type(screen.getByLabelText('Message'), 'more{Enter}')
  const card = screen.getByRole('group', { name: "Over DeepSeek's limit of 5.00 USD a day (10.50 spent today)" })
  expect(card).toHaveTextContent("Over DeepSeek's limit of 5.00 USD a day (10.50 spent today). Send it anyway?")
  await userEvent.click(within(card).getByRole('button', { name: 'Go on anyway' }))
  expect(onSend).toHaveBeenLastCalledWith('more', false, true)
})

test('a limit that cannot be kept says so on its card and in its tab, never "$6 / $5"', async () => {
  const today = [{ provider_name: 'DeepSeek', provider_id: 'p1', model_id: 'chat', runs: 1, agents: 1, input_tokens: 1, output_tokens: 1, cache_read_tokens: null, cache_write_tokens: null, unknown_agents: 0, cost: { amount: 6, currency: 'USD' } }]
  const unkept = "This limit can't be kept: your prices are in EUR"
  expect(readingOf(provider({ day_limit: 5 }), { today, unkept })).toEqual({ share: null, value: '$6', label: 'today', plain: true, more: unkept })
  expect(readingOf(provider({ day_limit: 5 }), { today, unkept: null })).toMatchObject({ value: '$6 / $5', share: 1.2 })
  render(<ModelsPage providers={[provider({ day_limit: 5 })]} picked="p1" {...handlers()} prices={[{ model_id: 'x', input: 1, output: 1, currency: 'eur' }]} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Limits' }))
  expect(screen.getByRole('note')).toHaveTextContent(unkept)
})

test('a provider named like the budget is still a provider: the server’s whole sentence is read', async () => {
  const onSend = vi.fn().mockRejectedValueOnce(new ApiError(409, "this project is over Budget box's limit of 5.00 USD a month (7.00 spent this month): say to go on over it"))
  render(<Composer running={false} permissionMode="ask" onSend={onSend} onStop={vi.fn()} onPermissionMode={vi.fn()} />)
  await userEvent.type(screen.getByLabelText('Message'), 'more{Enter}')
  expect(screen.getByRole('group', { name: "Over Budget box's limit of 5.00 USD a month (7.00 spent this month)" })).toBeInTheDocument()
})
