import { act, cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { AGENT_STATUS, WAITS } from '../agents/agentStatus'
import type { Board } from '../api/types'
import { waitCount, waitingTotal } from '../board/waiting'
import { commandStatus } from '../commands/commandStatus'
import { Inspector } from '../inspector/Inspector'
import { agent, boardTurn, convState, question, run } from '../test-fixtures'
import { Rail } from './Rail'
import { RunStatus } from './RunStatus'
import { Toasts } from './Toasts'

type BoardConversation = Board['conversations'][number]
type BoardAgent = BoardConversation['agents'][number]

const worker = (over: Partial<BoardAgent> = {}): BoardAgent => ({
  id: over.name ?? 'Lead',
  name: 'Lead',
  status: 'running',
  role: 'Lead',
  provider_name: 'Local',
  model_id: 'qwen',
  holds: [],
  copy: null,
  waiting_for: null,
  sign: null,
  last_event_at: null,
  in_tool: false,
  changes_to_approve: 0,
  questions: 0,
  ...over,
})
const talk = (id: string, title: string, over: Partial<BoardConversation> = {}): BoardConversation => ({
  conversation_id: id,
  title,
  agents: [],
  merges_pending: 0,
  turn: null,
  ...over,
})
const boardOf = (...conversations: BoardConversation[]): Board => ({ backlog_waiting: 0, limit: null, running: 0, conversations, conflicts: [] })

afterEach(() => vi.useRealTimers())

// --- what waits for you: one count, from the Board's own data -----------------------------------

test('an approval, a question or a sub-agent asked for is one thing; each set of changes to apply is one more', () => {
  const asks = talk('a', 'Docs', { agents: [worker({ status: 'waiting_approval' })] })
  // a sub-agent waits to be let start: its opener is the one asking, it is not counted twice
  const spawn = talk('b', 'Plans', { agents: [worker({ status: 'waiting_approval' }), worker({ name: 'Coder', status: 'proposed' })] })
  const merges = talk('c', 'Merging', { merges_pending: 2 })
  const busy = talk('d', 'Busy', { agents: [worker(), worker({ name: 'Coder 2', status: 'blocked' })] })
  expect([asks, spawn, merges, busy].map(waitCount)).toEqual([1, 1, 2, 0])
  expect(waitingTotal(boardOf(asks, spawn, merges, busy))).toBe(4)
  expect(waitingTotal(null)).toBe(0)
})

test('the evening note counts what waits the same way: the cases of `waiting_in` in tests/test_day_note.py', () => {
  const mixed = talk('a', 'Docs', { merges_pending: 2, agents: [worker({ status: 'proposed' }), worker({ name: 'Coder', status: 'waiting_approval' }), worker({ name: 'Coder 2' })] })
  const proposed = talk('b', 'Plans', { agents: [worker({ status: 'proposed' })] })
  const two = talk('c', 'Two', { agents: [worker({ status: 'waiting_approval' }), worker({ name: 'Coder', status: 'waiting_approval' }), worker({ name: 'Coder 2', status: 'proposed' })] })
  expect([mixed, proposed, two].map(waitCount)).toEqual([3, 1, 2])
  // a plan that waits for a yes is one thing more (K-60b-kalan)
  expect(waitCount(talk('d', 'Plan', { merges_pending: 1, turn: boardTurn('r', 'completed', 't', { plan_waits: true }) }))).toBe(2)
  // an agent that asks two questions at once, and a change, is three things (K-38f2)
  expect(waitCount(talk('e', 'Asks', { agents: [worker({ status: 'waiting_approval', questions: 2, changes_to_approve: 1 })] }))).toBe(3)
})

test('a plan that begins to wait is told as a plan, not as changes', () => {
  const ran = boardOf(talk('a', 'Docs', { turn: boardTurn('r1', 'running', null) }))
  const { rerender, container } = render(<Toasts board={ran} shownId={null} onOpen={() => {}} />)
  rerender(<Toasts board={boardOf(talk('a', 'Docs', { turn: boardTurn('r1', 'completed', 't', { plan_waits: true }) }))} shownId={null} onOpen={() => {}} />)
  expect(container.querySelector('[aria-live="polite"]')).toHaveTextContent('A plan waits for you · Docs')
})

test('the badge on the Ready button (tek-ev §1) counts what waits, goes with a decision, and opens Ready for you', async () => {
  const onView = vi.fn()
  const props = { view: 'canvas' as const, onView, theme: 'dark' as const, onToggleTheme: () => {} }
  const asking = boardOf(talk('a', 'Docs', { agents: [worker({ status: 'waiting_approval' })] }), talk('c', 'Merging', { merges_pending: 1 }))
  const { rerender } = render(<Rail {...props} waiting={waitingTotal(asking)} />)
  // its name stays the page's; the count is its description
  const button = screen.getByRole('button', { name: 'Ready' })
  expect(screen.getByRole('button', { name: 'Board' })).not.toHaveAttribute('aria-describedby')
  expect(button).toHaveAccessibleDescription('2 waiting')
  expect(within(button).getByText('2')).toHaveClass('tag-warn')
  // a fake approval more, then the decisions
  rerender(<Rail {...props} waiting={waitingTotal(boardOf(...asking.conversations, talk('e', 'More', { agents: [worker({ status: 'waiting_approval' })] })))} />)
  expect(button).toHaveAccessibleDescription('3 waiting')
  rerender(<Rail {...props} waiting={waitingTotal(boardOf(talk('a', 'Docs', { agents: [worker()] })))} />)
  expect(button).not.toHaveAttribute('aria-describedby')
  expect(within(button).queryByText(/\d/)).toBeNull()
  await userEvent.click(button)
  expect(onView).toHaveBeenCalledWith('ready')
})

// --- the toasts --------------------------------------------------------------------------------

test('a toast comes once for what starts waiting elsewhere, says who and where, and Open goes there', async () => {
  const onOpen = vi.fn()
  const calm = boardOf(talk('a', 'tes test 1', { agents: [worker({ name: 'Coder' })] }))
  const { rerender, container } = render(<Toasts board={calm} shownId={null} onOpen={onOpen} />)
  const live = container.querySelector('[aria-live="polite"]')!
  // what was there when the page first read the Board is no news
  expect(live).toBeEmptyDOMElement()
  const asks = boardOf(talk('a', 'tes test 1', { agents: [worker({ name: 'Coder', status: 'waiting_approval' })] }))
  rerender(<Toasts board={asks} shownId={null} onOpen={onOpen} />)
  expect(live).toHaveTextContent('Coder waits for you · tes test 1')
  // read again, the same: no second toast
  rerender(<Toasts board={{ ...asks }} shownId={null} onOpen={onOpen} />)
  expect(within(live as HTMLElement).getAllByRole('button', { name: 'Open' })).toHaveLength(1)
  await userEvent.click(within(live as HTMLElement).getByRole('button', { name: 'Open' }))
  expect(onOpen).toHaveBeenCalledWith('a')
  expect(live).toBeEmptyDOMElement()
})

test('a turn that ends elsewhere says so; nothing is said of the conversation on screen', () => {
  const going = boardOf(talk('a', 'Docs', { turn: boardTurn('r1', 'running', null) }), talk('b', 'Open one', { turn: boardTurn('r2', 'running', null) }))
  const { rerender, container } = render(<Toasts board={going} shownId="b" onOpen={() => {}} />)
  const done = boardOf(
    talk('a', 'Docs', { turn: boardTurn('r1', 'completed', 't') }),
    talk('b', 'Open one', { turn: boardTurn('r2', 'failed', 't'), agents: [worker({ status: 'waiting_approval' })] }),
  )
  rerender(<Toasts board={done} shownId="b" onOpen={() => {}} />)
  const live = container.querySelector('[aria-live="polite"]')!
  expect(live).toHaveTextContent('Done · Docs')
  expect(live).not.toHaveTextContent('Open one')
})

test('a turn that ends as the one queued after it starts is told too (K-38f2)', () => {
  // (the queued turn is the last one on the Board from the moment it is sent)
  const queued = boardOf(talk('a', 'Docs', { turn: boardTurn('r2', 'queued', null) }))
  const { rerender, container } = render(<Toasts board={queued} shownId={null} onOpen={() => {}} />)
  const started = boardOf(talk('a', 'Docs', { turn: boardTurn('r2', 'running', null, { started_at: 't' }) }))
  rerender(<Toasts board={started} shownId={null} onOpen={() => {}} />)
  const live = container.querySelector('[aria-live="polite"]')!
  expect(live).toHaveTextContent('Your queued message started · Docs')
  // read again, the same: no second toast
  rerender(<Toasts board={{ ...started }} shownId={null} onOpen={() => {}} />)
  expect(within(live as HTMLElement).getAllByRole('button', { name: 'Open' })).toHaveLength(1)
})

test('a queued turn that started and ended between two readings is told once, by its end (B-200)', () => {
  const queued = boardOf(talk('a', 'Docs', { turn: boardTurn('r2', 'queued', null) }))
  const { rerender, container } = render(<Toasts board={queued} shownId={null} onOpen={() => {}} />)
  rerender(<Toasts board={boardOf(talk('a', 'Docs', { turn: boardTurn('r2', 'completed', 't', { started_at: 't' }) }))} shownId={null} onOpen={() => {}} />)
  const live = container.querySelector('[aria-live="polite"]') as HTMLElement
  expect(live).toHaveTextContent('Done · Docs')
  expect(live).not.toHaveTextContent('started')
  expect(within(live).getAllByRole('button', { name: 'Open' })).toHaveLength(1)
})

test('at most three toasts stand at once, and each goes after six seconds', () => {
  vi.useFakeTimers()
  const names = ['A', 'B', 'C', 'D']
  const quiet = boardOf(...names.map(n => talk(n, n)))
  const { rerender, container } = render(<Toasts board={quiet} shownId={null} onOpen={() => {}} />)
  rerender(<Toasts board={boardOf(...names.map(n => talk(n, n, { merges_pending: 1 })))} shownId={null} onOpen={() => {}} />)
  const live = container.querySelector('[aria-live="polite"]') as HTMLElement
  expect(within(live).getAllByRole('button', { name: 'Open' })).toHaveLength(3)
  // the newest stay
  expect(live).toHaveTextContent('Changes wait for you · D')
  expect(live).not.toHaveTextContent('· A')
  act(() => void vi.advanceTimersByTime(5900))
  expect(within(live).getAllByRole('button', { name: 'Open' })).toHaveLength(3)
  act(() => void vi.advanceTimersByTime(200))
  expect(live).toBeEmptyDOMElement()
})

test('a second thing waiting in the same conversation updates its toast, names what is new, and has its six seconds again', () => {
  vi.useFakeTimers()
  const at = (agents: BoardAgent[], merges = 0) => boardOf(talk('a', 'Docs', { agents, merges_pending: merges }))
  const lead = worker({ status: 'waiting_approval' })
  const { rerender, container } = render(<Toasts board={at([worker()])} shownId={null} onOpen={() => {}} />)
  const live = container.querySelector('[aria-live="polite"]') as HTMLElement
  rerender(<Toasts board={at([lead])} shownId={null} onOpen={() => {}} />)
  expect(live).toHaveTextContent('Orchestrator waits for you · Docs')
  act(() => void vi.advanceTimersByTime(5000))
  // changes put before you while the lead still asks: the toast says it is changes, not the lead again
  rerender(<Toasts board={at([lead], 1)} shownId={null} onOpen={() => {}} />)
  expect(within(live).getAllByRole('button', { name: 'Open' })).toHaveLength(1)
  expect(live).toHaveTextContent('Changes wait for you · Docs')
  act(() => void vi.advanceTimersByTime(5000))
  rerender(<Toasts board={at([lead, worker({ name: 'Coder', status: 'waiting_approval' })], 1)} shownId={null} onOpen={() => {}} />)
  expect(live).toHaveTextContent('Coder waits for you · Docs')
  act(() => void vi.advanceTimersByTime(5900))
  expect(live).not.toBeEmptyDOMElement()
  act(() => void vi.advanceTimersByTime(200))
  expect(live).toBeEmptyDOMElement()
})

test('a toast pointed at or focused stays; a fourth one does not push out the one being read', () => {
  vi.useFakeTimers()
  const names = ['A', 'B', 'C', 'D']
  const quiet = boardOf(...names.map(n => talk(n, n)))
  const waits = (...which: string[]) => boardOf(...names.map(n => talk(n, n, { merges_pending: which.includes(n) ? 1 : 0 })))
  const { rerender, container } = render(<Toasts board={quiet} shownId={null} onOpen={() => {}} />)
  const live = container.querySelector('[aria-live="polite"]') as HTMLElement
  rerender(<Toasts board={waits('A', 'B', 'C')} shownId={null} onOpen={() => {}} />)
  const first = within(live).getAllByRole('button', { name: 'Open' })[0]
  act(() => first.focus())
  act(() => void vi.advanceTimersByTime(1000))
  rerender(<Toasts board={waits('A', 'B', 'C', 'D')} shownId={null} onOpen={() => {}} />)
  expect(live).toHaveTextContent('· A')
  expect(live).not.toHaveTextContent('· B')
  expect(live).toHaveTextContent('· D')
  // held as long as it is read
  act(() => void vi.advanceTimersByTime(10_000))
  expect(live).toHaveTextContent('Changes wait for you · A')
  expect(live).not.toHaveTextContent('· D')
  act(() => first.blur())
  act(() => void vi.advanceTimersByTime(6000))
  expect(live).toBeEmptyDOMElement()
  // the pointer holds one too (said again after a minute: the same note within one is not shown again)
  act(() => void vi.advanceTimersByTime(60_000))
  rerender(<Toasts board={quiet} shownId={null} onOpen={() => {}} />)
  rerender(<Toasts board={waits('D')} shownId={null} onOpen={() => {}} />)
  const toast = live.querySelector('.toast') as HTMLElement
  act(() => void toast.dispatchEvent(new MouseEvent('mouseover', { bubbles: true })))
  act(() => void vi.advanceTimersByTime(10_000))
  expect(live).toHaveTextContent('· D')
  act(() => void toast.dispatchEvent(new MouseEvent('mouseout', { bubbles: true })))
  act(() => void vi.advanceTimersByTime(6000))
  expect(live).toBeEmptyDOMElement()
})

test('over the canvas the toasts stand at the foot beside its buttons; above them only where a window is too narrow (6 Nov)', () => {
  // the canvas's buttons: a tall column at the bottom right
  const controls = document.body.appendChild(document.createElement('div'))
  controls.className = 'react-flow__controls'
  const box = (left: number, top: number, width: number, height: number) =>
    ({ left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) }) as DOMRect
  const at = (left: number, width = 26) => vi.spyOn(controls, 'getBoundingClientRect').mockReturnValue(box(left, window.innerHeight - 250, width, 235))
  const quiet = boardOf(talk('a', 'Docs'))
  const waits = boardOf(talk('a', 'Docs', { merges_pending: 1 }))
  const shown = () => {
    const { rerender, container } = render(<Toasts board={quiet} shownId={null} onOpen={() => {}} />)
    rerender(<Toasts board={waits} shownId={null} onOpen={() => {}} />)
    return (container.querySelector('.toasts') as HTMLElement).style
  }
  at(window.innerWidth - 41)
  const wide = shown()
  expect(wide.right).toBe(`${41 + 8}px`)
  expect(wide.bottom).toBe('') // board.css's 16px
  expect(wide.maxWidth).toBe('420px')
  cleanup()
  // the chat floating over the canvas's foot: the notes stand right of its message box, narrower
  const chat = document.body.appendChild(document.createElement('section'))
  chat.className = 'chat'
  const chatAt = (top: number) => vi.spyOn(chat, 'getBoundingClientRect').mockReturnValue(box(78, top, 480, 300))
  chatAt(window.innerHeight - 14 - 300)
  const besideChat = shown()
  expect(besideChat.right).toBe(`${41 + 8}px`)
  expect(besideChat.maxWidth).toBe(`${window.innerWidth - 41 - 8 - (558 + 8)}px`)
  cleanup()
  // a chat moved up, clear of the notes' foot, takes no room from them
  chatAt(20)
  expect(shown().maxWidth).toBe('420px')
  cleanup()
  chat.remove()
  // buttons not drawn (display: none, a box of nothing): the notes stand as anywhere
  at(0, 0)
  expect(shown().cssText).toBe('')
  cleanup()
  // a window with no room for a note left of the buttons: above them, as before
  const width = window.innerWidth
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 320 })
  at(320 - 41)
  const narrow = shown()
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
  controls.remove()
  expect(narrow.bottom).toBe('258px')
  expect(narrow.right).toBe('')
})

