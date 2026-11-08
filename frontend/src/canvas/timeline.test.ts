import { expect, test } from 'vitest'
import type { Discussion, Merge, Room, WebRequest } from '../api/types'
import { agent, assistantMessage, command, convState, fileChange, question, run, toolCall } from '../test-fixtures'
import { place, timeline, took } from './timeline'

const T = (s: number) => `2026-10-05T10:${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}Z`
const ms = (s: number) => Date.parse(T(s))

/** A turn that is over: the lead (0-100s), a Reviewer it opened at 10s (20-60s), and the lead's CLI's own sub-agent (30-50s). */
const over = () =>
  convState({
    runs: [run('r', 'completed', { started_at: T(0), ended_at: T(100) })],
    messages: [{ ...assistantMessage('m', 'r', ''), created_at: T(70) }],
    agents: [
      agent('r', 'completed', { id: 'lead', name: 'Lead', started_at: T(0), ended_at: T(100), input_tokens: 100, output_tokens: 10 }),
      agent('r', 'completed', {
        id: 'rev', name: 'Reviewer', role_name: 'Reviewer', parent_agent_id: 'lead', depth: 1,
        created_at: T(10), started_at: T(20), ended_at: T(60), input_tokens: 50, output_tokens: 5,
      }),
    ],
    toolCalls: [
      toolCall('1', 'r', 'read_file', 'succeeded', '{}', { agent_id: 'lead', started_at: T(2), ended_at: T(4) }),
      toolCall('2', 'r', 'claude__Agent', 'succeeded', '{"description":"Look around"}', { agent_id: 'lead', origin: 'cli', started_at: T(30), ended_at: T(50) }),
      toolCall('3', 'r', 'claude__Read', 'succeeded', '{}', { agent_id: 'lead', origin: 'cli', parent_call_id: '2', started_at: T(31), ended_at: T(32) }),
      toolCall('4', 'r', 'read_file', 'failed', '{}', { agent_id: 'rev', started_at: T(25), ended_at: T(26) }),
    ],
  })

test('each agent is a lane, a sub-agent under the one that opened it; a CLI’s own sub-agent is a lane of its own, its calls in it', () => {
  const line = timeline(over(), 'r', ms(500))!
  expect(line.lanes.map(l => [l.name, l.depth, l.cli, l.parent])).toEqual([
    ['Orchestrator', 0, false, null],
    ['Look around', 1, true, 'lead'],
    ['Reviewer', 1, false, 'lead'],
  ])
  const [lead, own, rev] = line.lanes
  expect([lead.from, lead.to]).toEqual([ms(0), ms(100)])
  // The lead's own calls only: the sub-agent call is a lane, and what was called in it is there.
  expect(lead.calls.map(c => c.name)).toEqual(['read_file'])
  expect(own.calls.map(c => [c.name, c.from, c.to])).toEqual([['claude__Read', ms(31), ms(32)]])
  expect([own.from, own.to, own.agentId, own.status[0]]).toEqual([ms(30), ms(50), 'lead', 'done'])
  expect(rev.calls[0].status).toBe('failed')
  // The line from the lead is drawn when it opened the Reviewer; what it waited before it started is said, for nobody named.
  expect(rev.opened).toBe(ms(10))
  expect(rev.waits).toEqual([{ from: ms(10), to: ms(20), who: null, what: 'to start', open: false }])
})

test('the turn’s length, its agents and their tokens; a token count not reported leaves the sum unknown', () => {
  const line = timeline(over(), 'r', ms(500))!
  expect([line.from, line.to, line.length, line.agents]).toEqual([ms(0), ms(100), 100_000, 2])
  expect(line.tokens).toEqual({ input_tokens: 150, output_tokens: 15 })
  const state = over()
  state.agents[1] = { ...state.agents[1], input_tokens: null }
  expect(timeline(state, 'r', ms(500))!.tokens.input_tokens).toBeNull()
  expect(timeline(state, 'nope', ms(500))).toBeNull()
})

