import { expect, test } from 'vitest'
import type { Agent, ChannelMessage, ChatTeam, ChatTeamState, Message } from '../api/types'
import { agent, assistantMessage, conversation, convState, run, toolCall } from '../test-fixtures'
import type { Loop } from './checksLoop'
import type { ChecksData } from './checksNode'
import { deriveGraph, type TeamData } from './deriveGraph'
import { foldGraph } from './foldGraph'
import { COL_GAP, layoutGraph, NODE_H, NODE_W } from './layout'

// tuval-kontrol-dongusu, the recipe case (the approved mockup checks-recipe-v1, the user's three live screens): in a recipe's
// turn the frame keeps the recipe's own steps, left to right; KOLONİ's looks, and the Coders of its send-back rounds, are the
// Checks · KOLONİ box - the frame's last part, inside it, right of the steps. No line from the Orchestrator into the frame but
// its door; no label floating between.

type Row = NonNullable<Message['checked']>[number]
const row = (state: Row['state'], text: string, more: Partial<Row> = {}): Row => ({ kind: 'tests', state, text, command: null, guessed: false, started_at: null, counts: null, ...more })
type Pass = NonNullable<Message['passes']>[number]
const checked = (rows: Row[], passes: Pass[]): Message => ({ ...assistantMessage('k', 'r', ''), role: 'checked', agent_id: null, checked: rows, passes })
/** A pass of KOLONİ's checks as the backend writes it (`app.proof.new_pass`). */
const pass = (n: number, more: Partial<Pass> = {}): Pass => ({ n, kind: 'check', tests: 'passed', looks: [], why: null, sent: null, fixers: [], diagnosis: null, tier: null, ...more })
const looked = (agent_id: string, role: string, verdict: string | null) => ({ agent_id, role, verdict })
const step = (id: string, name: string, state: 'done' | 'now' | 'next') => ({ id, name, state, round: 0, room: false, own_check: false, left_out: [], group: false })
const STEPS = [step('reproduce', 'Reproduce it', 'done'), step('fix', 'Fix it', 'done'), step('end', 'You', 'next')]
const team = (agents: string[], passes: ChatTeamState['passes'], steps = STEPS): ChatTeam => ({
  team_id: 'api',
  recipe_id: null,
  no_recipe: false,
  picked_by: 'user',
  why: null,
  state: { run_id: 'r', team: 'Backend / API', recipe: 'Bugfix', status: 'ready', why: null, steps, agents, ended_ready: false, passes },
})
type Finding = NonNullable<Agent['findings']>[number]
const blocking: Finding = { what: 'shellrun.py:12 runs with shell=True', kind: 'security', role: 'Orchestrator', blocking: true }

/** An agent of the turn and the call that opened it, `seq` in the turn's order - KOLONİ's own (`koloni_proof_…`) or the Lead's. */
function opened(id: string, role: string, name: string, seq: number, kolonis: boolean, over: Partial<Agent> = {}) {
  const call = toolCall(`s${id}`, 'r', 'spawn_agent', 'succeeded', '{}', { seq, provider_call_id: kolonis ? `koloni_proof_review_${id}` : `call_${id}` })
  return { agent: { ...agent('r', 'completed', { id, role_name: role, name, parent_agent_id: 'r', depth: 1, tool_call_id: call.id }), ...over }, call }
}
const testRun = (id: string, seq: number) => toolCall(id, 'r', 'run_command', 'succeeded', '{"command":"python -m pytest -q"}', { seq, provider_call_id: `koloni_proof_${id}` })

function turn(parts: ReturnType<typeof opened>[], runs: number[], frame: ChatTeam | ChatTeam[], rows: Row[], checks: Pass[], said: ChannelMessage[] = []) {
  const frames = Array.isArray(frame) ? frame : [frame]
  return convState({
    conversation: { ...conversation, teams_mode: 'manual', teams: frames },
    runs: [{ ...run('r', 'completed'), teams: frames }],
    agents: [agent('r', 'completed'), ...parts.map(one => one.agent)],
    toolCalls: [...parts.map(one => one.call), ...runs.map((seq, n) => testRun(`p${n}`, seq))],
    channelMessages: said,
    messages: [checked(rows, checks)],
  })
}

