import { expect, test } from 'vitest'
import { agent, command, convState, fileChange, question, run, toolCall, userMessage } from '../test-fixtures'
import type { Message } from '../api/types'
import { inScratch } from '../changes/copies'
import { deriveGraph } from './deriveGraph'
import { currentTurn, frontTurn, oneTurn, startsNewTurn, turnOf, turnRows, type TurnRow, workOf, workText } from './turns'

const byTrigger = (runId: string, content: string): Message => ({ ...userMessage(runId, content), id: `t-${runId}`, role: 'trigger' })
const nightly = { unattended: true, trigger_id: 'tr', trigger_name: 'Nightly look' }

/** Two turns of the user's that are over, one a trigger started, and one of the user's at work. */
const state = () =>
  convState({
    runs: [
      run('a', 'completed'),
      run('b', 'failed'),
      run('n', 'completed', { ...nightly, created_at: '2026-10-05T03:00:00Z' }),
      run('c'),
    ],
    messages: [
      userMessage('a', '\nFix the greeting\nand then the tests'),
      userMessage('b', 'x'.repeat(200)),
      { ...byTrigger('n', 'Look the project over'), created_at: '2026-10-05T03:00:00Z' },
      userMessage('c', 'go on'),
    ],
    agents: [
      agent('a', 'completed'),
      agent('a', 'completed', { id: 'kid', parent_agent_id: 'a', role_name: 'Reviewer', depth: 1 }),
      agent('b', 'failed'),
      agent('n', 'completed'),
      agent('c'),
    ],
    toolCalls: [toolCall('4', 'a', 'read_file', 'succeeded', '{}', { agent_id: 'kid' })],
    fileChanges: [fileChange('f2', 'a', { agent_id: 'kid' })],
  })

test('every turn is a row: what was asked, its work, how it ended - and whether nobody was watching', () => {
  const rows = turnRows(state())
  expect(rows.map(r => r.runId)).toEqual(['a', 'b', 'n', 'c'])
  // Its work (slice 107): the sub-agents it opened - not its Lead - and the files it changed.
  expect(rows[0]).toMatchObject({ unattended: false, text: 'Fix the greeting', agents: 1, files: 1, ended: 'done', waits: false })
  expect(workText(rows[0])).toBe('1 agent · 1 file')
  expect(rows[1]).toMatchObject({ text: 'x'.repeat(60) + '…', agents: 0, files: 0, ended: 'failed' })
  expect(workText(rows[1])).toBe('')
  expect(rows[2]).toMatchObject({ unattended: true, triggerName: 'Nightly look', ended: 'done', at: '2026-10-05T03:00:00Z' })
  expect(rows[3]).toMatchObject({ unattended: false, text: 'go on', ended: 'working' })
})

test('a row says how its turn stands by the turn’s own record, and no more', () => {
  const ended = (status: Parameters<typeof run>[1], over = {}) =>
    turnRows(convState({ runs: [run('a', status, over)], messages: [userMessage('a', 'x')] }))[0].ended
  expect((['queued', 'running', 'waiting_approval', 'completed', 'failed', 'cancelled', 'interrupted'] as const).map(s => ended(s, { started_at: 't' }))).toEqual([
    'queued', 'working', 'working', 'done', 'failed', 'stopped', 'interrupted',
  ])
  // a turn stopped for its trigger's budget says so
  expect(ended('failed', { ...nightly, error: 'budget: 15 model steps used' })).toBe('over budget')
  // a message taken out of the queue never became a turn
  expect(turnRows(convState({ runs: [run('a', 'cancelled', { started_at: null })], messages: [userMessage('a', 'x')] }))).toEqual([])
})

test('a turn in which something waits for the user is marked', () => {
  const waits = (over: Parameters<typeof convState>[0]) =>
    turnRows(convState({ runs: [run('a'), run('b', 'queued')], messages: [userMessage('a', 'x'), userMessage('b', 'y')], agents: [agent('a')], ...over }))[0].waits
  expect(waits({})).toBe(false)
  expect(waits({ commands: [command('k1', 'a', { status: 'proposed' })] })).toBe(true)
  expect(waits({ fileChanges: [fileChange('f1', 'a', { status: 'proposed' })] })).toBe(true)
  expect(waits({ questions: [question('q1', 'a')] })).toBe(true)
  expect(waits({ agents: [agent('a'), agent('a', 'proposed', { id: 'kid', parent_agent_id: 'a', depth: 1 })] })).toBe(true)
  expect(waits({ pendingRoles: [{ tool_call_id: '1', run_id: 'a', agent_id: 'a', name: 'Documenter', description: '', instructions: '', tools: [] }] })).toBe(true)
  expect(waits({ runs: [run('a', 'waiting_approval'), run('b', 'queued')] })).toBe(true)
  // what waits in another turn is that turn's
  expect(waits({ commands: [command('k1', 'b', { status: 'proposed' })] })).toBe(false)
})

