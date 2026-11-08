import { expect, test } from 'vitest'
import type { Message } from '../api/types'
import { when } from '../canvas/turns'
import { agent, convState, run, topic, userMessage } from '../test-fixtures'
import {
  chainOf,
  continuesFrom,
  messageTime,
  latestOfUser,
  nextTopic,
  titleOf,
  turnNumbers,
  wentOnIn,
} from './topics'

const byTrigger = (runId: string, content: string): Message => ({ ...userMessage(runId, content), id: `t-${runId}`, role: 'trigger' })
const nightly = { unattended: true, trigger_id: 'tr', trigger_name: 'Nightly look', topic_id: 'tn' }
const at = (minute: number) => `2026-10-05T10:${String(minute).padStart(2, '0')}:00Z`

/**
 * Two topics of the user's and a trigger's: "greeting" has three turns (a1, a2, a3), then
 * a trigger's turn (n1), then "docs" has one (b1) - and one more message waits in the queue (b2).
 */
const state = (over: Parameters<typeof convState>[0] = {}) =>
  convState({
    topics: [topic('ta', 'Fix the greeting'), topic('tn', 'Look the project over', { trigger_id: 'tr' }), topic('tb', 'Write the docs')],
    runs: [
      run('a1', 'completed', { topic_id: 'ta', created_at: at(1) }),
      run('a2', 'completed', { topic_id: 'ta', created_at: at(2) }),
      run('n1', 'completed', { ...nightly, created_at: at(3) }),
      run('a3', 'failed', { topic_id: 'ta', created_at: at(4) }),
      run('b1', 'running', { topic_id: 'tb', created_at: at(5) }),
      run('b2', 'queued', { topic_id: 'tb', created_at: at(6) }),
    ],
    messages: [
      userMessage('a1', 'Fix the greeting\nand the tests'),
      userMessage('a2', 'now in Turkish'),
      byTrigger('n1', 'Look the project over'),
      userMessage('a3', 'and in German'),
      userMessage('b1', 'Write the docs'),
      userMessage('b2', 'with examples'),
    ],
    agents: [
      agent('a1', 'completed'),
      agent('a1', 'completed', { id: 'coder1', parent_agent_id: 'a1', role_name: 'Coder', depth: 1, task: 'Change the greeting', report: 'It says merhaba.' }),
      agent('a2', 'completed', { continues_id: 'a1' }),
      agent('a2', 'completed', { id: 'coder2', parent_agent_id: 'a2', role_name: 'Coder', depth: 1, continues_id: 'coder1', task: 'Now in Turkish' }),
      agent('n1', 'completed'),
      agent('a3', 'failed', { continues_id: 'a2' }),
      agent('a3', 'failed', { id: 'coder3', parent_agent_id: 'a3', role_name: 'Coder', depth: 1, continues_id: 'coder2', task: 'And in German' }),
      agent('b1'),
    ],
    ...over,
  })

// --- which topic the next message goes to (mirrors app/topics.py) -------------------------------

test('the topic the user was last in is that of the newest turn they started in a topic of their own', () => {
  expect(latestOfUser(state())?.id).toBe('tb')
  // a message still in the queue counts (b2); one taken back before its turn started does not: nobody ever worked there
  const removed = state()
  removed.runs = [...removed.runs, run('a4', 'cancelled', { topic_id: 'ta', started_at: null, created_at: at(7) })]
  expect(latestOfUser(removed)?.id).toBe('tb')
  // a turn that was stopped after it started was worked on: it counts
  const stopped = state()
  stopped.runs = [...stopped.runs, run('a4', 'cancelled', { topic_id: 'ta', created_at: at(7) })]
  expect(latestOfUser(stopped)?.id).toBe('ta')
  // a trigger's turn never changes it, nor does a message the user sent into a trigger's topic
  const later = state()
  later.runs = [...later.runs, run('n2', 'completed', { ...nightly, created_at: at(8) }), run('n3', 'completed', { topic_id: 'tn', created_at: at(9) })]
  expect(latestOfUser(later)?.id).toBe('tb')
  // a turn on record with no topic, or with one that is not known yet, is no topic to go on with
  expect(latestOfUser(convState({ runs: [run('x', 'completed'), run('y', 'completed', { topic_id: 'gone' })] }))).toBeNull()
  expect(latestOfUser(convState())).toBeNull()
})

