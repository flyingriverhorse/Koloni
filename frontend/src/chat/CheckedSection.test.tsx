import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Message } from '../api/types'
import { useApp } from '../state/store'
import { assistantMessage, convState } from '../test-fixtures'
import { FIX_IT, checkedOf } from './checked'
import { CheckedSection } from './CheckedSection'

type Row = NonNullable<Message['checked']>[number]
const row = (state: Row['state'], text: string, more: Partial<Row> = {}): Row => ({ kind: 'tests', state, text, command: null, guessed: false, started_at: null, ...more })
const checked = (rows: Row[]): Message => ({ ...assistantMessage('k', 'r', rows.map(one => one.text).join('\n')), role: 'checked', agent_id: null, checked: rows })

const FAILED = row('failed', 'Tests failed: pytest -q - 1 failed, 3 passed', { command: 'pytest -q' })

test('renders one line a row with its state', () => {
  render(<CheckedSection message={checked([row('passed', 'Tests passed: pytest -q - 4 passed'), FAILED, row('not_run', 'No test command: nothing was run'), row('note', 'Sent back to fix: 1 of 2 rounds', { kind: 'rounds' })])} over latest={false} />)
  const section = screen.getByRole('region', { name: 'Checked' })
  const lines = Array.from(section.querySelectorAll('li'))
  expect(lines.map(line => [line.dataset.state, line.textContent])).toEqual([
    ['passed', '✓Tests passed: pytest -q - 4 passed'],
    ['failed', '✗Tests failed: pytest -q - 1 failed, 3 passed'],
    ['not_run', '–No test command: nothing was run'],
    ['note', '–Sent back to fix: 1 of 2 rounds'],
  ])
})

test('says guessed as a tag', () => {
  render(<CheckedSection message={checked([row('passed', 'Tests passed: npm test (guessed) - 5 passed', { guessed: true, command: 'npm test' })])} over latest />)
  expect(screen.getByText('guessed')).toHaveClass('tag')
})

test('shows Fix it only on the latest turn with a failed tests row', async () => {
  const send = vi.fn().mockResolvedValue(undefined)
  useApp.setState({ send })
  const { rerender } = render(<CheckedSection message={checked([FAILED])} over latest={false} />)
  expect(screen.queryByRole('button', { name: 'Fix it' })).toBeNull()
  rerender(<CheckedSection message={checked([row('passed', 'Tests passed: pytest -q - 4 passed', { command: 'pytest -q' })])} over latest />)
  expect(screen.queryByRole('button', { name: 'Fix it' })).toBeNull()
  rerender(<CheckedSection message={checked([FAILED])} over latest />)
  await userEvent.click(screen.getByRole('button', { name: 'Fix it' }))
  expect(send).toHaveBeenCalledWith(FIX_IT('pytest -q'))
  expect(FIX_IT('pytest -q')).toBe('The tests KOLONİ ran at the end of the last turn failed: `pytest -q`. Fix what fails.')
})

test('nothing without a checked message, or while the turn runs', () => {
  const { container, rerender } = render(<CheckedSection message={undefined} over latest />)
  expect(container).toBeEmptyDOMElement()
  rerender(<CheckedSection message={checked([FAILED])} over={false} latest />)
  expect(container).toBeEmptyDOMElement()
  const state = convState({ messages: [assistantMessage('a', 'r', 'done'), checked([FAILED])] })
  expect(checkedOf(state, 'r')?.id).toBe('k')
  expect(checkedOf(state, 'other')).toBeUndefined()
})
