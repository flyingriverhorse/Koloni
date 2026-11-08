import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Provider } from '../api/types'
import { ModelPicker, SWITCH_COSTS } from './ModelPicker'

// 89k: another model for a chat that has had a turn starts with no cache of it, on Claude Code.

const provider = (over: Partial<Provider>): Provider => ({
  id: 'cc', name: 'Claude', kind: 'claude_cli', base_url: null, default_model: 'claude-haiku-5',
  executable: null, mode: 'native', options: null, for_agents: false, note: null, models: [],
  only_listed: false, max_running: null, plan: false, step_down_at: null, day_limit: null,
  month_limit: null, has_key: false, position: 0, created_at: 't', updated_at: 't', ...over,
})
const claude = provider({})
const codex = provider({ id: 'cx', name: 'Codex', kind: 'codex_cli', default_model: null, position: 1 })

async function open(hasHistory: boolean) {
  render(<ModelPicker providers={[claude, codex]} providerId="cc" modelId={null} onSave={vi.fn()} hasHistory={hasHistory} />)
  await userEvent.click(screen.getByRole('button', { name: /^Model: Claude/ }))
}

test('another Claude Code model for a chat with a turn says the next turn costs more', async () => {
  await open(true)
  expect(screen.queryByText(SWITCH_COSTS)).toBeNull() // the model it runs on: nothing changes
  await userEvent.type(screen.getByLabelText('Model name'), 'claude-sonnet-5-5')
  expect(screen.getByText(SWITCH_COSTS)).toBeInTheDocument()
  // Codex: what a switch costs there is not measured, so nothing is said
  await userEvent.selectOptions(screen.getByLabelText('Provider'), 'cx')
  expect(screen.queryByText(SWITCH_COSTS)).toBeNull()
})

test('a chat on another provider moved to Claude Code is told nothing of a cache', async () => {
  render(<ModelPicker providers={[claude, codex]} providerId="cx" modelId={null} onSave={vi.fn()} hasHistory />)
  await userEvent.click(screen.getByRole('button', { name: /^Model: Codex/ }))
  await userEvent.selectOptions(screen.getByLabelText('Provider'), 'cc')
  await userEvent.type(screen.getByLabelText('Model name'), 'claude-sonnet-5-5')
  expect(screen.queryByText(SWITCH_COSTS)).toBeNull()
})

test('a chat with no turn yet is told nothing of a cache', async () => {
  await open(false)
  await userEvent.type(screen.getByLabelText('Model name'), 'claude-sonnet-5-5')
  expect(screen.queryByText(SWITCH_COSTS)).toBeNull()
})
