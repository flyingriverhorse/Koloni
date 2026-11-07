import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { Effort, ModelFacts, Provider } from '../api/types'
import { ModelPicker } from './ModelPicker'
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
const api = provider({ id: 'p3', name: 'Claude API', kind: 'anthropic', base_url: 'https://api.anthropic.com', options: null, has_key: true, position: 2 })

/** What the facts endpoint says of a model that takes `efforts` and nothing more. */
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

const handlers = () => ({
  onCreate: vi.fn().mockResolvedValue(undefined),
  onSave: vi.fn().mockResolvedValue(undefined),
  onDelete: vi.fn().mockResolvedValue(undefined),
  onTest: vi.fn().mockResolvedValue({ ok: true, model_id: 'qwen', tools_supported: true, error: null }),
})

/** Opens a provider's window by its card, and one of its tabs. */
async function open(name: string, tab?: 'Connection' | 'Limits') {
  await userEvent.click(screen.getByRole('button', { name: new RegExp(`^${name}`) }))
  if (tab) await userEvent.click(screen.getByRole('tab', { name: tab }))
}
const close = () => userEvent.click(screen.getByRole('button', { name: 'Close' }))

test('the first provider is the default and shows its address', async () => {
  render(<ModelsPage providers={[provider({}), claude]} {...handlers()} />)
  expect(screen.getByRole('button', { name: /Local.*default/ })).toBeInTheDocument()
  await open('Local', 'Connection')
  expect(screen.getByLabelText('Address')).toHaveValue('http://127.0.0.1:8080/v1')
  expect(screen.queryByLabelText('Path to the command')).not.toBeInTheDocument()
})

test('a CLI provider has a path instead of an address and key, and says what it costs', async () => {
  render(<ModelsPage providers={[provider({}), claude]} {...handlers()} />)
  await open('Claude Code', 'Connection')
  expect(screen.getByLabelText('Path to the command')).toBeInTheDocument()
  expect(screen.queryByLabelText('Address')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('API key')).not.toBeInTheDocument()
  expect(screen.getByText(/Its own tools are switched off/)).toBeInTheDocument()
  expect(screen.getByText(/no key is needed, and its use counts against your plan/)).toBeInTheDocument()
})

test('a stored key is never shown; typing replaces it and leaving it empty keeps it', async () => {
  const h = handlers()
  render(<ModelsPage providers={[provider({}), api]} {...h} />)
  await open('Claude API', 'Connection')
  const key = screen.getByLabelText('API key')
  expect(key).toHaveValue('')
  expect(key).toHaveAttribute('type', 'password')
  expect(screen.getByText(/A key is saved/)).toBeInTheDocument()
  expect(screen.getByText(/kept in plain text/)).toBeInTheDocument()
  await userEvent.type(screen.getByLabelText('Default model'), 'claude-sonnet-5-5')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenCalledWith('p3', {
    name: 'Claude API',
    base_url: 'https://api.anthropic.com',
    default_model: 'claude-sonnet-5-5',
  })
  await userEvent.type(key, 'sk-new')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenLastCalledWith('p3', expect.objectContaining({ api_key: 'sk-new' }))
  await userEvent.click(screen.getByRole('button', { name: 'Remove key' }))
  expect(h.onSave).toHaveBeenLastCalledWith('p3', { api_key: '' })
})

test('a new provider is created with the fields of its kind', async () => {
  const h = handlers()
  render(<ModelsPage providers={[provider({})]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: /Add a provider/ }))
  expect(screen.getByRole('button', { name: 'Add provider' })).toBeDisabled()
  await userEvent.type(screen.getByLabelText('Name'), 'Codex')
  await userEvent.selectOptions(screen.getByLabelText('Kind'), 'codex_cli')
  expect(screen.queryByLabelText('Address')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Add provider' }))
  expect(h.onCreate).toHaveBeenCalledWith({
    name: 'Codex',
    kind: 'codex_cli',
    default_model: '',
    executable: '',
    mode: 'session', // one of the ways with KOLONİ's tools is the default; native is a choice
  })
})