test('what is at work runs up to now; an agent that ended with no end on record is not drawn to now', () => {
  const state = convState({
    runs: [run('r', 'running', { started_at: T(0) })],
    agents: [
      agent('r', 'running', { id: 'lead', started_at: T(0) }),
      agent('r', 'interrupted', { id: 'old', name: 'Old', parent_agent_id: 'lead', started_at: T(5), ended_at: null }),
      agent('r', 'queued', { id: 'q', name: 'Q', parent_agent_id: 'lead', created_at: T(5), started_at: null }),
    ],
  })
  const line = timeline(state, 'r', ms(40))!
  expect([line.to, line.length]).toEqual([ms(40), 40_000])
  const [lead, old, queued] = line.lanes
  expect([lead.to, lead.atWork]).toEqual([ms(40), true])
  expect([old.from, old.to, old.atWork]).toEqual([ms(5), null, false])
  // Never started: no bar.
  expect([queued.from, queued.to]).toEqual([null, null])
})

test('waits: each from its own record’s time to its decision; one still undecided runs to now; whose word it waits for', () => {
  const merge = { id: 'mg', run_id: 'r', agent_id: 'b', status: 'applied', created_at: T(40), decided_at: T(45) } as Merge
  const web = { id: 'w', run_id: 'r', agent_id: 'lead', tool_call_id: '1', status: 'approved', created_at: T(50), decided_at: T(51) } as WebRequest
  const state = convState({
    runs: [run('r', 'waiting_approval', { started_at: T(0) })],
    messages: [{ ...assistantMessage('m', 'r', ''), created_at: T(60) }],
    agents: [
      agent('r', 'running', { id: 'lead', started_at: T(0) }),
      agent('r', 'blocked', { id: 'b', name: 'Bee', parent_agent_id: 'lead', created_at: T(1), started_at: T(1), waiting_for: { agent_id: 'x', agent_name: 'Ann', path: 'a.py' } }),
      agent('r', 'proposed', { id: 'p', name: 'Pea', parent_agent_id: 'lead', created_at: T(70), started_at: null }),
    ],
    toolCalls: [
      toolCall('1', 'r', 'read_file', 'succeeded', '{}', { agent_id: 'lead', started_at: T(1), ended_at: T(2) }),
      toolCall('9', 'r', 'read_file', 'pending', '{}', { agent_id: 'lead', message_id: 'm', outside_folder: 'C:/elsewhere' }),
      // (a command's reason, on its call: its wait is the command's)
      toolCall('k', 'r', 'run_skill_script', 'running', '{}', { agent_id: 'lead', message_id: 'm', why_asked: 'it names the project folder' }),
    ],
    questions: [question('q', 'r', { agent_id: 'lead', created_at: T(10), answered_at: T(20), status: 'answered' })],
    fileChanges: [
      fileChange('f1', 'r', { agent_id: 'lead', created_at: T(20), decided_at: T(30), status: 'applied' }),
      fileChange('f2', 'r', { agent_id: 'lead', created_at: T(80), decided_at: null, status: 'proposed', path: 'b.py' }),
      // Made in a working copy: not asked about by itself - the merge is.
      fileChange('f3', 'r', { agent_id: 'b', created_at: T(40), decided_at: T(45), status: 'applied' }),
    ],
    commands: [command('c', 'r', { agent_id: 'lead', tool_call_id: 'k', created_at: T(30), started_at: T(33) })],
    merges: [merge],
    webRequests: [web],
  })
  const [lead, bee, pea] = timeline(state, 'r', ms(90))!.lanes
  expect(lead.waits.map(w => [w.what, w.who, (w.from! - ms(0)) / 1000, (w.to! - ms(0)) / 1000])).toEqual([
    ['question', 'you', 10, 20],
    ['src/a.py', 'you', 20, 30],
    ['pytest -q', 'you', 30, 33],
    ['web request', 'you', 50, 51],
    // An approval with no record of its own: from its message.
    ['C:/elsewhere', 'you', 60, 90],
    ['b.py', 'you', 80, 90],
  ])
  // A file another agent holds: whose, and since when is not on record.
  expect(bee.waits).toEqual([
    { from: ms(40), to: ms(45), who: 'you', what: 'changes to take in', open: false },
    { from: null, to: null, who: 'Ann', what: 'a.py', open: true },
  ])
  expect(pea.waits).toEqual([{ from: ms(70), to: ms(90), who: 'you', what: 'to start', open: true, key: 'p' }])
})

