import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ReactFlowProvider } from '@xyflow/react'
import { expect, test, vi } from 'vitest'
import type { Agent, Message } from '../api/types'
import { Inspector } from '../inspector/Inspector'
import { FIX_REVIEW } from '../chat/checked'
import { useApp } from '../state/store'
import { agent, assistantMessage, convState, fileChange, run, toolCall } from '../test-fixtures'
import { checksSize, LOOP, type Loop } from './checksLoop'
import type { ChecksData } from './checksNode'
import { deriveGraph } from './deriveGraph'
import { nodeOf } from './foldGraph'
import { COL_GAP, layoutGraph, NODE_H, NODE_W } from './layout'
import { ChecksNode } from './nodes'

type Row = NonNullable<Message['checked']>[number]
type Finding = NonNullable<Agent['findings']>[number]
const row = (state: Row['state'], text: string, more: Partial<Row> = {}): Row => ({ kind: 'tests', state, text, command: null, guessed: false, started_at: null, counts: null, ...more })
const checked = (rows: Row[]): Message => ({ ...assistantMessage('k', 'r', 'x'), role: 'checked', agent_id: null, checked: rows })
const blocking = (what: string): Finding => ({ what, kind: 'security', role: 'Orchestrator', blocking: true })

/** A sub-agent of the turn, opened by the call `call` (its order: `seq`). */
function sub(id: string, role: string, name: string, seq: number, kolonis: boolean, over: Partial<Agent> = {}) {
  const call = toolCall(`s${id}`, 'r', 'spawn_agent', 'succeeded', '{}', { seq, provider_call_id: kolonis ? `koloni_proof_review_${id}` : `call_${id}` })
  return { agent: { ...agent(id, 'completed', { role_name: role }), run_id: 'r', depth: 1, parent_agent_id: 'r', tool_call_id: call.id, name, ...over }, call }
}
const test_run = (id: string, seq: number) => toolCall(id, 'r', 'run_command', 'succeeded', '{"command":"python -m pytest -q"}', { seq, provider_call_id: `koloni_proof_${id}` })
const merge = { report: 'Read it.\nVerdict: MERGE\n\nFindings: none', findings: [] }

/**
 * The approved sketch's turn (checks-rounds-v3): three Coders of the Orchestrator's, then KOLONİ's three looks - the Reviewer and
 * the Security reviewer each time - and two fix rounds, Coder 4 and Coder 5, still on hold at the end.
 */
