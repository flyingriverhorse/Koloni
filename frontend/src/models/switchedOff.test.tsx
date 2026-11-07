import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Provider } from '../api/types'
import { ProviderOptions } from './ModelNameInput'
import { ModelsPage } from './ModelsPage'

// A provider, or a model of it, switched off without being deleted: nobody uses it; it stays on the page, greyed.

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
  models: [
    { name: 'big', note: null, tier: 'strongest', agents: true },
    { name: 'dear', note: null, tier: 'strongest', agents: true, enabled: false },
  ],
  only_listed: false,
  max_running: null, plan: false, step_down_at: null, day_limit: null, month_limit: null,
  has_key: true,
  position: 0,
  created_at: 't',
  updated_at: 't',
  ...over,
})
const handlers = () => ({
  onCreate: vi.fn().mockResolvedValue(undefined),
  onSave: vi.fn().mockResolvedValue(undefined),
  onDelete: vi.fn().mockResolvedValue(undefined),
  onTest: vi.fn().mockResolvedValue({ ok: true, model_id: 'qwen', tools_supported: true, error: null }),
})

test('a model is switched off and on beside "Agents may use"; one off is greyed and says so', async () => {
  const h = handlers()
  render(<ModelsPage providers={[provider({})]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: /^Local/ }))
  const dialog = screen.getByRole('dialog', { name: 'Local' })
  const dear = within(dialog).getByRole('switch', { name: 'dear on' })
  expect(dear).not.toBeChecked()
  expect(dear.closest('tr')).toHaveClass('model-off')
  expect(within(dear.closest('tr')!).getByText('off')).toBeInTheDocument()
  expect(within(dialog).getByRole('switch', { name: 'big on' }).closest('tr')).not.toHaveClass('model-off')
  await userEvent.click(within(dialog).getByRole('switch', { name: 'big on' }))
  expect(h.onSave).toHaveBeenLastCalledWith('p1', {
    models: [
      { name: 'big', note: null, tier: 'strongest', agents: true, enabled: false },
      { name: 'dear', note: null, tier: 'strongest', agents: true, enabled: false },
    ],
  })
  expect(await within(dialog).findByText('big is switched off.')).toBeInTheDocument()
  await userEvent.click(within(dialog).getByRole('switch', { name: 'dear on' }))
  expect(h.onSave.mock.lastCall![1].models[1]).toEqual({ name: 'dear', note: null, tier: 'strongest', agents: true, enabled: true })
})

test('B-396: a model KOLONİ switched off as its CLI refused it says why; On sends no why back', async () => {
  const h = handlers()
  const why = 'Copilot refused it: not available on your account'
  render(<ModelsPage providers={[provider({ models: [{ name: 'dear', note: null, tier: 'balanced', agents: true, enabled: false, off_why: why }] })]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: /^Local/ }))
  const dear = within(screen.getByRole('dialog', { name: 'Local' })).getByRole('switch', { name: 'dear on' })
  expect(within(dear.closest('tr')!).getByText(why)).toBeInTheDocument()
  await userEvent.click(dear)
  expect(h.onSave.mock.lastCall![1].models[0]).toEqual({ name: 'dear', note: null, tier: 'balanced', agents: true, enabled: true })
})

test('a provider is switched off and on from its window’s head; one off is greyed on its card', async () => {
  const h = handlers()
  const { rerender } = render(<ModelsPage providers={[provider({})]} {...h} />)
  expect(screen.getByRole('button', { name: /^Local/ })).not.toHaveClass('provider-off')
  await userEvent.click(screen.getByRole('button', { name: /^Local/ }))
  const on = within(screen.getByRole('dialog', { name: 'Local' })).getByRole('switch', { name: 'Local on' })
  expect(on).toBeChecked()
  await userEvent.click(on)
  expect(h.onSave).toHaveBeenLastCalledWith('p1', { enabled: false })
  // As saved: off, its key kept; greyed, and its window still opens to switch it on again.
  rerender(<ModelsPage providers={[provider({ enabled: false, updated_at: 't2' })]} {...h} />)
  const card = document.getElementById('provider-card-p1')!
  expect(card).toHaveClass('provider-off')
  expect(card).toHaveTextContent('switched off')
  await userEvent.click(within(screen.getByRole('dialog', { name: 'Local' })).getByRole('switch', { name: 'Local on' }))
  expect(h.onSave).toHaveBeenLastCalledWith('p1', { enabled: true })
})

test('a provider is switched off and on from its card, without its window opening; one off is greyed and says so', async () => {
  const h = handlers()
  const { rerender } = render(<ModelsPage providers={[provider({})]} {...h} />)
  const on = screen.getByRole('switch', { name: 'Local on' })
  expect(on).toBeChecked()
  await userEvent.click(on)
  expect(h.onSave).toHaveBeenLastCalledWith('p1', { enabled: false })
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  rerender(<ModelsPage providers={[provider({ enabled: false, updated_at: 't2' })]} {...h} />)
  const card = document.getElementById('provider-card-p1')!
  expect(card).toHaveClass('provider-off')
  expect(card).toHaveTextContent('switched off')
  expect(screen.getByRole('switch', { name: 'Local on' })).not.toBeChecked()
  await userEvent.click(screen.getByRole('switch', { name: 'Local on' }))
  expect(h.onSave).toHaveBeenLastCalledWith('p1', { enabled: true })
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

test('a switch that is refused says which and why, on the page and only in that provider’s window', async () => {
  const h = handlers()
  h.onSave.mockRejectedValue(new Error('the server broke'))
  render(<ModelsPage providers={[provider({}), provider({ id: 'p2', name: 'Fast' })]} {...h} />)
  await userEvent.click(screen.getByRole('switch', { name: 'Local on' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Local could not be switched: the server broke')
  await userEvent.click(screen.getByRole('button', { name: /^Fast/ }))
  expect(within(screen.getByRole('dialog', { name: 'Fast' })).queryByRole('alert')).toBeNull()
  await userEvent.keyboard('{Escape}')
  await userEvent.click(screen.getByRole('button', { name: /^Local/ }))
  expect(within(screen.getByRole('dialog', { name: 'Local' })).getByRole('alert')).toHaveTextContent('the server broke')
})

test('a picker shows a provider switched off and does not let it be picked', () => {
  render(
    <select aria-label="Provider" defaultValue="p1">
      <ProviderOptions providers={[provider({ enabled: false }), provider({ id: 'p2', name: 'Fast' })]} />
    </select>,
  )
  expect(screen.getByRole('option', { name: 'Local — off' })).toBeDisabled()
  expect(screen.getByRole('option', { name: 'Fast' })).toBeEnabled()
})

test('a CLI switched off offers no “Read now”: Claude Code’s would be a model turn', async () => {
  const onLimits = vi.fn().mockResolvedValue({ unknown: 'not read yet', read_at: null, source: null, plan: null, windows: [], credits: null })
  const cli = { kind: 'claude_cli' as const, base_url: null, models: [] }
  render(<ModelsPage providers={[provider({ ...cli, id: 'on', name: 'On' }), provider({ ...cli, id: 'off', name: 'Off', enabled: false })]} {...handlers()} onLimits={onLimits} />)
  expect(await screen.findByRole('button', { name: 'Read On’s plan now' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Read Off’s plan now' })).toBeNull()
})
