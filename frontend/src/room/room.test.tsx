import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { AgentSteps } from '../agents/AgentSteps'
import { ApiError } from '../api/client'
import { EVENT_TYPES } from '../api/sse'
import type { Merge, Provider, Role, Room, RoomItem, RoomPost } from '../api/types'
import { deriveGraph } from '../canvas/deriveGraph'
import { copyLine } from '../changes/copies'
import { ChatPanel } from '../chat/ChatPanel'
import { MessageList, type RequestHandlers } from '../chat/MessageList'
import { Inspector } from '../inspector/Inspector'
import { applyEvent } from '../state/applyEvent'
import { resetStoreForTests, useApp } from '../state/store'
import { agent, assistantMessage, command, convState, run, toolCall, userMessage } from '../test-fixtures'
import { RoomTabs, RoomWindow } from './RoomWindow'
import { once, roomLine, roomTag, spentLines, waitsForYou } from './roomText'
import { WorkTogether } from './WorkTogether'

/** Slice 29b-1: a room the user opens - its form beside the message box, its window (AC), its node. */

const room = (over: Partial<Room> = {}): Room => ({
  id: 'o',
  run_id: 'r',
  goal: 'Fix the greeting together',
  agent_id: null,
  status: 'working',
  outcome: null,
  why: null,
  budget: { posts: 40, tokens: 400000, minutes: 30 },
  spent: { posts: 3, tokens: 1200, minutes: 2.5 },
  summary: null,
  paused: false,
  lead_follows: 'off',
  members: [
    { agent_id: 'coder', role: 'Coder', status: 'in' },
    { agent_id: 'rev', role: 'Reviewer', status: 'waiting' },
  ],
  created_at: '2026-10-13T10:00:00Z',
  ended_at: null,
  ...over,
})

const item = (number: number, title: string, over: Partial<RoomItem> = {}): RoomItem => ({
  id: `i${number}`,
  room_id: 'o',
  number,
  title,
  paths: [],
  holder_agent_id: null,
  status: 'open',
  result: null,
  created_at: '2026-10-13T10:00:01Z',
  ...over,
})

const post = (number: number, agentId: string | null, type: RoomPost['type'], text: string, over: Partial<RoomPost> = {}): RoomPost => ({
  id: `s${number}`,
  room_id: 'o',
  number,
  agent_id: agentId,
  type,
  text,
  to_agent_id: null,
  reply_to: null,
  open: false,
  created_at: '2026-10-13T10:00:02Z',
  ...over,
})

const member = (id: string, name: string, status: 'running' | 'waiting' | 'completed') =>
  agent('r', status, { id, parent_agent_id: 'lead', role_name: name, name, task: 'Fix the greeting together', depth: 1, copy: { state: 'parent' } })

const state = convState({
  runs: [run('r', 'running')],
  messages: [userMessage('r', 'Fix the greeting together')],
  agents: [agent('r', 'waiting', { id: 'lead', copy: { state: 'own' } }), member('coder', 'Coder', 'running'), member('rev', 'Reviewer', 'waiting')],
  rooms: [room()],
  roomItems: [
    item(1, 'Change the greeting', { paths: ['hello.py'], holder_agent_id: 'coder', status: 'taken' }),
    item(2, 'Review the greeting', { holder_agent_id: 'rev', status: 'done', result: 'It prints yo, as asked.' }),
    item(3, 'Write the notes'),
  ],
  roomPosts: [
    post(1, 'coder', 'question', 'Which greeting do you want?', { to_agent_id: 'rev', open: true }),
    post(2, null, 'said', 'Tests first!'),
    post(3, 'rev', 'review', 'Line 1 greets nobody.', { to_agent_id: 'coder' }),
    post(4, 'rev', 'done', 'Looked at it: fine.'),
  ],
})

const noop = async () => {}
const on: RequestHandlers = {
  onOpenChange: () => {},
  onDecide: noop,
  onDecideCommand: noop,
  onDecideWeb: noop,
  onSelectAgent: () => {},
  onDecideSpawn: noop,
  onDecideRole: noop,
  onDecideMerge: noop,
  onCheckMerge: noop,
  onCommitMerge: noop,
  onAnswer: noop,
}

const panel = (s = state, over: Partial<Parameters<typeof RoomWindow>[0]> = {}) =>
  render(<RoomWindow state={s} room={s.rooms[0]} on={on} roles={[]} providers={[]} onSay={noop} onEnd={noop} onMore={noop} onPause={noop} onFollow={noop} onShrink={() => {}} onClose={() => {}} {...over} />)

beforeEach(() => {
  localStorage.clear()
  resetStoreForTests()
})

// --- the window (AC) -------------------------------------------------------------------------

