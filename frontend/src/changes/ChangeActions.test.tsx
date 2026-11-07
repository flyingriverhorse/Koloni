import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { fileChange } from '../test-fixtures'
import { ChangeActions } from './ChangeActions'

test('a proposed change can be approved; both buttons lock while the decision is sent', async () => {
  let finish: () => void = () => {}
  const onDecide = vi.fn(() => new Promise<void>(resolve => (finish = resolve)))
  render(<ChangeActions change={fileChange('f', 'r', { status: 'proposed' })} onDecide={onDecide} />)
  await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
  expect(onDecide).toHaveBeenCalledWith('approve')
  expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled()
  finish()
})

test('a proposed change can be rejected', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  render(<ChangeActions change={fileChange('f', 'r', { status: 'proposed' })} onDecide={onDecide} />)
  await userEvent.click(screen.getByRole('button', { name: 'Reject' }))
  expect(onDecide).toHaveBeenCalledWith('reject')
})

test('a change approved while its agent waits for a place says so and has nothing left to decide', () => {
  render(<ChangeActions change={fileChange('f', 'r', { status: 'approved' })} onDecide={vi.fn()} />)
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
  expect(
    screen.getByText(
      'Approved — it is made once its agent has a place among the agents at work. The approval cannot be taken back; Stop ends the work.',
    ),
  ).toBeInTheDocument()
})

test('an applied change offers only Revert', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  render(<ChangeActions change={fileChange('f', 'r', { status: 'applied' })} onDecide={onDecide} />)
  expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Revert' }))
  expect(onDecide).toHaveBeenCalledWith('revert')
})

test('a refused decision shows the reason and unlocks the button', async () => {
  const onDecide = vi
    .fn()
    .mockRejectedValue({ detail: 'hello.py has changed since this edit; revert it by hand' })
  render(<ChangeActions change={fileChange('f', 'r', { status: 'applied' })} onDecide={onDecide} />)
  await userEvent.click(screen.getByRole('button', { name: 'Revert' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('has changed since this edit')
  expect(screen.getByRole('button', { name: 'Revert' })).toBeEnabled()
})

test.each([
  ['rejected', 'Rejected'],
  ['reverted', 'Reverted'],
  ['conflict', 'Conflict — file changed on disk'],
  // Also what an approved change becomes when its turn ends before it is made: not "Rejected".
  ['discarded', 'Discarded — never made in the project: its working copy was thrown away, or you approved it and the work ended before it was made'],
] as const)('a %s change has no buttons and says "%s"', (status, label) => {
  render(<ChangeActions change={fileChange('f', 'r', { status })} onDecide={vi.fn()} />)
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
  expect(screen.getByText(label)).toBeInTheDocument()
})
