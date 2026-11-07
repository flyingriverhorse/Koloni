import { beforeEach, expect, test, vi } from 'vitest'
import type { Board, ListedConversation, Project } from '../api/types'
import { boardTurn, convState } from '../test-fixtures'
import { chatOf, closing, kept, MORE_W, opened, remember, rememberChat, remembered, split, standingOfTab, TAB_MIN } from './openTabs'

const listed = (id: string, project_id: string | null, archived = false): ListedConversation => ({ ...convState().conversation, id, title: id, project_id, kept: false, backlog_task: null, wrote: false, archived_at: archived ? '2026-10-24T10:00:00Z' : null })
const project = (id: string) => ({ id, name: id }) as Project
type BoardConversation = Board['conversations'][number]
const onBoard = (id: string, over: Partial<BoardConversation> = {}): BoardConversation => ({ conversation_id: id, title: id, agents: [], merges_pending: 0, turn: null, ...over })

beforeEach(() => localStorage.clear())

test('a project opened gets its tab at the end; one that has a tab keeps its place', () => {
  expect(opened([], 'p')).toEqual(['p'])
  expect(opened(['p', 'none'], 'q')).toEqual(['p', 'none', 'q'])
  expect(opened(['p', 'none', 'q'], 'p')).toEqual(['p', 'none', 'q'])
})

test('closing the open tab opens its right neighbour, else its left, else nothing; another\'s opens nothing', () => {
  expect(closing(['a', 'b', 'c'], 'b', 'b')).toEqual({ tabs: ['a', 'c'], next: 'c' })
  expect(closing(['a', 'b', 'c'], 'c', 'c')).toEqual({ tabs: ['a', 'b'], next: 'b' })
  expect(closing(['a'], 'a', 'a')).toEqual({ tabs: [], next: null })
  expect(closing(['a', 'b'], 'a', 'b')).toEqual({ tabs: ['b'], next: null })
})

test('the tabs are remembered in the browser, and without its storage there are none', () => {
  remember(['p', 'none'])
  expect(remembered()).toEqual(['p', 'none'])
  localStorage.setItem('koloni-open-chats', '{not json')
  expect(remembered()).toEqual([])
  localStorage.setItem('koloni-open-chats', '{"a": 1}')
  expect(remembered()).toEqual([])
  const closed = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('storage is closed')
  })
  const full = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('storage is closed')
  })
  expect(remembered()).toEqual([])
  expect(() => remember(['p'])).not.toThrow()
  expect(() => rememberChat('p', 'a')).not.toThrow()
  expect(chatOf('p', [listed('a', 'p')])).toBe('a')
  closed.mockRestore()
  full.mockRestore()
})

test('86d\'s tabs, one per chat, are their chats\' folders\' tabs, each once; one of a chat or a folder gone goes', () => {
  const conversations = [listed('a', 'p'), listed('b', 'p'), listed('c', null), listed('d', 'q', true)]
  // (86d kept chat ids; 86e keeps a project's id, or 'none')
  expect(kept(['a', 'gone', 'b', 'c', 'd'], conversations, [project('p'), project('q')])).toEqual(['p', 'none', 'q'])
  expect(kept(['q', 'none', 'p', 'gone'], conversations, [project('p'), project('q')])).toEqual(['q', 'none', 'p'])
  // A folder made a project since the projects were read: kept, as its chat is listed.
  expect(kept(['p'], conversations, [])).toEqual(['p'])
  expect(kept(['r'], conversations, [project('p')])).toEqual([])
})

test('a tab opens the chat opened last in its project, while it is there; else the project\'s newest; else none', () => {
  // (the latest first, as the server lists them)
  const conversations = [listed('new', 'p'), listed('old', 'p'), listed('away', 'p', true), listed('plain', null)]
  expect(chatOf('p', conversations)).toBe('new')
  rememberChat('p', 'old')
  expect(chatOf('p', conversations)).toBe('old')
  expect(chatOf('none', conversations)).toBe('plain')
  // One archived, deleted or moved to another folder since: the newest.
  rememberChat('p', 'away')
  expect(chatOf('p', conversations)).toBe('new')
  rememberChat('p', 'plain')
  expect(chatOf('p', conversations)).toBe('new')
  expect(chatOf('q', conversations)).toBeNull()
  // What the browser kept that is not a map of them: the newest.
  localStorage.setItem('koloni-tab-chats', '"old"')
  expect(chatOf('p', conversations)).toBe('new')
  localStorage.setItem('koloni-tab-chats', 'null')
  expect(chatOf('p', conversations)).toBe('new')
})

test('a tab\'s dot sums its project\'s chats: orange where one waits, green where one works, else grey', () => {
  const conversations = [listed('a', 'p'), listed('b', 'p'), listed('c', null), listed('d', 'q')]
  const asking = { status: 'waiting_approval', changes_to_approve: 1, questions: 0 } as BoardConversation['agents'][number]
  const board = {
    conversations: [onBoard('a', { turn: boardTurn('r', 'completed', 't') }), onBoard('b', { turn: boardTurn('s', 'running', null) }), onBoard('c', { merges_pending: 1 }), onBoard('d', { agents: [asking], turn: boardTurn('u', 'running', null) })],
    backlog_waiting: 0,
  } as unknown as Board
  expect(standingOfTab('p', conversations, board)).toEqual(['working', 'var(--ok)'])
  expect(standingOfTab('none', conversations, board)).toEqual(['waits for you', 'var(--warn)'])
  expect(standingOfTab('q', conversations, board)).toEqual(['waits for you', 'var(--warn)'])
  // done, idle, or not read yet: grey, nothing said
  expect(standingOfTab('p', [listed('a', 'p')], board)).toEqual([null, 'var(--muted)'])
  expect(standingOfTab('p', conversations, null)).toEqual([null, 'var(--muted)'])
})

test('the tabs with no room go into "+N", and the open tab is always shown', () => {
  const tabs = ['a', 'b', 'c', 'd', 'e']
  // all of them fit: no "+N"
  expect(split(tabs, 'a', 5 * TAB_MIN)).toEqual({ shown: tabs, more: [] })
  // not all of them: as many as fit beside the "+N" button
  expect(split(tabs, 'a', 4 * TAB_MIN + MORE_W)).toEqual({ shown: ['a', 'b', 'c', 'd'], more: ['e'] })
  expect(split(tabs, 'b', 2 * TAB_MIN + MORE_W)).toEqual({ shown: ['a', 'b'], more: ['c', 'd', 'e'] })
  // the open one in the list takes the last place shown
  expect(split(tabs, 'e', 2 * TAB_MIN + MORE_W)).toEqual({ shown: ['a', 'e'], more: ['b', 'c', 'd'] })
  // too narrow for even one: the open tab alone
  expect(split(tabs, 'd', 0)).toEqual({ shown: ['d'], more: ['a', 'b', 'c', 'e'] })
  expect(split(tabs, null, 0)).toEqual({ shown: ['a'], more: ['b', 'c', 'd', 'e'] })
  // not measured yet
  expect(split(tabs, 'a', Infinity).more).toEqual([])
})
