import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { Day } from '../api/types'
import { since } from './period'
import { TodayView } from './TodayView'

const day: Day = {
  turns: 3,
  agents: ['Coder', 'Lead'],
  changed_files: ['src/a.ts'],
  waiting: 1,
  failed: 1,
  input_tokens: 1200,
  output_tokens: null,
  tokens_at_least: true,
  cost: null,
  conversations: [
    {
      conversation_id: 'c1',
      title: 'Docs',
      turns: 2,
      changed_files: 1,
      failed: 1,
      files: [{ path: 'src/a.ts', change_id: 'fc1' }],
      failed_runs: [{ run_id: 'r2', error: 'the model refused' }],
    },
    { conversation_id: 'c2', title: 'Tests', turns: 1, changed_files: 0, failed: 0, files: [], failed_runs: [] },
  ],
}

function view(over: Partial<Parameters<typeof TodayView>[0]> = {}) {
  const props = {
    currentId: null,
    noteAt: null,
    onLoad: vi.fn().mockResolvedValue(day),
    onWords: vi.fn().mockResolvedValue({ text: 'Three turns, one failed.', provider_name: 'Local', model_id: 'qwen' }),
    ...over,
  }
  render(<TodayView {...props} />)
  return props
}

test('the day is read from this midnight here: what failed and the files changed, each once, from the record', async () => {
  const props = view()
  expect(props.onLoad).toHaveBeenCalledWith(since('today'))
  const today = await screen.findByRole('region', { name: 'Today' })
  const box = (label: string) => within(today).getByText(label).closest('div')!
  expect(box('Failed')).toHaveTextContent('Failed1message today')
  expect(box('Files changed')).toHaveTextContent('Files changed1in the project, each once')
  // No list of files, nor of chats: each chat's Workspace has its files, Ready what waits.
  expect(screen.queryByRole('table')).toBeNull()
  expect(screen.queryByText('src/a.ts')).toBeNull()
  expect(screen.getByText(/^Since midnight, counted from the record/)).toHaveTextContent('It can be sent each evening: project settings, Notifications.')
})

test('the day’s failed work is folded under its count: its error, and Show its work opens its turn', async () => {
  const onOpenTurn = vi.fn().mockRejectedValueOnce(new Error('conversation not found')).mockResolvedValue(undefined)
  view({ onOpenTurn })
  const fold = (await screen.findByText('Failed today (1)')).closest('details')!
  expect(fold).not.toHaveAttribute('open')
  const failed = within(fold).getByRole('list', { name: 'Work that failed' })
  expect(failed).toHaveTextContent('Docs')
  expect(failed).toHaveTextContent('the model refused')
  await userEvent.click(within(failed).getByRole('button', { name: 'Show the work that failed in Docs' }))
  expect(onOpenTurn).toHaveBeenCalledWith('c1', 'r2')
  expect(await within(fold).findByRole('alert')).toHaveTextContent('Not opened: conversation not found')
})

test('a day that cannot be read says why', async () => {
  view({ onLoad: vi.fn().mockRejectedValue(new Error('the server did not answer')) })
  expect(await screen.findByRole('alert')).toHaveTextContent('The day could not be read: the server did not answer')
})

test('"Say it in words" asks the open conversation’s model once, and its text is marked as the model’s', async () => {
  const props = view({ currentId: 'c2' })
  await userEvent.click(await screen.findByRole('button', { name: 'Say it in words' }))
  expect(props.onWords).toHaveBeenCalledTimes(1)
  expect(props.onWords).toHaveBeenCalledWith(since('today'), 'c2')
  // By the button, in sight: what it costs, what it is sent and whose model writes it without a fast one; how to have one, behind ⓘ.
  const button = screen.getByRole('button', { name: 'Say it in words' })
  expect(button).toHaveAccessibleDescription(/^A model sums up the day, once: a request you pay for, on the Usage page as KOLONİ itself\. .* A fast model writes this summary/)
  const note = screen.getByText(/^A model sums up the day/)
  expect(note).toHaveTextContent('It is sent the numbers above, the conversations’ titles, the changed files’ paths (the first 20) and the agents’ names.')
  expect(note).toHaveTextContent('With no fast model, the Orchestrator’s own model writes it, in the open conversation.')
  const hint = screen.getByText(/^A fast model writes this summary/)
  expect(hint).not.toBeVisible()
  expect(hint).toHaveTextContent('give a model the fast tier on the Models page and tick “Agents may choose this” for its provider')
  await userEvent.click(screen.getByRole('button', { name: 'About this' }))
  expect(hint).toBeVisible()
  const said = await screen.findByRole('figure', { name: /Model text/ })
  expect(said).toHaveTextContent('Three turns, one failed.')
  expect(said).toHaveTextContent('Local · qwen')
})

test('with no conversation open, "Say it in words" says whose Lead it asks: the latest of the day', async () => {
  const props = view()
  await userEvent.click(await screen.findByRole('button', { name: 'Say it in words' }))
  expect(props.onWords).toHaveBeenCalledWith(since('today'), 'c1')
  expect(screen.getByText(/^A model sums up the day/)).toHaveTextContent('“Docs”, the latest of the day: no conversation is open')
})

test('over the month’s budget, "Say it in words" says so and asks again only on "Go on anyway"', async () => {
  const over = "this project is over this month's budget (10.50 of 10.00 USD): say to go on over it"
  const onWords = vi
    .fn()
    .mockRejectedValueOnce(new ApiError(409, over))
    .mockResolvedValue({ text: 'A costly day.', provider_name: 'Local', model_id: 'qwen' })
  view({ currentId: 'c2', onWords })
  await userEvent.click(await screen.findByRole('button', { name: 'Say it in words' }))
  const card = screen.getByRole('group', { name: 'Over this month’s budget' })
  expect(within(card).getByRole('alert')).toHaveTextContent(over)
  expect(onWords).toHaveBeenCalledTimes(1)
  await userEvent.click(within(card).getByRole('button', { name: 'Go on anyway' }))
  expect(onWords).toHaveBeenLastCalledWith(since('today'), 'c2', true)
  expect(await screen.findByRole('figure', { name: /Model text/ })).toHaveTextContent('A costly day.')
  expect(screen.queryByRole('group', { name: 'Over this month’s budget' })).toBeNull()
})
