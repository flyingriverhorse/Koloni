import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Provider } from '../api/types'
import { ModelNameInput } from './ModelNameInput'
import { ModelsPage } from './ModelsPage'

const provider = (over: Partial<Provider>): Provider => ({
  id: 'p1',
  name: 'Local',
  kind: 'openai_compat',
  base_url: 'http://127.0.0.1:8080/v1',
  default_model: null,
  executable: null,
  mode: null,
  options: null,
  for_agents: true,
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
const claude = provider({
  id: 'p2',
  name: 'Claude Code',
  kind: 'claude_cli',
  base_url: null,
  mode: 'step',
  for_agents: false,
  position: 1,
})

const handlers = () => ({
  onCreate: vi.fn().mockResolvedValue(undefined),
  onSave: vi.fn().mockResolvedValue(undefined),
  onDelete: vi.fn().mockResolvedValue(undefined),
  onTest: vi.fn().mockResolvedValue({ ok: true, model_id: 'qwen', tools_supported: true, error: null }),
})

async function openClaude(h = handlers(), saved: Partial<Provider> = {}) {
  render(<ModelsPage providers={[provider({}), { ...claude, ...saved }]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: /Claude Code/ }))
  return h
}

const connection = () => userEvent.click(screen.getByRole('tab', { name: 'Connection' }))

test('each model says whether agents may use it, and a switch is saved at once', async () => {
  const h = handlers()
  render(
    <ModelsPage
      providers={[provider({ models: [{ name: 'qwen', note: null, tier: null, agents: true }] }), { ...claude, models: [{ name: 'haiku', note: null, tier: null, agents: true }] }]}
      {...h}
    />,
  )
  // the model server on this machine comes ticked; a CLI does not
  await userEvent.click(screen.getByRole('button', { name: /^Local/ }))
  expect(screen.getByRole('switch', { name: 'Agents may use qwen' })).toBeChecked()
  await userEvent.click(screen.getByRole('button', { name: 'Close' }))
  await userEvent.click(screen.getByRole('button', { name: /Claude Code/ }))
  const tick = screen.getByRole('switch', { name: 'Agents may use haiku' })
  expect(tick).not.toBeChecked()
  // (there is no tick for the whole provider: it follows its models)
  expect(screen.queryByLabelText('Agents may choose this')).not.toBeInTheDocument()
  await userEvent.click(tick)
  expect(h.onSave).toHaveBeenLastCalledWith('p2', { models: [{ name: 'haiku', note: null, tier: null, agents: true }] })
  expect(await screen.findByText('Agents may use haiku now.')).toBeInTheDocument()
})

test('what it is good for is the user’s own line, counted up to 300', async () => {
  const h = await openClaude()
  await connection()
  const note = screen.getByLabelText('What it is good for')
  expect(note).toHaveAttribute('maxLength', '300')
  expect(screen.getByText('0 / 300')).toBeInTheDocument()
  await userEvent.type(note, 'Strongest; hard debugging.')
  expect(screen.getByText('26 / 300')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenLastCalledWith('p2', expect.objectContaining({ note: 'Strongest; hard debugging.' }))
  // nothing else about the guide was touched, so nothing else is sent
  const sent = h.onSave.mock.lastCall![1]
  expect('models' in sent || 'for_agents' in sent || 'only_listed' in sent).toBe(false)
})

test('models are added with a short note and removed again, each saved at once', async () => {
  const h = await openClaude(handlers(), { models: [{ name: 'haiku', note: 'quick', tier: null, agents: true }] })
  // (where the list comes from is behind ⓘ beside its buttons)
  const list = screen.getByRole('tabpanel', { name: 'Models' })
  expect(within(list).getByText(/^Your own list, kept with this provider/)).not.toBeVisible()
  // the name is read, not typed over
  expect(within(list).getByText('haiku')).toBeInTheDocument()
  expect(within(list).queryByRole('textbox')).not.toBeInTheDocument()
  // the note is in the row unfolded
  await userEvent.click(within(list).getByRole('button', { name: 'What is known of haiku' }))
  expect(within(list).getByLabelText('Note of haiku')).toHaveValue('quick')
  // a model with no name is not added
  await userEvent.click(within(list).getByRole('button', { name: 'Add a model' }))
  await userEvent.click(within(list).getByRole('button', { name: 'Add' }))
  expect(within(list).getByRole('alert')).toHaveTextContent('A model needs its name')
  expect(h.onSave).not.toHaveBeenCalled()
  await userEvent.type(within(list).getByLabelText('New model’s name'), 'opus{Enter}')
  // (a model added is not for agents while none of the others is: Claude Code is not ticked)
  expect(h.onSave).toHaveBeenLastCalledWith('p2', {
    // (a model has no tier until one is given)
    models: [
      { name: 'haiku', note: 'quick', tier: null, agents: false },
      { name: 'opus', note: null, tier: null, agents: false },
    ],
  })
  await userEvent.click(within(list).getByRole('button', { name: 'What is known of opus' }))
  await userEvent.type(within(list).getByLabelText('Note of opus'), 'slow, best')
  await userEvent.tab()
  expect(h.onSave.mock.lastCall![1].models[1]).toEqual({ name: 'opus', note: 'slow, best', tier: null, agents: false })
  await userEvent.click(within(list).getByRole('button', { name: 'Remove haiku' }))
  expect(h.onSave.mock.lastCall![1].models).toEqual([{ name: 'opus', note: 'slow, best', tier: null, agents: false }])
})

test('a model is given a tier at once, and it is kept when something else of the row is changed', async () => {
  const h = await openClaude(handlers(), {
    models: [
      { name: 'haiku', note: 'quick', tier: 'fast', agents: true },
      { name: 'opus', note: null, tier: null, agents: true },
    ],
  })
  expect(screen.getByLabelText('Tier of haiku')).toHaveValue('fast')
  expect(screen.getByLabelText('Tier of opus')).toHaveValue('')
  expect(within(screen.getByLabelText('Tier of opus')).getAllByRole('option').map(o => o.textContent)).toEqual(['no tier', 'fast', 'balanced', 'strongest'])
  expect(screen.getByText(/A model with no tier is only ever picked by name\./)).toBeInTheDocument()
  // nothing touched: nothing of the list is sent with the Connection tab's Save
  await connection()
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect('models' in h.onSave.mock.lastCall![1]).toBe(false)
  await userEvent.click(screen.getByRole('tab', { name: 'Models' }))

  await userEvent.selectOptions(screen.getByLabelText('Tier of opus'), 'strongest')
  expect(h.onSave.mock.lastCall![1].models).toEqual([
    { name: 'haiku', note: 'quick', tier: 'fast', agents: false },
    { name: 'opus', note: null, tier: 'strongest', agents: false },
  ])
  await userEvent.click(screen.getByRole('button', { name: 'What is known of haiku' }))
  await userEvent.type(screen.getByLabelText('Note of haiku'), ', cheap')
  await userEvent.tab()
  expect(h.onSave.mock.lastCall![1].models).toEqual([
    { name: 'haiku', note: 'quick, cheap', tier: 'fast', agents: false },
    { name: 'opus', note: null, tier: 'strongest', agents: false },
  ])
  await userEvent.selectOptions(screen.getByLabelText('Tier of haiku'), '')
  expect(h.onSave.mock.lastCall![1].models[0]).toEqual({ name: 'haiku', note: 'quick, cheap', tier: null, agents: false })
})

test('"Never run a model that is not on this list" needs a list, and goes when the list goes', async () => {
  const h = await openClaude()
  const only = screen.getByLabelText(/Never run a model that is not on this list/)
  expect(only).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: 'Add a model' }))
  expect(only).toBeDisabled() // a name being typed is no list yet
  await userEvent.type(screen.getByLabelText('New model’s name'), 'haiku{Enter}')
  expect(only).toBeEnabled()
  await connection()
  // Why, behind its ⓘ: opened there, it leaves the box as it was (slice 81a-2).
  const label = only.closest('label')!
  await userEvent.click(within(label).getByRole('button', { name: 'About this' }))
  expect(within(label).getByText(/Even a model you pick by hand has to be on the list. So a model your plan does not cover is never sent/)).toBeVisible()
  expect(only).not.toBeChecked()
  await userEvent.click(only)
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenLastCalledWith('p2', expect.objectContaining({ only_listed: true }))
  await userEvent.click(screen.getByRole('tab', { name: 'Models' }))
  await userEvent.click(screen.getByRole('button', { name: 'Remove haiku' }))
  expect(only).toBeDisabled()
  expect(only).not.toBeChecked()
})