function sketched(over: { running?: boolean } = {}) {
  const opened = [
    sub('c1', 'Coder', 'Coder', 1, false),
    sub('c2', 'Coder', 'Coder 2', 2, false),
    sub('c3', 'Coder', 'Coder 3', 3, false),
    sub('rv1', 'Reviewer', 'Reviewer', 5, true, merge),
    sub('sr1', 'Security reviewer', 'Security reviewer', 6, true, { findings: [blocking('runner.py:17 uses Popen with shell=True'), blocking('b'), blocking('c')] }),
    sub('f1', 'Coder', 'Coder 4', 7, false),
    sub('rv2', 'Reviewer', 'Reviewer 2', 9, true, merge),
    sub('sr2', 'Security reviewer', 'Security reviewer 2', 10, true, { findings: [blocking('d'), blocking('e'), blocking('f')] }),
    sub('f2', 'Coder', 'Coder 5', 11, false),
    sub('rv3', 'Reviewer', 'Reviewer 3', 13, true, { findings: [blocking('netcheck.fetch allows any URL (SSRF)')] }),
    sub('sr3', 'Security reviewer', 'Security reviewer 3', 14, true, { findings: [blocking('g'), blocking('h')] }),
  ]
  // (At work: round 3's two looks read, and have said nothing yet.)
  const agents = opened.map(one => (over.running && ['rv3', 'sr3'].includes(one.agent.id) ? { ...one.agent, status: 'running' as const, findings: null, report: null } : one.agent))
  const files = [...['a.py', 'b.py', 'c.py'].map((path, n) => fileChange(`fa${n}`, 'r', { agent_id: 'f1', path })), ...['a.py', 'b.py', 'c.py', 'd.py'].map((path, n) => fileChange(`fb${n}`, 'r', { agent_id: 'f2', path }))]
  const rows = [
    row('passed', 'Related tests passed: python -m pytest a_test.py - 19 passed', { command: 'python -m pytest a_test.py', counts: { passed: 19, failed: 0, skipped: 0, unit: 'tests' } }),
    row('passed', 'Tests passed: python -m pytest -q - 36 passed', { command: 'python -m pytest -q', counts: { passed: 36, failed: 0, skipped: 0, unit: 'tests' } }),
    row('note', 'Sent back to fix: 2 of 2 rounds (3 blocking findings; 3 blocking findings)', { kind: 'rounds' }),
    row('failed', 'Review: Security reviewer (x) - HOLD, 2 findings, 2 blocking', { kind: 'review' }),
    row('note', 'Blocking: netcheck.fetch allows any URL (SSRF)', { kind: 'finding' }),
    row('failed', 'Still on hold after 2 fix rounds: you decide (Fix it)', { kind: 'review' }),
  ]
  return convState({
    runs: [run('r', over.running ? 'running' : 'completed')],
    agents: [agent('r', over.running ? 'running' : 'completed'), ...agents],
    toolCalls: [...opened.map(one => one.call), test_run('p1', 4), test_run('p2', 8), test_run('p3', 12)],
    fileChanges: files,
    messages: over.running ? [] : [assistantMessage('a', 'r', 'Fixed the finding.'), checked(rows)],
  })
}

const dataIn = (graph: ReturnType<typeof deriveGraph>) => graph.nodes.find(n => n.kind === 'checks')!.data as ChecksData
const loopIn = (graph: ReturnType<typeof deriveGraph>) => dataIn(graph).loop as Loop

test('the sketched turn: KOLONİ’s looks and the fixes it sent back are one loop - each role once, its latest, ×N; the Orchestrator’s own Coders outside', () => {
  const graph = deriveGraph(sketched())
  const loop = loopIn(graph)
  expect(loop.loop).toBe(true)
  expect(loop.looks).toEqual([
    { agentId: 'rv3', name: 'Reviewer', count: 3, said: 'last: HOLD · 1 blocking', tone: 'bad' },
    { agentId: 'sr3', name: 'Security reviewer', count: 3, said: 'last: HOLD · 2 blocking', tone: 'bad' },
  ])
  expect(loop.fixes).toEqual([{ agentId: 'f2', name: 'Coder · fix', count: 2, said: 'last: 4 files', tone: 'note' }])
  expect(loop.status).toBe('⟲ 3 looks · 2 fix rounds · on hold')
  expect(loop.dots).toEqual(['held', 'held', 'held'])
  expect(loop.tests.map(line => line.text)).toEqual(['related 19', 'pytest 36'])
  // Each of the box's agents is no node, nor at a line's end; the Orchestrator's own three are, as before.
  const agents = graph.nodes.filter(n => n.kind === 'agent').map(n => n.id)
  expect(agents).toEqual(['agent:r', 'agent:c1', 'agent:c2', 'agent:c3'])
  for (const id of loop.agents) expect(graph.edges.some(e => e.source === `agent:${id}` || e.target === `agent:${id}`)).toBe(false)
  // One arrow into the box from the Orchestrator's work - its middle Coder -; no long line down past them, no round's line back.
  expect(graph.edges.filter(e => e.source.startsWith('checks:') || e.target.startsWith('checks:'))).toEqual([{ id: 'agent:c2>checks:r', source: 'agent:c2', target: 'checks:r', active: false }])
})

