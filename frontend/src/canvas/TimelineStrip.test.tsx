import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { Usage } from '../api/types'
import { useApp } from '../state/store'
import { agent, convState, question, run, toolCall } from '../test-fixtures'
import { TimelineStrip } from './TimelineStrip'

const usage = { by_model: [{ model_id: 'qwen', cost: { amount: 0.42, currency: 'USD' } }], by_conversation: [], by_start: [] } as unknown as Usage
const read = vi.fn()
beforeEach(() => {
  localStorage.clear()
  read.mockReset().mockResolvedValue(usage)
  useApp.setState({ usage: read, prices: [] })
})
afterEach(() => vi.restoreAllMocks())

/** A turn that is over: the lead, a Reviewer it opened that waited for the user's answer, and the lead's CLI's own sub-agent. */
const state = convState({
  runs: [run('r', 'completed', { started_at: '2026-10-05T10:00:00Z', ended_at: '2026-10-05T10:01:40Z' })],
  agents: [
    agent('r', 'completed', { id: 'lead', name: 'Lead', ended_at: '2026-10-05T10:01:40Z', input_tokens: 1200, output_tokens: 300 }),
    agent('r', 'failed', {
      id: 'rev', name: 'Reviewer', role_name: 'Reviewer', parent_agent_id: 'lead', depth: 1,
      created_at: '2026-10-05T10:00:10Z', started_at: '2026-10-05T10:00:10Z', ended_at: '2026-10-05T10:01:00Z', input_tokens: 10, output_tokens: 1,
    }),
  ],
  toolCalls: [
    toolCall('2', 'r', 'claude__Agent', 'succeeded', '{"description":"Look around"}', { agent_id: 'lead', origin: 'cli', started_at: '2026-10-05T10:00:30Z', ended_at: '2026-10-05T10:00:50Z' }),
  ],
  questions: [question('q', 'r', { agent_id: 'rev', created_at: '2026-10-05T10:00:20Z', answered_at: '2026-10-05T10:00:32Z', status: 'answered' })],
})

test('the strip says the turn’s totals and each agent as a row of a table: start, length, waiting, status - a sub-agent under its lead', async () => {
  render(<TimelineStrip state={state} runId="r" onOpen={() => {}} onClose={() => {}} />)
  const strip = screen.getByRole('region', { name: 'Timeline' })
  for (const said of ['1m 40s', '2', 'in 1,210 · out 301']) expect(within(strip).getAllByText(said).length).toBeGreaterThan(0)
  const table = within(strip).getByRole('table', { name: 'Its agents in time' })
  // The drawing is not read out: no column of it is said, empty.
  expect(within(table).getAllByRole('columnheader').map(h => h.textContent)).toEqual(['Agent', 'Start', 'Length', 'Waiting', 'Status'])
  const rows = within(table).getAllByRole('row').slice(1)
  expect(rows.map(r => within(r).getAllByRole('cell').map(c => c.textContent))).toEqual([
    ['Orchestrator', '+0s', '1m 40s', 'none', 'done'],
    ['Look around', '+30s', '20s', 'none', 'done'],
    ['Reviewer', '+10s', '50s', 'waits for you 12s · question', 'failed'],
  ])
  // Drawn under the one that opened it; a CLI's own sub-agent dashed. Colour is not all that says it.
  expect(rows[2]).toHaveClass('tl-depth-1')
  expect(rows[1]).toHaveClass('tl-cli')
  // However many waits, the cell is cut to its width; what it says in full is in its title.
  expect(rows[2].querySelector('.tl-waits')).toHaveAttribute('title', 'waits for you 12s · question')
})

test('a click on an agent - its name or its bar - opens its window; a CLI’s own sub-agent opens its agent’s', async () => {
  const onOpen = vi.fn()
  render(<TimelineStrip state={state} runId="r" onOpen={onOpen} onClose={() => {}} />)
  await userEvent.click(screen.getByRole('button', { name: 'Reviewer' }))
  expect(onOpen).toHaveBeenLastCalledWith('rev')
  await userEvent.click(screen.getByRole('button', { name: 'Look around' }))
  expect(onOpen).toHaveBeenLastCalledWith('lead')
  fireEvent.click(document.querySelector('.tl-row:first-child .tl-bar')!)
  expect(onOpen).toHaveBeenLastCalledWith('lead')
})

test('the known cost is said once the turn is over and its usage read; while it works, a dash', async () => {
  render(<TimelineStrip state={state} runId="r" onOpen={() => {}} onClose={() => {}} />)
  expect(await screen.findByText('≈ 0.42 USD')).toBeInTheDocument()
  expect(read).toHaveBeenCalledWith(null, null, 'r')
  read.mockClear()
  const working = { ...state, runs: [{ ...state.runs[0], status: 'running' as const, ended_at: null }] }
  render(<TimelineStrip state={working} runId="r" onOpen={() => {}} onClose={() => {}} />)
  expect(within(screen.getAllByRole('region', { name: 'Timeline' })[1]).getByText('Known cost').nextElementSibling).toHaveTextContent('–')
  expect(read).not.toHaveBeenCalled()
})

