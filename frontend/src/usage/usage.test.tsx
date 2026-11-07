import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Project, Usage } from '../api/types'
import { since } from './period'
import { UsagePage } from './UsagePage'

const project = { id: 'p', name: 'demo' } as Project
const other = { id: 'q', name: 'elsewhere' } as Project

const usage: Usage = {
  by_model: [
    { provider_name: 'Paid', model_id: 'claude-haiku-5-5', runs: 2, agents: 3, input_tokens: 1200000, output_tokens: 4500, cache_read_tokens: null, cache_write_tokens: null, unknown_agents: 0, cost: { amount: 1.2345678, currency: 'USD' } },
    { provider_name: 'Local', model_id: 'C:/models/qwen.gguf', runs: 1, agents: 2, input_tokens: 800, output_tokens: null, cache_read_tokens: null, cache_write_tokens: null, unknown_agents: 1, cost: null },
    { provider_name: 'Copilot', model_id: null, runs: 1, agents: 2, input_tokens: null, output_tokens: null, cache_read_tokens: null, cache_write_tokens: null, unknown_agents: 2, cost: null },
  ],
  by_conversation: [
    { conversation_id: 'c1', project_id: 'p', title: 'Fix greeting', runs: 3, agents: 5, input_tokens: 1200800, output_tokens: 4500, cache_read_tokens: null, cache_write_tokens: null, unknown_agents: 3 },
    { conversation_id: 'c2', project_id: 'q', title: 'Another', runs: 1, agents: 1, input_tokens: null, output_tokens: null, cache_read_tokens: null, cache_write_tokens: null, unknown_agents: 1 },
  ],
  by_start: [
    { started_by: 'user', runs: 3, agents: 5, input_tokens: 1200800, output_tokens: 4500, cache_read_tokens: null, cache_write_tokens: null, unknown_agents: 3, cost: { amount: 1.2345678, currency: 'USD', at_least: true } },
    { started_by: 'trigger', runs: 1, agents: 1, input_tokens: null, output_tokens: null, cache_read_tokens: null, cache_write_tokens: null, unknown_agents: 1, cost: null },
  ],
}
const cells = (row: HTMLElement) => within(row).getAllByRole('cell').map(cell => cell.textContent)

test('three tables say what was reported: what is not known is "–", never a zero, and money only where there is a price', async () => {
  const onLoad = vi.fn().mockResolvedValue(usage)
  const onOpen = vi.fn()
  render(<UsagePage project={project} projects={[project, other]} onLoad={onLoad} onOpen={onOpen} />)
  const models = within(await screen.findByRole('table', { name: 'Usage by provider and model' }))
  expect(cells(models.getByRole('row', { name: /Paid · claude-haiku-5-5/ }))).toEqual(['2', '3', '1,200,000', '4,500', '≈ 1.2346 USD'])
  // A model server's id is shown by its file's name; a part that is not known says so.
  const local = models.getByRole('row', { name: /Local · qwen/ })
  expect(cells(local)).toEqual(['1', '2', '800', '–', '–'])
  expect(within(local).getByText('1 agent reported nothing or only part')).toBeInTheDocument()
  const silent = models.getByRole('row', { name: /Copilot · model unknown/ })
  expect(cells(silent)).toEqual(['1', '2', '–', '–', '–'])
  expect(within(silent).getByText('2 agents reported nothing or only part')).toBeInTheDocument()
  expect(screen.getByText(/from the prices you entered\. Cache reads and writes are counted at the cache prices you gave, and not at all without them/)).toBeInTheDocument()

  // Every conversation is opened from its row (slice 86a: opened, its folder is the one open); one of another project is named.
  const talks = within(screen.getByRole('table', { name: 'Usage by conversation' }))
  expect(talks.getAllByRole('columnheader').map(h => h.textContent)).toEqual(['Conversation', 'Messages', 'Agents', 'Tokens sent', 'Tokens written'])
  await userEvent.click(talks.getByRole('button', { name: 'Fix greeting' }))
  expect(onOpen).toHaveBeenCalledWith('c1')
  expect(talks.getByRole('row', { name: /Another · elsewhere/ })).toBeInTheDocument()
  await userEvent.click(talks.getByRole('button', { name: 'Another' }))
  expect(onOpen).toHaveBeenCalledWith('c2')

  const starts = within(screen.getByRole('table', { name: 'Usage by who sent the message' }))
  expect(cells(starts.getByRole('row', { name: /^You/ }))).toEqual(['3', '5', '1,200,800', '4,500', '≥ 1.2346 USD'])
  expect(cells(starts.getByRole('row', { name: /^A trigger, with nobody watching/ }))).toEqual(['1', '1', '–', '–', '–'])
})