test('round by round: who looked and what each said, the first blocking finding, who fixed it with how many files; why the last stopped', () => {
  const loop = loopIn(deriveGraph(sketched()))
  expect(loop.rounds).toEqual([
    {
      n: 1,
      looks: [
        { agentId: 'rv1', name: 'Reviewer', verdict: 'MERGE' },
        { agentId: 'sr1', name: 'Security reviewer', verdict: 'HOLD · 3 blocking' },
      ],
      finding: 'runner.py:17 uses Popen with shell=True',
      fixed: [{ agentId: 'f1', name: 'Coder 4', files: 3 }],
      why: '3 blocking findings',
    },
    {
      n: 2,
      looks: [
        { agentId: 'rv2', name: 'Reviewer 2', verdict: 'MERGE' },
        { agentId: 'sr2', name: 'Security reviewer 2', verdict: 'HOLD · 3 blocking' },
      ],
      finding: 'd',
      fixed: [{ agentId: 'f2', name: 'Coder 5', files: 4 }],
      why: '3 blocking findings',
    },
    {
      n: 3,
      looks: [
        { agentId: 'rv3', name: 'Reviewer 3', verdict: 'HOLD · 1 blocking' },
        { agentId: 'sr3', name: 'Security reviewer 3', verdict: 'HOLD · 2 blocking' },
      ],
      finding: 'netcheck.fetch allows any URL (SSRF)',
      fixed: [],
      why: null,
    },
  ])
  expect(loop.stop).toBe('Still on hold after 2 fix rounds: you decide (Fix it)')
})

test('at work: the round and what it does now, the looks reading, the last dot amber - and nothing said of how it ends', () => {
  const loop = loopIn(deriveGraph(sketched({ running: true })))
  expect(loop.status).toBe('● round 3 · looking…')
  expect(loop.tone).toBe('run')
  expect(loop.dots).toEqual(['held', 'held', 'running'])
  expect(loop.looks[0]).toMatchObject({ name: 'Reviewer', count: 3, said: '● reading', tone: 'run' })
  expect(loop.stop).toBeNull()
})

test('the first fix round at work is a loop already: its fixer at work, one amber dot - and one that waits for you says so, never “at work”', () => {
  // Round 1's look held, and the Orchestrator's Coder fixes: KOLONİ has not run again yet, so no round is counted.
  const look = sub('rv', 'Reviewer', 'Reviewer', 2, true, { findings: [blocking('a.py:1 is wrong')] })
  const fix = sub('fx', 'Coder', 'Coder 2', 3, false, { status: 'running' })
  const turn = (fixer: Agent, more: Partial<Parameters<typeof convState>[0]> = {}) =>
    convState({ runs: [run('r', 'running')], agents: [agent('r', 'running'), look.agent, fixer], toolCalls: [test_run('p1', 1), look.call, fix.call], ...more })
  const loop = loopIn(deriveGraph(turn(fix.agent)))
  expect(loop).toMatchObject({ loop: true, status: '● round 1 · fixing…', tone: 'run', dots: ['running'] })
  expect(loop.fixes).toEqual([{ agentId: 'fx', name: 'Coder 2 · fix', count: 1, said: '● at work', tone: 'run' }])
  // Asked to be let start, or its change waiting for your yes (its node's cue, which the box takes over).
  const proposed = loopIn(deriveGraph(turn({ ...fix.agent, status: 'proposed' })))
  expect(proposed).toMatchObject({ status: '● round 1 · waits for you', fixes: [{ said: 'waits for you', tone: 'note' }] })
  const asked = loopIn(deriveGraph(turn(fix.agent, { fileChanges: [fileChange('w', 'r', { agent_id: 'fx', status: 'proposed' })] })))
  expect(asked).toMatchObject({ status: '● round 1 · waits for you', fixes: [{ said: 'waits for you' }] })
  // Its fix over, KOLONİ tests again: round 2 already, before a look of it is opened.
  const again = turn({ ...fix.agent, status: 'completed' }, { toolCalls: [test_run('p1', 1), look.call, fix.call, { ...test_run('p2', 4), status: 'running' }] })
  expect(loopIn(deriveGraph(again))).toMatchObject({ status: '● round 2 · testing…', dots: ['held', 'running'] })
  // Waiting for a slot is the agent's own words.
  expect(loopIn(deriveGraph(turn({ ...fix.agent, status: 'queued' }))).fixes[0]).toMatchObject({ said: 'waiting for a slot', tone: 'note' })
})

