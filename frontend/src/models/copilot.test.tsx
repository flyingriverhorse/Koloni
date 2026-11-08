import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { AgentsPage } from '../agents/AgentsPage'
import type { Provider, Role } from '../api/types'
import { modelName } from '../shell/modelName'
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
  created_at: '2026-10-06T10:00:00Z',
  updated_at: '2026-10-06T10:00:00Z',
  ...over,
})

const copilot = provider({
  id: 'cp',
  name: 'Copilot',
  kind: 'copilot_cli',
  base_url: 'http://localhost:8080/v1',
  default_model: 'qwen-local',
  mode: 'session',
  has_key: true,
  options: { provider_type: 'openai', max_prompt_tokens: 70000, max_output_tokens: 8000, offline: true },
})
const claude = provider({ id: 'cc', name: 'Claude Code', kind: 'claude_cli', base_url: null, mode: 'session' })

const handlers = {
  onCreate: vi.fn(async () => {}),
  onSave: vi.fn(async () => {}),
  onDelete: vi.fn(async () => {}),
  onTest: vi.fn(async () => ({ ok: true, model_id: 'x', tools_supported: true, error: null, reply: null })),
}

test('Copilot is added with a model server of your own', async () => {
  const onCreate = vi.fn(async () => {})
  render(<ModelsPage providers={[provider({})]} {...handlers} onCreate={onCreate} />)
  await userEvent.click(screen.getByRole('button', { name: /Add a provider/ }))
  await userEvent.type(screen.getByLabelText('Name'), 'Copilot')
  await userEvent.selectOptions(screen.getByLabelText('Kind'), 'copilot_cli')
  expect(screen.getByText(/no GitHub sign-in is needed/)).toBeInTheDocument()
  await userEvent.type(screen.getByLabelText('Model server address'), 'http://localhost:8080/v1')
  await userEvent.type(screen.getByLabelText('Most prompt tokens'), '70000')
  await userEvent.type(screen.getByLabelText('Default model'), 'qwen-local')
  await userEvent.click(screen.getByRole('button', { name: 'Add provider' }))
  expect(onCreate).toHaveBeenCalledWith({
    name: 'Copilot',
    kind: 'copilot_cli',
    default_model: 'qwen-local',
    executable: '',
    mode: 'session',
    base_url: 'http://localhost:8080/v1',
    api_key: '',
    options: { provider_type: 'openai', max_prompt_tokens: 70000, max_output_tokens: null, offline: true },
  })
})

