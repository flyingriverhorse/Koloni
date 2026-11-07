import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import { run } from '../test-fixtures'
import { PlanCard } from './PlanCard'

const proposed = (strongest = true) =>
  run('p', 'completed', { plan_turn: true, plan: { text: '1. read\n2. write', status: 'proposed', model_id: 'big-model', strongest } })

test('while the plan is written, the turn says nothing changes before it is approved', () => {
  render(<PlanCard run={run('p', 'running', { plan_turn: true })} onDecide={vi.fn()} />)
  expect(screen.getByRole('note')).toHaveTextContent('Writing a plan')
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

test('a plan turn still queued, or ended with no plan, has no card', () => {
  const { container, rerender } = render(<PlanCard run={run('p', 'queued', { plan_turn: true })} onDecide={vi.fn()} />)
  expect(container).toBeEmptyDOMElement()
  rerender(<PlanCard run={run('p', 'failed', { plan_turn: true })} onDecide={vi.fn()} />)
  expect(container).toBeEmptyDOMElement()
})

test('a proposed plan says which model wrote it, and is approved as it is', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  const { rerender } = render(<PlanCard run={proposed()} onDecide={onDecide} />)
  expect(screen.getByText(/big-model/)).toHaveTextContent('the team’s strongest model')
  await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
  expect(onDecide).toHaveBeenCalledWith('approve', undefined)
  rerender(<PlanCard run={proposed(false)} onDecide={onDecide} />)
  expect(screen.getByText(/big-model/)).toHaveTextContent('this conversation’s model')
})

test('Edit opens the plan in a box; what is approved is the edited text', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  render(<PlanCard run={proposed()} onDecide={onDecide} />)
  await userEvent.click(screen.getByRole('button', { name: 'Edit' }))
  const box = screen.getByRole('textbox', { name: 'Plan' })
  expect(box).toHaveValue('1. read\n2. write')
  await userEvent.type(box, '\n3. test')
  await userEvent.click(screen.getByRole('button', { name: 'Approve edited plan' }))
  expect(onDecide).toHaveBeenCalledWith('approve', '1. read\n2. write\n3. test')
})

test('over the budget the work waits for the user’s word: Cancel goes back to Approve, Go on keeps the edited plan', async () => {
  const onDecide = vi.fn().mockRejectedValueOnce(new ApiError(409, "this project is over this month's budget (13 of 12 USD): say to go on over it"))
  render(<PlanCard run={proposed()} onDecide={onDecide} />)
  await userEvent.click(screen.getByRole('button', { name: 'Edit' }))
  await userEvent.type(screen.getByRole('textbox', { name: 'Plan' }), '\n3. test')
  await userEvent.click(screen.getByRole('button', { name: 'Approve edited plan' }))
  const card = screen.getByRole('group', { name: 'Over this month’s budget' })
  expect(card).toHaveTextContent('Over this month’s budget. Start the work anyway?')
  expect(screen.getByRole('button', { name: 'Go on anyway' })).toHaveFocus()
  expect(screen.queryByText(/say to go on over it/)).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('group', { name: 'Over this month’s budget' })).toBeNull()
  expect(screen.getByRole('button', { name: 'Approve edited plan' })).toHaveFocus()
  onDecide.mockRejectedValueOnce(new ApiError(409, "this project is over this month's budget"))
  await userEvent.click(screen.getByRole('button', { name: 'Approve edited plan' }))
  onDecide.mockResolvedValueOnce(undefined)
  await userEvent.click(screen.getByRole('button', { name: 'Go on anyway' }))
  expect(onDecide).toHaveBeenLastCalledWith('approve', '1. read\n2. write\n3. test', true)
  expect(screen.queryByRole('group', { name: 'Over this month’s budget' })).toBeNull()
})

test('the card says it is approved here, and that a new message plans again', () => {
  render(<PlanCard run={proposed()} onDecide={vi.fn()} />)
  expect(screen.getByText('Approve here — a new message plans again.')).toBeInTheDocument()
})

test('Reject asks why first, then sends the reason if one is written; a refusal is said', async () => {
  const onDecide = vi.fn().mockRejectedValue(new ApiError(409, 'this turn has no plan waiting for a decision'))
  render(<PlanCard run={proposed()} onDecide={onDecide} />)
  expect(screen.queryByRole('textbox', { name: 'Why not (optional)' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Reject' }))
  expect(onDecide).not.toHaveBeenCalled()
  const why = screen.getByRole('textbox', { name: 'Why not (optional)' })
  expect(why).toHaveFocus()
  await userEvent.type(why, 'not now')
  await userEvent.click(screen.getByRole('button', { name: 'Reject plan' }))
  expect(onDecide).toHaveBeenCalledWith('reject', 'not now')
  expect(await screen.findByRole('alert')).toHaveTextContent('no plan waiting')
})

test('a plan a later turn has gone past can only be turned down, and says why', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  render(<PlanCard run={proposed()} stale onDecide={onDecide} />)
  expect(screen.getByText('A later message has started since this plan: reject it, or ask again.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Approve/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Reject' }))
  await userEvent.click(screen.getByRole('button', { name: 'Reject plan' }))
  expect(onDecide).toHaveBeenCalledWith('reject', undefined)
})

test('decided, the card stays on the record with what was decided', () => {
  const { rerender } = render(
    <PlanCard run={run('p', 'completed', { plan_turn: true, plan: { text: 'x', status: 'rejected', model_id: 'm', strongest: false, why: 'too big' } })} onDecide={vi.fn()} />,
  )
  expect(screen.getByRole('note')).toHaveTextContent('Plan rejected: too big')
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
  rerender(<PlanCard run={run('p', 'completed', { plan_turn: true, plan: { text: 'x', status: 'approved', model_id: 'm', strongest: false } })} onDecide={vi.fn()} />)
  expect(screen.getByRole('note')).toHaveTextContent('Plan approved')
})
