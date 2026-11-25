import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Cards } from '../api/types'
import { CardsSection } from './CardsSection'

const cards = (over: Partial<Cards> = {}): Cards => ({
  asked: 7,
  approved: 4,
  rejected: 1,
  unanswered: 2,
  by_reason: [
    { reason: 'delete', said: 'Deletes or overwrites', asked: 5, approved: 4, rejected: 1, unanswered: 0 },
    { reason: 'rule', said: 'No rule covers it', asked: 2, approved: 0, rejected: 0, unanswered: 2 },
  ],
  decide_seconds: 12.4,
  checked: { run: 3, refuse: 1, ask: 2 },
  suggestions: [],
  ...over,
})
const SUGGESTED = { key: 'k1', command: 'rm -rf build', cwd: '.', times: 5, rule: 'You may delete ./build.' }

test('the cards Full auto’s judge opened are a row of their own, by the server’s name for them', async () => {
  const judge = { reason: 'judge', said: "Full auto's judge found it risky", asked: 3, approved: 1, rejected: 2 }
  const onLoad = vi.fn().mockResolvedValue(cards({ by_reason: [{ ...judge, unanswered: 0 }] }))
  render(<CardsSection projectId="p" period="7" onLoad={onLoad} />)
  const table = await screen.findByRole('table', { name: 'Cards by reason' })
  expect(
    within(table)
      .getAllByRole('row')
      .map(row => row.textContent),
  ).toEqual(['Why it was askedAskedApprovedRejected', "Full auto's judge found it risky312"])
})

test('Cards says the period’s cards, answered how and why, and what Check what I said first did', async () => {
  const onLoad = vi.fn().mockResolvedValue(cards())
  const { unmount } = render(<CardsSection projectId="p" period="7" onLoad={onLoad} />)
  const section = await screen.findByRole('region', { name: 'Cards' })
  expect(
    await within(section).findByText('7 asked: 4 approved, 1 rejected, 2 not answered · 12 s to answer, on average'),
  ).toBeVisible()
  const rows = within(within(section).getByRole('table', { name: 'Cards by reason' })).getAllByRole('row')
  expect(rows.map(row => row.textContent)).toEqual([
    'Why it was askedAskedApprovedRejected',
    'Deletes or overwrites541',
    'No rule covers it200',
  ])
  expect(
    within(section).getByText('Check what I said first: 3 ran on a line of yours · 1 not run · 2 still asked'),
  ).toBeVisible()
  expect(onLoad).toHaveBeenCalledWith('p', expect.any(String))
  expect(within(section).queryByRole('button', { name: 'Add to rules' })).toBeNull()
  unmount()
  render(<CardsSection projectId="p" period="7" onLoad={vi.fn().mockResolvedValue(cards({ decide_seconds: 150 }))} />)
  expect(await screen.findByText(/3 min to answer, on average$/)).toBeVisible()
})

test('a period with no card says so, and no average where none was answered', async () => {
  render(
    <CardsSection
      projectId={null}
      period="all"
      onLoad={vi.fn().mockResolvedValue(
        cards({
          asked: 0,
          approved: 0,
          rejected: 0,
          unanswered: 0,
          by_reason: [],
          decide_seconds: null,
          checked: { run: 0, refuse: 0, ask: 0 },
        }),
      )}
    />,
  )
  expect(await screen.findByText('No command card was asked in this period.')).toBeVisible()
  expect(screen.queryByText(/Check what I said first:/)).toBeNull()
})

test('a suggested rule says the command, how often, and KOLONİ’s line; one click adds it, by its key', async () => {
  const onLoad = vi
    .fn()
    .mockResolvedValueOnce(cards({ suggestions: [SUGGESTED] }))
    .mockResolvedValue(cards())
  const onAdd = vi.fn().mockResolvedValue(undefined)
  render(<CardsSection projectId="p" period="30" onLoad={onLoad} onAdd={onAdd} />)
  const line = await screen.findByText(/^You approved/)
  expect(line).toHaveTextContent(
    'You approved rm -rf build 5 times - add “You may delete ./build.” to this project’s rules? Add to rules',
  )
  await userEvent.click(within(line).getByRole('button', { name: 'Add to rules' }))
  expect(onAdd).toHaveBeenCalledWith('p', 'k1')
  // (read again: once in the rules, it is suggested no more)
  await vi.waitFor(() => expect(screen.queryByText(/^You approved/)).toBeNull())
  expect(onLoad).toHaveBeenCalledTimes(2)
})

test('a refused click is said, and the suggestion stays', async () => {
  const onAdd = vi.fn().mockRejectedValue(new Error('origin not allowed'))
  render(
    <CardsSection
      projectId="p"
      period="30"
      onLoad={vi.fn().mockResolvedValue(cards({ suggestions: [SUGGESTED] }))}
      onAdd={onAdd}
    />,
  )
  await userEvent.click(await screen.findByRole('button', { name: 'Add to rules' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('origin not allowed')
  expect(screen.getByText(/^You approved/)).toBeVisible()
})
