import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { RecordRow, Sign } from '../api/types'
import { recordLine, recordSummary, rediscoveryLine } from './record'
import { Quiet, SignChip, Since } from './signs'

const sign: Sign = {
  kind: 'same_failure',
  count: 3,
  text: 'read_file failed 3 times with the same arguments and the same error, with no change applied and no command succeeding in between.',
}

beforeEach(() => {
  localStorage.clear()
  vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] })
  vi.setSystemTime(new Date('2026-10-14T12:00:00Z'))
})

afterEach(() => vi.useRealTimers())

const chip = () => screen.queryByRole('button', { name: '3× same error' })

test('a sign is a chip with the counted sentence, and its answers are kept in this browser', () => {
  render(<SignChip agentId="a1" sign={sign} />)
  expect(chip()).toHaveAttribute('title', sign.text)
  fireEvent.click(screen.getByRole('button', { name: 'Snooze 10 min', hidden: true }))
  expect(chip()).toBeNull()
  // ten minutes on, it is back; "it's fine" puts it away for thirty
  act(() => vi.advanceTimersByTime(10 * 60_000 + 1))
  expect(chip()).not.toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'It’s fine', hidden: true }))
  act(() => vi.advanceTimersByTime(29 * 60_000))
  expect(chip()).toBeNull()
  act(() => vi.advanceTimersByTime(2 * 60_000))
  expect(chip()).not.toBeNull()
})

test('a sign not to be shown for an agent stays away for that agent only', () => {
  const { unmount } = render(<SignChip agentId="a1" sign={sign} />)
  fireEvent.click(screen.getByRole('button', { name: 'Don’t show for this agent', hidden: true }))
  act(() => vi.advanceTimersByTime(24 * 60 * 60_000))
  expect(chip()).toBeNull()
  unmount()
  render(<SignChip agentId="a2" sign={sign} />)
  expect(chip()).not.toBeNull()
})

test('quiet is the time measured since the last event: its last step while it moves; past 5 minutes no tool or step - not "stuck", a model may be writing; slow past 20 inside a tool (R53 G6)', () => {
  const at = new Date(Date.now() - 12_000).toISOString()
  const { rerender } = render(<Quiet lastEventAt={at} inTool={false} />)
  expect(screen.getByText('last step 12s ago')).toBeInTheDocument()
  act(() => vi.advanceTimersByTime(6 * 60_000))
  expect(screen.getByText('no tool or step for 6 min')).toBeInTheDocument()
  expect(screen.queryByText(/stuck/)).toBeNull()
  // A tool may take that long: not stuck; how long it has run is said with it.
  rerender(<Quiet lastEventAt={at} inTool />)
  expect(screen.queryByText(/ago|for 6 min/)).toBeNull()
  act(() => vi.advanceTimersByTime(15 * 60_000))
  expect(screen.getByText('slow · no tool event for 21 min')).toBeInTheDocument()
  // Nothing on record: nothing said.
  rerender(<Quiet lastEventAt={null} inTool />)
  expect(screen.queryByText(/ago|min/)).toBeNull()
})

test('an agent’s work time counts from its record’s start (R53 G6)', () => {
  render(<Since at={new Date(Date.now() - 72_000).toISOString()} work />)
  expect(screen.getByText('at work 1m 12s')).toBeInTheDocument()
})

test('the record says what is unknown as unknown, never as a zero', () => {
  const row: RecordRow = {
    role_name: 'Coder',
    provider_name: 'Local',
    model_id: 'qwen',
    agents: 3,
    ended: { done: 2, failed: 1, stopped_by_koloni: 0, stopped_by_user: 0, interrupted: 0 },
    steps: 4.5,
    seconds: 42,
    input_tokens: null,
    output_tokens: null,
    changes: { taken: 1, rejected: 0 },
    compared: { chosen: 0, not_chosen: 0 },
    rediscovery: null,
    taken_in: 2, turned_down: 0, cost: null,
  }
  expect(recordLine(row, true)).toBe(
    'Coder on Local · qwen: 3 ran - 2 done, 1 failed. Middle one: 4.5 steps, 42 s, tokens sent none recorded, written none recorded. Changes: 1 taken, 0 rejected.',
  )
})

test("a role's record reads as one short line in the list, all its models together", () => {
  const row = (model_id: string, done: number, failed: number): RecordRow => ({
    role_name: 'Lead', provider_name: 'Local', model_id, agents: done + failed,
    ended: { done, failed, stopped_by_koloni: 0, stopped_by_user: 0, interrupted: 0 },
    steps: null, seconds: null, input_tokens: null, output_tokens: null, changes: { taken: 0, rejected: 0 }, compared: { chosen: 0, not_chosen: 0 },
    rediscovery: null, taken_in: done, turned_down: 0, cost: null,
  })
  expect(recordSummary([row('a', 29, 0), row('b', 20, 1)])).toBe('50 ran on 2 models · 49 done · 1 failed')
  expect(recordSummary([row('a', 3, 0)])).toBe('3 ran · 3 done')
  // K-devir-0: the reads before the first write, over the agents that have it on record; nothing where none has
  expect(rediscoveryLine([row('a', 3, 0)])).toBe('')
  expect(rediscoveryLine([{ ...row('a', 3, 0), rediscovery: { mean: 6.5, agents: 2 } }, { ...row('b', 1, 0), rediscovery: { mean: 2, agents: 1 } }])).toBe(
    'Reads before the first write: 5 · 3 agents',
  )
})

test('the panel says its work was stopped only where it was', () => {
  const { rerender } = render(<SignChip agentId="a1" sign={sign} />)
  expect(screen.getByText(/Nothing was stopped for it\./)).toBeInTheDocument()
  rerender(<SignChip agentId="a1" sign={sign} stopped />)
  expect(screen.queryByText(/Nothing was stopped/)).toBeNull()
  expect(screen.getByText(/Its work was stopped for it: nobody watched this turn\./)).toBeInTheDocument()
})

test('after an answer, focus goes to the row the sign was on', () => {
  render(
    <ul>
      <li tabIndex={-1} data-testid="row">
        <SignChip agentId="a1" sign={sign} />
      </li>
    </ul>,
  )
  fireEvent.click(screen.getByRole('button', { name: 'Snooze 10 min', hidden: true }))
  expect(screen.getByTestId('row')).toHaveFocus()
})
