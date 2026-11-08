import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { Away, BacklogTask } from '../api/types'
import { Rail } from '../shell/Rail'
import { resetStoreForTests, useApp } from '../state/store'
import { command, conversation, convState, memoryRecord, projectMemory, question, run } from '../test-fixtures'
import { readyItems } from './ready'
import { ReadyPage, ReadyPanel } from './ReadyViews'
import { useReady } from './useReady'

const task = (id: string, over: Partial<BacklogTask> = {}): BacklogTask => ({
  id, title: `Task ${id}`, detail: null, criteria: null, priority: 'normal', status: 'proposed', position: 0, conversation_id: null, created_by: 'agent',
  pending: null, assessment: null, not_in: false, after: [], queued: false, stuck: null, waiting: false, ...over,
})

/** The open chat "c", asking a question; another chat "x" of the folder whose agent asks to run a long command. */
const LONG = 'npm run build -- --mode production && node scripts/check-every-file-of-the-project.mjs --strict --report reports/today.json && echo done'
const here = convState({ runs: [run('r', 'waiting_approval')], questions: [question('q', 'r', { question: 'Which greeting?', created_at: '2026-10-05T10:05:00Z' })] })
const other = convState({
  conversation: { ...conversation, id: 'x', title: 'Fix the login' },
  runs: [run('rx', 'waiting_approval', { conversation_id: 'x' })],
  commands: [command('cmd', 'rx', { status: 'proposed', command: LONG, created_at: '2026-10-05T09:00:00Z' })],
})

/** The panel or the page as App draws them, from the store. */
function Shown({ page, openChat = vi.fn(async () => {}) }: { page?: boolean; openChat?: (id: string, key?: string) => Promise<void> }) {
  const items = useReady()
  return page ? <ReadyPage items={items} openChat={openChat} /> : <ReadyPanel items={items} openChat={openChat} onPage={vi.fn()} onClose={() => useApp.getState().showReady(false)} />
}

beforeEach(() => {
  resetStoreForTests()
  useApp.setState({ projectId: 'p', conv: here, readyChats: { x: other }, backlog: [task('t1'), task('t2')], memory: projectMemory({ proposals: [memoryRecord('m1', { status: 'proposed' })] }) })
})
afterEach(() => vi.unstubAllGlobals())

test('one list, oldest first, each decision once: a night job whose ask is its chat’s card is that card; a task waiting for Take in is its chat’s', () => {
  const night = { id: 'a', status: 'ended', started_at: '2026-10-05T08:00:00Z', jobs: [
    { title: 'one', task_id: 'j1', state: 'waits', asks: [{ kind: 'commands', id: 'cmd', text: 'Coder asks to run …' }] },
    { title: 'two', task_id: 'j2', state: 'waits', asks: [{ kind: null, id: 'call', text: 'asks you something' }] },
  ] } as unknown as Away
  const items = readyItems({ conv: here, chats: { x: other, c: here }, projectId: 'p', backlog: [task('t1'), task('t3', { status: 'review', not_in: true }), task('t4', { status: 'review' })], memory: null, away: night })
  expect(items.map(item => [item.key, item.source])).toEqual([
    ['a:j2', 'night'],
    ['cmd', 'chat'],
    ['q', 'chat'],
    ['todo:t1:new task', 'todo'],
    ['todo:t4:done?', 'todo'],
  ])
  // Another folder's chat is "other folders"; a plain chat is not another folder.
  expect(readyItems({ conv: null, chats: { x: { ...other, conversation: { ...other.conversation, project_id: 'q' } } }, projectId: 'p', backlog: null, memory: null, away: null })[0].source).toBe('other')
})