test('what KOLONİ asked a model with no message is a row of its own, KOLONİ itself, with its tokens and cost (K-56)', async () => {
  const itself = { started_by: 'koloni' as const, runs: 0, agents: 2, input_tokens: 900, output_tokens: 40, cache_read_tokens: null, cache_write_tokens: null, unknown_agents: 0, cost: { amount: 0.01, currency: 'USD' } }
  render(<UsagePage project={project} projects={[project]} onLoad={vi.fn().mockResolvedValue({ ...usage, by_start: [...usage.by_start, itself] })} onOpen={vi.fn()} />)
  const starts = within(await screen.findByRole('table', { name: 'Usage by who sent the message' }))
  // Its requests are no agents: said under its name, not in the Agents column, nor in the box on top.
  const row = starts.getByRole('row', { name: /^KOLONİ itself/ })
  expect(cells(row)).toEqual(['0', '—', '900', '40', '≈ 0.01 USD'])
  expect(within(row).getByText('2 requests of its own, in no message')).toBeInTheDocument()
  expect(screen.getByText('6 agents')).toBeInTheDocument()
  // In no message: counted by its requests where the others are by their messages.
  expect(screen.getByText('3 messages by you · 1 message by a trigger · 2 requests by KOLONİ itself')).toBeInTheDocument()
})

test('it starts on this project and Today, and reads again when either is changed', async () => {
  const onLoad = vi.fn().mockResolvedValue({ by_model: [], by_conversation: [], by_start: [] })
  render(<UsagePage project={project} projects={[project]} onLoad={onLoad} onOpen={vi.fn()} />)
  expect(await screen.findByText('No agent reported usage today.')).toBeInTheDocument()
  expect(screen.getByLabelText('Projects')).toHaveValue('this')
  expect(within(screen.getByLabelText('Period')).getAllByRole('option').map(o => o.textContent)).toEqual(['Today', '7 days', '30 days', 'All'])
  expect(screen.getByLabelText('Period')).toHaveValue('today')
  expect(onLoad).toHaveBeenLastCalledWith('p', since('today'))
  await userEvent.selectOptions(screen.getByLabelText('Projects'), 'All projects')
  expect(onLoad).toHaveBeenLastCalledWith(null, expect.any(String))
  await userEvent.selectOptions(screen.getByLabelText('Period'), 'All')
  expect(onLoad).toHaveBeenLastCalledWith(null, null)
  expect(await screen.findByText('No agent ran in this period.')).toBeInTheDocument()
})

test('a period starts at a moment: today at this day’s midnight here, the others so many days back', () => {
  const now = new Date(2026, 9, 11, 15, 30)
  expect(since('today', now)).toBe(new Date(2026, 9, 11).toISOString())
  expect(since('7', now)).toBe(new Date(2026, 9, 4, 15, 30).toISOString())
  expect(since('30', now)).toBe(new Date(now.getTime() - 30 * 86400000).toISOString())
  expect(since('all', now)).toBeNull()
})

