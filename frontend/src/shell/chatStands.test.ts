import { expect, test } from 'vitest'
import type { Board } from '../api/types'
import { boardTurn } from '../test-fixtures'
import { chatStands, nowSaid } from './chatStands'

type BoardConversation = Board['conversations'][number]
type BoardAgent = BoardConversation['agents'][number]
const onBoard = (over: Partial<BoardConversation> = {}): BoardConversation => ({
  conversation_id: 'c',
  title: 'c',
  agents: [],
  merges_pending: 0,
  turn: null,
  ...over,
})
const agent = (name: string, status: BoardAgent['status'], branch?: string): BoardAgent => ({
  id: name,
  name,
  role: name,
  status,
  provider_name: null,
  model_id: null,
  holds: [],
  copy: branch ? { state: 'own', branch } : null,
  waiting_for: null,
  sign: null,
  last_event_at: null,
  in_tool: false,
  changes_to_approve: 0,
  questions: 0,
  own_questions: 0,
})
const ended = (status: 'completed' | 'failed' | 'interrupted' | 'cancelled') =>
  onBoard({ turn: boardTurn('r', status, '2026-11-26T10:00:00Z', { agents: 1, model_id: 'qwen3', tokens: 900 }) })

test('a chat stands as its cell says: at work with who and on which branch; stuck, done or stopped as its last turn ended', () => {
  expect(
    chatStands(onBoard({ agents: [agent('Lead', 'running'), agent('Coder', 'blocked', 'koloni/login')] }), []),
  ).toEqual(['running', 'Orchestrator working, Coder waiting for a file', 'branch koloni/login'])
  expect(chatStands(ended('completed'), [])).toEqual(['done', 'Done', '1 agent · qwen3 · 900 tokens'])
  expect(chatStands(ended('failed'), [])?.slice(0, 2)).toEqual(['stuck', 'Stuck: its last turn failed'])
  expect(chatStands(ended('interrupted'), [])?.slice(0, 2)).toEqual(['stuck', 'Stuck: its last turn was interrupted'])
  // Stopped by you: nothing is wrong, nothing goes on - the empty cell.
  expect(chatStands(ended('cancelled'), [])?.slice(0, 2)).toEqual(['queued', 'Stopped'])
  expect(chatStands(onBoard(), [])).toEqual(['queued', 'No turn yet', ''])
  // Its To-do task blocked: stuck, though its turn ended well.
  expect(chatStands(ended('completed'), [], { id: 't', status: 'blocked', waiting: false })?.slice(0, 2)).toEqual([
    'stuck',
    'Stuck: its To-do task is blocked',
  ])
  // What waits for your word, as the Board says it before the chat is read.
  expect(chatStands(onBoard({ merges_pending: 1 }), [])).toEqual(['yours', 'Waits for your word', ''])
  // No row on the Board yet: nothing is said.
  expect(chatStands(undefined, [])).toBeNull()
})

test('Now’s sentence: at work, what waits for your word, and today’s; before the Board is read only what waits', () => {
  expect(nowSaid(2, 2, 1, 0, true)).toBe('2 chats at work; 2 things wait for your word. Today 1 stuck.')
  expect(nowSaid(0, 1, 0, 3, true)).toBe('Nothing at work; 1 thing waits for your word. Today 3 done.')
  expect(nowSaid(0, 0, 0, 0, true)).toBe('Nothing at work; nothing waits for your word.')
  expect(nowSaid(0, 3, 0, 0, false)).toBe('How the chats stand is not read yet; 3 things wait for your word.')
})