test('an agent drawn in the box, selected in the chat, is shown as the box', () => {
  const graph = deriveGraph(sketched())
  expect(nodeOf(graph, 'agent:rv2')?.id).toBe('checks:r')
  expect(nodeOf(graph, 'agent:c2')?.id).toBe('agent:c2')
})

test('one look and nothing sent back is the plain box: no loop, no ×N; with no agent of KOLONİ’s, the node of lines it was', () => {
  const look = sub('rv', 'Reviewer', 'Reviewer', 3, true, merge)
  const passed = row('passed', 'Tests passed: python check.py - 2 passed', { command: 'python check.py', counts: { passed: 2, failed: 0, skipped: 0, unit: 'tests' } })
  const once = convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed'), look.agent], toolCalls: [look.call, test_run('p1', 2)], messages: [checked([passed])] })
  const graph = deriveGraph(once)
  expect(loopIn(graph)).toMatchObject({ loop: false, looks: [{ name: 'Reviewer', count: 1, said: 'MERGE', tone: 'ok' }], fixes: [] })
  // (No agent of the Orchestrator's own: one column, right of the Orchestrator, level with it, its arrow from it.)
  const { positions, sizes } = layoutGraph(graph.nodes, graph.edges)
  expect(positions['checks:r']).toEqual({ x: positions['agent:r'].x + NODE_W + COL_GAP, y: positions['agent:r'].y })
  expect(sizes['checks:r'].width).toBe(2 * LOOP.pad + LOOP.card + LOOP.shadow)
  expect(graph.edges.filter(e => e.target === 'checks:r')).toEqual([{ id: 'agent:r>checks:r', source: 'agent:r', target: 'checks:r', active: false }])
  const plain = convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed')], toolCalls: [test_run('p1', 2)], messages: [checked([passed])] })
  expect(loopIn(deriveGraph(plain))).toBeNull()
})

test('layout: the box stands right of the Orchestrator’s Coders (the sketch’s state 1), level with their middle, as big as its loop - over nothing', () => {
  const graph = deriveGraph(sketched())
  const { positions, sizes } = layoutGraph(graph.nodes, graph.edges)
  const box = { ...positions['checks:r'], ...sizes['checks:r'] }
  expect(sizes['checks:r']).toEqual(checksSize(dataIn(graph)))
  const coders = ['agent:c1', 'agent:c2', 'agent:c3'].map(id => ({ ...positions[id], ...(sizes[id] ?? { width: NODE_W, height: NODE_H }) }))
  expect(box.x).toBe(Math.max(...coders.map(at => at.x + at.width)) + COL_GAP)
  const [high, low] = [Math.min(...coders.map(at => at.y)), Math.max(...coders.map(at => at.y + at.height))]
  expect(box.y + box.height / 2).toBeCloseTo((high + low) / 2, 0)
  for (const node of graph.nodes.filter(n => n.id !== 'checks:r')) {
    const at = { ...positions[node.id], ...(sizes[node.id] ?? { width: NODE_W, height: NODE_H }) }
    const apart = at.x + at.width <= box.x || box.x + box.width <= at.x || at.y + at.height <= box.y || box.y + box.height <= at.y
    expect(apart, node.id).toBe(true)
  }
})