test('a reading that fails says why', async () => {
  render(<UsagePage project={project} projects={[project]} onLoad={vi.fn().mockRejectedValue({ detail: 'the server is away' })} onOpen={vi.fn()} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('the server is away')
})

test('a cost over agents that are unknown is "at least", and an amount that is no number is a dash', async () => {
  const [paid, local] = usage.by_model
  const by_model = [
    { ...paid, unknown_agents: 1, cost: { amount: 0.42, currency: 'USD', at_least: true } },
    // What a price too big to add up with was answered as, before prices had a bound.
    { ...local, cost: { amount: null as unknown as number, currency: 'USD' } },
  ]
  render(<UsagePage project={project} projects={[project]} onLoad={vi.fn().mockResolvedValue({ ...usage, by_model })} onOpen={vi.fn()} />)
  const models = within(await screen.findByRole('table', { name: 'Usage by provider and model' }))
  expect(cells(models.getByRole('row', { name: /Paid/ })).at(-1)).toBe('≥ 0.42 USD')
  expect(cells(models.getByRole('row', { name: /Local/ })).at(-1)).toBe('–')
  expect(screen.getByText(/“≥” means an agent in the row reported nothing or only part/)).toBeInTheDocument()
})

test('after a reading that failed, the table read before is not left under the new period', async () => {
  const onLoad = vi.fn().mockResolvedValueOnce(usage).mockRejectedValueOnce({ detail: 'the server is away' })
  render(<UsagePage project={project} projects={[project]} onLoad={onLoad} onOpen={vi.fn()} />)
  expect(await screen.findByRole('table', { name: 'Usage by provider and model' })).toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('Period'), '30 days')
  expect(await screen.findByRole('alert')).toHaveTextContent('the server is away')
  expect(screen.queryByRole('table')).not.toBeInTheDocument()
  expect(screen.queryByText('Reading the usage…')).not.toBeInTheDocument()
})

test('what was read again from a cache and written to it is told on a row where it is known, and nothing where it is not', async () => {
  const [paid, local, silent] = usage.by_model
  const by_model = [
    { ...paid, cache_read_tokens: 400000, cache_write_tokens: 500000 },
    // An OpenAI-compatible server says what it read from its cache, and nothing of what it wrote.
    { ...local, cache_read_tokens: 64 },
    silent,
  ]
  const by_conversation = [{ ...usage.by_conversation[0], cache_read_tokens: 400064, cache_write_tokens: 500000 }, usage.by_conversation[1]]
  const by_start = [{ ...usage.by_start[0], cache_read_tokens: 0, cache_write_tokens: 0 }, usage.by_start[1]]
  render(<UsagePage project={project} projects={[project]} onLoad={vi.fn().mockResolvedValue({ by_model, by_conversation, by_start })} onOpen={vi.fn()} />)
  const models = within(await screen.findByRole('table', { name: 'Usage by provider and model' }))
  expect(within(models.getByRole('row', { name: /Paid/ })).getByText('400,000 read again from the cache · 500,000 written to it')).toBeInTheDocument()
  expect(within(models.getByRole('row', { name: /Local/ })).getByText('64 read again from the cache')).toBeInTheDocument()
  // nobody said: no line at all, and never a zero
  expect(models.getByRole('row', { name: /Copilot/ })).not.toHaveTextContent(/cache/)
  // the numbers sent are as they were: the cache is told beside them, not as a column
  expect(cells(models.getByRole('row', { name: /Paid/ }))).toEqual(['2', '3', '1,200,000', '4,500', '≈ 1.2346 USD'])
  const talks = within(screen.getByRole('table', { name: 'Usage by conversation' }))
  expect(within(talks.getByRole('row', { name: /Fix greeting/ })).getByText('400,064 read again from the cache · 500,000 written to it')).toBeInTheDocument()
  expect(talks.getByRole('row', { name: /Another/ })).not.toHaveTextContent(/cache/)
  const starts = within(screen.getByRole('table', { name: 'Usage by who sent the message' }))
  // a zero the provider said is a zero
  expect(within(starts.getByRole('row', { name: /^You/ })).getByText('0 read again from the cache · 0 written to it')).toBeInTheDocument()
  expect(starts.getByRole('row', { name: /^A trigger/ })).not.toHaveTextContent(/cache/)
})

test('a cost that leaves out cache tokens without a price says so and points at Prices', async () => {
  const [paid, local] = usage.by_model
  const by_model = [
    { ...paid, cache_read_tokens: 400000, cache_write_tokens: 500000, cost: { amount: 1.88, currency: 'USD', at_least: true, cache_unpriced: true } },
    { ...local, cost: { amount: 0.5, currency: 'USD' } },
  ]
  render(<UsagePage project={project} projects={[project]} onLoad={vi.fn().mockResolvedValue({ ...usage, by_model })} onOpen={vi.fn()} />)
  const models = within(await screen.findByRole('table', { name: 'Usage by provider and model' }))
  const row = models.getByRole('row', { name: /Paid/ })
  expect(cells(row).at(-1)).toBe('≥ 1.88 USD')
  expect(within(row).getByText('Cache tokens without a price are left out of the cost.')).toBeInTheDocument()
  expect(models.getByRole('row', { name: /Local/ })).not.toHaveTextContent(/left out/)
})

