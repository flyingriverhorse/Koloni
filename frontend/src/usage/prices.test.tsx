import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Project, Provider, Usage } from '../api/types'
import { UsagePage } from './UsagePage'

const project = { id: 'p', name: 'demo' } as Project
const provider = (over: Partial<Provider>): Provider => ({
  id: 'p1',
  name: 'Paid',
  kind: 'anthropic',
  base_url: 'https://api.anthropic.com',
  default_model: 'claude-haiku-5-5',
  executable: null,
  mode: null,
  options: null,
  for_agents: false,
  note: null,
  models: [{ name: 'claude-sonnet-5-5', note: null, agents: true }],
  only_listed: false,
  max_running: null, plan: false, step_down_at: null, day_limit: null, month_limit: null,
  has_key: true,
  position: 0,
  created_at: 't',
  updated_at: 't',
  ...over,
})
const cli = provider({ id: 'p2', name: 'Claude Code', kind: 'claude_cli', base_url: null, default_model: 'sonnet', models: [{ name: 'opus', note: null, agents: true }], position: 1 })
const ran = (provider_name: string | null, model_id: string | null) => ({ provider_name, model_id, runs: 1, agents: 1, input_tokens: 100, output_tokens: 10, cache_read_tokens: null, cache_write_tokens: null, unknown_agents: 0, cost: null })
const usage: Usage = {
  // A model no provider names, one of a CLI, one of a provider that is gone, and a run whose model is not known.
  by_model: [ran('Paid', 'typed-by-hand'), ran('Claude Code', 'claude-fable-5'), ran('Deleted', 'left-behind'), ran('Paid', null), ran('Paid', 'claude-haiku-5-5')],
  by_conversation: [],
  by_start: [],
}

test('every model is listed once, priced ones first: those with a price, those that ran and those an API provider names - not a CLI’s', async () => {
  const onPrice = vi.fn().mockResolvedValue(undefined)
  const onRemovePrice = vi.fn().mockResolvedValue(undefined)
  const onLoad = vi.fn().mockResolvedValue(usage)
  const saved = [
    { model_id: 'claude-sonnet-5-5', input: 3, output: 15, currency: 'USD' },
    { model_id: 'named-nowhere', input: 1, output: 2, currency: 'TL' },
  ]
  render(<UsagePage project={project} projects={[project]} onLoad={onLoad} onOpen={vi.fn()} providers={[provider({}), cli]} prices={saved} onPrice={onPrice} onRemovePrice={onRemovePrice} />)
  await screen.findByRole('table', { name: 'Usage by provider and model' })
  const prices = within(screen.getByRole('region', { name: 'Prices' }))
  expect(prices.getAllByRole('button', { name: /^Save the price of/ }).map(b => b.getAttribute('aria-label')?.replace('Save the price of ', ''))).toEqual([
    'claude-sonnet-5-5',
    'named-nowhere',
    'claude-haiku-5-5',
    'left-behind',
    'typed-by-hand',
  ])
  expect(prices.getByText(/Leave those empty and such tokens are left out of the cost, which then says “≥”\..*A CLI on a plan has no price for a token and is not listed\./)).toBeInTheDocument()
  // What is saved is shown, and can be taken away; a model without one has nothing to remove.
  expect(prices.getByLabelText('Input price of claude-sonnet-5-5')).toHaveValue('3')
  expect(prices.getByLabelText('Output price of claude-sonnet-5-5')).toHaveValue('15')
  expect(prices.getByLabelText('Currency of claude-sonnet-5-5')).toHaveValue('USD')
  expect(prices.queryByRole('button', { name: 'Remove the price of claude-haiku-5-5' })).not.toBeInTheDocument()
  expect(onLoad).toHaveBeenCalledTimes(1)
  await userEvent.click(prices.getByRole('button', { name: 'Remove the price of claude-sonnet-5-5' }))
  expect(onRemovePrice).toHaveBeenCalledWith('claude-sonnet-5-5')
  // The usage is read again, for the same project and period: its cost is of the prices as they are now.
  expect(onLoad).toHaveBeenCalledTimes(2)

  // A price is two numbers that are not negative and a currency: until then it cannot be saved.
  const save = prices.getByRole('button', { name: 'Save the price of typed-by-hand' })
  expect(save).toBeDisabled()
  await userEvent.type(prices.getByLabelText('Input price of typed-by-hand'), '0.8')
  await userEvent.type(prices.getByLabelText('Output price of typed-by-hand'), '-4')
  await userEvent.type(prices.getByLabelText('Currency of typed-by-hand'), ' TL ')
  expect(save).toBeDisabled()
  await userEvent.clear(prices.getByLabelText('Output price of typed-by-hand'))
  await userEvent.type(prices.getByLabelText('Output price of typed-by-hand'), '4')
  await userEvent.click(save)
  expect(onPrice).toHaveBeenCalledWith({ model_id: 'typed-by-hand', input: 0.8, output: 4, currency: 'TL' })
  expect(onLoad).toHaveBeenCalledTimes(3)
  expect(onLoad).toHaveBeenLastCalledWith('p', expect.any(String))
})

