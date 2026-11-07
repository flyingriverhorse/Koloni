import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Limits, ModelFacts, Provider, Tiers, Usage } from '../api/types'
import { readingOf } from './cards'
import { ModelsPage } from './ModelsPage'

// Slice 81a: the Models page as cards with gauges, the tiers' order under them, a provider in a window.

const provider = (over: Partial<Provider>): Provider => ({
  id: 'p1',
  name: 'Local',
  kind: 'openai_compat',
  base_url: 'http://127.0.0.1:8080/v1',
  default_model: null,
  executable: null,
  mode: null,
  options: null,
  for_agents: false,
  note: null,
  models: [],
  only_listed: false,
  max_running: null, plan: false, step_down_at: null, day_limit: null, month_limit: null,
  has_key: false,
  position: 0,
  created_at: 't',
  updated_at: 't',
  ...over,
})
const claude = provider({ id: 'cc', name: 'Claude Code', kind: 'claude_cli', base_url: null })
const codex = provider({ id: 'cx', name: 'Codex', kind: 'codex_cli', base_url: null })
const deepseek = provider({ id: 'ds', name: 'DeepSeek', base_url: 'https://api.deepseek.com', has_key: true })
const handlers = () => ({
  onCreate: vi.fn().mockResolvedValue(undefined),
  onSave: vi.fn().mockResolvedValue(undefined),
  onDelete: vi.fn().mockResolvedValue(undefined),
  onTest: vi.fn().mockResolvedValue({ ok: true, model_id: 'qwen', tools_supported: true, error: null }),
})
const window_ = (minutes: number, used: number | null, stale = false): Limits['windows'][number] => ({
  name: null,
  minutes,
  used_percent: used,
  resets_at: null,
  stale,
})
const limits = (windows: Limits['windows']): Limits => ({ unknown: null, read_at: null, source: null, plan: null, windows, credits: null })
const row = (provider_name: string, model_id: string, amount: number | null): Usage['by_model'][number] => ({
  provider_name,
  provider_id: ({ Local: 'p1', DeepSeek: 'ds' } as Record<string, string>)[provider_name] ?? null,
  model_id,
  runs: 2,
  agents: 2,
  input_tokens: 1000,
  output_tokens: 500,
  cache_read_tokens: null,
  cache_write_tokens: null,
  unknown_agents: 0,
  cost: amount === null ? null : { amount, currency: 'USD' },
})

