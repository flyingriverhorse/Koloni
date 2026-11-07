import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Effort, ModelFacts, Provider, Role } from '../api/types'
import { AgentsPage } from '../agents/AgentsPage'
import { ModelPicker } from './ModelPicker'
import { ModelsPage } from './ModelsPage'

// Slice 59c: what is known of the model being picked, from one lookup; suggestions for a provider
// not added yet; the catalogue updated only by the user's click.

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
const claude = provider({ id: 'p2', name: 'Claude Code', kind: 'claude_cli', base_url: null, default_model: 'sonnet', position: 1 })
const facts = (efforts: Effort[] | null, more: Partial<ModelFacts> = {}): ModelFacts => ({
  efforts,
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
const pageHandlers = () => ({
  onCreate: vi.fn().mockResolvedValue(undefined),
  onSave: vi.fn().mockResolvedValue(undefined),
  onDelete: vi.fn().mockResolvedValue(undefined),
  onTest: vi.fn().mockResolvedValue({ ok: true, model_id: 'qwen', tools_supported: true, error: null }),
})

test('the picker shows the levels of the model being picked, not of the one saved', async () => {
  const onFacts = vi.fn(async (_id: string, model: string) =>
    model === 'opus' ? facts(['low', 'high'], { deprecated: true }) : facts(['off', 'low', 'medium', 'high']),
  )
  render(<ModelPicker providers={[provider({}), claude]} providerId={null} modelId={null} onSave={vi.fn()} onFacts={onFacts} />)
  await userEvent.click(screen.getByRole('button', { name: /Model: Local/ }))
  expect(await screen.findByText(/Its model takes: Off, Low, Medium, High\./)).toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('Provider'), 'p2')
  await userEvent.type(screen.getByLabelText('Model name'), 'opus')
  expect(await screen.findByText(/Its model takes: Low, High\./)).toBeInTheDocument()
  expect(screen.getByText(/being retired: it still runs/)).toBeInTheDocument()
  expect(onFacts).toHaveBeenLastCalledWith('p2', 'opus')
  // looked up once the name stopped changing, not at each letter
  expect(onFacts.mock.calls.filter(([, model]) => model.startsWith('op'))).toHaveLength(1)
})

test('where the Lead role has a model of its own, the picker shows that model’s levels', async () => {
  const onFacts = vi.fn().mockResolvedValue(facts(['low']))
  render(
    <ModelPicker providers={[provider({}), claude]} providerId={null} modelId={null} onSave={vi.fn()} onFacts={onFacts} lead={{ provider_id: 'p2', model_id: null }} />,
  )
  await userEvent.click(screen.getByRole('button', { name: /Model: Local/ }))
  expect(await screen.findByText(/Its model takes: Low\. Of the Orchestrator role’s own model\./)).toBeInTheDocument()
  expect(onFacts).toHaveBeenLastCalledWith('p2', 'sonnet') // its provider's default model
})

test('a lookup that failed says so; a model that takes none says nothing is sent', async () => {
  const onFacts = vi.fn().mockResolvedValue(facts(null, { failed: true }))
  render(<ModelPicker providers={[provider({})]} providerId={null} modelId={null} onSave={vi.fn()} onFacts={onFacts} />)
  await userEvent.click(screen.getByRole('button', { name: /Model: Local/ }))
  expect(await screen.findByText(/Could not look up the model’s levels\./)).toBeInTheDocument()
  expect(screen.getByLabelText('Thinking')).toBeDisabled()
})

test('the role editor shows the levels of the model picked for the role, before it is saved', async () => {
  const role: Role = {
    id: 'r1', name: 'Coder', description: '', instructions: '', tools: [], builtin: false, created_by_agent: false, models: null,
    provider_id: null, model_id: null, tier: null, tier_min: null, tier_max: null, kind: 'build', enabled: true, teams: [], pick_from: null, max_steps: null, max_tokens: null, effort: null,
    max_effort: null, context_window: null, mcp: [], skills: [], inside_cli: false, knows: [], created_at: 't', updated_at: 't',
  }
  const onFacts = vi.fn().mockResolvedValue(facts(['low', 'medium'], { context_window: 200000, sources: { context_window: 'models.dev' }, catalogue_date: '2026-10-21' }))
  render(
    <AgentsPage roles={[role]} providers={[provider({}), claude]} onFacts={onFacts} onSave={vi.fn()} onCreate={vi.fn()} onDelete={vi.fn()} onReset={vi.fn()} />,
  )
  await userEvent.click(screen.getByRole('button', { name: /^Coder/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Edit model' }))
  await userEvent.click(screen.getByRole('radio', { name: 'One model' }))
  await userEvent.selectOptions(screen.getByLabelText('Provider'), 'p2')
  expect(await screen.findByText(/Its model takes: Low, Medium\./)).toBeInTheDocument()
  expect(screen.getByText('Found automatically: 200,000 tokens (from models.dev, 21 Oct).')).toBeInTheDocument()
  expect(onFacts).toHaveBeenLastCalledWith('p2', 'sonnet')
})

test('a saved provider’s default model says what is known of it and where from', async () => {
  const onFacts = vi.fn().mockResolvedValue(
    facts(['low', 'high'], {
      context_window: 1048576,
      price: { input: 0.66, output: 1.98, currency: 'USD', cache_read: null, cache_write: null },
      tier: 'strongest',
      deprecated: true,
      // (Another service's word, where the provider's own does not have the model: slice 81a-2.)
      sources: { efforts: 'models.dev', context_window: 'models.dev (deepseek)', price: 'you', tier: 'catalog' },
      catalogue_date: '2026-10-21',
    }),
  )
  render(<ModelsPage providers={[provider({ default_model: 'deepseek-v4-pro' })]} picked="p1" {...pageHandlers()} onFacts={onFacts} />)
  const said = await screen.findByText(/Its model takes: Low, High\./)
  expect(said).toHaveTextContent(
    'Reads 1,048,576 tokens at most, from models.dev (deepseek), 21 Oct · 0.66 / 1.98 USD a million tokens in / out, set by you · strongest, from the catalogue · being retired',
  )
  expect(onFacts).toHaveBeenCalledWith('p1', 'deepseek-v4-pro')
  expect(screen.getByText(/^Offered here: your own list, then the catalogue’s models/)).toBeInTheDocument()
})

test('an OpenAI-compatible provider is offered the known addresses, and a plan’s key at another address is said', async () => {
  const PAYG = 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1'
  const PLAN = 'https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1'
  const addresses = [
    { name: 'Alibaba', api: PAYG },
    { name: 'Alibaba Token Plan (Singapore)', api: PLAN },
  ]
  const onSuggest = vi.fn(async () => ({ models: [], service: null, api: null, env: [], addresses }))
  render(<ModelsPage providers={[provider({})]} picked="new" {...pageHandlers()} onSuggest={onSuggest} />)
  const address = screen.getByLabelText('Address')
  await waitFor(() => expect(address).toHaveAttribute('list'))
  const offered = document.getElementById(address.getAttribute('list')!)!.querySelectorAll('option')
  expect(Array.from(offered, o => [o.value, o.label])).toEqual(addresses.map(a => [a.api, a.name]))
  await userEvent.type(address, PAYG)
  await userEvent.type(screen.getByLabelText('API key'), 'sk-sp-123')
  expect(screen.getByText(/starts with sk-sp-: a plan’s key, which works only at its plan’s address/)).toBeInTheDocument()
  await userEvent.clear(address)
  await userEvent.type(address, PLAN)
  // A plan's key at its plan's address is what it should be.
  expect(screen.queryByText(/a plan’s key/)).toBeNull()
  await userEvent.clear(screen.getByLabelText('API key'))
  await userEvent.type(screen.getByLabelText('API key'), 'sk-123')
  expect(screen.getByText(/Token Plan’s address takes the plan’s own key/)).toBeInTheDocument()
})

test('a provider not added yet is offered the catalogue’s names, its service’s address and key name', async () => {
  const onSuggest = vi.fn(async (_kind: string, base: string | null) =>
    base
      ? { models: ['qwen3.8-max', 'qwen3.7-plus'], service: 'Alibaba', api: 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1', env: ['DASHSCOPE_API_KEY'], addresses: [] }
      : { models: [], service: null, api: null, env: [], addresses: [] },
  )
  render(<ModelsPage providers={[provider({})]} picked="new" {...pageHandlers()} onSuggest={onSuggest} />)
  await userEvent.type(screen.getByLabelText('Address'), 'https://dashscope-intl.aliyuncs.com')
  await userEvent.tab()
  // the address that named only the service is completed; the key is named as its docs name it
  await waitFor(() => expect(screen.getByLabelText('Address')).toHaveValue('https://dashscope-intl.aliyuncs.com/compatible-mode/v1'))
  expect(screen.getByLabelText('API key')).toHaveAttribute('placeholder', 'Your DASHSCOPE_API_KEY')
  expect(screen.getByText(/Alibaba calls its key DASHSCOPE_API_KEY\./)).toBeInTheDocument()
  // the default model and a model being added offer the same names
  const list = screen.getByLabelText('Default model').getAttribute('list')!
  expect(Array.from(document.getElementById(list)!.querySelectorAll('option'), o => o.value)).toEqual(['qwen3.8-max', 'qwen3.7-plus'])
  await userEvent.click(screen.getByRole('button', { name: 'Add a model' }))
  expect(screen.getByLabelText('New model’s name')).toHaveAttribute('list', list)
})

test('the page updates the catalogue only when the button is pressed, and says what it kept', async () => {
  const onUpdateCatalogue = vi
    .fn()
    .mockResolvedValueOnce({ providers: 120, models: 4500, updated_at: '2026-10-21T18:00:00+00:00', local: null, keep_fresh: true })
    .mockRejectedValueOnce(new Error("models.dev's list could not be used; nothing was changed"))
  const onCatalogue = vi.fn().mockResolvedValue({ providers: 6, models: 300, updated_at: '2026-10-20', local: null, keep_fresh: true })
  render(<ModelsPage providers={[provider({})]} {...pageHandlers()} onUpdateCatalogue={onUpdateCatalogue} onCatalogue={onCatalogue} />)
  // The copy read, by its date and count: the shipped one here.
  expect(await screen.findByText('Catalogue: models.dev, 20 Oct · 6 services')).toHaveAttribute('role', 'status')
  expect(onUpdateCatalogue).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: 'Update catalogue' }))
  // After an update it names the updated copy (kalan-isler 1i a), not the shipped one.
  expect(await screen.findByText(/^Catalogue: models\.dev, 21 Oct, \d\d:\d\d · 120 services$/)).toHaveAttribute('role', 'status')
  await userEvent.click(screen.getByRole('button', { name: 'Update catalogue' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(/nothing was changed/)
})

test('a catalog.local.json that is not read says why beside the catalogue', async () => {
  const local = 'catalog.local.json is not read: Expecting value: line 1 column 2 (char 1)'
  const onCatalogue = vi.fn().mockResolvedValue({ providers: 6, models: 300, updated_at: '2026-10-20', local, keep_fresh: true })
  render(<ModelsPage providers={[provider({})]} {...pageHandlers()} onCatalogue={onCatalogue} />)
  expect(await screen.findByRole('alert')).toHaveTextContent(local)
})

test('"Keep the catalogue fresh" is on until the user turns it off, and says so as the server kept it', async () => {
  const shipped = { providers: 6, models: 300, updated_at: '2026-10-20', local: null, keep_fresh: true }
  const onCatalogue = vi.fn().mockResolvedValue(shipped)
  const onKeepFresh = vi.fn().mockResolvedValue({ ...shipped, keep_fresh: false })
  render(<ModelsPage providers={[provider({})]} {...pageHandlers()} onUpdateCatalogue={vi.fn()} onCatalogue={onCatalogue} onKeepFresh={onKeepFresh} />)
  const fresh = await screen.findByRole('checkbox', { name: 'Keep the catalogue fresh' })
  expect(fresh).toBeChecked()
  await userEvent.click(fresh)
  expect(onKeepFresh).toHaveBeenCalledWith(false)
  expect(fresh).not.toBeChecked()
})
