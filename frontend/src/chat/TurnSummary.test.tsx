import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Merge, Price, Usage } from '../api/types'
import { agent, assistantMessage, command, convState, fileChange, run, userMessage } from '../test-fixtures'
import { MessageList } from './MessageList'

const noop = async () => {}
const said = (runId: string) => [userMessage(runId, 'go'), assistantMessage(`a-${runId}`, runId, 'Done.')]
const row = (over: Partial<Usage['by_model'][number]> = {}): Usage['by_model'][number] => ({
  provider_name: 'Paid',
  model_id: 'qwen',
  runs: 1,
  agents: 2,
  input_tokens: 100,
  output_tokens: 10,
  cache_read_tokens: null,
  cache_write_tokens: null,
  unknown_agents: 0,
  cost: null,
  ...over,
})
const usage = (rows: Usage['by_model']): Usage => ({ by_model: rows, by_conversation: [], by_start: [] })
const WORK = 'What it did'
const coder = (runId: string, over = {}) => agent(runId, 'completed', { id: `k-${runId}`, depth: 1, ...over })

test('slice 107: an answer whose message did work has one quiet line - sub-agents, files changed, what is left - and the summary, with the cost, under "details"', async () => {
  const onOpenChange = vi.fn()
  const onUsage = vi.fn((runId: string) => Promise.resolve(usage(runId === 'r2' ? [row({ cost: { amount: 0.42, currency: 'USD' } })] : [row()])))
  const kept: Merge = { id: 'm', run_id: 'r2', agent_id: 'k-r2', status: 'pending', files: [], created_at: 't', decided_at: null }
  const state = convState({
    runs: [run('r1', 'completed'), run('r2', 'completed')],
    messages: [...said('r1'), ...said('r2')],
    agents: [agent('r1', 'completed'), agent('r2', 'completed', { input_tokens: 1200, output_tokens: 30 }), coder('r2', { input_tokens: 800, output_tokens: 20 })],
    fileChanges: [
      fileChange('f1', 'r2', { path: 'a.py' }),
      fileChange('f2', 'r2', { path: 'a.py' }),
      fileChange('f3', 'r2', { path: 'b.py', status: 'merged' }),
      fileChange('f4', 'r2', { path: 'c.py', status: 'rejected' }),
    ],
    merges: [kept],
  })
  render(<MessageList state={state} onRemoveQueued={() => {}} onOpenChange={onOpenChange} onDecide={noop} onDecideCommand={noop} onUsage={onUsage} />)
  // The plain answer before it has nothing under it: it opened nobody, changed nothing.
  const line = screen.getByRole('region', { name: WORK })
  expect(screen.getAllByRole('region', { name: WORK })).toHaveLength(1)
  expect(within(line).getByText('1 agent · 2 files changed · changes to take in or discard')).toBeInTheDocument()
  expect(line.querySelector('dl')).toBeNull()
  // Nothing is read for a cost until it is asked for: no request per message of the chat.
  expect(onUsage).not.toHaveBeenCalled()
  await userEvent.click(within(line).getByRole('button', { name: 'details ▸' }))
  expect(within(line).getByRole('button', { name: 'details ▾' })).toHaveAttribute('aria-expanded', 'true')
  expect(onUsage.mock.calls).toEqual([['r2']])
  expect(line).toHaveTextContent('Files changed 2')
  expect(line).toHaveTextContent('Sub-agents 1')
  expect(line).toHaveTextContent('Tokens in 2,000 · out 50')
  expect(await within(line).findByText('≈ 0.42 USD')).toBeInTheDocument()
  expect(line).toHaveTextContent('Left open changes to take in or discard')
  await userEvent.click(within(line).getByRole('button', { name: 'View changes' }))
  expect(onOpenChange).toHaveBeenCalledWith('f1')
})

