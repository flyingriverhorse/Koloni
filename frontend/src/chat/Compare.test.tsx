import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { Compare, CompareSide, Merge, Provider } from '../api/types'
import { resetStoreForTests } from '../state/store'
import { assistantMessage, convState, run, toolCall, userMessage } from '../test-fixtures'
import { Composer } from './Composer'
import { MessageList } from './MessageList'

afterEach(() => resetStoreForTests())

const provider = (id: string, name: string): Provider => ({
  id, name, kind: 'openai_compat', base_url: 'http://x/v1', default_model: `${name.toLowerCase()}-1`, executable: null, mode: null, options: null,
  for_agents: true, note: null, models: [], only_listed: false, max_running: null, plan: false, step_down_at: null, day_limit: null, month_limit: null, has_key: false, position: 0, created_at: 't', updated_at: 't',
})
const providers = [provider('pa', 'Alpha'), provider('pb', 'Beta')]

const composer = (onCompare: () => Promise<void>) => (
  <Composer running={false} permissionMode="ask" onSend={vi.fn()} onStop={vi.fn()} onPermissionMode={vi.fn()} compare={{ providers, first: 'Alpha · alpha-1', onCompare }} />
)

test('Compare under More takes the message in the box to a second model, and clears the box', async () => {
  const onCompare = vi.fn().mockResolvedValue(undefined)
  render(composer(onCompare))
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, 'make greeting.txt')
  await userEvent.click(screen.getByRole('button', { name: 'More' }))
  await userEvent.click(screen.getByRole('button', { name: 'Compare…' }))
  const form = screen.getByRole('form', { name: 'Compare two models' })
  expect(within(form).getByText('First: Alpha · alpha-1')).toBeInTheDocument()
  expect(within(form).getByRole('button', { name: 'Compare' })).toBeDisabled() // no second model yet
  await userEvent.selectOptions(within(form).getByLabelText('Second model’s provider'), 'Beta')
  await userEvent.click(within(form).getByRole('button', { name: 'Compare' }))
  expect(onCompare).toHaveBeenCalledWith('make greeting.txt', { provider_id: 'pb', model_id: null }, false)
  expect(box).toHaveValue('')
  expect(screen.queryByRole('form', { name: 'Compare two models' })).not.toBeInTheDocument()
})

test('/compare opens it, the message written there; what the server refuses is said in it', async () => {
  const onCompare = vi.fn().mockRejectedValue(new Error('Beta runs only with the models listed for it'))
  render(composer(onCompare))
  await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), '/compare{Enter}')
  const form = screen.getByRole('form', { name: 'Compare two models' })
  await userEvent.type(within(form).getByLabelText('Message'), 'hi')
  await userEvent.selectOptions(within(form).getByLabelText('Second model’s provider'), 'Beta')
  await userEvent.click(within(form).getByRole('button', { name: 'Compare' }))
  expect(within(form).getByRole('alert')).toHaveTextContent('listed for it')
})

test('over the budget, the message box’s card asks; Go on anyway compares again with the word', async () => {
  const onCompare = vi.fn().mockRejectedValueOnce(new ApiError(409, "this project is over this month's budget: say to go on over it")).mockResolvedValue(undefined)
  render(composer(onCompare))
  const box = screen.getByRole('textbox', { name: 'Message' })
  await userEvent.type(box, 'make greeting.txt')
  await userEvent.click(screen.getByRole('button', { name: 'More' }))
  await userEvent.click(screen.getByRole('button', { name: 'Compare…' }))
  const form = screen.getByRole('form', { name: 'Compare two models' })
  await userEvent.selectOptions(within(form).getByLabelText('Second model’s provider'), 'Beta')
  await userEvent.click(within(form).getByRole('button', { name: 'Compare' }))
  const card = screen.getByRole('group', { name: 'Over this month’s budget' })
  expect(box).toHaveValue('make greeting.txt') // nothing sent yet
  await userEvent.click(within(card).getByRole('button', { name: 'Go on anyway' }))
  expect(onCompare).toHaveBeenLastCalledWith('make greeting.txt', { provider_id: 'pb', model_id: null }, false, true)
  expect(box).toHaveValue('')
  expect(screen.queryByRole('group', { name: 'Over this month’s budget' })).not.toBeInTheDocument()
})