test('Test says what the provider answered, or why it could not be reached', async () => {
  const h = handlers()
  render(<ModelsPage providers={[provider({})]} {...h} />)
  await open('Local', 'Connection')
  await userEvent.click(screen.getByRole('button', { name: 'Test' }))
  expect(await screen.findByText(/Reachable/)).toHaveTextContent('qwen')
  h.onTest.mockResolvedValue({ ok: false, model_id: null, tools_supported: null, error: 'model server unreachable: refused' })
  await userEvent.click(screen.getByRole('button', { name: 'Test' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('refused')
})

test('the last provider cannot be deleted, and a failed save says why', async () => {
  const h = handlers()
  const { rerender } = render(<ModelsPage providers={[provider({})]} {...h} />)
  await open('Local', 'Connection')
  expect(screen.getByRole('button', { name: 'Delete provider' })).toBeDisabled()
  rerender(<ModelsPage providers={[provider({}), claude]} {...h} />)
  h.onSave.mockRejectedValue(new ApiError(409, 'there is already a provider named Claude Code'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('already a provider')
  await userEvent.click(screen.getByRole('button', { name: 'Delete provider' }))
  expect(h.onDelete).toHaveBeenCalledWith('p1')
})

test('the picker shows the current choice and saves a new one', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  const { rerender } = render(
    <ModelPicker providers={[provider({}), claude]} providerId={null} modelId={null} onSave={onSave} />,
  )
  // nothing chosen: the first provider is what a turn would use
  expect(screen.getByRole('button', { name: /Model: Local/ })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /Model: Local/ }))
  await userEvent.selectOptions(screen.getByLabelText('Provider'), 'p2')
  expect(screen.getByLabelText('Model name')).toHaveAttribute('placeholder', 'sonnet')
  await userEvent.type(screen.getByLabelText('Model name'), 'opus')
  await userEvent.click(screen.getByRole('button', { name: 'Use this model' }))
  expect(onSave).toHaveBeenCalledWith({ provider_id: 'p2', model_id: 'opus' })

  rerender(<ModelPicker providers={[provider({}), claude]} providerId="p2" modelId="opus" onSave={onSave} />)
  expect(screen.getByRole('button', { name: /Model: Claude Code · opus/ })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /Model: Claude Code/ }))
  await userEvent.selectOptions(screen.getByLabelText('Provider'), '')
  await userEvent.click(screen.getByRole('button', { name: 'Use this model' }))
  expect(onSave).toHaveBeenLastCalledWith({ provider_id: null, model_id: null })
})

test('K-31: a click elsewhere keeps a pick not saved unless the user lets it go; unchanged, it just closes', async () => {
  // B-337: KOLONİ's own question, never the browser's.
  const confirm = vi.spyOn(window, 'confirm')
  render(<ModelPicker providers={[provider({}), claude]} providerId={null} modelId={null} onSave={vi.fn()} />)
  const form = () => screen.queryByRole('form', { name: 'Model for this conversation' })
  const asked = () => screen.queryByRole('alertdialog', { name: 'Close without saving what you changed?' })
  await userEvent.click(screen.getByRole('button', { name: /Model: Local/ }))
  await userEvent.click(document.body)
  expect(asked()).toBeNull()
  expect(form()).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: /Model: Local/ }))
  await userEvent.selectOptions(screen.getByLabelText('Provider'), 'p2')
  await userEvent.click(document.body)
  expect(asked()).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Close without saving' })).toHaveFocus()
  await userEvent.keyboard('{Escape}')
  expect(asked()).toBeNull()
  expect(screen.getByLabelText('Provider')).toHaveValue('p2')
  await userEvent.click(document.body)
  await userEvent.keyboard('{Enter}')
  expect(form()).toBeNull()
  expect(confirm).not.toHaveBeenCalled()
  confirm.mockRestore()
})