test('a wait that never happened is not drawn: a change the CLI made, one approved at once, an answer within a second; one asked and left without an end is said with no length', () => {
  const merge = { id: 'mg', run_id: 'r', agent_id: 'lead', status: 'pending', created_at: T(50), decided_at: null } as Merge
  const state = convState({
    runs: [run('r', 'completed', { started_at: T(0), ended_at: T(40) })],
    agents: [agent('r', 'completed', { id: 'lead', started_at: T(0), ended_at: T(40) })],
    toolCalls: [
      // Left running on a turn that is over: not drawn growing.
      toolCall('1', 'r', 'read_file', 'running', '{}', { agent_id: 'lead', started_at: T(1) }),
      toolCall('2', 'r', 'claude__Agent', 'running', '{}', { agent_id: 'lead', origin: 'cli', started_at: T(2) }),
    ],
    fileChanges: [
      fileChange('f1', 'r', { agent_id: 'lead', origin: 'cli', created_at: T(5), decided_at: T(9), status: 'applied' }),
      fileChange('f2', 'r', { agent_id: 'lead', created_at: T(6), decided_at: T(6), status: 'applied' }),
    ],
    questions: [
      question('q1', 'r', { agent_id: 'lead', created_at: T(10), answered_at: T(10), status: 'answered' }),
      question('q2', 'r', { agent_id: 'lead', created_at: T(20), answered_at: null, status: 'cancelled' }),
    ],
  })
  const line = timeline(state, 'r', ms(90))!
  const [lead, own] = line.lanes
  expect(lead.waits).toEqual([{ from: ms(20), to: null, who: 'you', what: 'question', open: false }])
  // (The line to a sub-agent that started at once meets its bar, not a wait too short to be drawn.)
  const quick = timeline({ ...state, agents: [...state.agents, agent('r', 'completed', { id: 'k', parent_agent_id: 'lead', created_at: T(3), started_at: '2026-10-05T10:00:03.500Z', ended_at: T(9) })] }, 'r', ms(90))!
  expect(quick.lanes.at(-1)!.opened).toBe(quick.lanes.at(-1)!.from)
  expect(lead.calls).toEqual([])
  expect([own.from, own.to, own.atWork]).toEqual([ms(2), null, false])
  expect(line.atWork).toBe(false)
  // Its changes kept for you to apply outlive the turn: that wait runs on, and the line with it.
  const kept = timeline({ ...state, merges: [merge] }, 'r', ms(90))!
  expect([kept.atWork, kept.lanes[0].waits.at(-1)?.to]).toEqual([true, ms(90)])
})

test('marks: a failure, a stop, a limit reached, and a discussion or a room opened and ended', () => {
  const talk = { id: 'd', run_id: 'r', agent_id: 'lead', created_at: T(10), ended_at: T(20) } as Discussion
  const room = { id: 'o', run_id: 'r', agent_id: null, created_at: T(5), ended_at: null } as Room
  const state = convState({
    runs: [run('r', 'failed', { started_at: T(0), ended_at: T(60), error: 'budget: 15 model steps used' })],
    agents: [
      agent('r', 'failed', { id: 'lead', started_at: T(0), ended_at: T(60) }),
      agent('r', 'cancelled', { id: 'a', name: 'A', parent_agent_id: 'lead', started_at: T(1), ended_at: T(30) }),
      agent('r', 'failed', { id: 'b', name: 'B', parent_agent_id: 'lead', started_at: T(1), ended_at: T(40), failure: 'rate_limited' }),
    ],
    discussions: [talk],
    rooms: [room],
  })
  const line = timeline(state, 'r', ms(90))!
  const said = (marks: { at: number; what: string }[]) => marks.map(m => [m.what, (m.at - ms(0)) / 1000])
  expect(said(line.lanes[0].marks)).toEqual([['discussion started', 10], ['discussion ended', 20], ['failed', 60]])
  expect(said(line.lanes[1].marks)).toEqual([['stopped', 30]])
  expect(said(line.lanes[2].marks)).toEqual([['limit reached', 40]])
  expect(said(line.marks)).toEqual([['room opened', 5], ['limit reached', 60]])
})