const side = (runId: string, providerId: string, model: string, answer: string, over: Partial<CompareSide> = {}): CompareSide => ({
  run_id: runId, provider_id: providerId, model_id: model, status: 'completed', answer, error: null,
  changed_files: ['greeting.txt'], kept: true, input_tokens: 21, output_tokens: 8, cost: null, seconds: 3.2, ...over,
})
const kept = (id: string, runId: string): Merge => ({
  id, run_id: runId, agent_id: `lead-${runId}`, status: 'interrupted', kept_in: 'x', check: null, commit: null, created_at: 't', decided_at: 't',
  files: [{ path: 'greeting.txt', kind: 'new', state: 'ready', diff: '--- a\n+++ b\n@@ -0,0 +1 @@\n+hello\n', additions: 1, deletions: 0, note: null }],
} as Merge)

test('the two sides stand side by side, the message once; one is used, or both thrown away', async () => {
  const ready: Compare = { id: 'k', conversation_id: 'c', status: 'ready', chosen_run_id: null, sides: [side('a', 'pa', 'alpha-1', 'Alpha made it.'), side('b', 'pb', 'beta-1', 'Beta made it.')] }
  const onLoad = vi.fn().mockResolvedValue(ready)
  const onDecide = vi.fn().mockResolvedValue({ ...ready, status: 'chosen', chosen_run_id: 'b', sides: [side('a', 'pa', 'alpha-1', 'Alpha made it.', { kept: false }), side('b', 'pb', 'beta-1', 'Beta made it.', { kept: false })] })
  const state = convState({
    runs: [run('a', 'completed', { compare_id: 'k' }), run('b', 'completed', { compare_id: 'k' })],
    messages: [userMessage('a', 'make greeting.txt'), userMessage('b', 'make greeting.txt')],
    merges: [kept('ma', 'a'), kept('mb', 'b')],
  })
  render(<MessageList state={state} providers={providers} onRemoveQueued={vi.fn()} onOpenChange={vi.fn()} onDecide={vi.fn()} onDecideCommand={vi.fn()} onLoadCompare={onLoad} onDecideCompare={onDecide} />)
  expect(await screen.findByRole('region', { name: 'Alpha · alpha-1' })).toHaveTextContent('Alpha made it.')
  expect(screen.getAllByText('make greeting.txt')).toHaveLength(1)
  const beta = screen.getByRole('region', { name: 'Beta · beta-1' })
  expect(beta).toHaveTextContent('in 21 · out 8')
  expect(beta).toHaveTextContent('Cost –')
  expect(within(beta).getByText('View diff')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Use Beta’s work' }))
  expect(onDecide).toHaveBeenCalledWith('k', 'b')
  // (the cards still waiting in the chat's record until their events come: the answer is what counts)
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Beta’s work was taken'))
  expect(screen.queryByRole('button', { name: 'Discard both' })).not.toBeInTheDocument()
})

test('a side that failed says why; one that left nothing is not offered; what was not all taken stays on its card', async () => {
  const failed = side('a', 'pa', 'alpha-1', '', { status: 'failed', error: 'the model server is down', changed_files: [], kept: false })
  const stopped = side('b', 'pb', 'beta-1', '', { status: 'cancelled', changed_files: [], kept: false })
  const onLoad = vi.fn().mockResolvedValue({ id: 'k', conversation_id: 'c', status: 'ready', chosen_run_id: null, sides: [failed, stopped] })
  const state = convState({
    runs: [run('a', 'failed', { compare_id: 'k' }), run('b', 'cancelled', { compare_id: 'k' })],
    messages: [userMessage('a', 'go'), userMessage('b', 'go')],
  })
  const view = (s = state) => <MessageList state={s} providers={providers} onRemoveQueued={vi.fn()} onOpenChange={vi.fn()} onDecide={vi.fn()} onDecideCommand={vi.fn()} onLoadCompare={onLoad} onDecideCompare={vi.fn()} />
  const { unmount } = render(view())
  const alpha = await screen.findByRole('region', { name: 'Alpha · alpha-1' })
  expect(alpha).toHaveTextContent('Why it failed: the model server is down')
  expect(alpha).not.toHaveTextContent('still yours to pick')
  expect(screen.queryByRole('button', { name: /^Use / })).not.toBeInTheDocument()
  unmount()

  // chosen, but a file of it moved since: its card stays, and nothing says it was taken
  const chosen = side('a', 'pa', 'alpha-1', 'Alpha made it.', { kept: true })
  onLoad.mockResolvedValue({ id: 'k', conversation_id: 'c', status: 'chosen', chosen_run_id: 'a', sides: [chosen, side('b', 'pb', 'beta-1', 'b', { kept: false })] })
  render(view({ ...state, merges: [kept('ma', 'a')] }))
  expect(await screen.findByRole('status')).toHaveTextContent('Not all of it could be taken yet: decide on its card.')
  expect(screen.queryByText(/work was taken/)).not.toBeInTheDocument()
})

test('a comparison goes to a new topic when the box’s line says so, as a message does', async () => {
  const onCompare = vi.fn().mockResolvedValue(undefined)
  render(<Composer running={false} permissionMode="ask" topic="new" onSend={vi.fn()} onStop={vi.fn()} onPermissionMode={vi.fn()} compare={{ providers, first: 'Alpha · alpha-1', onCompare }} />)
  await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), 'go')
  await userEvent.click(screen.getByRole('button', { name: 'More' }))
  await userEvent.click(screen.getByRole('button', { name: 'Compare…' }))
  const form = screen.getByRole('form', { name: 'Compare two models' })
  await userEvent.selectOptions(within(form).getByLabelText('Second model’s provider'), 'Beta')
  await userEvent.click(within(form).getByRole('button', { name: 'Compare' }))
  expect(onCompare).toHaveBeenCalledWith('go', { provider_id: 'pb', model_id: null }, true)
})