test('the models can be priced though no agent ran, and a refused price says why and reads nothing again', async () => {
  const onPrice = vi.fn().mockRejectedValue({ detail: 'origin not allowed' })
  const onLoad = vi.fn().mockResolvedValue({ by_model: [], by_conversation: [], by_start: [] })
  render(<UsagePage project={project} projects={[project]} onLoad={onLoad} onOpen={vi.fn()} providers={[provider({}), cli]} prices={[]} onPrice={onPrice} onRemovePrice={vi.fn()} />)
  expect(await screen.findByText('No agent reported usage today.')).toBeInTheDocument()
  const prices = within(screen.getByRole('region', { name: 'Prices' }))
  expect(prices.getAllByRole('button', { name: /^Save the price of/ })).toHaveLength(2)
  await userEvent.type(prices.getByLabelText('Input price of claude-haiku-5-5'), '1')
  await userEvent.type(prices.getByLabelText('Output price of claude-haiku-5-5'), '5')
  await userEvent.type(prices.getByLabelText('Currency of claude-haiku-5-5'), 'USD')
  await userEvent.click(prices.getByRole('button', { name: 'Save the price of claude-haiku-5-5' }))
  expect(await prices.findByRole('alert')).toHaveTextContent('origin not allowed')
  expect(onLoad).toHaveBeenCalledTimes(1)
})

test('without the price handlers the page has no Prices, and with nothing to list it says so', async () => {
  const onLoad = vi.fn().mockResolvedValue({ by_model: [], by_conversation: [], by_start: [] })
  const { unmount } = render(<UsagePage project={project} projects={[project]} onLoad={onLoad} onOpen={vi.fn()} providers={[cli]} />)
  await screen.findByText('No agent reported usage today.')
  expect(screen.queryByRole('region', { name: 'Prices' })).not.toBeInTheDocument()
  unmount()
  render(<UsagePage project={project} projects={[project]} onLoad={onLoad} onOpen={vi.fn()} providers={[cli]} prices={[]} onPrice={vi.fn()} onRemovePrice={vi.fn()} />)
  await screen.findByText('No agent reported usage today.')
  expect(within(screen.getByRole('region', { name: 'Prices' })).getByText(/No model has a price/)).toBeInTheDocument()
})