test('a gauge says only what is known: what is left of a plan’s narrowest window, an API key’s spend today, a server’s state', () => {
  // The window with the least left, whatever its length (81c): Claude Code's week, Codex's week here too.
  expect(readingOf(claude, { limits: limits([window_(300, 9), window_(10080, 42)]) })).toEqual({
    share: 0.58,
    value: '58%',
    label: 'left this week',
    more: '5 hours 91% left',
  })
  expect(readingOf(codex, { limits: limits([window_(10080, 70), window_(300, 18)]) })).toMatchObject({ value: '30%', label: 'left this week' })
  // A stale one or one not said is never shown as a number.
  expect(readingOf(codex, { limits: limits([window_(300, 18, true), window_(10080, 70)]) })).toMatchObject({ value: '30%', more: '5 hours –' })
  expect(readingOf(claude, { limits: limits([window_(10080, null)]) })).toEqual({ share: null, value: '–', label: 'plan use not known' })
  expect(readingOf(claude, { limits: null })).toEqual({ share: null, value: '–', label: 'plan use not known' })
  expect(readingOf(claude, {}).value).toBe('…')
  // Why it is not known, in short (slice 81a-2).
  const unknown = (why: string): Limits => ({ ...limits([]), unknown: why })
  const notRun = unknown('not run yet: Claude Code says its limits in its runs, and none has said them yet')
  expect(readingOf(claude, { limits: notRun }).label).toBe('Known after its first run here')
  expect(readingOf(codex, { limits: unknown('not read yet') }).label).toBe('Not read yet')
  // A reading that failed just now: the last one kept, and why under it; with none kept, why alone.
  expect(readingOf(codex, { limits: { ...limits([window_(300, 18)]), failed: 'Codex did not answer' } })).toMatchObject({
    label: 'left of 5 hours',
    failed: 'not read now: Codex did not answer',
  })
  expect(readingOf(codex, { limits: { ...unknown('not read yet'), failed: 'refused' } }).label).toBe('Could not be read: refused')
  expect(readingOf(codex, { limits: unknown('Codex did not answer within 15 seconds') }).label).toBe('Codex did not answer within 15 seconds')
  // An API key: what it spent today, by the record; nothing on record is none, a cost not known is a dash.
  const today = [row('DeepSeek', 'deepseek-chat', 1.25), row('DeepSeek', 'deepseek-reasoner', 0.6), row('Other', 'x', 9)]
  // (No arc without a daily limit: its amount stands in the gauge's place; with one, the gauge fills to it.)
  expect(readingOf(deepseek, { today })).toEqual({ share: null, value: '$1.85', label: 'today', plain: true })
  expect(readingOf({ ...deepseek, day_limit: 5 }, { today })).toEqual({ share: 0.37, value: '$1.85 / $5', label: 'today' })
  expect(readingOf(deepseek, { today: [] }).value).toBe('$0')
  expect(readingOf(deepseek, { today: [row('DeepSeek', 'deepseek-chat', null)] }).value).toBe('–')
  expect(readingOf(deepseek, { today: [...today, row('DeepSeek', 'other', null)] }).value).toBe('≥ $1.85')
  // Matched by the provider, not its name: another provider of the same name is not its.
  expect(readingOf(deepseek, { today: [{ ...row('DeepSeek', 'deepseek-chat', 3), provider_id: 'gone' }] }).value).toBe('$0')
  // A key that is a plan counts no money.
  expect(readingOf({ ...deepseek, plan: true }, { today })).toEqual({ share: null, value: 'plan', label: 'no money counted', plain: true })
  // Its quota last seen used up (its 429): when, here - the time today, else the date too; what is left is never said.
  const usedUp = (read_at: string) => ({ today, limits: { ...limits([]), read_at, used_up: true } })
  const now = new Date().toISOString()
  const clock = new Date(now).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  expect(readingOf({ ...deepseek, plan: true }, usedUp(now))).toEqual({ share: null, value: 'plan', label: `quota used up, seen ${clock}`, plain: true })
  const before = new Date('2026-09-24T11:02:00Z').toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  expect(readingOf({ ...deepseek, plan: true }, usedUp('2026-09-24T11:02:00Z')).label).toBe(`quota used up, seen ${before}`)
  expect(readingOf({ ...deepseek, plan: true }, { today, limits: limits([]) }).label).toBe('no money counted')
  expect(readingOf(deepseek, { today: null }).value).toBe('–')
  // A server on this machine: running, or not and why.
  const answered = { installed: null, models: [{ name: 'qwen', state: 'usable', why: null }] } as never
  expect(readingOf(provider({}), { avail: answered })).toEqual({ share: 1, value: 'on', label: 'running' })
  const silent = { installed: null, models: [{ name: 'qwen', state: 'unknown', why: 'unreachable' }] } as never
  expect(readingOf(provider({}), { avail: silent })).toEqual({ share: 0, value: 'off', label: 'not answering' })
})

test('each card says its kind, the default and its models by tier; the last one adds a provider', async () => {
  const tiered = provider({
    models: [
      { name: 'big', note: null, tier: 'strongest', agents: true },
      { name: 'small', note: null, tier: 'fast', agents: true },
      { name: 'other', note: null, tier: null, agents: true },
    ],
  })
  const onLimits = vi.fn().mockResolvedValue(limits([window_(10080, 42)]))
  render(<ModelsPage providers={[tiered, claude, deepseek]} {...handlers()} onLimits={onLimits} onUsage={vi.fn().mockResolvedValue({ by_model: [], by_conversation: [], by_start: [] })} />)
  const local = screen.getByRole('button', { name: /^Local/ })
  expect(local).toHaveTextContent(/this machine · default/)
  expect(local).toHaveTextContent(/1 strongest\s*1 fast\s*of 3 models/)
  expect(await screen.findByRole('button', { name: /Claude Code.*subscription.*58%.*left this week/ })).toBeInTheDocument()
  expect(await screen.findByRole('button', { name: /DeepSeek.*API key.*\$0.*today/ })).toBeInTheDocument()
  // Never asked afresh: that would start Codex.
  expect(onLimits.mock.calls).toEqual([['cc', false]])
  await userEvent.click(screen.getByRole('button', { name: /Add a provider/ }))
  const dialog = screen.getByRole('dialog', { name: 'Add a provider' })
  expect(within(dialog).getByLabelText('Kind')).toBeEnabled()
  expect(within(dialog).queryByRole('tab')).not.toBeInTheDocument()
})