test('a place on the line is a share of the turn; a turn of no length puts everything at its start', () => {
  expect(place(ms(25), { from: ms(0), to: ms(100) })).toBe(25)
  expect(place(ms(5), { from: ms(5), to: ms(5) })).toBe(0)
})

test('a length reads in seconds, minutes or hours; one not known is a dash', () => {
  expect(took(-5)).toBe('–')
  expect([took(null), took(0), took(400), took(12_400), took(185_000), took(3_720_000)]).toEqual(['–', '0s', '<1s', '12s', '3m 05s', '1h 02m'])
})

test('B-316: at Full auto a command that ran on no card waited for its start, not for you; one asked, or asked now, waits for you', () => {
  const state = convState({
    conversation: { ...convState().conversation, permission_mode: 'full_auto' },
    runs: [run('r', 'running', { started_at: T(0) })],
    agents: [agent('r', 'running', { id: 'dbg', name: 'Debugger', started_at: T(0) })],
    toolCalls: [toolCall('k', 'r', 'run_command', 'running', '{}', { agent_id: 'dbg', why_asked: 'it names the project folder' })],
    commands: [
      // Its working copy made by its first command: 38s before it started.
      command('c1', 'r', { agent_id: 'dbg', tool_call_id: 'x', command: 'git status --short', created_at: T(0), started_at: T(38) }),
      command('c2', 'r', { agent_id: 'dbg', tool_call_id: 'x', command: 'Set-Content AGENTS.md x', danger: 'Names agents.md', created_at: T(40), started_at: T(45) }),
      command('c3', 'r', { agent_id: 'dbg', tool_call_id: 'k', command: 'cat C:/p/x', created_at: T(46), started_at: T(50) }),
      command('c4', 'r', { agent_id: 'dbg', tool_call_id: 'x', command: 'rg KEY', status: 'proposed', created_at: T(60), started_at: null }),
    ],
  })
  const [dbg] = timeline(state, 'r', ms(90))!.lanes
  expect(dbg.waits.map(w => [w.what, w.who, w.open, w.key])).toEqual([
    ['git status --short', null, false, undefined],
    ['Set-Content AGENTS.md x', 'you', false, undefined],
    ['cat C:/p/x', 'you', false, undefined],
    ['rg KEY', 'you', true, 'c4'],
  ])
  expect(dbg.status[0]).toBe('waits for you')
  // Below Full auto a command is asked unless a rule or a read lets it through: taken as asked.
  const asks = timeline({ ...state, conversation: { ...state.conversation, permission_mode: 'ask' } }, 'r', ms(90))!
  expect(asks.lanes[0].waits[0].who).toBe('you')
})

test('B-316: an agent waiting on the agents it opened says whom it waits for; one with a card open waits for you', () => {
  const state = convState({
    runs: [run('r', 'running', { started_at: T(0) })],
    agents: [
      agent('r', 'waiting', { id: 'lead', name: 'Lead', started_at: T(0) }),
      agent('r', 'running', { id: 'co', name: 'Coder', parent_agent_id: 'lead', depth: 1, created_at: T(1), started_at: T(1) }),
      agent('r', 'running', { id: 'te', name: 'Tester', parent_agent_id: 'lead', depth: 1, created_at: T(1), started_at: T(1) }),
      agent('r', 'completed', { id: 'rv', name: 'Reviewer', parent_agent_id: 'lead', depth: 1, created_at: T(1), started_at: T(1), ended_at: T(5) }),
    ],
  })
  const [lead, coder] = timeline(state, 'r', ms(90))!.lanes
  expect(lead.status).toEqual(['waits for Coder, Tester', 'var(--accent)'])
  expect(coder.status[0]).toBe('working')
  // Nothing of it is the user's to answer: no wait for you, no "waits for you".
  expect(lead.waits.filter(w => w.who === 'you')).toEqual([])
  const asked = timeline({ ...state, questions: [question('q', 'r', { agent_id: 'co', created_at: T(10), answered_at: null, status: 'pending' })] }, 'r', ms(90))!
  expect(asked.lanes.map(l => l.status[0])).toEqual(['waits for Coder, Tester', 'waits for you', 'working', 'done'])
  expect(asked.lanes[1].waits).toEqual([{ from: ms(10), to: ms(90), who: 'you', what: 'question', open: true, key: 'q' }])
})