const merge = { report: 'Verdict: MERGE\n\n## Findings\nnone', findings: [] }
const hold = { report: 'Verdict: HOLD', findings: [blocking] }

/** Case 1 (the first live screen): thin Bugfix, a security-touching fix - three looks, two send-back rounds, on hold. */
function looksAndFixes() {
  const parts = [
    opened('d1', 'Debugger', 'Debugger', 1, false),
    opened('c1', 'Coder', 'Coder', 2, false),
    opened('rv1', 'Reviewer', 'Reviewer', 4, true, merge),
    opened('sr1', 'Security reviewer', 'Security reviewer', 5, true, hold),
    opened('f1', 'Coder', 'Coder 2', 6, false),
    opened('rv2', 'Reviewer', 'Reviewer 2', 8, true, merge),
    opened('sr2', 'Security reviewer', 'Security reviewer 2', 9, true, hold),
    opened('f2', 'Coder', 'Coder 3', 10, false),
    opened('rv3', 'Reviewer', 'Reviewer 3', 12, true, merge),
    opened('sr3', 'Security reviewer', 'Security reviewer 3', 13, true, hold),
  ]
  // (KOLONİ's send-back reran Fix it: its two Coders are passes of the recipe's step too, as the recipe run keeps them.)
  const passes = [
    { part: 'reproduce', agents: ['d1'] },
    { part: 'fix', agents: ['c1'] },
    { part: 'fix', agents: ['f1'] },
    { part: 'fix', agents: ['f2'] },
  ]
  const rows = [
    row('passed', 'Tests passed: python -m pytest -q - 46 passed', { command: 'python -m pytest -q', counts: { passed: 46, failed: 0, skipped: 0, unit: 'tests' } }),
    row('note', 'Sent back to fix: 2 of 2 rounds (1 blocking finding; 1 blocking finding)', { kind: 'rounds' }),
    row('failed', 'Review: Security reviewer (x) - HOLD, 1 findings, 1 blocking', { kind: 'review' }),
    row('failed', 'Still on hold after 2 fix rounds: you decide (Fix it)', { kind: 'review' }),
  ]
  const checks = [
    pass(1, { looks: [looked('rv1', 'Reviewer', 'MERGE'), looked('sr1', 'Security reviewer', 'HOLD')], why: '1 blocking finding', sent: 'fix', fixers: ['f1'] }),
    pass(2, { looks: [looked('rv2', 'Reviewer', 'MERGE'), looked('sr2', 'Security reviewer', 'HOLD')], why: '1 blocking finding', sent: 'fix', fixers: ['f2'] }),
    pass(3, { looks: [looked('rv3', 'Reviewer', 'MERGE'), looked('sr3', 'Security reviewer', 'HOLD')] }),
  ]
  return turn(parts, [3, 7, 11], team(['d1', 'c1', 'f1', 'f2'], passes), rows, checks)
}

/** Case 2 (the second): the recipe's own loop - Fix it ⇄ Test it, three rounds - and KOLONİ once, no look: its plain box. */
function ownLoop() {
  const steps = [step('reproduce', 'Reproduce it', 'done'), step('fix', 'Fix it', 'done'), step('test', 'Test it', 'done'), step('end', 'You', 'next')]
  const parts = [
    opened('d1', 'Debugger', 'Debugger', 1, false),
    opened('c1', 'Coder', 'Coder', 2, false),
    opened('t1', 'Tester', 'Tester', 3, false),
    opened('c2', 'Coder', 'Coder 2', 4, false),
    opened('t2', 'Tester', 'Tester 2', 5, false),
  ]
  const passes = [
    { part: 'reproduce', agents: ['d1'] },
    { part: 'fix', agents: ['c1'] },
    { part: 'test', agents: ['t1'] },
    { part: 'fix', agents: ['c2'] },
    { part: 'test', agents: ['t2'] },
  ]
  const said: ChannelMessage[] = [{ id: 'm1', run_id: 'r', from_agent_id: 't1', to_agent_id: 'c2', kind: 'findings', content: '- test_x fails', created_at: '2026-10-05T10:00:00Z' }]
  const rows = [
    row('failed', 'Tests failed: python -m pytest -q - 1 failed, 77 passed', { command: 'python -m pytest -q', counts: { passed: 77, failed: 1, skipped: 0, unit: 'tests' } }),
    row('note', 'No review: the tests still fail', { kind: 'review' }),
  ]
  return turn(parts, [6], team(['d1', 'c1', 't1', 'c2', 't2'], passes, steps), rows, [pass(1, { tests: 'failed' })], said)
}