test('the advice to give a price is said once on the page: beside the Cost box', async () => {
  const [paid] = usage.by_model
  const by_model = [{ ...paid, cache_read_tokens: 400000, cost: { amount: 1.88, currency: 'USD', at_least: true, cache_unpriced: true } }]
  const budget = { budget: 12, currency: 'USD', spent: 2, share: 0.17, warn: false, over: false, at_least: false, unpriced_runs: 2 }
  render(<UsagePage project={project} projects={[project]} onLoad={vi.fn().mockResolvedValue({ ...usage, by_model })} onOpen={vi.fn()} budget={budget} onPrice={vi.fn()} onRemovePrice={vi.fn()} />)
  await screen.findByRole('table', { name: 'Usage by provider and model' })
  expect(box('Cost')).toEqual(['≥ 1.88 USD', 'of what is priced · set prices'])
  expect(screen.getAllByRole('button', { name: 'set prices' })).toHaveLength(1)
  expect(document.body).not.toHaveTextContent(/under Prices|give (it|them|the model) (one|a price)/i)
})

test('Today, of this project, has the day beside the boxes; another period or every project has not', async () => {
  render(<UsagePage project={project} projects={[project]} onLoad={vi.fn().mockResolvedValue(usage)} onOpen={vi.fn()} today={<p>the day</p>} />)
  await screen.findByRole('table', { name: 'Usage by provider and model' })
  expect(screen.getByText('the day')).toBeInTheDocument()
  // The boxes the usage adds up stay: the day adds only what it alone knows.
  expect(box('Messages')).toEqual(['4', '6 agents'])
  await userEvent.selectOptions(screen.getByLabelText('Period'), '7 days')
  expect(screen.queryByText('the day')).toBeNull()
  await userEvent.selectOptions(screen.getByLabelText('Period'), 'Today')
  expect(screen.getByText('the day')).toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('Projects'), 'All projects')
  expect(screen.queryByText('the day')).toBeNull()
})

// --- slice 38d, 60a: the boxes on top and the tables' order -------------------------------------

/** The box on top called so: its number, then the lines under it. */
const box = (label: string) =>
  Array.from(within(document.querySelector<HTMLElement>('.usage-stats')!).getByText(label, { selector: 'dt' }).parentElement!.querySelectorAll('dd'), dd => dd.textContent)

test('the boxes on top add up the rows by model: "≥" with how many rows are not fully known said under it, "–" where none is', async () => {
  render(<UsagePage project={project} projects={[project]} onLoad={vi.fn().mockResolvedValue(usage)} onOpen={vi.fn()} />)
  await screen.findByRole('table', { name: 'Usage by provider and model' })
  // Turns and agents of the rows by who started them: each turn once.
  expect(box('Messages')).toEqual(['4', '6 agents'])
  // Local's 800 is of agents of which one reported nothing; Copilot's is unknown. Nothing said of a cache: no line.
  expect(box('Tokens sent')).toEqual(['≥ 1,200,800', '2 of 3 rows not fully known'])
  expect(box('Tokens written')).toEqual(['≥ 4,500', '2 of 3 rows not fully known'])
  // Only what has a price is costed: the rows without one are not unknown, they are left out.
  expect(box('Cost')).toEqual(['≈ 1.2346 USD', 'of what is priced'])
  expect(document.querySelector('.usage-stats')).not.toHaveTextContent(/\b0\b/)
})

test('rows all reported add up to a plain total, a zero a provider said is 0, and amounts in two currencies are not added together', async () => {
  const [paid] = usage.by_model
  const by_model = [
    { ...paid, cache_read_tokens: 0, cache_write_tokens: 10, cost: { amount: 1, currency: 'USD' } },
    { ...paid, model_id: 'other', input_tokens: 800, output_tokens: 500, cache_read_tokens: 0, cache_write_tokens: 5, cost: { amount: 0.5, currency: 'USD', at_least: true } },
    { ...paid, model_id: 'euro', input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0, cost: { amount: 2, currency: 'EUR' } },
  ]
  render(<UsagePage project={project} projects={[project]} onLoad={vi.fn().mockResolvedValue({ ...usage, by_model })} onOpen={vi.fn()} />)
  await screen.findByRole('table', { name: 'Usage by provider and model' })
  expect(box('Tokens sent')).toEqual(['1,200,800', '0 read from the cache · 15 written to the cache'])
  expect(box('Tokens written')).toEqual(['5,000'])
  // "≥" on the part it belongs to
  expect(box('Cost')).toEqual(['≥ 1.50 USD + ≈ 2.00 EUR', 'of what is priced'])
})

