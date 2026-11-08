import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Provider } from '../api/types'
import { ModelsPage } from './ModelsPage'

const local: Provider = {
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
}
const agy = (mode: Provider['mode']): Provider => ({ ...local, id: 'p2', name: 'agy', kind: 'agy_cli', base_url: null, mode, position: 1 })

const handlers = () => ({
  onCreate: vi.fn().mockResolvedValue(undefined),
  onSave: vi.fn().mockResolvedValue(undefined),
  onDelete: vi.fn().mockResolvedValue(undefined),
  onTest: vi.fn().mockResolvedValue({ ok: true, model_id: 'agy default', tools_supported: true, error: null }),
})

test('agy is added by its command’s name and runs reading unless native is chosen', async () => {
  const h = handlers()
  render(<ModelsPage providers={[local]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: /Add a provider/ }))
  await userEvent.type(screen.getByLabelText('Name'), 'agy')
  await userEvent.selectOptions(screen.getByLabelText('Kind'), screen.getByRole('option', { name: 'agy (CLI)' }))
  expect(screen.getByLabelText('Path to the command')).toHaveAttribute('placeholder', 'Leave empty to find "agy" on PATH')
  expect(screen.queryByLabelText('Address')).not.toBeInTheDocument()

  const how = screen.getByLabelText('How it runs')
  expect(within(how).getAllByRole('option').map(o => o.textContent)).toEqual([
    'Reads with its own tools; started without leave to write or run',
    'Native: its own tools, in the project; asks before every tool it uses',
  ])
  expect(how).toHaveValue('reads')
  // what reading means here, and what it does not promise
  const note = screen.getByRole('note')
  expect(note).toHaveTextContent(/agy itself refuses to write a file or run a command/)
  expect(note).toHaveTextContent(/at every permission level and for every role/)
  expect(note).toHaveTextContent(/a role’s write and command tools do not apply/)
  expect(note).toHaveTextContent(/permission rules in your own agy settings can allow more/)
  expect(note).toHaveTextContent(/From agy 1.4.9 on, KOLONİ’s tools reach it .* so it can open sub-agents, ask you questions/)
  expect(note).toHaveTextContent(/An older agy runs the old way, without them/)
  // nothing here is KOLONİ's tools with the CLI's own switched off
  expect(screen.queryByText(/Its own tools are switched off/)).not.toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: 'Add provider' }))
  expect(h.onCreate).toHaveBeenCalledWith({ name: 'agy', kind: 'agy_cli', default_model: '', executable: '', mode: 'reads' })
})

test('native agy says that it asks first through its hook and where its sub-agent works', async () => {
  const h = handlers()
  render(<ModelsPage providers={[local, agy('reads')]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: /^agy/ }))
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  await userEvent.selectOptions(screen.getByLabelText('How it runs'), 'native')
  const note = screen.getByRole('note')
  expect(note).toHaveTextContent(/As a sub-agent it works in its own copy of the project/)
  expect(note).toHaveTextContent(/--dangerously-skip-permissions/)
  expect(note).toHaveTextContent(/a hook of KOLONİ's asks KOLONİ before each tool it uses/)
  expect(note).toHaveTextContent(/in a home of KOLONİ's, so your own agy settings, hooks and MCP servers stay out/)
  expect(note).not.toHaveTextContent(/Full auto/)
  expect(note).toHaveTextContent(/From agy 1.4.9 on, KOLONİ’s tools reach it .* so it can open sub-agents, ask you questions/)
  expect(note).toHaveTextContent(/An older agy runs the old way, without them/)
  expect(note).not.toHaveTextContent(/It can still open sub-agents/)
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenCalledWith('p2', { name: 'agy', default_model: '', executable: '', mode: 'native' })
})

test('a check of agy only says the command was found', async () => {
  const h = handlers()
  render(<ModelsPage providers={[local, agy('reads')]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: /^agy/ }))
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  await userEvent.click(screen.getByRole('button', { name: 'Test' }))
  expect(await screen.findByText(/The agy command was found\. It was not run/)).toBeInTheDocument()
  expect(screen.getByText(/One short run of the CLI, reading only/)).toBeInTheDocument()
})

test.each([
  ['claude_cli', 'native'],
  ['codex_cli', 'native'],
  ['copilot_cli', 'native'],
  ['agy_cli', 'reads'],
  ['agy_cli', 'native'],
] as const)('%s run as %s says it is not started by a trigger', async (kind, mode) => {
  render(<ModelsPage providers={[{ ...local, id: 'p2', name: 'Own', kind, base_url: null, mode }]} picked="p2" {...handlers()} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  expect(screen.getByRole('note')).toHaveTextContent('It is not started by a trigger: with nobody watching, only an agent that works with KOLONİ’s tools runs.')
})

test.each([
  ['claude_cli', 'session'],
  ['claude_cli', 'step'],
  ['codex_cli', 'step'],
  ['copilot_cli', 'session'],
] as const)('%s run as %s works with KOLONİ’s tools, and nothing is said about triggers', (kind, mode) => {
  render(<ModelsPage providers={[{ ...local, id: 'p2', name: 'Kept', kind, base_url: null, mode }]} picked="p2" {...handlers()} />)
  expect(screen.getByLabelText('How it runs')).toHaveValue(mode)
  expect(screen.queryByText(/not started by a trigger/)).not.toBeInTheDocument()
})

test.each([true, false])('agy’s card says Google’s terms forbid it, on or off (enabled: %s)', enabled => {
  render(<ModelsPage providers={[local, { ...agy('reads'), enabled }]} {...handlers()} />)
  expect(document.getElementById('provider-card-p2')).toHaveTextContent(
    'Google’s terms forbid using Antigravity through another app; your Google account may be suspended.',
  )
  expect(document.getElementById('provider-card-p1')).not.toHaveTextContent('Antigravity')
})