test('a turn with a working copy that was kept and is not decided yet says so - it is over, and does not wait', () => {
  const kept = { id: 'g', run_id: 'a', agent_id: 'a', status: 'interrupted' as const, files: [], kept_in: 'C:\\runtime\\copies\\a\\tree', created_at: '', decided_at: null }
  const rows = (merge: object) => turnRows(convState({ runs: [run('a', 'interrupted'), run('b')], messages: [userMessage('a', 'x'), userMessage('b', 'y')], merges: [{ ...kept, ...merge }] }))
  expect(rows({}).map(r => [r.kept, r.waits])).toEqual([[true, false], [false, false]])
  // decided, or one whose folder is gone: nothing is kept any more
  expect(rows({ status: 'applied', kept_in: null })[0].kept).toBe(false)
  expect(rows({ status: 'interrupted', kept_in: null })[0].kept).toBe(false)
  // a card of a turn at work is that turn waiting for you
  expect(rows({ status: 'pending', kept_in: null })[0].kept).toBe(false)
})

test('the turn drawn is the newest one the user started, until they pick another', () => {
  const rows = turnRows(state())
  expect(currentTurn(rows, null)).toBe('c')
  expect(currentTurn(rows, 'a')).toBe('a')
  expect(currentTurn(rows, 'n')).toBe('n')
  // a pick that is no turn of this conversation counts for nothing
  expect(currentTurn(rows, 'gone')).toBe('c')
  expect(currentTurn([], null)).toBeNull()
})

test('a turn nobody is watching never becomes the one drawn by itself; alone, it is all there is to draw', () => {
  const later = convState({
    runs: [run('a', 'completed'), run('n', 'running', nightly)],
    messages: [userMessage('a', 'x'), byTrigger('n', 'Look')],
    agents: [agent('a', 'completed'), agent('n')],
  })
  expect(currentTurn(turnRows(later), null)).toBe('a')
  const only = convState({ runs: [run('m', 'completed', nightly), run('n', 'running', nightly)], messages: [byTrigger('n', 'Look')] })
  expect(currentTurn(turnRows(only), null)).toBe('n')
})

test('a message still in the queue is not drawn in place of the turn at work', () => {
  const queued = convState({ runs: [run('a'), run('b', 'queued')], messages: [userMessage('a', 'x'), userMessage('b', 'y')], agents: [agent('a')] })
  expect(currentTurn(turnRows(queued), null)).toBe('a')
  // with nothing else started, it is the newest there is
  const first = convState({ runs: [run('b', 'queued')], messages: [userMessage('b', 'y')] })
  expect(currentTurn(turnRows(first), null)).toBe('b')
})

test('a turn of the user’s that starts takes the canvas back; one a trigger starts does not', () => {
  expect(startsNewTurn(undefined, run('d'))).toBe(true)
  expect(startsNewTurn(run('d', 'queued'), run('d'))).toBe(true)
  // still in the queue, or already known to be at work: nothing new started
  expect(startsNewTurn(undefined, run('d', 'queued'))).toBe(false)
  expect(startsNewTurn(run('d'), run('d'))).toBe(false)
  expect(startsNewTurn(run('d'), run('d', 'completed'))).toBe(false)
  expect(startsNewTurn(undefined, run('d', 'running', nightly))).toBe(false)
})

test('one turn’s graph has that turn’s nodes and lines and no other’s', () => {
  const whole = deriveGraph(state())
  const own = oneTurn(whole, 'a')
  expect(own.nodes.map(n => n.id)).toEqual(['request:a', 'agent:a', 'agent:kid'])
  expect(own.nodes.every(n => n.runId === 'a')).toBe(true)
  expect(own.edges.map(e => e.id)).toEqual(['request:a>agent:a', 'agent:a>agent:kid'])
  // the nodes are the ones the whole graph has
  expect(own.nodes[0]).toBe(whole.nodes[0])
  // a turn a trigger started begins at the trigger's message
  expect(oneTurn(whole, 'n').nodes.map(n => n.id)).toEqual(['request:n', 'agent:n'])
  expect(oneTurn(whole, null)).toEqual({ nodes: [], edges: [] })
})