test('a running room is a window of its own: its topic, who is in it and how each stands, who opened it and what is spent', () => {
  panel()
  const window = screen.getByRole('dialog', { name: 'Room: Fix the greeting together' })
  expect(window).toHaveTextContent('Room · Fix the greeting together')
  const head = screen.getByRole('region', { name: 'The room' })
  expect(head).toHaveTextContent('Coder · Reviewer · opened by you')
  expect(head).toHaveTextContent('Coder · at work')
  expect(head).toHaveTextContent('Reviewer · waiting for a post')
  expect(screen.getByRole('group', { name: 'Spent of its budget' })).toHaveTextContent(
    '3 of 40 posts · 1200 of 400000 tokens sent and written - each step resends its context · 2.5 of 30 minutes',
  )
  // while it runs: — and ×, and no line of what came of it yet
  expect(screen.getByRole('button', { name: 'Make the room small' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Close the room' })).toBeInTheDocument()
  expect(window).not.toHaveTextContent('done ·')
})

test('29c: a running room is paused and resumed beside Give it more and End; paused, its head and its tab say so', async () => {
  const onPause = vi.fn(async () => {})
  panel(state, { onPause })
  expect(screen.getByRole('status')).toBeEmptyDOMElement()
  await userEvent.click(screen.getByRole('button', { name: 'Pause' }))
  expect(onPause).toHaveBeenCalledWith('o', true)
  cleanup()

  const paused = convState({ ...state, rooms: [room({ paused: true })] })
  panel(paused, { onPause })
  expect(screen.getByRole('status')).toHaveTextContent('paused')
  await userEvent.click(screen.getByRole('button', { name: 'Resume' }))
  expect(onPause).toHaveBeenLastCalledWith('o', false)
  // it can still be read, written into and ended
  expect(screen.getByRole('button', { name: 'End' })).toBeEnabled()
  expect(roomTag(paused, paused.rooms[0])).toBe('paused')
  cleanup()
  render(<RoomTabs state={paused} windows={{}} onOpen={() => {}} />)
  expect(screen.getByRole('button', { name: /Room · Fix the greeting together/ })).toHaveTextContent('3 posts · paused')
  // over, it is no longer paused, whatever the record says
  expect(roomTag(paused, room({ paused: true, status: 'ended', outcome: 'agreed' }))).toMatch(/^done/)
})

test('K-oda-izle: a room you opened has an off-by-default switch that lets the Lead follow it; an agent’s room has none', async () => {
  const onFollow = vi.fn(async () => {})
  panel(state, { onFollow })
  const off = screen.getByRole('switch', { name: /Let the Orchestrator follow/ })
  expect(off).not.toBeChecked()
  expect(off).toHaveAccessibleDescription(/^Off: the Orchestrator takes no part/)
  // Beside the switch, in sight, one line at most: what following spends while on, why it stopped once stopped (B-195).
  const shown = () => screen.queryAllByText(/^(Its steps count toward the room’s tokens|Stopped: answered)/).map(line => line.textContent!.trim())
  expect(shown()).toEqual([])
  await userEvent.click(off)
  expect(onFollow).toHaveBeenCalledWith('o', true)
  cleanup()

  const followed = convState({ ...state, rooms: [room({ lead_follows: 'on' })] })
  panel(followed, { onFollow })
  const on = screen.getByRole('switch', { name: /Let the Orchestrator follow/ })
  expect(on).toBeChecked()
  expect(on).toHaveAccessibleDescription(/^On: the Orchestrator reads what is said here.*Its steps count toward the room’s tokens\.$/)
  expect(on).toHaveAccessibleName('Let the Orchestrator follow')
  expect(shown()).toEqual(['Its steps count toward the room’s tokens.'])
  await userEvent.click(on)
  expect(onFollow).toHaveBeenLastCalledWith('o', false)
  cleanup()

  // a Lead that stopped following is shown so, and cannot be switched on again
  panel(convState({ ...state, rooms: [room({ lead_follows: 'stopped' })] }))
  const stopped = screen.getByRole('switch', { name: /Let the Orchestrator follow/ })
  expect(stopped).toBeDisabled()
  expect(stopped).not.toBeChecked()
  expect(stopped).toHaveAccessibleDescription(/^The Orchestrator stopped following.* Stopped: answered, few steps left, or a CLI session\.$/)
  expect(shown()).toEqual(['Stopped: answered, few steps left, or a CLI session.'])
  cleanup()

  // a refusal is said in the window
  panel(state, { onFollow: async () => Promise.reject(new ApiError(409, 'the room is still opening: try again in a moment')) })
  await userEvent.click(screen.getByRole('switch', { name: /Let the Orchestrator follow/ }))
  const refused = await screen.findByRole('alert')
  expect(refused).toHaveTextContent('still opening')
  // B-195: over the buttons, which it does not push from under the pointer; the switch's note behind its ⓘ
  expect(refused.compareDocumentPosition(screen.getByRole('button', { name: 'End' })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(screen.getByText(/^Off: the Orchestrator takes no part/)).not.toBeVisible()
  cleanup()

  // not for an agent's room, nor once it is over - which says the Lead ended it
  panel(convState({ ...state, rooms: [room({ agent_id: 'lead' })] }))
  expect(screen.queryByRole('switch')).not.toBeInTheDocument()
  cleanup()
  const ended = room({ status: 'ended', outcome: 'ended_by_opener' })
  panel(convState({ ...state, rooms: [ended] }))
  expect(screen.queryByRole('switch')).not.toBeInTheDocument()
  expect(roomLine(ended)).toBe('Ended: the Orchestrator ended it')
  expect(roomTag(state, ended)).toMatch(/^the Orchestrator ended it/)
})

test('B-167: paused, a member held once its step is over is "paused" in the tags; one still finishing it is at work', () => {
  // (The Coder's step is over and it waits for the Resume; the Tester still finishes its own.)
  const held = convState({
    ...state,
    agents: [...state.agents.filter(a => a.id !== 'coder'), member('coder', 'Coder', 'waiting'), member('tester', 'Tester', 'running')],
    rooms: [room({ paused: true, members: [...room().members, { agent_id: 'tester', role: 'Tester', status: 'in' }] })],
  })
  panel(held)
  const head = screen.getByRole('region', { name: 'The room' })
  expect(head).toHaveTextContent('Coder · paused')
  expect(head).toHaveTextContent('Tester · at work')
  expect(head).toHaveTextContent('Reviewer · waiting for a post')
  cleanup()
  // Resumed, it is at work again.
  panel(convState({ ...held, rooms: [room({ members: held.rooms[0].members })] }))
  expect(screen.getByRole('region', { name: 'The room' })).toHaveTextContent('Coder · at work')
})

test('tokens no model reported are said to be none reported, not a zero', () => {
  expect(spentLines(room({ spent: { posts: 0, tokens: null, minutes: 0 } }))[1]).toBe('no tokens reported of 400000')
  expect(spentLines(room({ budget: { posts: 40, tokens: null, minutes: 30 }, spent: { posts: 0, tokens: null, minutes: 0 } }))[1]).toBe(
    'no tokens reported (no limit)',
  )
  // B-390: billed tokens, said so beside the agents' boxes (their context now); R185: no limit unless set
  expect(spentLines(room({ budget: { posts: 40, tokens: null, minutes: 30 } }))[1]).toBe(
    '1200 tokens sent and written (no limit) - each step resends its context',
  )
})

test('a room that ended says why in its own words, and in short in its head', () => {
  expect(roomLine(room({ status: 'ended', outcome: 'budget', why: 'posts' }))).toBe('Ended: its budget of posts was reached')
  expect(roomLine(room({ status: 'ended', outcome: 'too_few', why: 'unanswered' }))).toBe(
    'Ended: everybody’s work is over, and a question was left unanswered',
  )
  expect(roomLine(room({ status: 'ended', outcome: 'too_few' }))).toBe('Ended: fewer than two members were still working')
  // the head's tag: how it ended, and how many of its items are done of all
  const tag = (over: Partial<Room>, items = state.roomItems) => roomTag({ roomItems: items }, room(over))
  expect(tag({ status: 'ended', outcome: 'agreed' })).toBe('done · 1 of 3')
  expect(tag({ status: 'ended', outcome: 'agreed' }, [])).toBe('done')
  expect(tag({ status: 'ended', outcome: 'budget', why: 'posts' })).toBe('out of posts · 1 of 3')
  expect(tag({ status: 'ended', outcome: 'ended_by_user' })).toBe('you ended it · 1 of 3')
  expect(tag({ status: 'ended', outcome: 'too_few', why: 'unanswered' })).toBe('a question was left · 1 of 3')
  expect(tag({ status: 'cancelled' })).toBe('stopped')
  expect(tag({ status: 'interrupted' })).toBe('interrupted')
  expect(tag({})).toBe('at work')
})

test('a limit the room does not have is said as none, not as a number', () => {
  expect(spentLines(room({ budget: { posts: null, tokens: 9000, minutes: null }, spent: { posts: 2, tokens: 0, minutes: 1 } }))).toEqual([
    '2 posts (no limit)',
    '0 of 9000 tokens sent and written - each step resends its context',
    '1 minutes (no limit)',
  ])
})

test('the items are one line each - how it stands, what it is, who has it - and what came of one unfolds', async () => {
  panel()
  const items = screen.getByRole('region', { name: 'Items' })
  const lines = within(items).getAllByRole('group')
  expect(lines.map(line => line.querySelector('summary')!.textContent)).toEqual([
    'taken1. Change the greetingCoder',
    '✓ done2. Review the greetingReviewer',
    'open3. Write the notes', // nobody's: no holder is made up for it
  ])
  expect(lines.every(line => !line.hasAttribute('open'))).toBe(true)
  expect(lines[0]).toHaveTextContent('hello.py')
  await userEvent.click(within(lines[1]).getByText('Review the greeting', { exact: false }))
  expect(lines[1]).toHaveAttribute('open')
  expect(lines[1]).toHaveTextContent('It prints yo, as asked.')
})

test('while it runs the talk is open; a member’s report is under Reports, with no line of KOLONİ’s that its work is over', () => {
  panel()
  const open = screen.getByRole('region', { name: 'Open questions' })
  expect(open).toHaveTextContent('1. Coder to Reviewer')
  expect(open).toHaveTextContent('Which greeting do you want?')
  expect(open).not.toHaveTextContent('Tests first!')
  const said = screen.getByRole('group', { name: 'Said in the room' })
  expect(said).toHaveAttribute('open')
  expect(said).toHaveTextContent('Said in the room 3 messages')
  expect(said).toHaveTextContent('1. Coder · question · to Reviewer')
  expect(said).toHaveTextContent('2. You')
  expect(said).toHaveTextContent('3. Reviewer · review · to Coder')
  expect(said).not.toHaveTextContent('Looked at it: fine.')
  const reports = screen.getByRole('group', { name: 'Reports' })
  expect(reports).not.toHaveAttribute('open')
  expect(reports).toHaveTextContent('Reports Reviewer')
  expect(reports).toHaveTextContent('Looked at it: fine.')
  expect(screen.getByRole('dialog')).not.toHaveTextContent('work is over')
})

test('a line of KOLONİ’s said again word for word shows once, with how many times', () => {
  const posts = [post(1, 'rev', 'left', 'It failed: the model is gone.'), post(2, 'coder', 'result', 'ok'), post(3, 'rev', 'left', 'It failed: the model is gone.'), post(4, 'coder', 'result', 'ok')]
  expect(once(posts).map(([post, times]) => [post.number, times])).toEqual([[1, 2], [2, 1], [4, 1]])
  panel(convState({ ...state, roomPosts: posts }))
  const said = screen.getByRole('group', { name: 'Said in the room' })
  expect(said).toHaveTextContent('1. Reviewer · left the room ×2')
  expect(said).not.toHaveTextContent('3. Reviewer')
  expect(said).toHaveTextContent('4. Coder · result') // what a member says twice is its own: both stay
})

test('while it runs you write into it, give it more and end it', async () => {
  const [onSay, onEnd, onMore] = [vi.fn(noop), vi.fn(noop), vi.fn(noop)]
  panel(state, { onSay, onEnd, onMore })
  expect(screen.getByLabelText('Say something in the room')).toHaveAttribute('placeholder', 'Say something…')
  await userEvent.type(screen.getByLabelText('Say something in the room'), 'Tests first!')
  await userEvent.click(screen.getByRole('button', { name: 'Post' }))
  expect(onSay).toHaveBeenCalledWith('o', 'Tests first!')
  expect(screen.getByLabelText('Say something in the room')).toHaveValue('')

  await userEvent.click(screen.getByRole('button', { name: 'Give it more' }))
  const more = screen.getByRole('form', { name: 'Give it more' })
  expect(within(more).getByRole('button', { name: 'Add' })).toBeDisabled()        // nothing to add yet
  await userEvent.type(within(more).getByLabelText('More posts'), '5')
  await userEvent.type(within(more).getByLabelText('More minutes'), '10')
  await userEvent.click(within(more).getByRole('button', { name: 'Add' }))
  expect(onMore).toHaveBeenCalledWith('o', { posts: 5, minutes: 10 })

  await userEvent.click(screen.getByRole('button', { name: 'End' }))
  expect(onEnd).toHaveBeenCalledWith('o')
})

test('— and Esc make a running room small, and so does ×: a running room keeps its tab', async () => {
  const [onShrink, onClose] = [vi.fn(), vi.fn()]
  panel(state, { onShrink, onClose })
  await userEvent.click(screen.getByRole('button', { name: 'Make the room small' }))
  await userEvent.click(screen.getByRole('button', { name: 'Close the room' }))
  screen.getByRole('dialog').focus()
  await userEvent.keyboard('{Escape}')
  expect(onShrink).toHaveBeenCalledTimes(3)
  expect(onClose).not.toHaveBeenCalled()
})

test('what the server refuses is said, and nothing is added to a limit the room does not have', async () => {
  const onSay = vi.fn(async () => {
    throw Object.assign(new Error('x'), { detail: 'this room is over' })
  })
  panel(convState({ ...state, rooms: [room({ budget: { posts: null, tokens: 400000, minutes: 30 } })] }), { onSay })
  await userEvent.type(screen.getByLabelText('Say something in the room'), 'late')
  await userEvent.click(screen.getByRole('button', { name: 'Post' }))
  expect(screen.getByRole('alert')).toHaveTextContent('this room is over')
  expect(screen.getByLabelText('Say something in the room')).toHaveValue('late')    // not lost
  await userEvent.click(screen.getByRole('button', { name: 'Give it more' }))
  expect(screen.getByLabelText('More posts')).toBeDisabled()
})

const ended = (over: Partial<Room> = {}) =>
  convState({
    ...state,
    rooms: [room({ status: 'ended', outcome: 'agreed', summary: 'hello.py prints yo. It prints yo, as asked.', members: [{ agent_id: 'coder', role: 'Coder', status: 'done' }, { agent_id: 'rev', role: 'Reviewer', status: 'done' }], ...over })],
    roomItems: state.roomItems.map(i => ({ ...i, status: 'done' as const, holder_agent_id: i.holder_agent_id ?? 'coder' })),
    roomPosts: state.roomPosts.map(p => ({ ...p, open: false })),
  })

test('once it is over the same window says what came of it: its line, the items, and what was said and reported, folded', async () => {
  const [onShrink, onClose] = [vi.fn(), vi.fn()]
  panel(ended(), { onShrink, onClose })
  const window = screen.getByRole('dialog', { name: 'Room: Fix the greeting together' })
  expect(within(window).getByText('done · 3 of 3')).toHaveAttribute('title', 'Ended: everybody’s work is over')
  expect(within(window).getByText('hello.py prints yo. It prints yo, as asked.')).toBeInTheDocument()
  // nothing of its copy waits for you: no From you
  expect(screen.queryByRole('region', { name: 'From you' })).toBeNull()
  expect(screen.getByRole('region', { name: 'Items' })).toHaveTextContent('✓ done2. Review the greetingReviewer')
  expect(screen.getByRole('group', { name: 'Said in the room' })).not.toHaveAttribute('open')
  expect(screen.getByRole('group', { name: 'Reports' })).not.toHaveAttribute('open')
  // neither written into, given more nor ended; — is gone, and × closes it for good
  expect(screen.queryByLabelText('Say something in the room')).toBeNull()
  expect(screen.queryByRole('button', { name: 'End' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Give it more' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Make the room small' })).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Close the room' }))
  expect(onClose).toHaveBeenCalled()
  // Esc makes it small, over as it is: a tab, not gone
  screen.getByRole('dialog').focus()
  await userEvent.keyboard('{Escape}')
  expect(onShrink).toHaveBeenCalledTimes(1)
  expect(onClose).toHaveBeenCalledTimes(1)
})

test('a room that ended otherwise says so in short in its head, and with nothing done it has no line made up', () => {
  panel(convState({ ...state, rooms: [room({ status: 'ended', outcome: 'budget' })] }))
  expect(screen.getByText('out of budget · 1 of 3')).toHaveAttribute('title', 'Ended: its budget was reached')
  expect(screen.getByRole('region', { name: 'The room' }).querySelector('.room-summary')).toBeNull()
})

test('K-oda-lead: a room its opener ended says so, its sentence is its line, and its last word is in the talk', () => {
  const s = ended({ agent_id: 'lead', outcome: 'ended_by_opener', summary: 'It prints yo; checked.' })
  panel({ ...s, roomPosts: [...s.roomPosts, post(9, 'lead', 'ended', 'It prints yo; checked.')] })
  const window = screen.getByRole('dialog', { name: 'Room: Fix the greeting together' })
  expect(within(window).getByText('its opener ended it · 3 of 3')).toHaveAttribute('title', 'Ended: the agent that opened it ended it')
  expect(window.querySelector('.room-summary')).toHaveTextContent('It prints yo; checked.')
  expect(screen.getByRole('group', { name: 'Said in the room' })).toHaveTextContent('9. Orchestrator · ended the room')
})

const merge = (over: Partial<Merge> = {}): Merge => ({
  id: 'g1',
  run_id: 'r',
  agent_id: 'lead',
  status: 'pending',
  files: [{ path: 'hello.py', kind: 'changed', state: 'ready', diff: '--- a/hello.py\n+++ b/hello.py\n@@ -1 +1 @@\n-hi\n+yo', additions: 1, deletions: 1, note: null }],
  kept_in: null,
  check: null,
  commit: null,
  room_id: 'o',
  created_at: '2026-10-13T10:00:00Z',
  decided_at: null,
  ...over,
})

test('what a member waits on you for is in the room’s window: no call of the lead’s opened it', async () => {
  const onDecideCommand = vi.fn(noop)
  const asks = convState({ ...state, commands: [command('k', 'r', { agent_id: 'coder', status: 'proposed', started_at: null, ended_at: null })] })
  expect(waitsForYou(asks, asks.rooms[0])).toBe(true)
  expect(waitsForYou(state, state.rooms[0])).toBe(false)
  panel(asks, { on: { ...on, onDecideCommand } })
  const waiting = screen.getByRole('region', { name: 'Waits for you' })
  expect(waiting).toHaveTextContent('Coder asks')
  expect(waiting).toHaveTextContent('pytest -q')
  await userEvent.click(within(waiting).getByRole('button', { name: 'Run once' }))
  expect(onDecideCommand).toHaveBeenCalledWith('k', 'once')
})

test('nothing waiting, there is no Waits for you', () => {
  panel()
  expect(screen.queryByRole('region', { name: 'Waits for you' })).toBeNull()
})

test('the room’s changes are asked about once, From you, on a card that says it is the room’s', async () => {
  const onDecideMerge = vi.fn(noop)
  const over = convState({ ...ended(), merges: [merge()] })
  expect(waitsForYou(over, over.rooms[0])).toBe(true)
  panel(over, { on: { ...on, onDecideMerge } })
  const fromYou = screen.getByRole('region', { name: 'From you' })
  expect(fromYou).toHaveTextContent("Take in The room's work?")
  expect(fromYou).toHaveTextContent('hello.py')
  expect(fromYou).not.toHaveTextContent('did not finish')
  await userEvent.click(within(fromYou).getByRole('button', { name: 'Take in' }))
  expect(onDecideMerge).toHaveBeenCalledWith('g1', 'approve', {}, {}) // nothing clashed: no side to choose
})

test('once the room’s changes are applied, From you goes on with their commit where it is offered', () => {
  const applied = merge({ status: 'applied', files: [{ ...merge().files[0], state: 'applied' }], commit: { state: 'offered', message: 'Room: Fix the greeting together', sha: null } })
  panel(convState({ ...ended(), merges: [applied] }))
  expect(within(screen.getByRole('region', { name: 'From you' })).getByRole('group', { name: /Commit of/ })).toBeInTheDocument()
})

test('only the room’s own copy is on its card: not another copy of its lead’s, with its files and its commit', () => {
  // the lead's recipe or earlier room: applied, its commit offered - and the room's own, still asked about
  const other = merge({ id: 'g0', room_id: null, status: 'applied', files: [{ path: 'calc.py', kind: 'changed', state: 'applied', diff: '', additions: 1, deletions: 1, note: null }], commit: { state: 'offered', message: 'Room: Fix the greeting together', sha: null } })
  const over = convState({ ...ended(), merges: [other, merge()] })
  panel(over)
  const fromYou = screen.getByRole('region', { name: 'From you' })
  expect(fromYou).toHaveTextContent("Take in The room's work?")
  expect(fromYou).not.toHaveTextContent('calc.py')
  expect(within(fromYou).queryByRole('group', { name: /Commit of/ })).toBeNull()
  expect(waitsForYou(convState({ ...over, merges: [{ ...other, status: 'pending' }] }), over.rooms[0])).toBe(false)
})

test('B-156: a kept copy of the room’s that holds no file is nothing From you - one that holds a file is', () => {
  const kept = { status: 'interrupted' as const, kept_in: 'C:/copies/room' }
  panel(convState({ ...ended(), merges: [merge({ ...kept, files: [] })] }))
  expect(screen.queryByRole('region', { name: 'From you' })).toBeNull()
  cleanup()
  panel(convState({ ...ended(), merges: [merge(kept)] }))
  expect(screen.getByRole('region', { name: 'From you' })).toBeInTheDocument()
})

test('a room that did not end with everybody done says so on the card of its changes', () => {
  panel(convState({ ...ended({ outcome: 'ended_by_user' }), merges: [merge()] }))
  expect(screen.getByRole('region', { name: 'From you' })).toHaveTextContent('The room did not finish its work')
})

// --- the chat panel and the canvas's foot ----------------------------------------------------

test('the chat has no Room tab, and Channel is Talk', () => {
  useApp.setState({ conv: state, projectId: 'p' })
  render(<ChatPanel />)
  expect(screen.getAllByRole('tab').map(tab => tab.textContent)).toEqual(['Chat', 'Talk', 'Notes'])
  expect(screen.getByRole('tab', { name: 'Talk' })).toHaveAttribute('title', 'What the agents say to each other, to hand work on or ask one another')
})

test('a running room with no window open is a tab at the canvas’s foot that opens it; — makes it a tab again, with the focus on it', async () => {
  useApp.setState({ conv: state, projectId: 'p' })
  render(<ChatPanel />)
  expect(screen.queryByRole('dialog')).toBeNull() // nothing opens by itself
  await userEvent.click(screen.getByRole('button', { name: 'Room · Fix the greeting together · 3 posts' }))
  const window = await screen.findByRole('dialog', { name: 'Room: Fix the greeting together' })
  await waitFor(() => expect(window).toHaveFocus())
  expect(screen.queryByRole('group', { name: 'Rooms' })).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Make the room small' }))
  expect(screen.queryByRole('dialog')).toBeNull()
  await waitFor(() => expect(screen.getByRole('button', { name: 'Room · Fix the greeting together · 3 posts' })).toHaveFocus())
})

test('a question that comes while the room is small is said on its tab, in the accent colour, and opens nothing', () => {
  const asks = convState({ ...state, commands: [command('k', 'r', { agent_id: 'coder', status: 'proposed', started_at: null, ended_at: null })] })
  useApp.setState({ conv: asks, projectId: 'p', roomWindows: { o: 'small' } })
  render(<ChatPanel />)
  const tab = screen.getByRole('button', { name: 'Room · Fix the greeting together · 3 posts waits for you' })
  expect(tab).toHaveClass('asks')
  expect(screen.queryByRole('dialog')).toBeNull()
})

test('in the chat a room is one line that opens its window, and an ended one closed with × leaves the canvas', async () => {
  useApp.setState({ conv: ended(), projectId: 'p' })
  render(<ChatPanel />)
  expect(screen.queryByRole('group', { name: 'Rooms' })).toBeNull() // over, and never opened: no tab
  const chat = screen.getByRole('region', { name: 'Chat' })
  const row = within(chat).getByRole('button', { name: 'Room · Fix the greeting together done · 3 of 3 · Open' })
  // in the chat it is that line only: no reports, nothing said in the room
  expect(chat).not.toHaveTextContent('Looked at it: fine.')
  await userEvent.click(row)
  expect(screen.getByRole('dialog')).toHaveTextContent('hello.py prints yo. It prints yo, as asked.')
  await userEvent.click(screen.getByRole('button', { name: 'Close the room' }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.queryByRole('group', { name: 'Rooms' })).toBeNull()
  // the focus goes back to where it can be opened again: its line
  await waitFor(() => expect(row).toHaveFocus())
})

test('a room not opened in this page that ended with its changes waiting has its tab, and the chat opens with Ready for you’s panel, which has its card', async () => {
  useApp.setState({ conv: convState({ ...ended(), merges: [merge()] }), projectId: 'p' })
  render(<ChatPanel />)
  expect(screen.getByRole('button', { name: 'Room · Fix the greeting together · done · 3 of 3 waits for you' })).toHaveClass('asks')
  await userEvent.click(screen.getByRole('button', { name: 'Hide chat' }))
  await userEvent.click(screen.getByRole('button', { name: /^Chat/ }))
  expect(screen.getByRole('tab', { name: 'Chat' })).toHaveAttribute('aria-selected', 'true')
  expect(useApp.getState().readyPanel.open).toBe(true)
})

test('a member’s read outside the folder waits for you in the room, and what members said of their work stays once it is over', () => {
  const outside = toolCall('x', 'r', 'read_file', 'pending', '{"path": "C:/elsewhere/a.txt"}', { agent_id: 'coder', started_at: 't' })
  const asks = convState({ ...state, toolCalls: [outside] })
  expect(waitsForYou(asks, asks.rooms[0])).toBe(true)
  panel(asks)
  expect(screen.getByRole('region', { name: 'Waits for you' })).toHaveTextContent('Coder asks')
  // a member's word to another member, once the room is over: still there, with no box of what waits
  const talk = toolCall('t', 'r', 'message_agent', 'succeeded', '{"to": "Reviewer", "message": "Look at line 2"}', { agent_id: 'coder' })
  panel(convState({ ...ended(), toolCalls: [talk] }))
  expect(screen.getAllByRole('dialog')[1]).toHaveTextContent('Look at line 2')
  expect(screen.getAllByRole('dialog')[1].querySelector('.room-ask')).toBeNull()
})

test('a room that ended with a member gone says who, and Esc leaves a word half written alone', async () => {
  const onShrink = vi.fn()
  panel(ended({ outcome: 'too_few', members: [{ agent_id: 'coder', role: 'Coder', status: 'done' }, { agent_id: 'rev', role: 'Reviewer', status: 'left' }] }), { onShrink })
  expect(screen.getByRole('region', { name: 'The room' })).toHaveTextContent('Reviewer · left')
  expect(screen.getByText('fewer than two working · 3 of 3')).toBeInTheDocument()
  // (running: a draft in the say box)
  panel(state, { onShrink })
  const box = screen.getAllByLabelText('Say something in the room')[0]
  await userEvent.type(box, 'half{Escape}')
  expect(onShrink).not.toHaveBeenCalled()
  await userEvent.clear(box)
  await userEvent.type(box, '{Escape}')
  expect(onShrink).toHaveBeenCalledTimes(1)
})

// --- the form --------------------------------------------------------------------------------

const role = (name: string): Role =>
  ({ id: name, name, description: '', instructions: '', tools: [], builtin: true, created_by_agent: false, models: null, provider_id: null, model_id: null, tier: null, pick_from: null, max_steps: null, max_tokens: null, mcp: [], created_at: 't', updated_at: 't' }) as Role
const provider = (id: string, name: string, over: Partial<Provider> = {}): Provider =>
  ({ id, name, kind: 'openai_compat', base_url: 'http://127.0.0.1:1/v1', default_model: 'its-default', mode: null, ...over }) as Provider

const ROLES = [role('Lead'), role('Coder'), role('Tester'), role('Reviewer')]
const PROVIDERS = [provider('p1', 'Local'), provider('p2', 'Codex', { kind: 'codex_cli', mode: 'native' })]
const LIMITS = { posts: 40, tokens: 400000, minutes: null }

const form = (over: Partial<Parameters<typeof WorkTogether>[0]> = {}) => {
  const onOpen = vi.fn(noop)
  render(<WorkTogether roles={ROLES} providers={PROVIDERS} limits={LIMITS} busy={false} onOpen={onOpen} {...over} />)
  return onOpen
}

test('"Work together…" opens a room with a goal, two to six members and what it may spend', async () => {
  const onOpen = form()
  await userEvent.click(screen.getByRole('button', { name: /Work together/ }))
  const open = screen.getByRole('button', { name: 'Open the room' })
  expect(open).toBeDisabled()                                                      // no goal yet
  // it starts from a Coder and a Reviewer, and from the conversation's own limits
  expect(screen.getByLabelText('Role of member 1')).toHaveValue('Coder')
  expect(screen.getByLabelText('Role of member 2')).toHaveValue('Reviewer')
  expect(screen.getByLabelText('Posts by its members')).toHaveValue('40')
  expect(screen.getByLabelText('Minutes')).toHaveValue('')                         // none
  expect(screen.queryByRole('button', { name: 'Remove' })).toBeNull()               // two is the fewest

  await userEvent.type(screen.getByLabelText('Goal'), 'Fix the greeting together')
  await userEvent.click(screen.getByRole('button', { name: 'Add a member' }))
  await userEvent.selectOptions(screen.getByLabelText('Role of member 3'), 'Tester')
  await userEvent.selectOptions(screen.getByLabelText('Provider of member 1'), 'p1')
  await userEvent.type(screen.getByLabelText('Model of member 1'), 'qwen-big')
  await userEvent.clear(screen.getByLabelText('Posts by its members'))
  await userEvent.type(screen.getByLabelText('Posts by its members'), '12')
  await userEvent.clear(screen.getByLabelText('Tokens sent and written'))
  await userEvent.click(open)
  expect(onOpen).toHaveBeenCalledWith({
    goal: 'Fix the greeting together',
    // a provider goes by its name; a member with none runs on its role's own model
    with: [{ role: 'Coder', provider: 'Local', model: 'qwen-big' }, { role: 'Reviewer' }, { role: 'Tester' }],
    // said whole: what was emptied is no limit
    budget: { posts: 12, tokens: null, minutes: null },
    over_budget: false,
  })
  expect(screen.queryByRole('form', { name: 'Work together' })).toBeNull()         // closed once it is open
})

test('over the month’s budget the room waits for the user’s word, as a message does', async () => {
  const over = new ApiError(409, "this project is over this month's budget (10.50 of 10.00 USD): say to go on over it")
  const onOpen = vi.fn().mockRejectedValueOnce(over).mockRejectedValueOnce(over).mockResolvedValue(undefined)
  form({ onOpen })
  await userEvent.click(screen.getByRole('button', { name: /Work together/ }))
  await userEvent.type(screen.getByLabelText('Goal'), 'x')
  await userEvent.click(screen.getByRole('button', { name: 'Open the room' }))
  const card = screen.getByRole('group', { name: 'Over this month’s budget' })
  expect(card).toHaveTextContent('Open the room anyway?')
  expect(within(card).getByRole('button', { name: 'Go on anyway' })).toHaveFocus()
  await userEvent.click(within(card).getByRole('button', { name: 'Cancel' }))
  expect(screen.getByRole('button', { name: 'Open the room' })).toHaveFocus()
  await userEvent.click(screen.getByRole('button', { name: 'Open the room' }))
  await userEvent.click(screen.getByRole('button', { name: 'Go on anyway' }))
  expect(onOpen).toHaveBeenLastCalledWith(expect.objectContaining({ goal: 'x', over_budget: true }))
})

test('the limits written for one room are that room’s; the project’s are set in one place, which the form names', async () => {
  const onOpen = form()
  await userEvent.click(screen.getByRole('button', { name: /Work together/ }))
  expect(screen.queryByLabelText(/Keep these limits/)).toBeNull()
  expect(screen.getByText(/A room starts from the project’s limits: Settings › This project › New chats start with\./)).toBeInTheDocument()
  await userEvent.type(screen.getByLabelText('Goal'), 'x')
  await userEvent.type(screen.getByLabelText('Minutes'), '15')
  await userEvent.click(screen.getByRole('button', { name: 'Open the room' }))
  expect(onOpen).toHaveBeenCalledTimes(1)
  // opened again, it starts from what the conversation has
  await userEvent.click(screen.getByRole('button', { name: /Work together/ }))
  expect(screen.getByLabelText('Minutes')).toHaveValue('')
})

test('six is the most, a CLI with its own tools cannot be picked, and a limit is a whole number from 1', async () => {
  form()
  await userEvent.click(screen.getByRole('button', { name: /Work together/ }))
  await userEvent.type(screen.getByLabelText('Goal'), 'x')
  for (let n = 0; n < 4; n++) await userEvent.click(screen.getByRole('button', { name: 'Add a member' }))
  expect(screen.queryByRole('button', { name: 'Add a member' })).toBeNull()
  expect(screen.getAllByRole('button', { name: 'Remove' })).toHaveLength(6)
  expect(within(screen.getByLabelText('Provider of member 1')).getByRole('option', { name: /Codex/ })).toBeDisabled()
  await userEvent.clear(screen.getByLabelText('Posts by its members'))
  await userEvent.type(screen.getByLabelText('Posts by its members'), '0')
  expect(screen.getByRole('button', { name: 'Open the room' })).toBeDisabled()
  expect(screen.getByText(/A limit is a whole number from 1/)).toBeInTheDocument()
})

test('while a turn is at work no room is opened, and what the server refuses is said in the form', async () => {
  const onOpen = vi.fn(async () => {
    throw Object.assign(new Error('x'), { detail: 'unknown role: Coder' })
  })
  const { rerender } = render(<WorkTogether roles={ROLES} providers={PROVIDERS} limits={LIMITS} busy onOpen={onOpen} />)
  await userEvent.click(screen.getByRole('button', { name: /Work together/ }))
  await userEvent.type(screen.getByLabelText('Goal'), 'x')
  expect(screen.getByRole('button', { name: 'Open the room' })).toBeDisabled()
  expect(screen.getByText(/Something is at work/)).toBeInTheDocument()
  rerender(<WorkTogether roles={ROLES} providers={PROVIDERS} limits={LIMITS} busy={false} onOpen={onOpen} />)
  await userEvent.click(screen.getByRole('button', { name: 'Open the room' }))
  expect(screen.getByRole('alert')).toHaveTextContent('unknown role: Coder')
  expect(screen.getByLabelText('Goal')).toHaveValue('x')                           // still there to send again
})

// --- the state, the canvas and a member's own record -----------------------------------------

test('a room, its items and its posts arrive as events and are kept by their ids', () => {
  let s = convState()
  s = applyEvent(s, 1, 'room.created', room({ status: 'sharing' }))
  s = applyEvent(s, 2, 'room.updated', room())
  s = applyEvent(s, 3, 'room_item.created', item(1, 'Change the greeting'))
  s = applyEvent(s, 4, 'room_item.updated', item(1, 'Change the greeting', { status: 'taken', holder_agent_id: 'coder' }))
  s = applyEvent(s, 5, 'room_post.created', post(1, 'coder', 'question', 'Which?', { open: true }))
  s = applyEvent(s, 6, 'room_post.updated', post(1, 'coder', 'question', 'Which?'))
  expect(s.rooms.map(r => r.status)).toEqual(['working'])
  expect(s.roomItems.map(i => [i.status, i.holder_agent_id])).toEqual([['taken', 'coder']])
  expect(s.roomPosts.map(p => p.open)).toEqual([false])
  // the page listens for every one of them
  for (const type of ['room.created', 'room.updated', 'room_item.created', 'room_item.updated', 'room_post.created', 'room_post.updated']) {
    expect(EVENT_TYPES).toContain(type)
  }
})

test('on the canvas the room is a node of its own, by the lead that waits for it and joined to its members', () => {
  const waits = toolCall('9', 'r', 'wait_for_post', 'running', '{}', { agent_id: 'rev' })
  const { nodes, edges } = deriveGraph(convState({ ...state, toolCalls: [waits] }))
  const node = nodes.find(n => n.kind === 'room')!
  // what each waits for is said as it is: the lead for the room, a member for a post
  const doing = (id: string) => (nodes.find(n => n.id === id)!.data as { activity: string }).activity
  expect([doing('agent:lead'), doing('agent:rev')]).toEqual(['Waiting for the room', 'Waiting for a post in the room'])
  const forItem = toolCall('9', 'r', 'wait_for_item', 'running', '{"item": 1}', { agent_id: 'rev' })
  const waiting = deriveGraph(convState({ ...state, toolCalls: [forItem] })).nodes.find(n => n.id === 'agent:rev')!
  expect((waiting.data as { activity: string }).activity).toBe('Waiting for an item in the room')
  expect(node).toMatchObject({ id: 'room:o', runId: 'r', refId: 'o', agentId: 'lead' })
  expect(node.data).toMatchObject({
    goal: 'Fix the greeting together',
    line: 'At work',
    members: ['Coder · at work', 'Reviewer · waiting for a post'],
    items: '1 of 3 items done',
    running: true,
    attention: false,
  })
  // each member's own work stays on its own node, a sub-agent of the lead's as any is
  expect(edges.filter(e => e.target === 'room:o').map(e => [e.source, e.active])).toEqual([
    ['agent:coder', true],
    ['agent:rev', false],
  ])
  expect(edges.some(e => e.source === 'agent:lead' && e.target === 'agent:coder' && e.spawn)).toBe(true)
  // where each changes files is said as the room's copy, not as the lead's own
  expect(copyLine(state, state.agents[1])).toBe('works in the room’s copy')
  expect(copyLine(state, state.agents[0])).toBe('holds the room’s copy')
})

test('the room’s node opens a panel that says where it stands, and a way into its window', async () => {
  const onOpenRoom = vi.fn()
  render(<Inspector state={state} selectedId="room:o" onClose={() => {}} onOpenRoom={onOpenRoom} />)
  expect(screen.getByText('Fix the greeting together')).toBeInTheDocument()
  expect(screen.getByText('Coder · at work · Reviewer · waiting for a post')).toBeInTheDocument()
  expect(
    screen.getByText('3 of 40 posts · 1200 of 400000 tokens sent and written - each step resends its context · 2.5 of 30 minutes'),
  ).toBeInTheDocument()
  expect(screen.getByText('Looked at it: fine.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Open the room' }))
  expect(onOpenRoom).toHaveBeenCalledWith('o')
})

test('a post handed to a member is on its own record as handed from the room', () => {
  const handed = { ...assistantMessage('h', 'r', 'Said in the room - post 2. the user: "Tests first!"'), role: 'agent' as const, agent_id: 'rev', room_post_id: 's2', delivered_at: 't' }
  render(<AgentSteps state={convState({ ...state, messages: [handed] })} agent={state.agents[2]} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(screen.getByText('handed to it from the room')).toBeInTheDocument()
  expect(screen.getByText(/Tests first!/)).toBeInTheDocument()
  expect(screen.queryByText('from Agent')).toBeNull()                              // nobody is made its sender
})

test('"Work together…" stands under More, in the row under the message box with the model, which is drawn once', async () => {
  // (It once had the model picker's key: two children of one key in one row are drawn twice.)
  useApp.setState({ conv: state, projectId: 'p', providers: PROVIDERS, roles: ROLES })
  render(<ChatPanel />)
  await userEvent.click(screen.getByRole('button', { name: 'More' }))
  expect(screen.getAllByRole('button', { name: /^Model: / })).toHaveLength(1)
  expect(screen.getAllByRole('button', { name: /Work together/ })).toHaveLength(1)
})

// --- a room an agent opens (slice 29b-2) -----------------------------------------------------

test('an agent’s room: its members are asked for under its call, and then the call is the room, saying who opened it', async () => {
  const onDecideSpawn = vi.fn(noop)
  const asked = (id: string, name: string) =>
    agent('r', 'proposed', { id, parent_agent_id: 'lead', tool_call_id: 'c1', role_name: name, name, task: 'Fix the greeting together', depth: 1 })
  const opening = convState({
    runs: [run('r', 'running')],
    messages: [userMessage('r', 'fix it'), assistantMessage('m', 'r', '')],
    agents: [agent('r', 'waiting', { id: 'lead' }), asked('coder', 'Coder'), asked('rev', 'Reviewer')],
    toolCalls: [toolCall('c1', 'r', 'open_room', 'running', '{}', { agent_id: 'lead' })],
  })
  const list = (s: typeof opening) => <MessageList state={s} onRemoveQueued={() => {}} onOpenChange={() => {}} onDecide={noop} onDecideCommand={noop} onDecideSpawn={onDecideSpawn} />
  const { rerender } = render(list(opening))
  expect(screen.getAllByText('Open this sub-agent?')).toHaveLength(2)
  await userEvent.click(screen.getAllByRole('button', { name: 'Open agent' })[1])
  expect(onDecideSpawn).toHaveBeenCalledWith('rev', 'approve')

  const open = convState({ ...opening, agents: [opening.agents[0], member('coder', 'Coder', 'running'), member('rev', 'Reviewer', 'waiting')], rooms: [room({ agent_id: 'lead' })] })
  rerender(list(open))
  expect(screen.queryByText('Open this sub-agent?')).toBeNull()
  // once, under the call that opened it - not under the user's message as well
  expect(screen.getAllByRole('button', { name: /Room/ })).toHaveLength(1)
  expect(screen.getByRole('button', { name: 'Room · Fix the greeting together at work · Open' })).toBeInTheDocument()
})

test('in its window an agent’s room says who opened it, and one a member asks in waits there for your word', async () => {
  const onDecideSpawn = vi.fn(noop)
  const tester = agent('r', 'proposed', { id: 'tester', parent_agent_id: 'lead', tool_call_id: 'i1', role_name: 'Tester', name: 'Tester', depth: 1 })
  const opened = convState({ ...state, rooms: [room({ agent_id: 'lead' })] })
  const invited = convState({ ...opened, agents: [...opened.agents, tester], toolCalls: [toolCall('i1', 'r', 'invite_to_room', 'running', '{}', { agent_id: 'coder' })] })
  expect(waitsForYou(opened, opened.rooms[0])).toBe(false)
  expect(waitsForYou(invited, invited.rooms[0])).toBe(true)
  panel(invited, { on: { ...on, onDecideSpawn } })
  expect(screen.getByRole('region', { name: 'The room' })).toHaveTextContent('Coder · Reviewer · opened by Orchestrator')
  const waiting = screen.getByRole('region', { name: 'Waits for you' })
  expect(waiting).toHaveTextContent('Tester')
  await userEvent.click(within(waiting).getByRole('button', { name: 'Open agent' }))
  expect(onDecideSpawn).toHaveBeenCalledWith('tester', 'approve')
})

test('K-oda-lead: one its opener asks in while it follows the room waits for your word there too', () => {
  const tester = agent('r', 'proposed', { id: 'tester', parent_agent_id: 'lead', tool_call_id: 'i1', role_name: 'Tester', name: 'Tester', depth: 1 })
  const opened = convState({ ...state, rooms: [room({ agent_id: 'lead' })] })
  const invited = convState({ ...opened, agents: [...opened.agents, tester], toolCalls: [toolCall('i1', 'r', 'invite_to_room', 'running', '{}', { agent_id: 'lead' })] })
  expect(waitsForYou(invited, invited.rooms[0])).toBe(true)
  panel(invited)
  expect(screen.getByRole('region', { name: 'Waits for you' })).toHaveTextContent('Tester')
})

test('an open_room call that was refused is not shown as the room a later call opened', () => {
  const refused = toolCall('c1', 'r', 'open_room', 'failed', '{}', { agent_id: 'lead', seq: 1, result: 'error: the user turned down the Coder' })
  const opened = toolCall('c2', 'r', 'open_room', 'succeeded', '{}', { agent_id: 'lead', seq: 2 })
  const s = convState({ ...state, messages: [userMessage('r', 'fix it'), assistantMessage('m', 'r', '')], toolCalls: [refused, opened], rooms: [room({ agent_id: 'lead' })] })
  render(<MessageList state={s} onRemoveQueued={() => {}} onOpenChange={() => {}} onDecide={noop} onDecideCommand={noop} />)
  expect(screen.getAllByRole('button', { name: /^Room · Fix the greeting together/ })).toHaveLength(1)
})

test('the Observer is not offered as a member', async () => {
  form({ roles: [...ROLES, role('Observer')] })
  await userEvent.click(screen.getByRole('button', { name: /Work together/ }))
  const offered = Array.from(screen.getByLabelText('Role of member 1').querySelectorAll('option'), o => o.textContent)
  expect(offered).toEqual(['Lead', 'Coder', 'Tester', 'Reviewer'])
})

test('R178: the Orchestrator watching a room is said on its window and its card, and its own post is marked', () => {
  const watched = convState({ ...state, rooms: [room({ agent_id: 'lead', lead_follows: 'on' })], roomPosts: [...state.roomPosts, post(5, 'lead', 'said', 'Keep it short.')] })
  panel(watched)
  const said = 'Watched by Orchestrator · can post, invite, end'
  expect(screen.getByRole('region', { name: 'The room' })).toHaveTextContent(said)
  expect(screen.getAllByText('watching')).toHaveLength(1) // (its post, not a member's)
  const node = deriveGraph(watched).nodes.find(n => n.kind === 'room')!
  expect(node.data).toMatchObject({ watched: said, last: [expect.anything(), { who: 'Orchestrator (watching)', text: 'Keep it short.' }] })
  cleanup()
  panel() // (nobody follows it: nothing is said)
  expect(screen.queryByText(/Watched by/)).toBeNull()
})