test('Codex’s card reads its plan afresh on its own button, as the Usage page’s Check now does; only it and Claude Code’s do (87)', async () => {
  const { ApiError } = await import('../api/client')
  let fails = false
  const onLimits = vi.fn(async (_id: string, afresh: boolean) => {
    if (fails) throw new ApiError(500, 'Codex is gone')
    return afresh ? limits([window_(300, 18)]) : { ...limits([]), unknown: 'not read yet' }
  })
  render(<ModelsPage providers={[codex, claude, deepseek]} {...handlers()} onLimits={onLimits} />)
  const card = await screen.findByRole('button', { name: /^Codex.*Not read yet/ })
  const read = screen.getByRole('button', { name: 'Read Codex’s plan now' })
  expect(screen.getAllByRole('button', { name: /plan now$/ }).map(button => button.getAttribute('aria-label'))).toEqual(['Read Codex’s plan now', 'Read Claude Code’s plan now'])
  await userEvent.click(read)
  await waitFor(() => expect(card).toHaveTextContent(/82%\s*left of 5 hours/))
  expect(onLimits.mock.calls.filter(([, afresh]) => afresh)).toEqual([['cx', true]])
  // Reading it is not opening it.
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  // A read that fails keeps the last one, and says why.
  fails = true
  await userEvent.click(read)
  await waitFor(() => expect(card).toHaveTextContent(/82%\s*left of 5 hours\s*not read now: Codex is gone/))
})

test('each card is busy on its own: one Read now ending leaves another’s going, and that one is not started twice', async () => {
  const pending: Record<string, (told: Limits) => void> = {}
  const onLimits = vi.fn((id: string, afresh: boolean) =>
    afresh ? new Promise<Limits>(done => (pending[id] = done)) : Promise.resolve({ ...limits([]), unknown: 'not read yet' }),
  )
  render(<ModelsPage providers={[codex, claude]} {...handlers()} onLimits={onLimits} />)
  const codexRead = await screen.findByRole('button', { name: 'Read Codex’s plan now' })
  const claudeRead = screen.getByRole('button', { name: 'Read Claude Code’s plan now' })
  await userEvent.click(codexRead)
  await userEvent.click(claudeRead)
  expect(codexRead).toBeDisabled()
  expect(claudeRead).toBeDisabled()
  pending.cc(limits([window_(300, 18)]))
  await waitFor(() => expect(claudeRead).toBeEnabled())
  expect(codexRead).toBeDisabled()
  // A second click while it reads starts nothing: Claude Code's would be a second paid turn.
  fireEvent.click(codexRead)
  expect(onLimits.mock.calls.filter(([, afresh]) => afresh)).toEqual([['cx', true], ['cc', true]])
  pending.cx(limits([window_(300, 18)]))
  await waitFor(() => expect(codexRead).toBeEnabled())
})

const tiers = (): Tiers => ({
  strongest: [
    { provider_id: 'p1', provider_name: 'Local', model: 'big', agents: true },
    { provider_id: 'cc', provider_name: 'Claude Code', model: 'opus', agents: true },
    { provider_id: 'ds', provider_name: 'DeepSeek', model: 'deep', agents: true },
  ],
  balanced: [],
  fast: [{ provider_id: 'cc', provider_name: 'Claude Code', model: 'haiku', agents: true }],
})
const names = (tier: string) => within(screen.getByRole('region', { name: tier })).getAllByRole('listitem').map(item => item.textContent)

test('a tier’s models are moved by their arrows and by dragging, and each order is saved at once', async () => {
  const onSaveTiers = vi.fn(async (order: Tiers) => order)
  const onTiers = vi.fn().mockResolvedValue(tiers())
  render(<ModelsPage providers={[provider({}), claude, deepseek]} {...handlers()} onTiers={onTiers} onSaveTiers={onSaveTiers} />)
  expect(await screen.findByText('big')).toBeInTheDocument()
  expect(names('Strongest')).toEqual(['1bigLocal', '2opusClaude Code', '3deepDeepSeek'])
  expect(screen.getByRole('button', { name: 'Move big up' })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: 'Move big down' }))
  expect(names('Strongest')).toEqual(['1opusClaude Code', '2bigLocal', '3deepDeepSeek'])
  expect(onSaveTiers).toHaveBeenLastCalledWith({ ...tiers(), strongest: [tiers().strongest[1], tiers().strongest[0], tiers().strongest[2]] })
  // deep dragged onto the first place
  const items = within(screen.getByRole('region', { name: 'Strongest' })).getAllByRole('listitem')
  fireEvent.dragStart(items[2])
  fireEvent.dragOver(items[0])
  fireEvent.drop(items[0])
  await waitFor(() => expect(names('Strongest')).toEqual(['1deepDeepSeek', '2opusClaude Code', '3bigLocal']))
  expect(onSaveTiers).toHaveBeenCalledTimes(2)
  // Not into another tier: the tier is set on the provider.
  const fast = within(screen.getByRole('region', { name: 'Fast' })).getAllByRole('listitem')
  fireEvent.dragStart(fast[0])
  fireEvent.drop(screen.getAllByRole('listitem')[0])
  expect(onSaveTiers).toHaveBeenCalledTimes(2)
})