test('a new provider is created with its guide', async () => {
  const h = handlers()
  render(<ModelsPage providers={[provider({})]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: /Add a provider/ }))
  await userEvent.type(screen.getByLabelText('Name'), 'Codex')
  await userEvent.selectOptions(screen.getByLabelText('Kind'), 'codex_cli')
  await userEvent.type(screen.getByLabelText('What it is good for'), 'Big refactors.')
  await userEvent.click(screen.getByRole('button', { name: 'Add a model' }))
  await userEvent.type(screen.getByLabelText('New model’s name'), 'gpt-5.5-codex{Enter}')
  // nothing new is for agents until the user says so
  const tick = screen.getByRole('switch', { name: 'Agents may use gpt-5.5-codex' })
  expect(tick).not.toBeChecked()
  await userEvent.click(tick)
  // (nothing is saved before the provider is added)
  expect(h.onSave).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: 'Add provider' }))
  expect(h.onCreate).toHaveBeenCalledWith(
    expect.objectContaining({
      name: 'Codex',
      note: 'Big refactors.',
      models: [{ name: 'gpt-5.5-codex', note: null, tier: null, agents: true }],
    }),
  )
  expect('for_agents' in h.onCreate.mock.lastCall![0]).toBe(false)
})

test('the model a real run reported can be put on the list with one click', async () => {
  const h = handlers()
  h.onTest.mockResolvedValue({ ok: true, model_id: 'claude-haiku-4-5-20251001', tools_supported: true, error: null, reply: 'ok', model_from: null })
  await openClaude(h)
  await connection()
  await userEvent.click(screen.getByRole('button', { name: 'Try a real run' }))
  expect(await screen.findByText(/It answered "ok" · model claude-haiku-4-5-20251001/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Add it to the list' }))
  expect(h.onSave).toHaveBeenLastCalledWith('p2', { models: [{ name: 'claude-haiku-4-5-20251001', note: null, tier: null, agents: false }] })
  expect(screen.queryByRole('button', { name: 'Add it to the list' })).not.toBeInTheDocument()
})

test('a run that could not name its model offers nothing to add, and settings are named as the source', async () => {
  const h = handlers()
  h.onTest.mockResolvedValue({ ok: true, model_id: 'claude default', tools_supported: true, error: null, reply: 'ok', model_from: null })
  await openClaude(h)
  await connection()
  await userEvent.click(screen.getByRole('button', { name: 'Try a real run' }))
  expect(await screen.findByText(/CLI default \(model not reported\)/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Add it to the list' })).not.toBeInTheDocument()
  h.onTest.mockResolvedValue({ ok: true, model_id: 'gpt-5.5-codex', tools_supported: true, error: null, reply: 'ok', model_from: 'settings' })
  await userEvent.click(screen.getByRole('button', { name: 'Try a real run' }))
  expect(await screen.findByText(/model gpt-5\.5-codex \(from Codex's settings\)/)).toBeInTheDocument()
})

test('a picker offers whatever the server says the provider has, the user’s list first', async () => {
  const loadModels = vi.fn().mockResolvedValue({ models: ['mine', 'sonnet', 'haiku'], note: null })
  const { container } = render(
    <ModelNameInput label="Model name" value="" providerId="p2" loadModels={loadModels} onChange={() => {}} />,
  )
  await screen.findByLabelText('Model name')
  await vi.waitFor(() => expect(container.querySelectorAll('datalist option')).toHaveLength(3))
  expect(Array.from(container.querySelectorAll('datalist option')).map(o => o.getAttribute('value'))).toEqual([
    'mine',
    'sonnet',
    'haiku',
  ])
})