test('with nothing reported and nothing priced each box says "–", never a zero, and where a price is written', async () => {
  const silent = usage.by_model[2]
  render(<UsagePage project={project} projects={[project]} onLoad={vi.fn().mockResolvedValue({ ...usage, by_model: [silent] })} onOpen={vi.fn()} />)
  await screen.findByRole('table', { name: 'Usage by provider and model' })
  expect(box('Tokens sent')).toEqual(['–'])
  expect(box('Tokens written')).toEqual(['–'])
  expect(box('Cost')).toEqual(['–', 'no price set'])
})

test('"set prices" opens the folded Prices and moves there; the folded sections count what they hold', async () => {
  const prices = [{ model_id: 'claude-haiku-5-5', currency: 'USD', input: 1, output: 2 }]
  const silent = usage.by_model[2]
  render(
    <UsagePage project={project} projects={[project, other]} onLoad={vi.fn().mockResolvedValue({ ...usage, by_model: [silent] })} onOpen={vi.fn()} prices={prices} onPrice={vi.fn()} onRemovePrice={vi.fn()} />,
  )
  await screen.findByRole('table', { name: 'Usage by provider and model' })
  const fold = (name: string) => screen.getByRole('region', { name }).querySelector('details')!
  // Open: the table by model. Folded: the others, each with its count.
  expect(fold('By conversation')).not.toHaveAttribute('open')
  expect(fold('By conversation').querySelector('summary')).toHaveTextContent('By conversation2 conversations')
  expect(fold('Who started it').querySelector('summary')).toHaveTextContent('Who started it3 messages by you · 1 message by a trigger')
  expect(fold('Prices').querySelector('summary')).toHaveTextContent('Prices1 model · 1 priced')
  expect(fold('Prices')).not.toHaveAttribute('open')
  // A price is set, for a model that did not run here: nothing is priced yet, not "no price".
  expect(box('Cost')).toEqual(['–', 'nothing priced yet · set prices'])
  await userEvent.click(screen.getByRole('button', { name: 'set prices' }))
  expect(fold('Prices')).toHaveAttribute('open')
  expect(fold('Prices').querySelector('summary')).toHaveFocus()
})

test('a period with nothing in it has no boxes on top; how the page counts is folded, closed, all of it there', async () => {
  render(<UsagePage project={project} projects={[project]} onLoad={vi.fn().mockResolvedValue({ by_model: [], by_conversation: [], by_start: [] })} onOpen={vi.fn()} />)
  expect(await screen.findByText('No agent reported usage today.')).toBeInTheDocument()
  expect(document.querySelector('.usage-stats')).toBeNull()
  const how = screen.getByText('How this works').closest('details')!
  expect(how).not.toHaveAttribute('open')
  expect(how).toHaveTextContent('Nothing is estimated: what was not reported shows as “–”, and an agent from before totals were kept has no total of what it sent.')
})

