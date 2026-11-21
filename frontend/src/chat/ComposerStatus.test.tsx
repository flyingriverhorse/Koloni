import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { agent, command, convState, question, run, toolCall } from '../test-fixtures'
import { ComposerStatus } from './ComposerStatus'

// The turn began at 10:00:00 (the fixtures'); it is 12s later.
beforeEach(() => vi.useFakeTimers({ now: Date.parse('2026-10-05T10:00:12Z'), toFake: ['Date', 'setInterval', 'clearInterval'] }))
afterEach(() => vi.useRealTimers())

const at = { compact: false, running: false, onStop: vi.fn() }
const atWork = (over: Parameters<typeof agent>[2] = {}) =>
  convState({
    runs: [run('r'), run('q', 'queued', { started_at: null })],
    agents: [agent('r', 'running', { output_tokens: 1234, tier: 'fast', ...over })],
    toolCalls: [toolCall('1', 'r', 'run_command', 'running', '{"command":"pytest -q"}')],
    commands: [command('k', 'r', { tool_call_id: '1', status: 'running', exit_code: null, ended_at: null })],
  })

test('ready, running, asking and queued, in one line over the box; Stop while it runs', async () => {
  const onStop = vi.fn()
  const { container, rerender } = render(<ComposerStatus {...at} conv={convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed')] })} />)
  const line = () => container.querySelector('.composer-status')
  expect(line()).toHaveTextContent(/^Orchestrator is ready$/)
  expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull()
  rerender(<ComposerStatus {...at} conv={atWork()} running onStop={onStop} />)
  expect(line()).toHaveTextContent(/^pytest -q · 12s · ↓ 1\.2k tokens · Fast · 1 queued$/)
  await userEvent.click(screen.getByRole('button', { name: 'Stop' }), { advanceTimers: vi.advanceTimersByTime })
  expect(onStop).toHaveBeenCalled()
  const asks = convState({ runs: [run('r', 'waiting_approval')], agents: [agent('r', 'waiting')], questions: [question('q', 'r')] })
  rerender(<ComposerStatus {...at} conv={asks} running />)
  expect(line()).toHaveTextContent(/^Orchestrator waits for your answer$/)
  // (The closed chat's small box has none.)
  rerender(<ComposerStatus {...at} conv={asks} compact />)
  expect(line()).toBeNull()
})

test('a turn in which any agent’s tokens are not known shows no token count', () => {
  const conv = atWork()
  const { container } = render(<ComposerStatus {...at} conv={{ ...conv, agents: [...conv.agents, agent('r', 'running', { id: 'k', depth: 1, parent_agent_id: 'r' })] }} running />)
  expect(container.querySelector('.composer-status')).not.toHaveTextContent(/tokens|↓/)
  expect(container.querySelector('.composer-status')).toHaveTextContent(/^pytest -q · 12s · Fast · 1 queued$/)
})

test('the status line is no live region: its clock is not read out every second', () => {
  const { container } = render(<ComposerStatus {...at} conv={atWork()} running />)
  expect(container.querySelector('.composer-status')!.closest('[aria-live],[role=status],[role=alert]')).toBeNull()
  expect(container.querySelector('.composer-status [aria-live],.composer-status [role=status]')).toBeNull()
})

test('the model is on the line in every tone: ready, at work and waiting for your answer', () => {
  const model = <button type="button">Model: qwen</button>
  const asks = convState({ runs: [run('r', 'waiting_approval')], agents: [agent('r', 'waiting')], questions: [question('q', 'r')] })
  const { rerender } = render(<ComposerStatus {...at} conv={convState({ runs: [run('r', 'completed')] })} model={model} />)
  const picker = screen.getByRole('button', { name: 'Model: qwen' })
  rerender(<ComposerStatus {...at} conv={atWork()} running model={model} />)
  // (The same element: a picker open as a turn starts stays open.)
  expect(screen.getByRole('button', { name: 'Model: qwen' })).toBe(picker)
  rerender(<ComposerStatus {...at} conv={asks} running model={model} />)
  expect(screen.getByRole('button', { name: 'Model: qwen' })).toBe(picker)
})