/** Case 3 (the third): KOLONİ sent the work back for the tests alone - fewer ran - twice; nothing looked. */
function testsOnly() {
  const parts = [opened('d1', 'Debugger', 'Debugger', 1, false), opened('c1', 'Coder', 'Coder', 2, false), opened('f1', 'Coder', 'Coder 2', 4, false), opened('f2', 'Coder', 'Coder 3', 6, false)]
  const passes = [
    { part: 'reproduce', agents: ['d1'] },
    { part: 'fix', agents: ['c1'] },
    { part: 'fix', agents: ['f1'] },
    { part: 'fix', agents: ['f2'] },
  ]
  const rows = [
    row('passed', 'Tests passed: python -m pytest -q - 45 passed', { command: 'python -m pytest -q', counts: { passed: 45, failed: 0, skipped: 0, unit: 'tests' } }),
    row('failed', 'Tests went from 48 to 45 (3 removed)'),
    row('note', 'Sent back to fix: 2 of 2 rounds (tests removed or skipped; tests removed or skipped)', { kind: 'rounds' }),
    row('failed', 'Not taken in: fewer of its tests run, or more are skipped, after its fix rounds', { kind: 'not_taken' }),
  ]
  const why = 'tests removed or skipped'
  const checks = [pass(1, { why, sent: 'fix', fixers: ['f1'] }), pass(2, { why, sent: 'fix', fixers: ['f2'] }), pass(3)]
  return turn(parts, [3, 5, 7], team(['d1', 'c1', 'f1', 'f2'], passes), rows, checks)
}

const graphOf = (state: ReturnType<typeof convState>) => foldGraph(deriveGraph(state), {})
const dataIn = (graph: ReturnType<typeof graphOf>) => graph.nodes.find(n => n.kind === 'checks')!.data as ChecksData
const frameIn = (graph: ReturnType<typeof graphOf>) => graph.nodes.find(n => n.kind === 'team')!

/** No line from the Orchestrator to an agent in the frame - its door only; none from the frame's agents but into the box and on. */
function orchestratorReachesTheFrameAtItsDoor(graph: ReturnType<typeof graphOf>) {
  const inFrame = new Set(graph.nodes.filter(n => n.team === frameIn(graph).id).map(n => n.id))
  expect(graph.edges.filter(e => e.source === 'agent:r' && inFrame.has(e.target))).toEqual([])
}

test('case 1: the looks and the send-back Coders are the box - each role once, ×N - and the frame keeps the recipe’s own steps', () => {
  const graph = graphOf(looksAndFixes())
  const loop = dataIn(graph).loop as Loop
  expect(loop).toMatchObject({
    loop: true,
    looks: [
      { name: 'Reviewer', count: 3 },
      { name: 'Security reviewer', count: 3, tone: 'bad' },
    ],
    fixes: [{ name: 'Coder · fix', count: 2 }],
    status: '⟲ 3 looks · 2 fix rounds · on hold',
  })
  const drawn = graph.nodes.map(n => n.id)
  for (const id of ['f1', 'f2', 'rv1', 'sr3']) expect(drawn).not.toContain(`agent:${id}`)
  // (The frame's steps: the Debugger, then the Coder - none of the send-back's, no round of them folded.)
  expect((frameIn(graph).data as TeamData).columns.map(column => column.ids)).toEqual([['agent:d1'], ['agent:c1']])
  expect(graph.nodes.some(n => n.kind === 'round')).toBe(false)
  expect(graph.edges.filter(e => e.target === 'checks:r').map(e => e.source)).toEqual(['agent:c1'])
  orchestratorReachesTheFrameAtItsDoor(graph)
  // The panel's rounds: who looked, the first blocking finding, who fixed it - and why each went back.
  expect(loop.rounds.map(one => [one.looks.map(l => l.name), one.fixed.map(f => f.name), one.why])).toEqual([
    [['Reviewer', 'Security reviewer'], ['Coder 2'], '1 blocking finding'],
    [['Reviewer 2', 'Security reviewer 2'], ['Coder 3'], '1 blocking finding'],
    [['Reviewer 3', 'Security reviewer 3'], [], null],
  ])
  expect(loop.rounds[0].finding).toBe('shellrun.py:12 runs with shell=True')
})