test('the same note within a minute is not shown again but stays on the bell’s list; an error said again counts ×N (K-bildirim-duzeni)', () => {
  vi.useFakeTimers()
  const bellIn = document.body.appendChild(document.createElement('span'))
  const at = (id: string, status: 'running' | 'failed' | 'completed') =>
    boardOf(talk('a', 'Docs', { turn: boardTurn(id, status, status === 'running' ? null : 't') }))
  const { rerender, container } = render(<Toasts board={at('r1', 'running')} shownId={null} onOpen={() => {}} bellIn={bellIn} />)
  const live = container.querySelector('[aria-live="polite"]') as HTMLElement
  for (const [id, status] of [['r1', 'failed'], ['r2', 'running'], ['r2', 'failed'], ['r3', 'running'], ['r3', 'completed'], ['r4', 'running'], ['r4', 'completed']] as const)
    rerender(<Toasts board={at(id, status)} shownId={null} onOpen={() => {}} bellIn={bellIn} />)
  expect(Array.from(live.querySelectorAll('.toast > span'), span => span.textContent)).toEqual(['Failed · Docs ×2', 'Done · Docs'])
  // the bell stands where it is given (the top bar), not in the live region; its list has every note, newest first
  const bell = screen.getByRole('button', { name: 'Notifications, 1 not shown' })
  expect(bellIn).toContainElement(bell)
  expect(live).not.toContainElement(bell)
  act(() => bell.click())
  const list = screen.getByRole('dialog', { name: 'Recent notifications' })
  expect(within(list).getAllByRole('listitem').map(li => li.querySelector('.recent-text')?.textContent)).toEqual([
    'Done · Docs · not shown',
    'Done · Docs',
    'Failed · Docs',
    'Failed · Docs',
  ])
})