test('Copilot is added with no token, on your own GitHub sign-in', async () => {
  const onCreate = vi.fn(async () => {})
  render(<ModelsPage providers={[provider({})]} {...handlers} onCreate={onCreate} />)
  await userEvent.click(screen.getByRole('button', { name: /Add a provider/ }))
  await userEvent.type(screen.getByLabelText('Name'), 'Copilot')
  await userEvent.selectOptions(screen.getByLabelText('Kind'), 'copilot_cli')
  expect(screen.getByLabelText('API key')).not.toBeRequired()
  expect(screen.getByText(/Leave empty to use your own GitHub sign-in \(gh\)/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Add provider' }))
  expect(onCreate).toHaveBeenCalledWith(expect.objectContaining({ kind: 'copilot_cli', base_url: '', api_key: '' }))
})

test('a saved Copilot provider shows its model server and never its key', async () => {
  const onSave = vi.fn(async () => {})
  render(<ModelsPage providers={[copilot, provider({})]} picked="cp" {...handlers} onSave={onSave} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  expect(screen.getByLabelText('Model server address')).toHaveValue('http://localhost:8080/v1')
  expect(screen.getByLabelText('Most prompt tokens')).toHaveValue('70000')
  expect(screen.getByLabelText('API key')).toHaveValue('')
  expect(screen.getByLabelText(/Never connect to GitHub/)).toBeChecked()
  await userEvent.clear(screen.getByLabelText('Most output tokens'))
  await userEvent.click(screen.getByLabelText(/Never connect to GitHub/))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith('cp', {
    name: 'Copilot',
    default_model: 'qwen-local',
    executable: '',
    mode: 'session',
    base_url: 'http://localhost:8080/v1',
    options: { provider_type: 'openai', max_prompt_tokens: 70000, max_output_tokens: null, offline: false },
  })
})

test('an address typed for another kind is shown open on Claude Code, never saved unseen', async () => {
  render(<ModelsPage providers={[provider({})]} {...handlers} />)
  await userEvent.click(screen.getByRole('button', { name: /Add a provider/ }))
  await userEvent.type(screen.getByLabelText('Address'), 'http://127.0.0.1:8080/v1')
  await userEvent.selectOptions(screen.getByLabelText('Kind'), 'claude_cli')
  const field = screen.getByLabelText('Model server address')
  expect(field).toHaveValue('http://127.0.0.1:8080/v1')
  expect(field.closest('details')).toHaveAttribute('open')
})

// K-cli-llama: Claude Code or Codex on the user's llama-server - its address only, never a key.
test('Claude Code and Codex take a model server of your own, and send it only when it changed', async () => {
  const onCreate = vi.fn(async () => {})
  const { unmount } = render(<ModelsPage providers={[provider({})]} {...handlers} onCreate={onCreate} />)
  await userEvent.click(screen.getByRole('button', { name: /Add a provider/ }))
  await userEvent.type(screen.getByLabelText('Name'), 'Codex local')
  await userEvent.selectOptions(screen.getByLabelText('Kind'), 'codex_cli')
  expect(screen.queryByLabelText('API key')).not.toBeInTheDocument()
  await userEvent.type(screen.getByLabelText('Model server address'), 'http://127.0.0.1:8080/v1')
  expect(screen.getByText(/Runs the codex command on this machine, on your model server/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Add provider' }))
  // A step there: its session on a model server of the user's is not measured (without one it is a session).
  expect(onCreate).toHaveBeenCalledWith(expect.objectContaining({ kind: 'codex_cli', base_url: 'http://127.0.0.1:8080/v1', mode: 'step' }))
  expect(onCreate.mock.calls[0]).not.toHaveProperty('0.api_key')
  unmount()

  const onSave = vi.fn(async () => {})
  const local = { ...claude, base_url: 'http://127.0.0.1:8080/v1' }
  render(<ModelsPage providers={[local, provider({})]} picked="cc" {...handlers} onSave={onSave} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  expect(screen.getByLabelText('Model server address')).toHaveValue('http://127.0.0.1:8080/v1')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave.mock.calls[0]).not.toHaveProperty('1.base_url')
  await userEvent.clear(screen.getByLabelText('Model server address'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith('cc', expect.objectContaining({ base_url: '' }))
})

test('model names the provider can list are offered, and a provider that lists none says so', async () => {
  const onModels = vi.fn(async (id: string) =>
    id === 'cp'
      ? { models: ['qwen-a', 'qwen-b'], note: null }
      : { models: [], note: 'Codex does not list its models: type the name you would give its --model option.' },
  )
  const { unmount } = render(<ModelsPage providers={[copilot, provider({})]} picked="cp" {...handlers} onModels={onModels} />)
  await waitFor(() => expect(document.querySelectorAll('datalist option')).toHaveLength(2))
  expect(Array.from(document.querySelectorAll('datalist option')).map(o => o.getAttribute('value'))).toEqual(['qwen-a', 'qwen-b'])
  unmount()

  render(<ModelPicker providers={[claude, copilot]} providerId="cc" modelId={null} onSave={async () => {}} onModels={onModels} />)
  await userEvent.click(screen.getByRole('button', { name: /^Model:/ }))
  expect(await screen.findByText(/does not list its models/)).toBeInTheDocument()
})

test('a CLI provider can be tried with a real run, and the page says what that costs', async () => {
  const onTest = vi.fn(async (_id: string, run?: boolean) => ({
    ok: true, model_id: 'claude-sonnet-5-5', tools_supported: true, error: null, reply: run ? 'ok' : null,
  }))
  render(<ModelsPage providers={[claude, provider({})]} picked="cc" {...handlers} onTest={onTest} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  const button = screen.getByRole('button', { name: 'Try a real run' })
  expect(screen.getByText(/One short run of the CLI; it counts against your plan/)).toBeInTheDocument()
  await userEvent.click(button)
  expect(onTest).toHaveBeenCalledWith('cc', true)
  expect(await screen.findByText('It answered "ok" · model claude-sonnet-5-5')).toBeInTheDocument()
})

const role = (over: Partial<Role>): Role => ({
  id: 'r1',
  name: 'Coder',
  description: '',
  instructions: '',
  tools: ['read_file'],
  builtin: true,
  created_by_agent: false, models: null,
  provider_id: null,
  model_id: null,
  tier: null,
  tier_min: null,
  tier_max: null,
  kind: 'build',
  enabled: true,
  teams: [],
  pick_from: null,
  max_steps: null,
  max_tokens: null,
  effort: null,
  max_effort: null,
  context_window: null,
  mcp: [],
  skills: [],
  inside_cli: false,
  knows: [],
  created_at: '2026-10-06T10:00:00Z',
  updated_at: '2026-10-06T10:00:00Z',
  ...over,
})

// Slice 81b: a card says a role's tier rule; where it runs is said in its form ("Runs on").
test('a role with a model of its own says so on its panel; for the rest the Lead picks a tier', async () => {
  render(
    <AgentsPage
      roles={[role({}), role({ id: 'r2', name: 'Reviewer', provider_id: 'cp', model_id: null }), role({ id: 'r3', name: 'Planner', provider_id: 'cc', model_id: 'opus' })]}
      providers={[claude, copilot]}
      onSave={async () => {}}
      onCreate={async () => {}}
      onDelete={async () => {}}
      onReset={async () => {}}
    />,
  )
  for (const [name, rule] of [
    ['Coder', 'Orchestrator · fast–strongest'],
    ['Reviewer', 'Copilot · its default'],
    ['Planner', 'Claude Code · opus'],
  ]) {
    await userEvent.click(screen.getByRole('button', { name: new RegExp(`^${name}`) }))
    expect(screen.getByRole('complementary', { name: `Role ${name}` })).toHaveTextContent(`Which model${rule}`)
  }
})

test('a CLI that did not say which model it used is shown as just that', () => {
  expect(modelName('codex default')).toBe('CLI default (model not reported)')
  expect(modelName('claude-sonnet-5-5')).toBe('claude-sonnet-5-5')
  expect(modelName('models\\Qwen3.8-27B-UD-Q3_K_XL_D3.gguf')).toBe('Qwen3.8-27B-UD-Q3_K_XL_D3')
})

test('a real run of a CLI that did not name its model says so instead of a made-up name', async () => {
  const codex = provider({ id: 'cx', name: 'Codex', kind: 'codex_cli', base_url: null, mode: 'step' })
  const onTest = vi.fn(async () => ({ ok: true, model_id: 'codex default', tools_supported: true, error: null, reply: 'ok' }))
  render(<ModelsPage providers={[codex, provider({})]} picked="cx" {...handlers} onTest={onTest} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  await userEvent.click(screen.getByRole('button', { name: 'Try a real run' }))
  expect(await screen.findByText('It answered "ok" · model CLI default (model not reported)')).toBeInTheDocument()
})

test('each CLI says what running natively gives and takes', async () => {
  render(<ModelsPage providers={[provider({ ...claude, mode: 'native' }), provider({})]} picked="cc" {...handlers} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  expect(screen.getByText(/It asks KOLONİ before every tool\s+of its own, its reads too/)).toBeInTheDocument()
  expect(screen.queryByText(/only runs when the permission level is Full\s+auto/)).not.toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('How it runs'), 'session')
  expect(screen.queryByText(/It asks KOLONİ before/)).not.toBeInTheDocument()
})

test('the "How it runs" line itself says what each native CLI asks before', async () => {
  const asks = 'Native: its own tools, in the project; asks before every tool it uses'
  const { unmount } = render(
    <ModelsPage providers={[provider({ ...claude, mode: 'native' }), provider({})]} picked="cc" {...handlers} />,
  )
  const options = () => Array.from(screen.getByLabelText<HTMLSelectElement>('How it runs').options).map(o => o.text)
  expect(options().at(-1)).toBe(asks)
  expect(screen.getByLabelText('How it runs')).toHaveDisplayValue(asks)
  unmount()
  // Since 89a/89c Codex and Copilot ask too (B-43), each before what it asks about
  const codex = provider({ id: 'cx', name: 'Codex', kind: 'codex_cli', base_url: null, mode: 'native' })
  const qoder = provider({ id: 'qd', name: 'Qoder', kind: 'qoder_cli', base_url: null, mode: 'native' })
  for (const [other, said] of [
    [codex, 'asks before each command and patch, but not those its own rules count as safe'],
    [copilot, 'asks before each command, write and read'],
    [qoder, 'asks before every tool it uses (not yet measured)'],
  ] as const) {
    const shown = render(<ModelsPage providers={[provider({ ...other, mode: 'native' }), provider({})]} picked={other.id} {...handlers} />)
    expect(options().at(-1)).toBe(`Native: its own tools, in the project; ${said}`)
    shown.unmount()
  }
})

test('Qoder natively says it is not yet measured, and that a tool it uses unasked stops the run', () => {
  const qoder = provider({ id: 'qd', name: 'Qoder', kind: 'qoder_cli', base_url: null, mode: 'native' })
  render(<ModelsPage providers={[qoder, provider({})]} picked="qd" {...handlers} />)
  const note = screen.getByText(/Native, not yet measured: Qoder works in the project folder/)
  expect(note).toHaveTextContent('Whether Qoder really does is not measured yet')
  expect(note).toHaveTextContent('a tool of its own seen running without KOLONİ being asked stops the run')
  expect(note).not.toHaveTextContent('without your own Qoder settings')
})

test('a Copilot test on a GitHub account says its sign-in was asked, not that it was not checked', async () => {
  const onTest = vi.fn(async () => ({ ok: true, model_id: 'x', tools_supported: true, error: null, reply: null }))
  render(<ModelsPage providers={[{ ...copilot, base_url: null }, provider({})]} picked="cp" {...handlers} onTest={onTest} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  await userEvent.click(screen.getByRole('button', { name: 'Test' }))
  const status = await screen.findByRole('status')
  expect(status).toHaveTextContent('The copilot command was found, and Copilot did not say it is signed out')
  expect(status).not.toHaveTextContent('sign-in is not checked')
})

test('Copilot natively asks KOLONİ first, and the page says so', () => {
  render(<ModelsPage providers={[provider({ ...copilot, mode: 'native' }), provider({})]} picked="cp" {...handlers} />)
  const note = screen.getByText(/Native: Copilot works in the project folder/)
  // Since slice 89c it asks KOLONİ before each command, write and read, at any permission level.
  expect(note).toHaveTextContent('asks KOLONİ before each command it runs, each file it writes and each file it reads')
  expect(note).toHaveTextContent('at any permission level')
  expect(note).toHaveTextContent('unasked is marked so on the record')
  expect(note).not.toHaveTextContent('only runs when the permission level is Full auto')
  // Slice 105: its commands are sandboxed away from the secret files, where the machine can.
  expect(note).toHaveTextContent('its commands run in Copilot’s sandbox, denied the project’s secret files')
  expect(note).toHaveTextContent('where it cannot, the run says so')
  // B-309: it is measured in no copy, so its sub-agents take turns in the project.
  expect(note).toHaveTextContent('Copilot (native) runs its sub-agents one at a time here; session mode runs them at once')
  // R175, B-377: measured live - its sandbox never starts Python; a new Copilot is a session (test above).
  expect(note).toHaveTextContent(
    'Copilot’s own sandbox cannot start Python here (measured): tests run only through a sub-agent or in session mode',
  )
})

test('a command whose exit code was not reported is not shown as a failure', async () => {
  const { commandStatus } = await import('../commands/commandStatus')
  const { command } = await import('../test-fixtures')
  expect(commandStatus(command('k', 'r', { status: 'exited', exit_code: null }))).toEqual({
    label: 'ended · exit code not reported',
    tone: 'muted',
  })
  expect(commandStatus(command('k', 'r', { status: 'exited', exit_code: 1 })).tone).toBe('del')
})

test('a Copilot model on your GitHub account takes a context tier, saved at once; one on your own server does not', async () => {
  const onSave = vi.fn(async () => {})
  const github = provider({
    id: 'gh',
    name: 'Copilot GitHub',
    kind: 'copilot_cli',
    base_url: null,
    mode: 'session',
    for_agents: true,
    models: [{ name: 'gpt-x', note: null, tier: 'strongest', agents: true }],
  })
  const own = { ...copilot, models: [{ name: 'qwen-local', note: null, tier: 'fast' as const, agents: true }] }
  const { unmount } = render(<ModelsPage providers={[github]} {...handlers} onSave={onSave} />)
  await userEvent.click(screen.getByRole('button', { name: /^Copilot GitHub/ }))
  const dialog = screen.getByRole('dialog', { name: 'Copilot GitHub' })
  const tier = within(dialog).getByLabelText('Context of gpt-x')
  expect(tier).toHaveValue('default')
  expect(tier).toHaveAttribute('title', expect.stringMatching(/Long costs more/))
  await userEvent.selectOptions(tier, 'long_context')
  expect(onSave).toHaveBeenLastCalledWith('gh', {
    models: [{ name: 'gpt-x', note: null, tier: 'strongest', agents: true, context: 'long_context' }],
  })
  expect(await within(dialog).findByText('gpt-x: long context.')).toBeInTheDocument()
  unmount()
  render(<ModelsPage providers={[own]} {...handlers} onSave={onSave} />)
  await userEvent.click(screen.getByRole('button', { name: /^Copilot/ }))
  expect(screen.getByText('qwen-local')).toBeInTheDocument()
  expect(screen.queryByLabelText('Context of qwen-local')).not.toBeInTheDocument()
})