test('B-193: a CLI given no model shows the one KOLONİ names for it, else that its own default runs', () => {
  // (the fixture of tests/test_tiers.py's B-193 test: the same rule on both sides)
  const listed = [
    { name: 'claude-fable', tier: 'strongest' as const, agents: true },
    { name: 'claude-sonnet', tier: 'balanced' as const, agents: true },
    { name: 'claude-haiku', tier: 'fast' as const, agents: true },
  ]
  const cli = provider({ id: 'p2', name: 'Claude Code', kind: 'claude_cli', base_url: null, models: listed })
  const { rerender } = render(<ModelPicker providers={[cli]} providerId={null} modelId={null} onSave={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Model: Claude Code · claude-sonnet' })).toBeInTheDocument()
  rerender(<ModelPicker providers={[{ ...cli, models: [listed[0], listed[2]] }]} providerId={null} modelId={null} onSave={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Model: Claude Code · claude-haiku' })).toBeInTheDocument()
  rerender(<ModelPicker providers={[{ ...cli, models: [] }]} providerId={null} modelId={null} onSave={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Model: Claude Code’s own default (unknown model)' })).toBeInTheDocument()
  // (a server's own default is its own: not said so)
  rerender(<ModelPicker providers={[provider({})]} providerId={null} modelId={null} onSave={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Model: Local' })).toBeInTheDocument()
})

test('the Lead’s reasoning level is chosen with the model, of the levels its model takes, and sent only when it changed', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  const onFacts = vi.fn().mockResolvedValue(facts(['medium', 'high']))
  render(<ModelPicker providers={[provider({ default_model: 'qwen' })]} providerId={null} modelId={null} leadEffort="high" onSave={onSave} onFacts={onFacts} />)
  await userEvent.click(screen.getByRole('button', { name: /Model: Local/ }))
  expect(await screen.findByText(/Its model takes: Medium, High\./)).toBeInTheDocument()
  expect(onFacts).toHaveBeenLastCalledWith('p1', 'qwen') // the default provider's default model
  expect(screen.getAllByRole('option', { name: /Medium|High|Low|Max/ }).map(o => o.textContent)).toEqual(['Medium', 'High'])
  expect(screen.getByLabelText('Thinking')).toHaveValue('high')
  await userEvent.click(screen.getByRole('button', { name: 'Use this model' }))
  expect(onSave).toHaveBeenLastCalledWith({ provider_id: null, model_id: null })
  await userEvent.click(screen.getByRole('button', { name: /Model: Local/ }))
  await userEvent.selectOptions(screen.getByLabelText('Thinking'), 'Default')
  await userEvent.click(screen.getByRole('button', { name: 'Use this model' }))
  expect(onSave).toHaveBeenLastCalledWith({ provider_id: null, model_id: null, lead_effort: null })
})

test('the lead’s model can follow the message: the choice says what it costs, and only a change of it is sent', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  const { rerender } = render(<ModelPicker providers={[provider({}), claude]} providerId={null} modelId={null} onSave={onSave} />)
  await userEvent.click(screen.getByRole('button', { name: /Model: Local/ }))
  const auto = screen.getByLabelText(/Orchestrator model: automatic/)
  expect(auto).not.toBeChecked()
  // what it costs, and that the request carries the message
  // and what it overrides, which "A role with its own model keeps" above it does not hold for - both in sight
  const note = screen.getByText(
    /^One more request for each message you send: a fast model of your team guide is sent your message and asked how hard it is\. It overrides the Orchestrator role’s own model and tier\. A trigger’s message does not use it\.$/,
  )
  // (those stand under the box; the rest of the note is behind ⓘ beside it, closed - and opening it is not ticking the box)
  const rest = within(note).getByText(/^The Orchestrator then runs/)
  expect(rest).not.toBeVisible()
  await userEvent.click(within(note).getByRole('button', { name: 'About this' }))
  expect(rest).toBeVisible()
  await userEvent.click(rest)
  expect(auto).not.toBeChecked()
  // The box is named as it was - by all of its note, word for word what the page shows - and not by the
  // button that opens it. It says so in its own label: a browser leaves a closed hint out of a name.
  expect(auto).toHaveAccessibleName(/^Orchestrator model: automatic One more request .* asked how hard it is\. It overrides .* does not use it\. The Orchestrator then runs .* else the model above\.$/)
  // (less the hint's "Learn more →": a link to the guide, no part of the note)
  const shown = note.closest('label')!.textContent!.replace('Learn more →', '')
  expect(auto.getAttribute('aria-label')!.replace(/\s+/g, '')).toBe(shown.replace(/\s+/g, ''))
  expect(rest).toHaveTextContent(/shows the answer as that model’s guess\./)
  expect(rest).not.toHaveTextContent(/overrides|trigger/)
  // with nothing to go by the Lead is not put on "the model above": it runs where it otherwise would
  expect(rest).toHaveTextContent(/the Orchestrator runs where it otherwise would: its role’s model, else its tier, else the model above\.$/)
  await userEvent.click(auto)
  // who is asked - or that nobody can be - is the server's to say: nothing is guessed here
  expect(screen.queryByText(/nobody is asked/)).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Use this model' }))
  expect(onSave).toHaveBeenLastCalledWith({ provider_id: null, model_id: null, lead_auto: true })

  const fast = provider({ id: 'p3', name: 'Fast', for_agents: true, models: [{ name: 'quick', tier: 'fast', agents: true }] })
  rerender(<ModelPicker providers={[provider({}), fast]} providerId={null} modelId={null} leadAuto onSave={onSave} />)
  // the button says it, so it is seen without opening anything
  await userEvent.click(screen.getByRole('button', { name: 'Model: Orchestrator: automatic · Local' }))
  expect(screen.getByLabelText(/Orchestrator model: automatic/)).toBeChecked()
  // left as it is, it is not sent again
  await userEvent.click(screen.getByRole('button', { name: 'Use this model' }))
  expect(onSave).toHaveBeenLastCalledWith({ provider_id: null, model_id: null })
  await userEvent.click(screen.getByRole('button', { name: 'Model: Orchestrator: automatic · Local' }))
  await userEvent.click(screen.getByLabelText(/Orchestrator model: automatic/))
  await userEvent.click(screen.getByRole('button', { name: 'Use this model' }))
  expect(onSave).toHaveBeenLastCalledWith({ provider_id: null, model_id: null, lead_auto: false })
})

test('a CLI test result says the command was found, not that the model was reached', async () => {
  const h = handlers()
  h.onTest.mockResolvedValue({ ok: true, model_id: 'sonnet', tools_supported: true, error: null })
  render(<ModelsPage providers={[claude, provider({})]} {...h} />)
  await open('Claude Code', 'Connection')
  await userEvent.click(screen.getByRole('button', { name: 'Test' }))
  const status = await screen.findByRole('status')
  expect(status).toHaveTextContent('The claude command was found')
  expect(status).toHaveTextContent('sign-in is not checked')
  expect(status).not.toHaveTextContent('Reachable')
})

test('any provider but the first can be made the default', async () => {
  const h = { ...handlers(), onMakeDefault: vi.fn().mockResolvedValue(undefined) }
  render(<ModelsPage providers={[provider({}), claude]} {...h} />)
  await open('Local', 'Connection')
  expect(screen.queryByRole('button', { name: 'Make default' })).not.toBeInTheDocument()
  await close()
  await open('Claude Code', 'Connection')
  await userEvent.click(screen.getByRole('button', { name: 'Make default' }))
  expect(h.onMakeDefault).toHaveBeenCalledWith('p2')
})

test('Claude Code can run as a session or step by step, and says what each means', async () => {
  const h = handlers()
  render(<ModelsPage providers={[{ ...claude, mode: 'session' }, provider({})]} {...h} />)
  await open('Claude Code', 'Connection')
  expect(screen.getByLabelText('How it runs')).toHaveValue('session')
  expect(screen.getByText(/keeps its own loop for the whole of an agent's work/)).toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('How it runs'), 'step')
  expect(screen.getByText(/Each model step is a separate run of the CLI/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenCalledWith('p2', expect.objectContaining({ mode: 'step' }))
})

test('Qoder and Codex each run the ways they safely can', async () => {
  const h = handlers()
  const qoder = provider({ id: 'p4', name: 'Qoder', kind: 'qoder_cli', base_url: null, mode: 'session' })
  const codex = provider({ id: 'p5', name: 'Codex', kind: 'codex_cli', base_url: null, mode: null })
  render(<ModelsPage providers={[qoder, codex]} {...h} />)
  await open('Qoder', 'Connection')
  expect(screen.getByLabelText('How it runs')).toHaveValue('session')  // natively too since B-306, not by default
  expect(screen.getByText(/keeps its own loop/)).toBeInTheDocument()
  expect(screen.getByText(/a model name has to be set/i)).toBeInTheDocument()
  await close()
  await open('Codex', 'Connection')
  // A session since 7 Nov 2026 and its default since its live test, said plainly: its patch tool stays, and is refused.
  expect(screen.getByLabelText('How it runs')).toHaveValue('session')
  const session = screen.getByRole('option', { name: "One session per agent, with KOLONİ's tools (recommended)" })
  expect(session).toHaveValue('session')
  expect(screen.getByText(/KOLONİ refuses every patch it asks to make/)).toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('How it runs'), 'step')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenCalledWith('p5', expect.objectContaining({ mode: 'step' }))
  await close()
  await userEvent.click(screen.getByRole('button', { name: /Add a provider/ }))
  expect(screen.getByRole('option', { name: 'Qoder (CLI)' })).toBeInTheDocument()
})

test('Codex can run natively, and the page says plainly how it is asked first', async () => {
  const h = handlers()
  const codex = provider({ id: 'p5', name: 'Codex', kind: 'codex_cli', base_url: null, mode: 'step' })
  render(<ModelsPage providers={[codex, provider({})]} {...h} />)
  await open('Codex', 'Connection')
  expect(screen.getByLabelText('How it runs')).toHaveValue('step')
  await userEvent.selectOptions(screen.getByLabelText('How it runs'), 'native')
  const warning = screen.getByRole('note')
  // Since slice 89a it asks KOLONİ before each command and patch, at any permission level.
  expect(warning).toHaveTextContent('asks KOLONİ before each command it runs and each patch it makes')
  expect(warning).toHaveTextContent('at any permission level')
  expect(warning).toHaveTextContent('unasked is marked so on the record')
  expect(warning).not.toHaveTextContent('only runs when the permission level is Full auto')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenCalledWith('p5', expect.objectContaining({ mode: 'native' }))
})