test('the panel: This chat first, then Elsewhere; it takes the focus, Esc closes it and the focus goes back', async () => {
  render(<button type="button">pill</button>)
  screen.getByRole('button', { name: 'pill' }).focus()
  useApp.getState().showReady(true)
  const { unmount } = render(<Shown />)
  const panel = screen.getByRole('complementary', { name: 'Ready for you · 5' })
  expect(panel).toHaveFocus()
  const mine = within(panel).getByRole('heading', { name: 'This chat · 1' })
  const rest = within(panel).getByRole('heading', { name: 'Elsewhere · 4' })
  expect(mine.compareDocumentPosition(screen.getByText('Which greeting?')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(screen.getByText('Which greeting?').compareDocumentPosition(rest) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(within(panel).getByRole('group', { name: 'chat: “Fix the login”' })).toBeInTheDocument()
  expect(within(panel).getByRole('button', { name: 'Open all as a page →' })).toBeInTheDocument()
  await userEvent.keyboard('{Escape}')
  expect(useApp.getState().readyPanel.open).toBe(false)
  unmount()
  expect(screen.getByRole('button', { name: 'pill' })).toHaveFocus()
})

test('decision 1: the command beside Run is the whole command, in a monospace block', () => {
  render(<Shown page />)
  const row = screen.getByRole('group', { name: 'chat: “Fix the login”' })
  expect(within(row).getByText(LONG).tagName).toBe('PRE')
  expect(within(row).getByText(LONG)).toHaveClass('mono')
  expect(within(row).getByRole('button', { name: 'Run once' })).toBeInTheDocument()
})

test('the page: the same list, by where it is from', async () => {
  render(<Shown page />)
  const shows = screen.getByRole('group', { name: 'Show' })
  expect(within(shows).getAllByRole('button').map(button => button.textContent)).toEqual(['All · 5', 'Chats · 2', 'To-do · 2', 'Memory · 1', 'While away · 0', 'Other folders · 0'])
  await userEvent.click(within(shows).getByRole('button', { name: 'To-do · 2' }))
  expect(screen.getAllByRole('group', { name: /^(chat|to-do|memory)/ }).map(row => row.getAttribute('aria-label'))).toEqual(['to-do: To-do', 'to-do: To-do'])
  await userEvent.click(within(shows).getByRole('button', { name: 'Memory · 1' }))
  expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument()
  await userEvent.click(within(shows).getByRole('button', { name: 'While away · 0' }))
  expect(screen.getByText('Nothing waits for you here.')).toBeInTheDocument()
})

test('Approve all: the To-do list’s new tasks one after another; one that fails stays on its row with why', async () => {
  const order: string[] = []
  const decideTask = vi.fn(async (id: string) => {
    order.push(id)
    if (id === 't1') throw new Error('It changed meanwhile.')
    useApp.setState(s => ({ backlog: s.backlog!.filter(one => one.id !== id) }))
  })
  useApp.setState({ decideTask, backlog: [task('t1'), task('t2'), task('t3', { status: 'review' })] })
  render(<Shown page />)
  await userEvent.click(screen.getByRole('button', { name: 'Approve all 2 proposals' }))
  expect(order).toEqual(['t1', 't2'])
  expect(decideTask).toHaveBeenCalledWith('t1', 'approve')
  const rows = screen.getAllByRole('group', { name: 'to-do: To-do' })
  // t1 left, with its error; t3 ("done?") was not touched.
  expect(rows).toHaveLength(2)
  expect(within(rows[0]).getByRole('alert')).toHaveTextContent('It changed meanwhile.')
  expect(screen.getByRole('button', { name: 'Approve all 1 proposal' })).toBeInTheDocument()
})

test('the same decision everywhere: answered in Ready, another chat’s card is read again and gone; answered in the chat, it leaves Ready', async () => {
  const fetch = vi.fn(async (url: string) =>
    new Response(JSON.stringify(url.endsWith('/conversations/x') ? { conversation: other.conversation, messages: [], runs: other.runs, tool_calls: [], file_changes: [], commands: [{ ...other.commands[0], status: 'approved' }], allowed_commands: [], agents: [], channel_messages: [], pending_roles: [], questions: [], discussions: [], discussion_posts: [], board_posts: [], last_event_id: 1 } : {}), { status: 200 }),
  )
  vi.stubGlobal('fetch', fetch)
  // (The Board still says "x" waits: it is read again because a decision was made on it.)
  useApp.setState({ everywhere: { backlog_waiting: 0, limit: null, running: 0, conflicts: [], conversations: [{ conversation_id: 'x', title: 'Fix the login', merges_pending: 1, turn: null, agents: [], project_id: 'p' }] } as never })
  render(<Shown page />)
  await userEvent.click(within(screen.getByRole('group', { name: 'chat: “Fix the login”' })).getByRole('button', { name: 'Run once' }))
  expect(fetch.mock.calls.map(([url]) => String(url))).toEqual(expect.arrayContaining([expect.stringContaining('/api/commands/cmd/approve'), expect.stringContaining('/api/conversations/x')]))
  await vi.waitFor(() => expect(screen.queryByRole('group', { name: 'chat: “Fix the login”' })).toBeNull())
  // The open chat's question, answered there (its event): gone from Ready too.
  expect(screen.getByText('Which greeting?')).toBeInTheDocument()
  act(() => useApp.setState({ conv: { ...here, questions: [{ ...here.questions[0], status: 'answered', answer: 'hi' }] } }))
  expect(screen.queryByText('Which greeting?')).toBeNull()
})

test('the rail: Ready carries the badge, the total; Board none', () => {
  render(<Rail view="canvas" onView={vi.fn()} theme="dark" onToggleTheme={vi.fn()} waiting={5} />)
  expect(screen.getByRole('button', { name: 'Ready' })).toHaveAccessibleDescription('5 waiting')
  expect(screen.getByRole('button', { name: 'Board' })).not.toHaveAccessibleDescription()
  expect(screen.getAllByText('5')).toHaveLength(1)
})

test('Open chat: a card’s row opens its chat at that card; a To-do row has no chat to open', async () => {
  const openChat = vi.fn(async () => {})
  render(<Shown page openChat={openChat} />)
  await userEvent.click(within(screen.getByRole('group', { name: 'chat: “Fix the login”' })).getByRole('button', { name: 'Open chat' }))
  expect(openChat).toHaveBeenCalledWith('x', 'cmd')
  expect(within(screen.getAllByRole('group', { name: 'to-do: To-do' })[0]).queryByRole('button', { name: 'Open chat' })).toBeNull()
})

test('a chat answered here that asks again with the same Board row is read again: the badge says 1, not 0', async () => {
  let asking = command('cmd', 'rx', { status: 'proposed', command: 'python check.py' })
  const snapshot = () => ({ conversation: other.conversation, messages: [], runs: other.runs, tool_calls: [], file_changes: [], commands: [asking], allowed_commands: [], agents: [], channel_messages: [], pending_roles: [], questions: [], discussions: [], discussion_posts: [], board_posts: [], last_event_id: 1 })
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.includes('/approve')) asking = { ...asking, status: 'approved' }
    return new Response(JSON.stringify(url.endsWith('/conversations/x') ? snapshot() : {}), { status: 200 })
  }))
  // (The Board's row says "x" waits - before the decision, and the same again once it asks anew.)
  const row = { conversation_id: 'x', title: 'Fix the login', merges_pending: 0, turn: null, project_id: 'p', agents: [{ id: 'a', status: 'waiting_approval', changes_to_approve: 0, questions: 0 }] }
  useApp.setState({ conv: null, readyChats: {}, backlog: [], memory: null, everywhere: { backlog_waiting: 0, limit: null, running: 0, conflicts: [], conversations: [row] } as never })
  function Badge() {
    return <Rail view="ready" onView={vi.fn()} theme="dark" onToggleTheme={vi.fn()} waiting={useReady().length} />
  }
  await act(() => useApp.getState().loadReadyChats())
  render(<><Badge /><Shown page /></>)
  const ready = screen.getByRole('button', { name: 'Ready' })
  expect(ready).toHaveAccessibleDescription('1 waiting')
  await userEvent.click(screen.getByRole('button', { name: 'Run once' }))
  await vi.waitFor(() => expect(ready).not.toHaveAccessibleDescription())
  // It asks again; the next reading of the Board finds the same row.
  asking = command('cmd2', 'rx', { status: 'proposed', command: 'python check.py' })
  await act(() => useApp.getState().loadReadyChats())
  expect(ready).toHaveAccessibleDescription('1 waiting')
})

test('Approve all approves only what is shown: no button under a filter that shows no new task', async () => {
  render(<Shown page />)
  expect(screen.getByRole('button', { name: 'Approve all 2 proposals' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Memory · 1' }))
  expect(screen.queryByRole('button', { name: /^Approve all/ })).toBeNull()
})

test('the panel asked to open at a card takes the focus to it', () => {
  useApp.getState().showReady(true, 'ready-cmd')
  render(<Shown />)
  expect(document.getElementById('ready-cmd')).toHaveFocus()
})