test('a price written while its details are open reads its cost again (K-38f2)', async () => {
  const onUsage = vi.fn().mockResolvedValueOnce(usage([row()]))
  onUsage.mockResolvedValueOnce(usage([row({ cost: { amount: 0.42, currency: 'USD' } })]))
  const state = convState({ runs: [run('r', 'completed')], messages: said('r'), agents: [agent('r', 'completed'), coder('r')] })
  const list = (prices: Price[]) => <MessageList state={state} onRemoveQueued={() => {}} onOpenChange={() => {}} onDecide={noop} onDecideCommand={noop} onUsage={onUsage} prices={prices} />
  const { rerender } = render(list([]))
  const line = screen.getByRole('region', { name: WORK })
  expect(within(line).getByText('1 agent')).toBeInTheDocument()
  await userEvent.click(within(line).getByRole('button', { name: 'details ▸' }))
  await vi.waitFor(() => expect(onUsage).toHaveBeenCalledTimes(1))
  expect(line).toHaveTextContent('Known cost –')
  // (the same prices, another array: not read again)
  rerender(list([]))
  rerender(list([{ model_id: 'qwen', currency: 'USD', input: 1, output: 2 }]))
  expect(await within(line).findByText('≈ 0.42 USD')).toBeInTheDocument()
  expect(onUsage).toHaveBeenCalledTimes(2)
})

test('what is not known is left out of the line, and is a dash in the details - never a made-up zero', async () => {
  const state = convState({ runs: [run('r', 'failed', { error: 'boom' })], messages: said('r'), agents: [agent('r', 'failed', { input_tokens: null, output_tokens: null }), coder('r', { input_tokens: null, output_tokens: null })] })
  render(<MessageList state={state} onRemoveQueued={() => {}} onOpenChange={() => {}} onDecide={noop} onDecideCommand={noop} />)
  const line = screen.getByRole('region', { name: WORK })
  expect(within(line).getByText('1 agent')).toBeInTheDocument()
  await userEvent.click(within(line).getByRole('button', { name: 'details ▸' }))
  expect(line).toHaveTextContent('Files changed 0')
  expect(line).toHaveTextContent('Tokens –')
  expect(line).toHaveTextContent('Known cost –')
  expect(line).toHaveTextContent('Left open nothing')
  expect(within(line).getAllByRole('button')).toHaveLength(1)
})

test('a turn at work has no line yet', () => {
  const state = convState({ runs: [run('r', 'running')], messages: said('r'), agents: [agent('r'), coder('r', { status: 'running' })] })
  render(<MessageList state={state} onRemoveQueued={() => {}} onOpenChange={() => {}} onDecide={noop} onDecideCommand={noop} />)
  expect(screen.queryByRole('region', { name: WORK })).toBeNull()
})

test('a server the turn left running is said on the line (slice 42b); once stopped it is not', () => {
  const serving = command('k', 'r', { command: 'npm run dev', keep_running: true, status: 'running', exit_code: null, ended_at: null })
  const state = convState({ runs: [run('r', 'completed')], messages: said('r'), agents: [agent('r', 'completed')], commands: [serving] })
  const { unmount } = render(<MessageList state={state} onRemoveQueued={() => {}} onOpenChange={() => {}} onDecide={noop} onDecideCommand={noop} />)
  expect(screen.getByRole('region', { name: WORK })).toHaveTextContent('a server running')
  unmount()
  render(<MessageList state={{ ...state, commands: [{ ...serving, status: 'killed' }] }} onRemoveQueued={() => {}} onOpenChange={() => {}} onDecide={noop} onDecideCommand={noop} />)
  expect(screen.queryByRole('region', { name: WORK })).toBeNull()
})

test('G1.3: under a recipe turn whose team ended before its end, the details say how - and what Take in also takes in', async () => {
  const stopped = {
    team_id: 'web',
    recipe_id: null,
    no_recipe: false,
    picked_by: 'user' as const,
    why: null,
    state: { run_id: 'r', team: 'Web app', recipe: 'Build then test', status: 'stopped' as const, why: 'rule broken: Test it was not done', steps: [], agents: ['c'], ended_ready: false, passes: [] },
  }
  const state = convState({
    conversation: { ...convState().conversation, teams_mode: 'manual', teams: [stopped] },
    runs: [run('r', 'completed')],
    messages: said('r'),
    agents: [agent('r', 'completed'), agent('r', 'completed', { id: 'c', depth: 1 })],
    fileChanges: [fileChange('f1', 'r', { agent_id: 'c', status: 'in_copy' })],
  })
  render(<MessageList state={state} onRemoveQueued={() => {}} onOpenChange={() => {}} onDecide={noop} onDecideCommand={noop} />)
  const line = screen.getByRole('region', { name: WORK })
  await userEvent.click(within(line).getByRole('button', { name: 'details ▸' }))
  expect(within(line).getByText('Web app: rule broken: Test it was not done. Take in also takes in what Web app left before it stopped.')).toBeInTheDocument()
})