test('a source shows at most four a minute; an error over that is said once there is room again', () => {
  vi.useFakeTimers()
  const bellIn = document.body.appendChild(document.createElement('span'))
  const titles = ['one', 'two', 'three', 'four', 'five']
  const at = (n: number, status: 'running' | 'failed' | 'completed') => boardOf(talk('a', titles[n], { turn: boardTurn(`r${n}`, status, status === 'running' ? null : 't') }))
  const { rerender, container } = render(<Toasts board={at(0, 'running')} shownId={null} onOpen={() => {}} bellIn={bellIn} />)
  const live = container.querySelector('[aria-live="polite"]') as HTMLElement
  for (const n of [0, 1, 2, 3]) {
    rerender(<Toasts board={at(n, 'running')} shownId={null} onOpen={() => {}} bellIn={bellIn} />)
    rerender(<Toasts board={at(n, 'completed')} shownId={null} onOpen={() => {}} bellIn={bellIn} />)
  }
  rerender(<Toasts board={at(4, 'running')} shownId={null} onOpen={() => {}} bellIn={bellIn} />)
  rerender(<Toasts board={at(4, 'failed')} shownId={null} onOpen={() => {}} bellIn={bellIn} />)
  expect(live).not.toHaveTextContent('five')
  expect(screen.getByRole('button', { name: 'Notifications, 1 not shown' })).toBeInTheDocument()
  act(() => void vi.advanceTimersByTime(60_000))
  expect(live).toHaveTextContent('1 error not shown · last: Failed · five')
})