test('an order that is refused goes back as it was and says why', async () => {
  const { ApiError } = await import('../api/client')
  const onSaveTiers = vi.fn().mockRejectedValue(new ApiError(422, 'the strongest list has to be exactly the models whose tier is strongest, each once'))
  const onTiers = vi.fn().mockResolvedValue(tiers())
  render(<ModelsPage providers={[provider({}), claude, deepseek]} {...handlers()} onTiers={onTiers} onSaveTiers={onSaveTiers} />)
  await userEvent.click(await screen.findByRole('button', { name: 'Move opus up' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(/exactly the models whose tier is strongest/)
  expect(names('Strongest')[0]).toBe('1bigLocal')
  // and the tiers are read again, as they are now
  await waitFor(() => expect(onTiers).toHaveBeenCalledTimes(2))
})

test('a tier that cannot be read says so in a line; a model moved to an end keeps the keyboard', async () => {
  const { ApiError } = await import('../api/client')
  const { unmount } = render(
    <ModelsPage providers={[provider({})]} {...handlers()} onTiers={vi.fn().mockRejectedValue(new ApiError(500, 'the server broke'))} onSaveTiers={vi.fn()} />,
  )
  expect(await screen.findByRole('alert')).toHaveTextContent('The tiers could not be read: the server broke')
  unmount()
  render(<ModelsPage providers={[provider({}), claude, deepseek]} {...handlers()} onTiers={vi.fn().mockResolvedValue(tiers())} onSaveTiers={vi.fn(async (order: Tiers) => order)} />)
  await userEvent.click(await screen.findByRole('button', { name: 'Move opus up' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Move opus down' })).toHaveFocus())
  // (opus, big, deep: big goes to the end)
  await userEvent.click(screen.getByRole('button', { name: 'Move big down' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Move big up' })).toHaveFocus())
})

test('a model whose provider does not run now is faded and said off', async () => {
  const onAvailability = vi.fn(async (id: string) =>
    id === 'p1' ? { installed: null, models: [{ name: 'big', state: 'unusable', why: 'unreachable' }] } : { installed: true, models: [] },
  ) as never
  render(<ModelsPage providers={[provider({}), claude, deepseek]} {...handlers()} onAvailability={onAvailability} onTiers={vi.fn().mockResolvedValue(tiers())} onSaveTiers={vi.fn()} />)
  const big = (await screen.findByText('big')).closest('li')!
  await waitFor(() => expect(big).toHaveClass('tier-item-down'))
  // As it looked when this page read it: said, and passed over by a pick (see the Hint).
  expect(big).toHaveTextContent('Local · not answering')
  expect(screen.getByText('opus').closest('li')).not.toHaveClass('tier-item-down')
})

test('with no model in any tier the slots say so in one calm line, and the red box is gone', async () => {
  const empty = { strongest: [], balanced: [], fast: [] }
  render(
    <ModelsPage providers={[provider({})]} {...handlers()} onTiers={vi.fn().mockResolvedValue(empty)} onSaveTiers={vi.fn()} onFillAll={vi.fn()} onSaveFillAll={vi.fn()} />,
  )
  expect(await screen.findByText('No model has a tier yet. Fill the tiers from the catalogue')).toBeInTheDocument()
  expect(screen.queryByText(/so the Orchestrator cannot pick one/)).not.toBeInTheDocument()
  expect(screen.queryByText('How this works')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Fill tiers' })).toBeInTheDocument()
})

test('the head’s Fill tiers opens the preview in a window, also once models have tiers; Escape leaves it', async () => {
  const onFillAll = vi.fn().mockResolvedValue({ providers: [{ id: 'p1', name: 'Local', kind: 'openai_compat', catalogued: false, for_agents: true, models: [] }], notes: {} })
  render(<ModelsPage providers={[provider({ models: [{ name: 'q', note: null, tier: 'fast', agents: true }] })]} {...handlers()} onFillAll={onFillAll} onSaveFillAll={vi.fn()} />)
  const button = screen.getByRole('button', { name: 'Fill tiers' })
  await userEvent.click(button)
  const preview = screen.getByRole('dialog', { name: 'Tiers from the catalogue' })
  expect(within(preview).getByRole('heading', { name: 'Tiers from the catalogue' })).toHaveFocus()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Fill tiers' })).toHaveFocus()
})

const facts = (more: Partial<ModelFacts>): ModelFacts => ({
  efforts: null,
  context_window: null,
  max_output: null,
  price: null,
  tier: null,
  deprecated: null,
  sources: {},
  catalogue_date: null,
  failed: false,
  inputs: [],
  ...more,
})

test('a provider opens in a window with its Models, Connection and Limits; Escape closes it', async () => {
  const listed = provider({ models: [{ name: 'big', note: null, tier: 'strongest', agents: true }] })
  render(<ModelsPage providers={[listed]} {...handlers()} />)
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  const card = screen.getByRole('button', { name: /^Local/ })
  await userEvent.click(card)
  const dialog = screen.getByRole('dialog', { name: 'Local' })
  expect(within(dialog).getByRole('tab', { name: 'Models' })).toHaveAttribute('aria-selected', 'true')
  expect(within(dialog).getByRole('table', { name: 'Models agents and you can pick' })).toBeVisible()
  expect(within(dialog).getByLabelText('Address')).not.toBeVisible()
  await userEvent.click(within(dialog).getByRole('tab', { name: 'Connection' }))
  expect(within(dialog).getByLabelText('Address')).toBeVisible()
  expect(within(dialog).queryByRole('table', { name: 'Models agents and you can pick' })).not.toBeInTheDocument()
  // The arrows move along the tabs.
  await userEvent.keyboard('{ArrowRight}')
  expect(within(dialog).getByRole('tab', { name: 'Limits' })).toHaveFocus()
  expect(within(dialog).getByText(/spends no money and has no plan: there is nothing to limit/)).toBeVisible()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(card).toHaveFocus()
})

test('a Save draws the form anew on the tab it was on, and Escape still closes the window', async () => {
  const h = handlers()
  const { rerender } = render(<ModelsPage providers={[provider({})]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: /^Local/ }))
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  await userEvent.clear(screen.getByLabelText('Address'))
  await userEvent.type(screen.getByLabelText('Address'), 'http://127.0.0.1:8081/v1')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenCalledWith('p1', expect.objectContaining({ base_url: 'http://127.0.0.1:8081/v1' }))
  rerender(<ModelsPage providers={[provider({ base_url: 'http://127.0.0.1:8081/v1', updated_at: 't2' })]} {...h} />)
  expect(screen.getByRole('tab', { name: 'Connection' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByLabelText('Address')).toBeVisible()
  // (The Save button the focus was on is gone: Escape is heard all the same.)
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

test('a model’s row unfolds to every fact known of it, each with where it came from, its note and its use', async () => {
  const listed = provider({ models: [{ name: 'big', note: 'mine', tier: 'strongest', agents: true }, { name: 'old', note: null, tier: null, agents: true }] })
  const onFacts = vi.fn(async (_id: string, model: string) =>
    model === 'big'
      ? facts({
          efforts: ['low', 'medium', 'high'],
          context_window: 1000000,
          max_output: 64000,
          price: { input: 3, output: 15, currency: 'USD', cache_read: 0.3, cache_write: null },
          sources: { efforts: 'server', context_window: 'models.dev', max_output: 'models.dev', price: 'you' },
          catalogue_date: '2026-10-21',
        })
      : facts({}),
  )
  const month = { by_model: [row('Local', 'big', null)], by_conversation: [], by_start: [] }
  render(<ModelsPage providers={[listed]} {...handlers()} onFacts={onFacts} onUsage={vi.fn().mockResolvedValue(month)} />)
  await userEvent.click(screen.getByRole('button', { name: /^Local/ }))
  const table = screen.getByRole('table', { name: 'Models agents and you can pick' })
  const [, first, second] = within(table).getAllByRole('row')
  // The table: tier, window, output, levels, price; the model without a tier last, faded.
  await waitFor(() => expect(first).toHaveTextContent('1M64kLow–High3 / 15'))
  expect(second).toHaveClass('model-untiered')
  expect(second).toHaveTextContent('––––')
  await userEvent.click(within(table).getByRole('button', { name: 'What is known of big' }))
  const known = table.querySelector('.model-facts')!
  expect(known).toHaveTextContent('Context window1,000,000 tokensfrom models.dev, 21 Oct')
  expect(known).toHaveTextContent('Max output64,000 tokensfrom models.dev, 21 Oct')
  expect(known).toHaveTextContent('Thinking levelsLow, Medium, Highfrom the server')
  expect(known).toHaveTextContent('Price in / out (1M)3 / 15 USD, cache read 0.3set by you')
  expect(known).toHaveTextContent('Known tier–')
  expect(known).toHaveTextContent('Used in 30 days2 messages, 1,500 tokens')
  expect(within(table).getByLabelText('Note of big')).toHaveValue('mine')
})

test('Find again has the server asked again and the facts read again; a CLI’s model has none (77)', async () => {
  const { api } = await import('../api/client')
  const post = vi.spyOn(api, 'post').mockResolvedValue(undefined as never)
  let window = 32768
  const onFacts = vi.fn(async () => facts({ context_window: window, sources: { context_window: 'server' } }))
  const listed = provider({ models: [{ name: 'qwen', note: null, tier: 'fast', agents: true }] })
  const cli = provider({ ...claude, models: [{ name: 'sonnet', note: null, tier: 'fast', agents: true }] })
  render(<ModelsPage providers={[listed, cli]} {...handlers()} onFacts={onFacts} />)
  await userEvent.click(screen.getByRole('button', { name: /^Local/ }))
  await userEvent.click(screen.getByRole('button', { name: 'What is known of qwen' }))
  const known = document.querySelector('.model-facts')!
  await waitFor(() => expect(known).toHaveTextContent('Context window32,768 tokens'))
  window = 80128 // llama-server restarted with another -c
  await userEvent.click(within(known as HTMLElement).getByRole('button', { name: 'Find again' }))
  expect(post).toHaveBeenCalledWith('/providers/p1/find-again')
  await waitFor(() => expect(known).toHaveTextContent('Context window80,128 tokens'))
  await userEvent.click(screen.getByRole('button', { name: /^Claude Code/ }))
  await userEvent.click(screen.getByRole('button', { name: 'What is known of sonnet' }))
  expect(within(document.querySelector('.model-facts') as HTMLElement).queryByRole('button', { name: 'Find again' })).not.toBeInTheDocument()
  post.mockRestore()
})

test('a tier that is not the catalogue’s is marked “you”; the catalogue’s, as a fill saved it, is not', async () => {
  const listed = provider({ models: [{ name: 'mine', note: null, tier: 'strongest', agents: true }, { name: 'filled', note: null, tier: 'fast', agents: true }] })
  const onFacts = vi.fn(async (_id: string, model: string) =>
    model === 'mine' ? facts({ tier: 'strongest', sources: { tier: 'you' } }) : facts({ tier: 'fast', sources: { tier: 'catalog' } }),
  )
  render(<ModelsPage providers={[listed]} {...handlers()} onFacts={onFacts} />)
  await userEvent.click(screen.getByRole('button', { name: /^Local/ }))
  const table = screen.getByRole('table', { name: 'Models agents and you can pick' })
  const [, mine, filled] = within(table).getAllByRole('row')
  await waitFor(() => expect(within(mine).getByTitle('Set by you, not the catalogue’s')).toHaveTextContent('you'))
  expect(within(filled).queryByTitle('Set by you, not the catalogue’s')).toBeNull()
  // Changed here, before it is saved: yours too.
  await userEvent.selectOptions(within(filled).getByLabelText('Tier of filled'), 'balanced')
  expect(within(filled).getByTitle('Set by you, not the catalogue’s')).toBeInTheDocument()
})

test('the Models tab is read first: a tier or agents switched is saved at once and said; a model is named only when added', async () => {
  const h = handlers()
  const listed = provider({
    for_agents: true,
    models: [
      { name: 'big', note: 'mine', tier: 'strongest', agents: true },
      { name: 'old', note: null, tier: null, agents: false },
    ],
  })
  render(<ModelsPage providers={[listed]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: /^Local/ }))
  const dialog = screen.getByRole('dialog', { name: 'Local' })
  // No textbox for a saved model's name; its tier and whether agents may use it are the quick edits.
  expect(within(dialog).queryByRole('textbox')).not.toBeInTheDocument()
  expect(within(dialog).getByRole('switch', { name: 'Agents may use big' })).toBeChecked()
  expect(within(dialog).getByRole('switch', { name: 'Agents may use old' })).not.toBeChecked()
  await userEvent.selectOptions(within(dialog).getByLabelText('Tier of old'), 'fast')
  expect(h.onSave).toHaveBeenLastCalledWith('p1', {
    models: [
      { name: 'big', note: 'mine', tier: 'strongest', agents: true },
      { name: 'old', note: null, tier: 'fast', agents: false },
    ],
  })
  expect(await within(dialog).findByText('old: fast.')).toBeInTheDocument()
  await userEvent.click(within(dialog).getByRole('switch', { name: 'Agents may use big' }))
  expect(h.onSave.mock.lastCall![1].models[0]).toEqual({ name: 'big', note: 'mine', tier: 'strongest', agents: false })
  expect(await within(dialog).findByText('Agents may not use big now.')).toBeInTheDocument()
  // Added by name, inline: Enter adds and saves; a name already there is refused, nothing saved.
  await userEvent.click(within(dialog).getByRole('button', { name: 'Add a model' }))
  await userEvent.type(within(dialog).getByLabelText('New model’s name'), 'big{Enter}')
  expect(within(dialog).getByRole('alert')).toHaveTextContent('big is on the list already.')
  const saves = h.onSave.mock.calls.length
  await userEvent.clear(within(dialog).getByLabelText('New model’s name'))
  await userEvent.type(within(dialog).getByLabelText('New model’s name'), 'fresh{Enter}')
  expect(h.onSave).toHaveBeenCalledTimes(saves + 1)
  expect(h.onSave.mock.lastCall![1].models.at(-1)).toEqual({ name: 'fresh', note: null, tier: null, agents: false })
  expect(within(dialog).queryByLabelText('New model’s name')).not.toBeInTheDocument()
  // The provider's own settings are on Connection, saved there without the models.
  expect(within(dialog).getByLabelText('Never run a model that is not on this list')).not.toBeVisible()
  expect(within(dialog).queryByLabelText('Agents may choose this')).not.toBeInTheDocument()
  await userEvent.click(within(dialog).getByRole('tab', { name: 'Connection' }))
  await userEvent.type(within(dialog).getByLabelText('What it is good for'), 'Local work.')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
  expect(h.onSave.mock.lastCall![1]).toEqual(expect.objectContaining({ note: 'Local work.' }))
  expect(h.onSave.mock.lastCall![1]).not.toHaveProperty('models')
  expect(within(dialog).getByRole('button', { name: 'Delete provider' })).toBeVisible()
})

test('a model agents may not use keeps its place in its tier, faded and said so', async () => {
  const off = tiers()
  off.strongest[1] = { ...off.strongest[1], agents: false }
  render(<ModelsPage providers={[provider({}), claude, deepseek]} {...handlers()} onTiers={vi.fn().mockResolvedValue(off)} onSaveTiers={vi.fn()} />)
  const opus = (await screen.findByText('opus')).closest('li')!
  expect(opus).toHaveClass('tier-item-down')
  expect(opus).toHaveTextContent('Claude Code · off for agents')
  expect(names('Strongest')[1]).toMatch(/^2opus/)
})

test('a tier shows its first five; the rest on "+N more", their arrows working, and a model moved past five stays in sight', async () => {
  const many = tiers()
  many.strongest = ['m1', 'm2', 'm3', 'm4', 'm5', 'm6', 'm7'].map(model => ({ provider_id: 'p1', provider_name: 'Local', model, agents: true }))
  const onSaveTiers = vi.fn(async (order: Tiers) => order)
  render(<ModelsPage providers={[provider({})]} {...handlers()} onTiers={vi.fn().mockResolvedValue(many)} onSaveTiers={onSaveTiers} />)
  const slot = await screen.findByRole('region', { name: 'Strongest' })
  expect(names('Strongest')).toHaveLength(5)
  await userEvent.click(within(slot).getByRole('button', { name: '+2 more' }))
  expect(names('Strongest')).toHaveLength(7)
  await userEvent.click(within(slot).getByRole('button', { name: 'Move m7 up' }))
  expect(onSaveTiers.mock.lastCall![0].strongest.map(one => one.model)).toEqual(['m1', 'm2', 'm3', 'm4', 'm5', 'm7', 'm6'])
  await userEvent.click(within(slot).getByRole('button', { name: 'Show fewer' }))
  expect(names('Strongest')).toHaveLength(5)
  // The fifth moved down: it is sixth now, and shown with the rest.
  await userEvent.click(within(slot).getByRole('button', { name: 'Move m5 down' }))
  await waitFor(() => expect(names('Strongest')).toHaveLength(7))
  expect(names('Strongest')[5]).toMatch(/^6m5/)
  expect(within(slot).getByRole('button', { name: 'Show fewer' })).toHaveAttribute('aria-expanded', 'true')
})

test('a provider’s models from before 81a, its agents off, read off in its window and in the slots alike', async () => {
  // (The rows as the API gives them after migration 0064: each says what its provider said.)
  const old = provider({ for_agents: false, models: [{ name: 'big', note: null, tier: 'strongest', agents: false }] })
  const off = { ...tiers(), strongest: [{ provider_id: 'p1', provider_name: 'Local', model: 'big', agents: false }] }
  render(<ModelsPage providers={[old]} {...handlers()} onTiers={vi.fn().mockResolvedValue(off)} onSaveTiers={vi.fn()} />)
  expect((await screen.findByText('big')).closest('li')).toHaveTextContent('Local · off for agents')
  await userEvent.click(screen.getByRole('button', { name: /^Local/ }))
  expect(screen.getByRole('switch', { name: 'Agents may use big' })).not.toBeChecked()
})

test('a change the Models tab saves keeps what is typed on Connection and not saved yet', async () => {
  const h = handlers()
  const listed = (updated_at: string) => provider({ for_agents: true, updated_at, models: [{ name: 'big', note: null, tier: null, agents: true }] })
  const { rerender } = render(<ModelsPage providers={[listed('t')]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: /^Local/ }))
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  await userEvent.type(screen.getByLabelText('What it is good for'), 'not saved yet')
  await userEvent.click(screen.getByRole('tab', { name: 'Models' }))
  await userEvent.selectOptions(screen.getByLabelText('Tier of big'), 'fast')
  rerender(<ModelsPage providers={[{ ...listed('t2'), models: [{ name: 'big', note: null, tier: 'fast', agents: true }] }]} {...h} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  expect(screen.getByLabelText('What it is good for')).toHaveValue('not saved yet')
})


test('a provider with no list says itself whether agents may use it, on Connection', async () => {
  const h = handlers()
  render(<ModelsPage providers={[provider({ for_agents: false })]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: /^Local/ }))
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  await userEvent.click(screen.getByRole('switch', { name: 'Agents may use this provider' }))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenLastCalledWith('p1', expect.objectContaining({ for_agents: true }))
  // with a list, each model says it in its row instead
  const listed = provider({ id: 'p2', name: 'Listed', models: [{ name: 'big', note: null, tier: null, agents: true }] })
  render(<ModelsPage providers={[listed]} {...handlers()} picked="p2" />)
  expect(screen.getAllByRole('switch', { name: 'Agents may use this provider', hidden: true })).toHaveLength(1)
})

test('closing the window asks before what is typed and not saved is thrown away', async () => {
  const ask = vi.spyOn(window, 'confirm')
  const asked = () => screen.queryByRole('alertdialog', { name: 'Close without saving what you typed?' })
  render(<ModelsPage providers={[provider({})]} {...handlers()} />)
  await userEvent.click(screen.getByRole('button', { name: /^Local/ }))
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  await userEvent.type(screen.getByLabelText('What it is good for'), 'typed')
  await userEvent.keyboard('{Escape}')
  expect(asked()).toBeInTheDocument()
  await userEvent.keyboard('{Escape}')
  expect(asked()).toBeNull()
  expect(screen.getByLabelText('What it is good for')).toHaveValue('typed')
  await userEvent.click(screen.getByRole('button', { name: 'Close' }))
  await userEvent.click(screen.getByRole('button', { name: 'Close without saving' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(ask).not.toHaveBeenCalled()
  ask.mockRestore()
})

test('a model change that fails shows the provider as last saved, and why', async () => {
  const { ApiError } = await import('../api/client')
  const h = { ...handlers(), onSave: vi.fn().mockRejectedValue(new ApiError(422, 'refused')) }
  render(<ModelsPage providers={[provider({ for_agents: true, models: [{ name: 'big', note: null, tier: null, agents: true }] })]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: /^Local/ }))
  await userEvent.selectOptions(screen.getByLabelText('Tier of big'), 'fast')
  expect(await screen.findByRole('alert')).toHaveTextContent('refused')
  expect(screen.getByLabelText('Tier of big')).toHaveValue('')
})

test("a plan key's card says when its quota was last seen used up, read as it is", async () => {
  const plan = { ...deepseek, id: 'ab', name: 'Alibaba', plan: true }
  const seen = new Date().toISOString()
  const onLimits = vi.fn().mockResolvedValue({ ...limits([]), read_at: seen, used_up: true })
  render(<ModelsPage providers={[plan, deepseek]} {...handlers()} onLimits={onLimits} />)
  expect(await screen.findByRole('button', { name: /Alibaba.*API key.*plan.*quota used up, seen/ })).toBeInTheDocument()
  // Only the plan key's last reading is looked up: a key that pays is asked nothing.
  expect(onLimits.mock.calls).toEqual([['ab', false]])
})
