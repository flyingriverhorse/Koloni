import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { api } from '../api/client'
import type { Message } from '../api/types'
import { useApp } from '../state/store'
import { assistantMessage, convState } from '../test-fixtures'
import { FIX_IT, FIX_REVIEW, checkedOf } from './checked'
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

test('a whole suite gone on after the answer ticks its clock, and Stop this check stops it', async () => {
  vi.useFakeTimers({ now: Date.parse('2026-11-22T10:02:14Z'), toFake: ['Date', 'setInterval', 'clearInterval'] })
  try {
    const post = vi.spyOn(api, 'post').mockResolvedValue({} as never)
    const running = row('running', 'Full tests running: pytest -q', { command: 'pytest -q', started_at: '2026-11-22T10:00:00+00:00' })
    render(<CheckedSection message={checked([row('passed', 'Related tests passed: pytest -q t.py - 3 passed'), running])} over latest />)
    const line = () => screen.getByRole('region', { name: 'Checked' }).querySelector('[data-state=running]')
    expect(line()).toHaveTextContent('…Full tests running: pytest -q (2:14)')
    act(() => vi.advanceTimersByTime(3000))
    expect(line()).toHaveTextContent('(2:17)')
    await userEvent.click(screen.getByRole('button', { name: 'Stop this check' }), { advanceTimers: vi.advanceTimersByTime })
    expect(post).toHaveBeenCalledWith('/runs/r/check/stop')
  } finally {
    vi.useRealTimers()
    vi.restoreAllMocks()
  }
})

test('waiting for the machine it has no clock; with nothing running, no Stop', () => {
  const { rerender } = render(<CheckedSection message={checked([row('running', 'Full tests waiting for another test run to end: pytest -q')])} over latest />)
  expect(screen.getByRole('region', { name: 'Checked' })).not.toHaveTextContent('(0:')
  expect(screen.getByRole('button', { name: 'Stop this check' })).toBeVisible()
  rerender(<CheckedSection message={checked([FAILED])} over latest />)
  expect(screen.queryByRole('button', { name: 'Stop this check' })).toBeNull()
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

test('off for this chat: one line says so, nothing else', () => {
  render(<CheckedSection message={checked([row('note', 'Not checked: off for this chat', { kind: 'chat_off' })])} over latest />)
  const lines = Array.from(screen.getByRole('region', { name: 'Checked' }).querySelectorAll('li'))
  expect(lines.map(li => li.textContent)).toEqual(['–Not checked: off for this chat'])
  expect(screen.queryByRole('button', { name: 'Fix it' })).toBeNull()
})

test('a Reviewer that still held the change after the Fix rounds: Fix it asks for its blocking findings', async () => {
  const send = vi.fn().mockResolvedValue(undefined)
  useApp.setState({ send })
  render(
    <CheckedSection
      message={checked([
        row('passed', 'Tests passed: pytest -q - 4 passed', { command: 'pytest -q' }),
        row('failed', 'Review: Reviewer (Local · m) - HOLD, 2 findings, 1 blocking', { kind: 'review' }),
        row('note', 'Blocking: a.py:3 divides by zero', { kind: 'finding' }),
        row('note', 'Suggestion: name it better', { kind: 'finding' }),
        row('failed', 'Still on hold after 2 fix rounds: you decide (Fix it)', { kind: 'review' }),
      ])}
      over
      latest
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: 'Fix it' }))
  // (The user's words only: the findings, a model's, reach the Orchestrator as data.)
  expect(send).toHaveBeenCalledWith(FIX_REVIEW)
  expect(FIX_REVIEW).not.toContain('divides by zero')
})
