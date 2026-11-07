import { expect, test } from 'vitest'
import type { Board } from '../api/types'
import { boardTurn } from '../test-fixtures'
import { columnOf, lastAt, since } from './columns'

type BoardConversation = Board['conversations'][number]
type BoardAgent = BoardConversation['agents'][number]

const agent = (status: BoardAgent['status'], last_event_at: string | null = null, over: Partial<BoardAgent> = {}): BoardAgent => ({
  id: status, name: 'Lead', status, role: 'Lead', provider_name: null, model_id: null, holds: [], copy: null,
  waiting_for: null, sign: null, last_event_at, in_tool: false, changes_to_approve: 0, questions: 0, ...over,
})
const talk = (over: Partial<BoardConversation> = {}): BoardConversation => ({
  conversation_id: 'a', title: 'A', agents: [], merges_pending: 0, turn: null, ...over,
})
// Noon, local time: "today" is the browser's own day.
const NOW = new Date(2026, 9, 21, 12, 0)
const at = (day: number, hour: number) => new Date(2026, 9, day, hour, 0).toISOString()

test('work going on is at work, an agent that waits for your word too; a turn that ended today is today’s, failed or stopped too', () => {
  expect(columnOf(talk({ agents: [agent('waiting_approval')] }), NOW)).toBe('work')
  expect(columnOf(talk({ agents: [agent('running')] }), NOW)).toBe('work')
  // a turn that has started but has no agent on the board yet
  expect(columnOf(talk({ turn: boardTurn('r', 'queued', null) }), NOW)).toBe('work')
  // what waits after the turn (changes to take in, a plan) is Ready for you's: the row is where its turn ended
  expect(columnOf(talk({ merges_pending: 1, turn: boardTurn('r', 'completed', at(21, 9)) }), NOW)).toBe('today')
  expect(columnOf(talk({ turn: boardTurn('r', 'completed', at(14, 9), { plan_waits: true }) }), NOW)).toBe('older')
  for (const status of ['failed', 'cancelled', 'interrupted'] as const) {
    expect(columnOf(talk({ turn: boardTurn('r', status, at(21, 9)) }), NOW)).toBe('today')
    expect(columnOf(talk({ turn: boardTurn('r', status, at(14, 9)) }), NOW)).toBe('older')
  }
})

test('a turn that ended today is done today; one of yesterday, and one that never ran, are older', () => {
  expect(columnOf(talk({ turn: boardTurn('r', 'completed', at(21, 0)) }), NOW)).toBe('today')
  expect(columnOf(talk({ turn: boardTurn('r', 'completed', at(20, 23)) }), NOW)).toBe('older')
  expect(columnOf(talk(), NOW)).toBe('older')
})

test('when anything last happened, and how long ago', () => {
  expect(lastAt(talk({ agents: [agent('running', at(21, 10)), agent('running', at(21, 11))], turn: boardTurn('r', 'running', null) }))).toBe(at(21, 11))
  expect(lastAt(talk())).toBeNull()
  expect([at(21, 12), at(21, 11), at(21, 7), at(19, 12)].map(iso => since(iso, NOW.getTime()))).toEqual(['<1 min', '1 h', '5 h', '2 d'])
})