test('its edge makes it taller or shorter - dragged, or with the arrow keys - and the height is kept; its own button closes it', async () => {
  const onClose = vi.fn()
  const { unmount } = render(<TimelineStrip state={state} runId="r" onOpen={() => {}} onClose={onClose} />)
  const edge = screen.getByRole('separator', { name: 'Timeline height' })
  const was = Number(edge.getAttribute('aria-valuenow'))
  edge.focus()
  await userEvent.keyboard('{ArrowUp}{ArrowUp}')
  await waitFor(() => expect(Number(edge.getAttribute('aria-valuenow'))).toBe(was + 48))
  await userEvent.keyboard('{ArrowDown}')
  expect(Number(edge.getAttribute('aria-valuenow'))).toBe(was + 24)
  unmount()
  render(<TimelineStrip state={state} runId="r" onOpen={() => {}} onClose={onClose} />)
  expect(Number(screen.getByRole('separator', { name: 'Timeline height' }).getAttribute('aria-valuenow'))).toBe(was + 24)
  await userEvent.click(screen.getByRole('button', { name: 'Close timeline' }))
  expect(onClose).toHaveBeenCalled()
})

test('as tall as the canvas leaves room for the windows over it: at most 60% of it and 330px under it; Home and End go to the ends; a kept height is cut to it', async () => {
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(function (this: HTMLElement) {
    return this.classList.contains('canvas') ? 700 : 0
  })
  localStorage.setItem('koloni-timeline-height', '600')
  render(
    <div className="canvas">
      <TimelineStrip state={state} runId="r" onOpen={() => {}} onClose={() => {}} />
    </div>,
  )
  const edge = screen.getByRole('separator', { name: 'Timeline height' })
  // 700 less 330 (under 60%: 420)
  expect([edge.getAttribute('aria-valuenow'), edge.getAttribute('aria-valuemax')]).toEqual(['370', '370'])
  edge.focus()
  await userEvent.keyboard('{Home}')
  expect(edge).toHaveAttribute('aria-valuenow', '120')
  await userEvent.keyboard('{End}')
  expect(edge).toHaveAttribute('aria-valuenow', '370')
  // The windows stand on it, never on more than 60% of the stage.
  expect(screen.getByRole('region', { name: 'Timeline' }).closest('.canvas')).toBeTruthy()
})

test('storage closed to the page: the strip is drawn all the same', () => {
  const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('closed')
  })
  render(<TimelineStrip state={state} runId="r" onOpen={() => {}} onClose={() => {}} />)
  expect(screen.getByRole('region', { name: 'Timeline' })).toBeInTheDocument()
  get.mockRestore()
})

test('B-316: a Lead waiting on its sub-agents says whom; what still waits for you leads to its card on Ready for you', async () => {
  const waiting = convState({
    runs: [run('r', 'running', { started_at: '2026-10-05T10:00:00Z' })],
    agents: [
      agent('r', 'waiting', { id: 'lead', name: 'Lead', started_at: '2026-10-05T10:00:00Z' }),
      agent('r', 'running', { id: 'co', name: 'Coder', parent_agent_id: 'lead', depth: 1, created_at: '2026-10-05T10:00:01Z', started_at: '2026-10-05T10:00:01Z' }),
      agent('r', 'running', { id: 'te', name: 'Tester', parent_agent_id: 'lead', depth: 1, created_at: '2026-10-05T10:00:01Z', started_at: '2026-10-05T10:00:01Z' }),
    ],
    questions: [question('q', 'r', { agent_id: 'te', created_at: '2026-10-05T10:00:10Z', answered_at: null, status: 'pending' })],
  })
  render(<TimelineStrip state={waiting} runId="r" onOpen={() => {}} onClose={() => {}} />)
  const rows = within(screen.getByRole('table', { name: 'Its agents in time' })).getAllByRole('row').slice(1)
  expect(rows.map(r => within(r).getAllByRole('cell').at(-1)!.textContent)).toEqual(['waits for Coder, Tester', 'working', 'waits for you'])
  // (Only the Tester's row says "waits for you": its question is the user's to answer.)
  expect(within(rows[0]).queryByText('waits for you')).toBeNull()
  await userEvent.click(within(rows[2]).getByRole('button', { name: 'waits for you' }))
  expect(useApp.getState().readyPanel).toEqual({ open: true, at: 'waiting-q' })
})
