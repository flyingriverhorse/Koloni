import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { NotesOffer } from '../api/types'
import { NotesOfferCard } from './NotesOfferCard'

// K-bilgi 6: "Add to Project notes?" under a turn - answered whenever you like, every item ticked at first.
const LINES = ["Coder's report (its words): the total skipped tax - fixed: added it", 'docs/api.md was changed', "Coder's report (its words): a typo - fixed: spelled"]
const OFFER: NotesOffer = { id: 'o1', run_id: 'r1', lines: LINES, status: 'waiting', answer: null }

test('a tick for each item; Add sends the lines shown and the ticked ones, Not now none', async () => {
  const onAnswer = vi.fn().mockResolvedValue(undefined)
  render(<NotesOfferCard offer={OFFER} onAnswer={onAnswer} />)
  const ticks = screen.getAllByRole('checkbox')
  expect(ticks).toHaveLength(3)
  expect(ticks.every(one => (one as HTMLInputElement).checked)).toBe(true)
  await userEvent.click(screen.getByLabelText('docs/api.md was changed'))
  await userEvent.click(screen.getByRole('button', { name: 'Add' }))
  expect(onAnswer).toHaveBeenLastCalledWith(LINES, [LINES[0], LINES[2]])
  await userEvent.click(screen.getByRole('button', { name: 'Not now' }))
  expect(onAnswer).toHaveBeenLastCalledWith(LINES, [])
})

test('a tick follows its item, not its place, when the offer grows; a refusal is said', async () => {
  const onAnswer = vi.fn().mockRejectedValue(new ApiError(409, 'the offer changed since your card showed it: look at it again'))
  const { rerender } = render(<NotesOfferCard offer={OFFER} onAnswer={onAnswer} />)
  await userEvent.click(screen.getByLabelText('docs/api.md was changed'))
  const grown = { ...OFFER, lines: ['docs/new.md was changed', ...LINES] }
  rerender(<NotesOfferCard offer={grown} onAnswer={onAnswer} />)
  expect(screen.getByLabelText('docs/api.md was changed')).not.toBeChecked()
  expect(screen.getByLabelText('docs/new.md was changed')).toBeChecked()
  await userEvent.click(screen.getByRole('button', { name: 'Add' }))
  expect(onAnswer).toHaveBeenLastCalledWith(grown.lines, ['docs/new.md was changed', LINES[0], LINES[2]])
  expect(await screen.findByRole('alert')).toHaveTextContent('the offer changed')
})

test('an answered offer is one line', () => {
  const { rerender } = render(<NotesOfferCard offer={{ ...OFFER, status: 'added', answer: 'added 2 of 3' }} onAnswer={vi.fn()} />)
  expect(screen.getByText('Project notes: added 2 of 3.')).toBeInTheDocument()
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  rerender(<NotesOfferCard offer={{ ...OFFER, status: 'discarded', answer: 'not now' }} onAnswer={vi.fn()} />)
  expect(screen.getByText('Not added to Project notes.')).toBeInTheDocument()
})
