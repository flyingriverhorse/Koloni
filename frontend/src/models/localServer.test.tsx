import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import type { LocalServer, Provider } from '../api/types'
import { toArgs, toForm, words } from './LocalServerTab'
import { ModelsPage } from './ModelsPage'

// Slice 64: the model server on this machine, started and stopped from its provider's Server tab.

const READY =
  'models\\Qwen3.8-27B-UD-Q3_K_XL_D3.gguf --port 8080 -ngl 99 -fa on --cache-type-k q4_0 --cache-type-v q4_0 -c 82000 -np 1 -b 2048 -ub 512 --load-mode mlock --spec-type draft-mtp --spec-draft-n-max 3 --reasoning-effort medium --temp 0.3 --top-p 0.9 --top-k 40 --min-p 0.05 --cache-prompt --jinja'
const ARGS = ['-m', ...READY.split(' ')]
const EXE = 'C:\\llama\\Release\\llama-server.exe'

const provider = (over: Partial<Provider> = {}): Provider => ({
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
  max_running: null,
  plan: false,
  step_down_at: null,
  day_limit: null,
  month_limit: null,
  has_key: false,
  position: 0,
  created_at: 't',
  updated_at: 't',
  ...over,
})
const server = (over: Partial<LocalServer> = {}): LocalServer => ({
  executable: EXE,
  args: ARGS,
  models: ['models\\Qwen3.8-27B-UD-Q3_K_XL_D3.gguf', 'models\\small.gguf'],
  state: 'stopped',
  exit_code: null,
  model: null,
  n_ctx: null,
  gpu: null,
  output: '',
  ...over,
})
const RUNNING = server({
  state: 'running',
  model: 'Qwen3.8-27B-UD-Q3_K_XL_D3.gguf',
  n_ctx: 82000,
  gpu: { memory_used: 18432, memory_total: 24576, load: 35, share: null },
  output: 'main: server is listening on http://127.0.0.1:8080\nkey ***\n',
})
const handlers = () => ({
  onCreate: vi.fn().mockResolvedValue(undefined),
  onSave: vi.fn().mockResolvedValue(undefined),
  onDelete: vi.fn().mockResolvedValue(undefined),
  onTest: vi.fn().mockResolvedValue({ ok: true, model_id: 'x', tools_supported: true, error: null }),
})

afterEach(() => vi.useRealTimers())

const sorted = (list: string[]) => [...list].sort()

test('the command is split into the boxes and Advanced and joined back without losing an argument', () => {
  const form = toForm(ARGS)
  expect(form).toMatchObject({ model: 'models\\Qwen3.8-27B-UD-Q3_K_XL_D3.gguf', ctx: '82000', ngl: '99', effort: 'medium', temp: '0.3', topP: '0.9', topK: '40', minP: '0.05' })
  expect(form.advanced).toBe('--port 8080 -fa on --cache-type-k q4_0 --cache-type-v q4_0 -np 1 -b 2048 -ub 512 --load-mode mlock --spec-type draft-mtp --spec-draft-n-max 3 --cache-prompt --jinja')
  expect(sorted(toArgs(form))).toEqual(sorted(ARGS))
  expect(toForm(toArgs(form))).toEqual(form)
  // A path with spaces stays one argument; a flag given twice keeps the one llama-server reads, the other in Advanced.
  const twice = ['--lora', 'C:\\my models\\a b.gguf', '-c', '1000', '--ctx-size', '2000']
  expect(toForm(twice)).toMatchObject({ ctx: '2000', advanced: '--lora "C:\\my models\\a b.gguf" -c 1000' })
  expect(sorted(toArgs(toForm(twice)))).toEqual(sorted(['--lora', 'C:\\my models\\a b.gguf', '-c', '1000', '-c', '2000']))
  expect(words('  -a  "x y"  b\\c ')).toEqual(['-a', 'x y', 'b\\c'])
})