test('a comparison’s two sides are one turn: one row, one “You”, the two Leads under it', () => {
  const sides = convState({
    runs: [run('x', 'completed'), run('s1', 'completed', { compare_id: 'cmp' }), run('s2', 'running', { compare_id: 'cmp' })],
    messages: [userMessage('x', 'before'), userMessage('s1', 'compare it'), { ...userMessage('s2', 'compare it'), id: 'm-s2' }],
    agents: [agent('x', 'completed'), agent('s1', 'completed'), agent('s2')],
  })
  const rows = turnRows(sides)
  expect(rows.map(r => r.runId)).toEqual(['x', 's1'])
  // (at work while either side is)
  expect(rows[1]).toMatchObject({ text: 'compare it', ended: 'working' })
  // Its work is both sides'.
  const opened = convState({ ...sides, agents: [...sides.agents, agent('s2', 'completed', { id: 'k2', depth: 1 })], fileChanges: [fileChange('f', 's1'), fileChange('g', 's2', { path: 'b.py' })] })
  expect(turnRows(opened)[1]).toMatchObject({ agents: 1, files: 2 })
  const own = oneTurn(deriveGraph(sides), currentTurn(rows, 's2'))
  expect(own.nodes.map(n => n.id)).toEqual(['request:s1', 'agent:s1', 'agent:s2'])
  expect(own.edges.map(e => e.id)).toEqual(['request:s1>agent:s1', 'request:s1>agent:s2'])
  // The later side picked, with a turn after it: the comparison's turn, not the newest.
  const later = convState({ ...sides, runs: [...sides.runs, run('y', 'completed')], messages: [...sides.messages, userMessage('y', 'after')] })
  expect(currentTurn(turnRows(later), turnOf(later, 's2'))).toBe('s1')
})

// --- what the canvas has in front (slice 107) ---------------------------------------------------

const row = (runId: string, over: Partial<TurnRow> = {}): TurnRow => ({
  runId,
  unattended: false,
  text: runId,
  triggerName: null,
  agents: 0,
  files: 0,
  ended: 'done',
  waits: false,
  kept: false,
  at: '2026-10-05T10:00:00Z',
  ...over,
})

test('slice 107: in front, while nothing is picked - what waits for you, else what is at work, else the last work', () => {
  // none: the newest is drawn (currentTurn's own rule)
  expect(frontTurn([])).toBeNull()
  expect(frontTurn([row('a'), row('b')])).toBeNull()
  // a trigger's turns never take it, whatever they did
  expect(frontTurn([row('n', { unattended: true, agents: 2, ended: 'working', waits: true })])).toBeNull()
  // the last message with work, past the plain answers after it
  expect(frontTurn([row('w', { files: 1 }), row('x', { agents: 1 }), row('p')])).toBe('x')
  // a message at work - not one still queued behind it
  expect(frontTurn([row('w', { agents: 1 }), row('r', { ended: 'working' }), row('q', { ended: 'queued' })])).toBe('r')
  // what waits for you comes first: a plan to approve, say, though a later message is at work
  expect(frontTurn([row('p', { waits: true }), row('r', { ended: 'working' })])).toBe('p')
})

test('slice 107: a plan to approve waits for you; one decided does not', () => {
  const plan = (status: 'proposed' | 'approved') => ({ text: '1. read', status, model_id: 'm', strongest: false })
  const rows = (status: 'proposed' | 'approved') =>
    turnRows(convState({ runs: [run('p', 'completed', { plan_turn: true, plan: plan(status) })], messages: [userMessage('p', 'plan it')] }))
  expect(rows('proposed')[0].waits).toBe(true)
  expect(rows('approved')[0].waits).toBe(false)
  // (its time is its message's, as the chat says it)
  expect(turnRows(convState({ runs: [run('a', 'completed')], messages: [{ ...userMessage('a', 'x'), created_at: '2026-10-05T11:11:00Z' }] }))[0].at).toBe('2026-10-05T11:11:00Z')
})

test('a write into the scratch, .koloni/tmp/, is in no count or list of what changed (K-koloni-klasor)', () => {
  const changes = [fileChange('s', 'a', { path: '.koloni/tmp/a.txt' }), fileChange('b', 'a', { path: 'src/b.py' })]
  expect(workOf(convState({ runs: [run('a', 'completed')], fileChanges: changes }), ['a']).files).toBe(1)
  expect([inScratch('./.KOLONI/tmp/x'), inScratch('.koloni\\tmp\\x'), inScratch('.koloni/tmpx'), inScratch('.koloni/rules.md')]).toEqual([true, true, false, false])
})