test('a column is sorted by its heading: the bigger first, a second click the other way, and what is unknown last both ways', async () => {
  render(<UsagePage project={project} projects={[project]} onLoad={vi.fn().mockResolvedValue(usage)} onOpen={vi.fn()} />)
  const table = await screen.findByRole('table', { name: 'Usage by provider and model' })
  const order = () => within(table).getAllByRole('rowheader').map(h => h.textContent!.split(' · ')[0])
  const heading = (name: string) => within(table).getByRole('columnheader', { name })
  // As read, until a heading is clicked.
  expect(order()).toEqual(['Paid', 'Local', 'Copilot'])
  expect(within(table).getAllByRole('columnheader').filter(h => h.hasAttribute('aria-sort'))).toEqual([])
  await userEvent.click(within(table).getByRole('button', { name: 'Tokens sent' }))
  expect(order()).toEqual(['Paid', 'Local', 'Copilot'])
  expect(heading('Tokens sent')).toHaveAttribute('aria-sort', 'descending')
  await userEvent.click(within(table).getByRole('button', { name: 'Tokens sent' }))
  expect(order()).toEqual(['Local', 'Paid', 'Copilot'])
  expect(heading('Tokens sent')).toHaveAttribute('aria-sort', 'ascending')
  // Names from A, and the cost: only the one priced has a number.
  await userEvent.click(within(table).getByRole('button', { name: 'Provider and model' }))
  expect(order()).toEqual(['Copilot', 'Local', 'Paid'])
  expect(heading('Provider and model')).toHaveAttribute('aria-sort', 'ascending')
  expect(heading('Tokens sent')).not.toHaveAttribute('aria-sort')
  await userEvent.click(within(table).getByRole('button', { name: 'Cost' }))
  expect(order()[0]).toBe('Paid')
  await userEvent.click(within(table).getByRole('button', { name: 'Cost' }))
  expect(order()[0]).toBe('Paid')
  // The other tables sort the same way, each by itself.
  const talks = screen.getByRole('table', { name: 'Usage by conversation' })
  await userEvent.click(within(talks).getByRole('button', { name: 'Tokens written' }))
  expect(within(talks).getAllByRole('rowheader').map(h => h.textContent)).toEqual(['Fix greeting3 agents reported nothing or only part', 'Another · another project1 agent reported nothing or only part'])
  expect(order()[0]).toBe('Paid')
})

test('a model with a price whose cost is not known makes the cost "at least", in its currency only', async () => {
  const [paid, , silent] = usage.by_model
  const by_model = [
    { ...paid, cost: { amount: 1, currency: 'USD' } },
    { ...paid, model_id: 'euro', cost: { amount: 2, currency: 'EUR' } },
    // priced, but nothing it used was reported: its cost is not known
    { ...silent, model_id: 'priced-silent' },
  ]
  const prices = [{ model_id: 'priced-silent', currency: 'EUR', input: 1, output: 2 }]
  render(<UsagePage project={project} projects={[project]} onLoad={vi.fn().mockResolvedValue({ ...usage, by_model })} onOpen={vi.fn()} prices={prices} />)
  await screen.findByRole('table', { name: 'Usage by provider and model' })
  expect(box('Cost')).toEqual(['≈ 1.00 USD + ≥ 2.00 EUR', 'of what is priced'])
})

test('a cost is sorted by its currency, then its amount', async () => {
  const [paid] = usage.by_model
  const by_model = [
    { ...paid, provider_name: 'A', cost: { amount: 5, currency: 'USD' } },
    { ...paid, provider_name: 'B', cost: { amount: 9, currency: 'EUR' } },
    { ...paid, provider_name: 'C', cost: { amount: 2, currency: 'USD' } },
  ]
  render(<UsagePage project={project} projects={[project]} onLoad={vi.fn().mockResolvedValue({ ...usage, by_model })} onOpen={vi.fn()} />)
  const table = await screen.findByRole('table', { name: 'Usage by provider and model' })
  const order = () => within(table).getAllByRole('rowheader').map(h => h.textContent!.split(' · ')[0])
  await userEvent.click(within(table).getByRole('button', { name: 'Cost' }))
  expect(order()).toEqual(['A', 'C', 'B'])
  await userEvent.click(within(table).getByRole('button', { name: 'Cost' }))
  expect(order()).toEqual(['B', 'C', 'A'])
})

test('in a plain chat every folder’s usage is shown, and a plain chat’s row says "No folder"', async () => {
  const plain = { ...usage.by_conversation[1], conversation_id: 'c3', project_id: null, title: 'What is a CRDT?' }
  const onLoad = vi.fn().mockResolvedValue({ ...usage, by_conversation: [...usage.by_conversation, plain] })
  render(<UsagePage project={null} projects={[project, other]} onLoad={onLoad} onOpen={() => {}} />)
  const talks = within(await screen.findByRole('table', { name: 'Usage by conversation' }))
  expect(onLoad.mock.calls[0][0]).toBeNull()
  expect(screen.getByLabelText('Projects')).toHaveValue('all')
  expect(within(screen.getByLabelText('Projects')).getAllByRole('option').map(o => o.textContent)).toEqual(['All projects'])
  expect(talks.getByRole('row', { name: /What is a CRDT\? · No folder/ })).toBeInTheDocument()
  expect(talks.getByRole('row', { name: /Fix greeting · demo/ })).toBeInTheDocument()
})