test('case 2: the recipe’s own loop stays in the frame, its line back grey; KOLONİ’s box beside it is plain - no look, nothing sent back', () => {
  const graph = graphOf(ownLoop())
  expect(dataIn(graph).loop).toBeNull()
  // (Its steps that ran more than once fold as the frame's rounds - Fix it, Test it - the last pass of each drawn.)
  const frame = frameIn(graph).id
  expect(graph.nodes.filter(n => n.team === frame && n.kind !== 'checks').map(n => n.id)).toEqual([
    'agent:d1',
    `round:${frame}:fix:0`,
    `round:${frame}:test:0`,
    'agent:c2',
    'agent:t2',
  ])
  expect(deriveGraph(ownLoop()).edges.find(e => e.findings !== undefined)).toMatchObject({ source: 'agent:t1', target: 'agent:c2', loopBack: true })
  expect(graph.edges.find(e => e.findings !== undefined)).toMatchObject({ source: `round:${frame}:test:0`, target: 'agent:c2', loopBack: true })
  expect(graph.edges.filter(e => e.target === 'checks:r').map(e => e.source)).toEqual(['agent:t2'])
  orchestratorReachesTheFrameAtItsDoor(graph)
})

test('case 3: sent back for the tests alone - the loop’s left end is the tests, “48 → 45 (3 removed)” ⇄ Coder · fix ×2, not taken in', () => {
  const graph = graphOf(testsOnly())
  const loop = dataIn(graph).loop as Loop
  expect(loop).toMatchObject({
    loop: true,
    looks: [{ name: 'Tests', count: 1, said: '48 → 45 (3 removed)', tone: 'bad' }],
    fixes: [{ name: 'Coder · fix', count: 2 }],
    status: '⟲ 2 fix rounds · not taken in',
    dots: ['held', 'held', 'held'],
  })
  for (const id of ['f1', 'f2']) expect(graph.nodes.some(n => n.id === `agent:${id}`)).toBe(false)
  expect(loop.rounds.map(one => one.why)).toEqual(['tests removed or skipped', 'tests removed or skipped', null])
  orchestratorReachesTheFrameAtItsDoor(graph)
})

test('case 3, a Coder and a Tester each send-back: one round each, not one an agent', () => {
  const steps = [step('fix', 'Fix it', 'done'), step('test', 'Test it', 'done'), step('end', 'You', 'next')]
  const parts = [
    opened('c1', 'Coder', 'Coder', 1, false),
    opened('t1', 'Tester', 'Tester', 2, false),
    opened('f1', 'Coder', 'Coder 2', 4, false),
    opened('ft1', 'Tester', 'Tester 2', 5, false),
    opened('f2', 'Coder', 'Coder 3', 7, false),
    opened('ft2', 'Tester', 'Tester 3', 8, false),
  ]
  const passes = [
    { part: 'fix', agents: ['c1'] },
    { part: 'test', agents: ['t1'] },
    { part: 'fix', agents: ['f1'] },
    { part: 'test', agents: ['ft1'] },
    { part: 'fix', agents: ['f2'] },
    { part: 'test', agents: ['ft2'] },
  ]
  const rows = [
    row('failed', 'Tests went from 48 to 45 (3 removed)'),
    row('note', 'Sent back to fix: 2 of 2 rounds (tests removed or skipped; tests removed or skipped)', { kind: 'rounds' }),
    row('failed', 'Not taken in: fewer of its tests run, or more are skipped, after its fix rounds', { kind: 'not_taken' }),
  ]
  const why = 'tests removed or skipped'
  const checks = [pass(1, { why, sent: 'fix', fixers: ['f1', 'ft1'] }), pass(2, { why, sent: 'fix', fixers: ['f2', 'ft2'] }), pass(3)]
  const loop = dataIn(graphOf(turn(parts, [3, 6, 9], team(['c1', 't1', 'f1', 'ft1', 'f2', 'ft2'], passes, steps), rows, checks))).loop as Loop
  expect(loop.rounds.map(one => [one.fixed.map(f => f.name), one.why])).toEqual([
    [['Coder 2', 'Tester 2'], 'tests removed or skipped'],
    [['Coder 3', 'Tester 3'], 'tests removed or skipped'],
    [[], null],
  ])
  expect(loop).toMatchObject({ dots: ['held', 'held', 'held'], status: '⟲ 2 fix rounds · not taken in' })
})