test('the node: Checks · KOLONİ, its rounds in its head, each role once with ×N, looks ⇄ fixes, its tests and a dot a round at its foot', () => {
  const data = dataIn(deriveGraph(sketched()))
  const props = { id: 'checks:r', data, selected: false, type: 'checks', dragging: false, zIndex: 0, isConnectable: false, positionAbsoluteX: 0, positionAbsoluteY: 0, draggable: false, selectable: false, deletable: false }
  const { container } = render(
    <ReactFlowProvider>
      <ChecksNode {...(props as Parameters<typeof ChecksNode>[0])} />
    </ReactFlowProvider>,
  )
  expect(container.querySelector('.node-checks-loop')).not.toBeNull()
  expect(screen.getByText('Checks · KOLONİ')).toBeInTheDocument()
  expect(screen.getByText('⟲ 3 looks · 2 fix rounds · on hold')).toBeInTheDocument()
  const cards = Array.from(container.querySelectorAll('.checks-card-at'), card => card.textContent)
  expect(cards).toEqual(['×3Reviewerlast: HOLD · 1 blocking', '×3Security reviewerlast: HOLD · 2 blocking', '×2Coder · fixlast: 4 files'])
  expect(screen.getByText('⇄')).toBeInTheDocument()
  expect(container.querySelector('.checks-tests')?.textContent).toBe('✓ related 19 · ✓ pytest 36')
  // (Each role with its earlier rounds behind it: the shadows' cards.)
  expect(container.querySelectorAll('.checks-stack')).toHaveLength(3)
  expect(screen.getByRole('img', { name: '3 rounds: held, held, held' }).children).toHaveLength(3)
  // Its panel open: the frame amber.
  const picked = render(
    <ReactFlowProvider>
      <ChecksNode {...({ ...props, selected: true } as Parameters<typeof ChecksNode>[0])} />
    </ReactFlowProvider>,
  )
  expect(picked.container.querySelector('.node-checks-loop')).toHaveClass('node-checks-selected')
})

test('the panel: its tests, round by round with each agent’s window a click away, Fix it on the latest turn, and the way to the Checked section', async () => {
  const opened = vi.fn()
  const showChatTab = vi.spyOn(useApp.getState(), 'showChatTab')
  const send = vi.fn().mockResolvedValue(undefined)
  useApp.setState({ send })
  render(<Inspector state={sketched()} selectedId="checks:r" onClose={() => {}} onOpenAgent={opened} />)
  const panel = screen.getByRole('complementary', { name: 'Inspector' })
  // (Its head says it as the Orchestrator's strip does.)
  expect(within(panel).getByText('✗ on hold · 2 rounds')).toBeInTheDocument()
  const tests = within(panel).getByRole('region', { name: 'Tests' })
  expect(tests).toHaveTextContent('✓ Related tests passed: python -m pytest a_test.py - 19 passed✓ Tests passed: python -m pytest -q - 36 passed')
  const first = within(panel).getByRole('region', { name: 'Round 1' })
  expect(first).toHaveTextContent('ReviewerMERGESecurity reviewerHOLD · 3 blocking• runner.py:17 uses Popen with shell=True→ fixed by Coder 43 files')
  const last = within(panel).getByRole('region', { name: 'Round 3' })
  expect(last).toHaveTextContent('Still on hold after 2 fix rounds: you decide (Fix it)')
  await userEvent.click(within(first).getByRole('button', { name: 'Coder 4' }))
  expect(opened).toHaveBeenCalledWith('f1')
  render(<Inspector state={sketched()} selectedId="checks:r" onClose={() => {}} onOpenAgent={opened} />)
  await userEvent.click(screen.getAllByRole('button', { name: 'Open the Checked section' }).at(-1)!)
  expect(showChatTab).toHaveBeenCalledWith('Chat', true, 'checked-r')
  await userEvent.click(screen.getAllByRole('button', { name: 'Fix it' }).at(-1)!)
  expect(send).toHaveBeenCalledWith(FIX_REVIEW)
})
