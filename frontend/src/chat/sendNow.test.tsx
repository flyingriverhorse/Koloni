import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { resetStoreForTests, useApp } from '../state/store'
import { convState, run } from '../test-fixtures'
import { Composer } from './Composer'

afterEach(() => {
  resetStoreForTests()
  vi.unstubAllGlobals()
})

const props = {
  running: true,
  permissionMode: 'ask' as const,
  onSend: vi.fn().mockResolvedValue(null),
  onStop: vi.fn(),
  onPermissionMode: vi.fn(),
}

test('while a turn runs, Send now is Enter’s and goes into the turn; After this turn queues; with no turn, Send alone', async () => {
  const onSend = vi.fn().mockResolvedValue(null)
  const { rerender } = render(<Composer {...props} onSend={onSend} />)
  const box = screen.getByLabelText('Message')
  expect(box).toHaveAttribute('placeholder', 'Write to the Orchestrator - it reads it in this turn…')
  const now = screen.getByRole('button', { name: 'Send now' })
  const later = screen.getByRole('button', { name: 'After this turn' })
  expect(now).toHaveAttribute('title', 'Send now: the Orchestrator reads it in this turn')
  expect(later).toHaveAttribute('title', 'After this turn: it waits in the queue and starts its own turn')
  await userEvent.type(box, 'how is it going?{Enter}')
  expect(onSend).toHaveBeenLastCalledWith('how is it going?', false, undefined, undefined, true)
  await userEvent.type(box, 'then this')
  await userEvent.click(later)
  expect(onSend).toHaveBeenLastCalledWith('then this', false)
  await userEvent.type(box, 'and now')
  await userEvent.click(now)
  expect(onSend).toHaveBeenLastCalledWith('and now', false, undefined, undefined, true)
  expect(screen.queryByRole('status', { name: /Queued/ })).toBeNull()
  rerender(<Composer {...props} running={false} onSend={onSend} />)
  expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'After this turn' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Send now' })).toBeNull()
})

test('a word sent now that the turn does not take waits in the queue, and the box says why under it', async () => {
  const onSend = vi.fn().mockResolvedValue('this turn takes no message now (a plan turn)')
  render(<Composer {...props} onSend={onSend} />)
  await userEvent.type(screen.getByLabelText('Message'), 'one more thing{Enter}')
  expect(await screen.findByText('Queued: this turn takes no message now (a plan turn)')).toHaveAttribute(
    'role',
    'status',
  )
  // (The next word sent says its own.)
  onSend.mockResolvedValueOnce(null)
  await userEvent.type(screen.getByLabelText('Message'), 'more{Enter}')
  expect(screen.queryByText(/^Queued:/)).toBeNull()
})

test('the store sends now: true and gives back why it was queued', async () => {
  const posted = vi.fn(
    async () =>
      new Response(JSON.stringify({ message: {}, run: {}, queued_why: 'the turn was ending' }), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }),
  )
  vi.stubGlobal('fetch', posted)
  useApp.setState({ conv: convState({ runs: [run('r', 'running')] }) })
  expect(await useApp.getState().send('hi', { now: true })).toBe('the turn was ending')
  expect(posted).toHaveBeenCalledWith(
    '/api/conversations/c/messages',
    expect.objectContaining({ method: 'POST', body: JSON.stringify({ content: 'hi', now: true }) }),
  )
})