test('R1: two recipe frames - KOLONİ checks once at the end: one box, each frame lined to it; team 1’s send-back Coder in it', () => {
  const parts = [
    opened('a1', 'Coder', 'Coder', 1, false),
    opened('w1', 'Coder', 'Coder 2', 2, false),
    opened('rv1', 'Reviewer', 'Reviewer', 4, true, { findings: [blocking] }),
    opened('af', 'Coder', 'Coder 3', 5, false),
    opened('rv2', 'Reviewer', 'Reviewer 2', 7, true, { report: 'Verdict: MERGE', findings: [] }),
  ]
  const fix = [step('fix', 'Fix it', 'done'), step('end', 'You', 'next')]
  const api = team(['a1', 'af'], [{ part: 'fix', agents: ['a1'] }, { part: 'fix', agents: ['af'] }], fix)
  const web: ChatTeam = { ...team(['w1'], [{ part: 'fix', agents: ['w1'] }], fix), team_id: 'web' }
  web.state = { ...web.state, team: 'Web app' }
  const checks = [pass(1, { looks: [looked('rv1', 'Reviewer', 'HOLD')], why: '1 blocking finding', sent: 'fix', fixers: ['af'] }), pass(2, { looks: [looked('rv2', 'Reviewer', 'MERGE')] })]
  const graph = graphOf(turn(parts, [3, 6], [api, web], [row('passed', 'Tests passed: pytest - 4 passed')], checks))
  expect(graph.nodes.filter(n => n.kind === 'checks')).toHaveLength(1)
  expect(dataIn(graph).loop).toMatchObject({ agents: ['rv1', 'rv2', 'af'], fixes: [{ name: 'Coder 3 · fix', count: 1 }] })
  expect(graph.nodes.some(n => n.id === 'agent:af')).toBe(false)
  // (The box in the turn's last frame, from its last step; the other frame lined to it from the frame itself.)
  expect(graph.edges.filter(e => e.target === 'checks:r').map(e => e.source).sort()).toEqual(['agent:w1', 'team:r:api'])
})

test('layout: the box is the frame’s last part - right of its last step, inside it, clear of its edges and of every other node', () => {
  for (const state of [looksAndFixes(), ownLoop(), testsOnly()]) {
    const graph = graphOf(state)
    const { positions, sizes } = layoutGraph(graph.nodes, graph.edges)
    const rect = (id: string) => ({ ...positions[id], ...(sizes[id] ?? { width: NODE_W, height: NODE_H }) })
    const [box, frame] = [rect('checks:r'), rect(frameIn(graph).id)]
    const steps = graph.nodes.filter(n => n.team === frameIn(graph).id && n.kind !== 'checks').map(n => rect(n.id))
    expect(box.x).toBe(Math.max(...steps.map(one => one.x + one.width)) + COL_GAP)
    expect(box.x > frame.x && box.y > frame.y && box.x + box.width < frame.x + frame.width && box.y + box.height < frame.y + frame.height).toBe(true)
    for (const node of graph.nodes.filter(n => n.id !== 'checks:r' && n.kind !== 'team' && positions[n.id])) {
      const at = rect(node.id)
      const apart = at.x + at.width <= box.x || box.x + box.width <= at.x || at.y + at.height <= box.y || box.y + box.height <= at.y
      expect(apart, node.id).toBe(true)
    }
  }
})
