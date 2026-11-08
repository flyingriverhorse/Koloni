import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import type { RawLine, RawLines } from '../api/types'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { agent, assistantMessage, convState, openAgentFold, run, toolCall } from '../test-fixtures'
import { AgentWindow } from './AgentWindow'

afterEach(() => {
  vi.unstubAllGlobals()
  useApp.setState({ agentWindowId: null, agentWindowRaw: false })
})

const line = (n: number, text: string, stream: RawLine['stream'] = 'stdout'): RawLine => ({ n, stream, text })
const told = (lines: RawLine[], over: Partial<RawLines> = {}): RawLines => ({ available: true, dropped: 0, more: false, lines, ...over })

/** The backend answers with these, in order, and with no new line after them. */
function answers(...inOrder: RawLines[]) {
  const read = vi.fn(async (_agentId: string, _after: number) => inOrder.shift() ?? told([]))
  useApp.setState({ rawStream: read })
  return read
}

/** The clipboard, as a page served securely has it. */
function clipboard() {
  const writeText = vi.fn(async (_text: string) => {})
  vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
  return writeText
}

/** The agent's window as the app holds it: open for the agent the store names. */
function Opened({ state }: { state: ConvState }) {
  const agentId = useApp(s => s.agentWindowId)
  return agentId ? <AgentWindow state={state} agentId={agentId} onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} /> : null
}

/** The window's Details fold, where Copy raw is. */
const more = () => screen.getByText('Details', { selector: 'summary' }).closest('details') as HTMLElement

const cli = convState({
  runs: [run('r', 'completed')],
  agents: [agent('r', 'completed', { id: 'lead', provider_name: 'Claude Code', provider_mode: 'native' })],
})

test('K-inspector: under Details the raw stream is not drawn - no CLI init blob, no whole files - and Copy raw takes every line kept', async () => {
  const INIT = '{"type":"system","subtype":"init","tools":["Read"],"slash_commands":["review"]}'
  const read = answers(told([line(1, INIT), line(2, '{"type":"user"}', 'stdin')], { more: true }), told([line(3, 'warning: slow', 'stderr')]))
  const copied = clipboard()
  render(<AgentWindow state={cli} agentId="lead" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  await userEvent.click(within(more()).getByText('Details'))
  expect(more()).toHaveAttribute('open')
  // Not read until it is asked for, and never on the page.
  expect(read).not.toHaveBeenCalled()
  expect(screen.queryByRole('region', { name: 'Raw stream' })).not.toBeInTheDocument()

  await userEvent.click(within(more()).getByRole('button', { name: 'Copy raw' }))
  // What one answer does not carry is asked for at once, after the last line it had.
  expect(read.mock.calls.map(([id, after]) => [id, after])).toEqual([['lead', 0], ['lead', 2]])
  expect(copied).toHaveBeenCalledWith(`${INIT}\n{"type":"user"}\nwarning: slow`)
  expect(within(more().querySelector('.raw-copy') as HTMLElement).getByRole('status')).toHaveTextContent('Copied 3 lines')
  expect(document.body).not.toHaveTextContent('slash_commands')
  // What it is, said once, under the button.
  expect(within(more()).getByText(/Kept in memory only: it is gone when KOLONİ restarts\./)).toBeInTheDocument()
})

test('Copy raw says where there is nothing to copy, and why it could not', async () => {
  const copied = clipboard()
  answers(told([], { available: false }), told([]))
  const { unmount } = render(<AgentWindow state={cli} agentId="lead" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  await openAgentFold('Details')
  const button = within(more()).getByRole('button', { name: 'Copy raw' })
  await userEvent.click(button)
  expect(within(more().querySelector('.raw-copy') as HTMLElement).getByRole('status')).toHaveTextContent('Its model is not a CLI: there is no raw stream.')
  await userEvent.click(button)
  expect(within(more().querySelector('.raw-copy') as HTMLElement).getByRole('status')).toHaveTextContent('Nothing its CLI wrote is kept.')
  expect(copied).not.toHaveBeenCalled()
  unmount()

  useApp.setState({ rawStream: vi.fn(async () => Promise.reject(new Error('the server is gone'))) })
  render(<AgentWindow state={cli} agentId="lead" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  await openAgentFold('Details')
  await userEvent.click(within(more()).getByRole('button', { name: 'Copy raw' }))
  expect(screen.getByRole('alert')).toHaveTextContent('The raw stream could not be read: the server is gone')
})

test('opened from the “Raw” button of its node the window has Details open at once - also when it lay open with Details folded', async () => {
  answers()
  render(<Opened state={cli} />)
  // (what the button does, through the canvas and the app)
  act(() => useApp.getState().openAgentWindow('lead', true))
  expect(more()).toHaveAttribute('open')
  expect(within(more()).getByRole('button', { name: 'Copy raw' })).toBeInTheDocument()
  await userEvent.click(within(more()).getByText('Details'))
  expect(more()).not.toHaveAttribute('open')
  // Folded by the user, the button opens it again.
  act(() => useApp.getState().openAgentWindow('lead', true))
  expect(more()).toHaveAttribute('open')
  // Closed, and opened again the usual way: Details folded.
  act(() => useApp.getState().closeAgentWindow())
  act(() => useApp.getState().openAgentWindow('lead'))
  expect(more()).not.toHaveAttribute('open')
})

test('its steps read as a timeline: each tool with its argument, how big its result is and how long it took; the result itself folded', async () => {
  const FILE = 'x'.repeat(115_000)
  const s = convState({
    runs: [run('r', 'completed')],
    agents: [agent('r', 'completed', { id: 'lead', provider_name: 'Claude Code', provider_mode: 'native' })],
    messages: [{ ...assistantMessage('m1', 'r', 'Reading.'), agent_id: 'lead' }],
    toolCalls: [
      toolCall('1', 'r', 'Read', 'succeeded', '{"file_path":"server.py"}', {
        agent_id: 'lead',
        message_id: 'm1',
        origin: 'cli',
        result: FILE,
        started_at: '2026-11-03T20:00:00Z',
        ended_at: '2026-11-03T20:00:02Z',
      }),
    ],
  })
  render(<AgentWindow state={s} agentId="lead" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  const steps = await openAgentFold('Every step as recorded')
  expect(within(steps).getByText('result 115,000 chars · 2s')).toBeInTheDocument()
  const row = within(steps).getByRole('button', { name: /own tool.*done/ })
  expect(row).toHaveAttribute('aria-expanded', 'false')
  expect(steps).not.toHaveTextContent(FILE.slice(0, 50))
  await userEvent.click(row)
  expect(row).toHaveAttribute('aria-expanded', 'true')
  expect(steps).toHaveTextContent(FILE.slice(0, 50))
})
