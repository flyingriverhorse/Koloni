import { expect, test } from 'vitest'
import type { Room, RoomItem } from '../api/types'
import { roomLine, roomTag } from './roomText'

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
  members: [],
  created_at: '2026-10-13T10:00:00Z',
  ended_at: null,
  ...over,
})
const ended = (over: Partial<Room>) => room({ status: 'ended', ...over })

test('where a room stands, in a few words: every state and every way it ended', () => {
  expect(roomLine(room({ paused: true }))).toBe('Paused: nothing is posted or spent until you resume it')
  expect(roomLine(room({ status: 'sharing', paused: true }))).toBe(
    'Paused: nothing is posted or spent until you resume it',
  )
  expect(roomLine(room({ status: 'sharing' }))).toBe('Sharing the work out')
  expect(roomLine(room())).toBe('At work')
  expect(roomLine(room({ status: 'cancelled', paused: true }))).toBe('Stopped')
  expect(roomLine(room({ status: 'interrupted' }))).toBe('Interrupted')
  expect(roomLine(ended({ paused: true }))).toBe('Ended: it is over')
  expect(roomLine(ended({ outcome: 'agreed' }))).toBe('Ended: everybody’s work is over')
  expect(roomLine(ended({ outcome: 'ended_by_user' }))).toBe('Ended: you ended it')
  expect(roomLine(ended({ outcome: 'ended_by_opener' }))).toBe('Ended: the Orchestrator ended it')
  expect(roomLine(ended({ outcome: 'ended_by_opener', agent_id: 'a' }))).toBe(
    'Ended: the agent that opened it ended it',
  )
  expect(roomLine(ended({ outcome: 'budget', why: 'tokens' }))).toBe('Ended: its budget of tokens was reached')
  expect(roomLine(ended({ outcome: 'budget', why: 'unanswered' }))).toBe('Ended: its budget was reached')
  expect(roomLine(ended({ outcome: 'budget' }))).toBe('Ended: its budget was reached')
  expect(roomLine(ended({ outcome: 'too_few', why: 'unanswered' }))).toBe(
    'Ended: everybody’s work is over, and a question was left unanswered',
  )
  expect(roomLine(ended({ outcome: 'too_few', why: 'posts' }))).toBe('Ended: fewer than two members were still working')
})

test('a room’s tag: every state, and every way it ended with its items done of all', () => {
  const tag = (one: Room) => roomTag({ roomItems: [] }, one)
  expect(tag(room({ paused: true }))).toBe('paused')
  expect(tag(room({ status: 'sharing' }))).toBe('sharing the work out')
  expect(tag(room())).toBe('at work')
  expect(tag(room({ status: 'cancelled', paused: true }))).toBe('stopped')
  expect(tag(room({ status: 'interrupted' }))).toBe('interrupted')
  expect(tag(ended({}))).toBe('over')
  expect(tag(ended({ outcome: 'agreed' }))).toBe('done')
  expect(tag(ended({ outcome: 'ended_by_user' }))).toBe('you ended it')
  expect(tag(ended({ outcome: 'ended_by_opener' }))).toBe('the Orchestrator ended it')
  expect(tag(ended({ outcome: 'ended_by_opener', agent_id: 'a' }))).toBe('its opener ended it')
  expect(tag(ended({ outcome: 'budget', why: 'minutes' }))).toBe('out of minutes')
  expect(tag(ended({ outcome: 'budget', why: 'unanswered' }))).toBe('out of budget')
  expect(tag(ended({ outcome: 'budget' }))).toBe('out of budget')
  expect(tag(ended({ outcome: 'too_few', why: 'unanswered' }))).toBe('a question was left')
  expect(tag(ended({ outcome: 'too_few' }))).toBe('fewer than two working')
  const item = (id: string, room_id: string, status: RoomItem['status']): RoomItem => ({
    id,
    room_id,
    number: 1,
    title: 't',
    paths: [],
    holder_agent_id: null,
    status,
    result: null,
    created_at: '2026-10-13T10:00:01Z',
  })
  const items = [item('1', 'o', 'done'), item('2', 'o', 'open'), item('3', 'other', 'done')]
  expect(roomTag({ roomItems: items }, ended({ outcome: 'too_few' }))).toBe('fewer than two working · 1 of 2')
})