test('while they work both can be thrown away; a side in two currencies says each', async () => {
  const two = side('a', 'pa', 'alpha-1', '', { status: 'running', cost: [{ amount: 0.75, currency: 'USD' }, { amount: 1, currency: 'EUR', at_least: true }] })
  const running: Compare = { id: 'k', conversation_id: 'c', status: 'running', chosen_run_id: null, sides: [two, side('b', 'pb', 'beta-1', '', { status: 'queued' })] }
  const onDecide = vi.fn().mockResolvedValue({ ...running, status: 'discarded' })
  const state = convState({
    runs: [run('a', 'running', { compare_id: 'k' }), run('b', 'queued', { compare_id: 'k' })],
    messages: [userMessage('a', 'go'), userMessage('b', 'go')],
  })
  render(<MessageList state={state} providers={providers} onRemoveQueued={vi.fn()} onOpenChange={vi.fn()} onDecide={vi.fn()} onDecideCommand={vi.fn()} onLoadCompare={vi.fn().mockResolvedValue(running)} onDecideCompare={onDecide} />)
  expect(await screen.findByRole('region', { name: 'Alpha · alpha-1' })).toHaveTextContent('Cost ≈ 0.75 USD + ≥ 1.00 EUR')
  await userEvent.click(screen.getByRole('button', { name: 'Discard both' }))
  expect(onDecide).toHaveBeenCalledWith('k', null)
  expect(await screen.findByRole('status')).toHaveTextContent('Both were thrown away')
})

test('once one is used, the other side’s rows are one closed row, and the pick can be undone', async () => {
  const chosen: Compare = { id: 'k', conversation_id: 'c', status: 'chosen', chosen_run_id: 'b', sides: [side('a', 'pa', 'alpha-1', 'a', { kept: false }), side('b', 'pb', 'beta-1', 'b', { kept: false })] }
  const state = convState({
    runs: [run('a', 'completed', { compare_id: 'k' }), run('b', 'completed', { compare_id: 'k' })],
    messages: [userMessage('a', 'go'), userMessage('b', 'go'), assistantMessage('ma', 'a', 'a'), assistantMessage('mb', 'b', 'b')],
    toolCalls: [
      toolCall('ca', 'a', 'read_file', 'succeeded', '{"path":"alpha.py"}', { message_id: 'ma' }),
      toolCall('cb', 'b', 'read_file', 'succeeded', '{"path":"beta.py"}', { message_id: 'mb' }),
    ],
  })
  const { container } = render(<MessageList state={state} providers={providers} onRemoveQueued={vi.fn()} onOpenChange={vi.fn()} onDecide={vi.fn()} onDecideCommand={vi.fn()} onLoadCompare={vi.fn().mockResolvedValue(chosen)} onDecideCompare={vi.fn()} />)
  const folded = (await screen.findByText('The other side (not used)')).closest('details')!
  expect(folded).not.toHaveAttribute('open')
  expect(folded).toHaveTextContent('alpha.py')
  expect(container.querySelectorAll('details.tool-run')).toHaveLength(1) // the used side's rows stand as they were
  expect(screen.getByText(/beta\.py/)).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'Undo these changes' }))
  expect(screen.getByRole('region', { name: 'Undo these changes' })).toBeInTheDocument()
})