test('a price has two more boxes, for what is read from a cache and written to it: each may be left empty, and an empty one is not sent', async () => {
  const onPrice = vi.fn().mockResolvedValue(undefined)
  const saved = [{ model_id: 'claude-sonnet-5-5', input: 3, output: 15, currency: 'USD', cache_read: 0.3, cache_write: 3.75 }]
  render(<UsagePage project={project} projects={[project]} onLoad={vi.fn().mockResolvedValue(usage)} onOpen={vi.fn()} providers={[provider({})]} prices={saved} onPrice={onPrice} onRemovePrice={vi.fn()} />)
  await screen.findByRole('table', { name: 'Usage by provider and model' })
  const prices = within(screen.getByRole('region', { name: 'Prices' }))
  // a saved price shows its cache prices; the boxes say what they are for
  expect(prices.getByLabelText('A million read from the cache, for claude-sonnet-5-5')).toHaveValue('0.3')
  expect(prices.getByLabelText('A million written to it, for claude-sonnet-5-5')).toHaveValue('3.75')
  expect(prices.getAllByText('A million read from the cache').length).toBeGreaterThan(1)

  // both left empty: not sent at all
  const save = prices.getByRole('button', { name: 'Save the price of typed-by-hand' })
  await userEvent.type(prices.getByLabelText('Input price of typed-by-hand'), '4')
  await userEvent.type(prices.getByLabelText('Output price of typed-by-hand'), '20')
  await userEvent.type(prices.getByLabelText('Currency of typed-by-hand'), 'USD')
  await userEvent.click(save)
  expect(onPrice).toHaveBeenLastCalledWith({ model_id: 'typed-by-hand', input: 4, output: 20, currency: 'USD' })
  expect(Object.keys(onPrice.mock.lastCall?.[0])).not.toContain('cache_read')

  // one that holds no price cannot be saved; one that does is sent, the other still left out
  const read = prices.getByLabelText('A million read from the cache, for typed-by-hand')
  await userEvent.type(read, 'cheap')
  expect(save).toBeDisabled()
  await userEvent.clear(read)
  await userEvent.type(read, '0.2')
  await userEvent.click(save)
  expect(onPrice).toHaveBeenLastCalledWith({ model_id: 'typed-by-hand', input: 4, output: 20, currency: 'USD', cache_read: 0.2 })
  expect(Object.keys(onPrice.mock.lastCall?.[0])).not.toContain('cache_write')
})

test('a model models.dev has a price for is listed at it, can be given the user’s own, and put back', async () => {
  const onPrice = vi.fn().mockResolvedValue(undefined)
  const onRemovePrice = vi.fn().mockResolvedValue(undefined)
  const onLoad = vi.fn().mockResolvedValue(usage)
  const catalogue = [
    { model_id: 'claude-haiku-5-5', provider_name: 'Paid', input: 0.1, output: 0.5, cache_read: 0.01, cache_write: null, currency: 'USD', read_on: '2026-10-21' },
    { model_id: 'claude-sonnet-5-5', provider_name: 'Paid', input: 2, output: 10, cache_read: null, cache_write: null, currency: 'USD', read_on: '2026-10-21' },
  ]
  const saved = [{ model_id: 'claude-sonnet-5-5', input: 3, output: 15, currency: 'USD' }]
  render(
    <UsagePage project={project} projects={[project]} onLoad={onLoad} onOpen={vi.fn()} providers={[provider({})]} prices={saved} cataloguePrices={catalogue} onPrice={onPrice} onRemovePrice={onRemovePrice} />,
  )
  await screen.findByRole('table', { name: 'Usage by provider and model' })
  const prices = within(screen.getByRole('region', { name: 'Prices' }))
  // the catalogue's, to start from: in use until the user saves their own
  expect(prices.getByLabelText('Input price of claude-haiku-5-5')).toHaveValue('0.1')
  expect(prices.getByLabelText('Currency of claude-haiku-5-5')).toHaveValue('USD')
  expect(prices.getByText('models.dev’s price (21 Oct), used until you save your own.')).toBeInTheDocument()
  await userEvent.clear(prices.getByLabelText('Input price of claude-haiku-5-5'))
  await userEvent.type(prices.getByLabelText('Input price of claude-haiku-5-5'), '0.2')
  await userEvent.click(prices.getByRole('button', { name: 'Save the price of claude-haiku-5-5' }))
  expect(onPrice).toHaveBeenCalledWith({ model_id: 'claude-haiku-5-5', input: 0.2, output: 0.5, currency: 'USD', cache_read: 0.01 })
  // the user's own wins, and the catalogue's is one click away
  expect(prices.getByText('Your price is used. models.dev’s (21 Oct): 2 / 10 USD.')).toBeInTheDocument()
  await userEvent.click(prices.getByRole('button', { name: 'Use models.dev’s price for claude-sonnet-5-5' }))
  expect(onRemovePrice).toHaveBeenCalledWith('claude-sonnet-5-5')
})