test('the next message goes on with the topic the user was last in, unless a turn of another topic of theirs is on screen', () => {
  expect(nextTopic(state(), null)).toEqual({ kind: 'topic', topic: expect.objectContaining({ id: 'tb' }), instead: null })
  // a turn of the same topic on screen changes nothing
  expect(nextTopic(state(), 'b1')).toMatchObject({ kind: 'topic', topic: { id: 'tb' }, instead: null })
  // a turn of an earlier topic of the user's: the message goes to that one
  expect(nextTopic(state(), 'a2')).toMatchObject({ kind: 'topic', topic: { id: 'ta' }, instead: null })
  // a turn that is no turn of this conversation counts for nothing
  expect(nextTopic(state(), 'gone')).toMatchObject({ kind: 'topic', topic: { id: 'tb' }, instead: null })
})

test('looking at a trigger’s turn does not send the next message into the trigger’s topic: only choosing that does', () => {
  // the message still goes on with the user's own topic, and the trigger's is offered instead
  expect(nextTopic(state(), 'n1')).toMatchObject({ kind: 'topic', topic: { id: 'tb' }, instead: { id: 'tn' } })
  // chosen: it goes into the trigger's topic, and the way back is the user's own
  expect(nextTopic(state(), 'n1', 'tn')).toMatchObject({ kind: 'topic', topic: { id: 'tn' }, instead: { id: 'tb' } })
  // the choice was for the trigger's topic on screen: with another turn there it counts for nothing
  expect(nextTopic(state(), 'a2', 'tn')).toMatchObject({ kind: 'topic', topic: { id: 'ta' }, instead: null })
  expect(nextTopic(state(), null, 'tn')).toMatchObject({ kind: 'topic', topic: { id: 'tb' }, instead: null })
  // a topic of the user's own is never gone into by that choice: it is where the message goes anyway
  expect(nextTopic(state(), 'n1', 'ta')).toMatchObject({ kind: 'topic', topic: { id: 'tb' }, instead: { id: 'tn' } })
  // a message the user wrote into the trigger's topic is a turn of that topic: looked at, it is a trigger's all the same
  const written = state()
  written.runs = [...written.runs, run('n2', 'completed', { topic_id: 'tn', created_at: at(9) })]
  expect(nextTopic(written, 'n2')).toMatchObject({ kind: 'topic', topic: { id: 'tb' }, instead: { id: 'tn' } })
})

test('with no topic of the user’s to go on with the next message starts one; in an empty conversation nothing is said', () => {
  const only = convState({ topics: [topic('tn', 'Look', { trigger_id: 'tr' })], runs: [run('n1', 'completed', nightly)], messages: [byTrigger('n1', 'Look')] })
  expect(nextTopic(only, null)).toEqual({ kind: 'new', instead: null })
  // the trigger's turn on screen: the message still starts the user's first topic, and the trigger's is offered
  expect(nextTopic(only, 'n1')).toMatchObject({ kind: 'new', instead: { id: 'tn' } })
  // chosen: into the trigger's topic, and the way back is a new topic (there is none of the user's)
  expect(nextTopic(only, 'n1', 'tn')).toMatchObject({ kind: 'topic', topic: { id: 'tn' }, instead: null })
  expect(nextTopic(convState(), null)).toBeNull()
})

// --- numbers and names --------------------------------------------------------------------------

test('"turn N" counts the turns of a topic that were started; one that waits in the queue has no number yet', () => {
  const numbers = turnNumbers(state())
  expect(Object.fromEntries(numbers)).toEqual({ a1: 1, a2: 2, a3: 3, n1: 1, b1: 1 })
  // a message taken out of the queue never was a turn: the ones after it keep counting
  const removed = state({})
  removed.runs = [run('a0', 'cancelled', { topic_id: 'ta', started_at: null }), ...removed.runs]
  expect(turnNumbers(removed).get('a1')).toBe(1)
  // a turn in no topic has no number
  expect(turnNumbers(convState({ runs: [run('x', 'completed')] })).size).toBe(0)
})