// --- one word for one state ----------------------------------------------------------------------

test('what waits for you has one name and one colour: an agent, a sub-agent asked for, a command, the turn', () => {
  expect(WAITS).toBe('waits for you')
  expect(AGENT_STATUS.waiting_approval).toEqual([WAITS, 'var(--warn)'])
  expect(AGENT_STATUS.proposed).toEqual(AGENT_STATUS.waiting_approval)
  expect(commandStatus({ status: 'proposed', exit_code: null, started_at: null })).toEqual({ label: WAITS, tone: 'warn' })
  const asking = convState({ runs: [run('r', 'waiting_approval')], agents: [agent('r')] })
  // (The run status: its warning colour and dot; the words are the Ready pill’s, tek-ev §1.)
  const { container } = render(<RunStatus conv={asking} connection="open" />)
  expect(container.querySelector('.tag-warn > .dot')).toBeInTheDocument()
  cleanup()
  // the inspector says the word too, not the record's own ("waiting approval")
  render(<Inspector state={asking} selectedId="agent:r" onClose={() => {}} />)
  expect(within(screen.getByRole('complementary', { name: 'Inspector' })).getByText(WAITS)).toHaveClass('status')
})

test('a turn that ended well says "done" in the top bar, as its agents, its row in the turn list and the Conversations list do', () => {
  render(<RunStatus conv={convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed')] })} connection="open" />)
  expect(screen.getByText(AGENT_STATUS.completed[0].toUpperCase())).toHaveClass('tag-ok')
})

test('a turn that waits for an answer is the warning colour, its words left to the Ready pill (tek-ev §1)', () => {
  const conv = convState({ runs: [run('r', 'waiting_approval')], agents: [agent('r')], questions: [question('q', 'r')] })
  const { container } = render(<RunStatus conv={conv} connection="open" />)
  expect(container.querySelector('.tag-warn')).toHaveTextContent(/^$/)
  expect(screen.queryByText(/WAITS FOR YOU/)).toBeNull()
})