test('a server on this machine has a Server tab that shows the ready command, the models folder and Start', async () => {
  const onLocalServer = vi.fn().mockResolvedValue(server())
  const onRunLocalServer = vi.fn().mockResolvedValue(RUNNING)
  render(<ModelsPage providers={[provider()]} picked="p1" {...handlers()} onLocalServer={onLocalServer} onRunLocalServer={onRunLocalServer} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Server' }))
  const panel = screen.getByRole('tabpanel', { name: 'Server' })
  expect(await within(panel).findByRole('status')).toHaveTextContent('Stopped')
  expect(within(panel).getByLabelText('Program')).toHaveValue(EXE)
  const model = within(panel).getByLabelText('Model')
  expect(model).toHaveValue('models\\Qwen3.8-27B-UD-Q3_K_XL_D3.gguf')
  expect(within(model).getAllByRole('option').map(o => o.textContent)).toEqual(['None (-m not given)', ...server().models])
  expect(within(panel).getByLabelText('Context (-c)')).toHaveValue('82000')
  expect(within(panel).queryByRole('button', { name: 'Stop' })).toBeNull()
  // A change is what runs: kept first, then started.
  await userEvent.selectOptions(model, 'models\\small.gguf')
  await userEvent.clear(within(panel).getByLabelText('Context (-c)'))
  await userEvent.type(within(panel).getByLabelText('Context (-c)'), '32000')
  await userEvent.click(within(panel).getByRole('button', { name: 'Start' }))
  const [action, config] = onRunLocalServer.mock.calls[0]
  expect(action).toBe('start')
  expect(config.executable).toBe(EXE)
  expect(sorted(config.args)).toEqual(sorted(ARGS.map(a => (a === '82000' ? '32000' : a.endsWith('D3.gguf') ? 'models\\small.gguf' : a))))
  expect(within(panel).getByRole('status')).toHaveTextContent('Running · Qwen3.8-27B-UD-Q3_K_XL_D3.gguf · n_ctx 82,000')
  expect(within(panel).getByText('GPU memory 18.0 GB / 24.0 GB · load 35% · llama-server –')).toBeInTheDocument()
  expect(within(panel).getByLabelText('Server output')).toHaveTextContent('server is listening')
  // Running: Restart and Stop.
  onRunLocalServer.mockResolvedValue(server({ output: 'bye' }))
  await userEvent.click(within(panel).getByRole('button', { name: 'Stop' }))
  expect(onRunLocalServer).toHaveBeenLastCalledWith('stop', undefined)
  expect(within(panel).getByRole('status')).toHaveTextContent('Stopped')
  expect(within(panel).getByRole('button', { name: 'Start' })).toBeInTheDocument()
})

test('while it runs it is read again every few seconds; a model not in the folder stays a choice', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const onLocalServer = vi
    .fn()
    .mockResolvedValueOnce(server({ ...RUNNING, args: ['-m', 'D:\\elsewhere\\big.gguf'], gpu: null, model: null, n_ctx: null }))
    .mockResolvedValue(server({ ...RUNNING, state: 'exited', exit_code: 1, gpu: null }))
  render(<ModelsPage providers={[provider()]} picked="p1" {...handlers()} onLocalServer={onLocalServer} onRunLocalServer={vi.fn()} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Server' }))
  const panel = screen.getByRole('tabpanel', { name: 'Server' })
  expect(await within(panel).findByRole('status')).toHaveTextContent('Running · loading… · n_ctx –')
  expect(within(panel).getByText('GPU –')).toBeInTheDocument()
  expect(within(panel).getByLabelText('Model')).toHaveValue('D:\\elsewhere\\big.gguf')
  expect(within(panel).getByRole('button', { name: 'Restart' })).toBeInTheDocument()
  await act(() => vi.advanceTimersByTimeAsync(3100))
  expect(within(panel).getByRole('status')).toHaveTextContent('Ended by itself (exit code 1)')
  const calls = onLocalServer.mock.calls.length
  await act(() => vi.advanceTimersByTimeAsync(10_000))
  expect(onLocalServer).toHaveBeenCalledTimes(calls)
})

test('a reading waits for the one before it, and none is made while the page is hidden', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  let answer: (told: LocalServer) => void = () => {}
  const onLocalServer = vi
    .fn()
    .mockResolvedValueOnce(RUNNING)
    .mockImplementation(() => new Promise<LocalServer>(resolve => (answer = resolve)))
  render(<ModelsPage providers={[provider()]} picked="p1" {...handlers()} onLocalServer={onLocalServer} onRunLocalServer={vi.fn()} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Server' }))
  expect(await screen.findByText(/Running · Qwen/)).toBeInTheDocument()
  // A slow one (nvidia-smi is asked each time): no second is sent while it is out.
  await act(() => vi.advanceTimersByTimeAsync(20_000))
  expect(onLocalServer).toHaveBeenCalledTimes(2)
  await act(async () => answer(RUNNING))
  const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
  await act(() => vi.advanceTimersByTimeAsync(20_000))
  expect(onLocalServer).toHaveBeenCalledTimes(2)
  hidden.mockReturnValue(false)
  await act(() => vi.advanceTimersByTimeAsync(3100))
  expect(onLocalServer).toHaveBeenCalledTimes(3)
})

test('a hosted service and a CLI have no Server tab', () => {
  const page = render(<ModelsPage providers={[provider({ base_url: 'https://api.deepseek.com' })]} picked="p1" {...handlers()} onLocalServer={vi.fn()} onRunLocalServer={vi.fn()} />)
  expect(screen.queryByRole('tab', { name: 'Server' })).toBeNull()
  page.unmount()
  render(<ModelsPage providers={[provider({ kind: 'codex_cli', base_url: null })]} picked="p1" {...handlers()} onLocalServer={vi.fn()} onRunLocalServer={vi.fn()} />)
  expect(screen.queryByRole('tab', { name: 'Server' })).toBeNull()
})