test('a topic is called by its title; a trigger’s by the trigger’s name, as its newest turn has it', () => {
  const s = state()
  expect(titleOf(s, s.topics[0])).toBe('Fix the greeting')
  expect(titleOf(s, s.topics[1])).toBe('Nightly look')
  s.runs = [...s.runs, run('n2', 'completed', { ...nightly, trigger_name: 'Morning look' })]
  expect(titleOf(s, s.topics[1])).toBe('Morning look')
  // with no turn that names it, it is a trigger and no more is claimed
  expect(titleOf(convState(), topic('tn', 'Look the project over', { trigger_id: 'tr' }))).toBe('A trigger')
})

// --- an agent that goes on from an earlier one --------------------------------------------------

test('the chain of an agent: the agents it goes on from, oldest first, each with its turn', () => {
  const s = state()
  expect(chainOf(s, 'coder3').map(link => [link.agent.id, link.turn])).toEqual([['coder1', 1], ['coder2', 2], ['coder3', 3]])
  expect(chainOf(s, 'coder1').map(link => [link.agent.id, link.turn])).toEqual([['coder1', 1]])
  expect(chainOf(s, 'gone')).toEqual([])
  // "continues from the 10:42 message" is the link before it, by its message's time; said of a sub-agent only - a
  // lead goes on by the topic itself
  expect(continuesFrom(s, 'coder3')).toBe(messageTime(s, 'a2'))
  expect(messageTime(s, 'a2')).toBe(when(s.messages.find(m => m.run_id === 'a2' && m.role === 'user')!.created_at))
  expect(continuesFrom(s, 'coder1')).toBeNull()
  expect(continuesFrom(s, 'a2')).toBeNull()
})

test('a chain stays inside its topic and never turns round', () => {
  const link = (over: object) => {
    const s = state()
    s.agents = s.agents.map(a => (a.id === 'coder3' ? { ...a, ...over } : a))
    return chainOf(s, 'coder3').map(l => l.agent.id)
  }
  // an agent of another topic, one that is not on record, one of another depth, and itself
  expect(link({ continues_id: 'n1' })).toEqual(['coder3'])
  expect(link({ continues_id: 'nobody' })).toEqual(['coder3'])
  expect(link({ continues_id: 'a2' })).toEqual(['coder3'])
  expect(link({ continues_id: 'coder3' })).toEqual(['coder3'])
  // a link that points forward in the topic ends the walk
  const s = state()
  s.agents = s.agents.map(a => (a.id === 'coder1' ? { ...a, continues_id: 'coder2' } : a))
  expect(chainOf(s, 'coder3').map(l => l.agent.id)).toEqual(['coder1', 'coder2', 'coder3'])
  expect(chainOf(s, 'coder2').map(l => l.agent.id)).toEqual(['coder1', 'coder2'])
})

test('an agent a later one went on from says in which turn; one that was only asked for, or declined, did not go on', () => {
  const s = state()
  expect(wentOnIn(s, 'coder1')).toMatchObject({ agent: { id: 'coder2' }, turn: 2 })
  expect(wentOnIn(s, 'coder3')).toBeNull()
  const declined = state()
  declined.agents = declined.agents.map(a => (a.id === 'coder3' ? { ...a, status: 'rejected' as const } : a))
  expect(wentOnIn(declined, 'coder2')).toBeNull()
  const asked = state()
  asked.agents = asked.agents.map(a => (a.id === 'coder3' ? { ...a, status: 'proposed' as const } : a))
  expect(wentOnIn(asked, 'coder2')).toBeNull()
  // a lead is not said to go on: the topic's turns are that
  expect(wentOnIn(s, 'a1')).toBeNull()
})
