import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Provider } from '../api/types'
import { namedOf } from './levels'
import { ModelPicker } from './ModelPicker'
import { ModelsPage } from './ModelsPage'

const github = (over: Partial<Provider> = {}): Provider => ({
  id: 'gh',
  name: 'Copilot',
  kind: 'copilot_cli',
  base_url: null,
  default_model: null,
  executable: null,
  mode: 'native',
  options: null,
  for_agents: true,
  note: null,
  models: [
    { name: 'auto', note: null, tier: 'fast', agents: true },
    { name: 'fusion', note: null, tier: null, agents: true, routing: 'high' },
    { name: 'gpt-x', note: null, tier: 'strongest', agents: true },
  ],
  only_listed: false,
  max_running: null, plan: false, step_down_at: null, day_limit: null, month_limit: null,
  has_key: false,
  position: 0,
  created_at: '2026-11-21T10:00:00Z',
  updated_at: '2026-11-21T10:00:00Z',
  ...over,
})

const handlers = {
  onCreate: vi.fn(async () => {}),
  onDelete: vi.fn(async () => {}),
  onTest: vi.fn(async () => ({ ok: true, model_id: 'x', tools_supported: true, error: null, reply: null })),
}

const options = (select: HTMLElement) => within(select).getAllByRole('option').map(option => option.textContent)

test('Copilot’s auto and fusion on your GitHub account take a routing on their row, saved at once', async () => {
  const onSave = vi.fn(async () => {})
  render(<ModelsPage providers={[github()]} {...handlers} onSave={onSave} />)
  await userEvent.click(screen.getByRole('button', { name: /^Copilot/ }))
  const dialog = screen.getByRole('dialog', { name: 'Copilot' })
  const auto = within(dialog).getByLabelText('Routing of auto')
  expect(options(auto)).toEqual(['Default', 'Efficiency', 'Balance', 'Intelligence'])
  expect(auto).toHaveValue('')
  const fusion = within(dialog).getByLabelText('Routing of fusion')
  expect(options(fusion)).toEqual(['Default', 'Standard', 'High', 'Max'])
  expect(fusion).toHaveValue('high')
  expect(fusion).toHaveAttribute('title', expect.stringMatching(/cost more than auto/))
  expect(within(dialog).queryByLabelText('Routing of gpt-x')).not.toBeInTheDocument()
  await userEvent.selectOptions(auto, 'balance')
  expect(onSave).toHaveBeenLastCalledWith('gh', {
    models: [
      { name: 'auto', note: null, tier: 'fast', agents: true, routing: 'balance' },
      { name: 'fusion', note: null, tier: null, agents: true, routing: 'high' },
      { name: 'gpt-x', note: null, tier: 'strongest', agents: true },
    ],
  })
  expect(await within(dialog).findByText('auto: balance routing.')).toBeInTheDocument()
})

test('a Copilot on a model server of your own has no routing', async () => {
  render(<ModelsPage providers={[github({ base_url: 'http://localhost:8080/v1' })]} {...handlers} onSave={vi.fn(async () => {})} />)
  await userEvent.click(screen.getByRole('button', { name: /^Copilot/ }))
  expect(screen.getByText('auto')).toBeInTheDocument()
  expect(screen.queryByLabelText('Routing of auto')).not.toBeInTheDocument()
})

test('the chat’s model panel shows Copilot’s routing and saves it on its Models row; none for another model', async () => {
  const onRouting = vi.fn(async () => {})
  const { unmount } = render(<ModelPicker providers={[github()]} providerId="gh" modelId="auto" onSave={async () => {}} onRouting={onRouting} />)
  await userEvent.click(screen.getByRole('button', { name: /^Model:/ }))
  const routing = screen.getByLabelText('Routing')
  expect(screen.getByText('Saved on its Models row: every chat and agent on Copilot · auto uses it.')).toBeInTheDocument()
  await userEvent.selectOptions(routing, 'balance')
  expect(onRouting).toHaveBeenLastCalledWith('gh', [
    { name: 'auto', note: null, tier: 'fast', agents: true, routing: 'balance' },
    { name: 'fusion', note: null, tier: null, agents: true },
    { name: 'gpt-x', note: null, tier: 'strongest', agents: true },
  ])
  unmount()
  render(<ModelPicker providers={[github()]} providerId="gh" modelId="gpt-x" onSave={async () => {}} onRouting={onRouting} />)
  await userEvent.click(screen.getByRole('button', { name: /^Model:/ }))
  expect(screen.queryByLabelText('Routing')).not.toBeInTheDocument()
})

test('fusion picks its own level, as auto does', () => {
  expect(namedOf(true, 'fusion')).toBe('auto')
  expect(namedOf(true, 'auto')).toBe('auto')
  expect(namedOf(true, 'gemini-3-high')).toBe('name')
})
