import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ReactFlowProvider } from '@xyflow/react'
import { expect, test, vi } from 'vitest'
import type { Agent, Message } from '../api/types'
import { Inspector } from '../inspector/Inspector'
import { useApp } from '../state/store'
import { agent, assistantMessage, convState, run, toolCall } from '../test-fixtures'
import type { Loop } from './checksLoop'
import type { ChecksData } from './checksNode'
import { deriveGraph } from './deriveGraph'
import { layoutGraph } from './layout'
import { ChecksNode } from './nodes'

// tuval-kontrol-dongusu, round 2 (the review's HOLD): the box, its ×N, dots, foot and panel read the passes KOLONİ wrote with
// its Checked section (`Message.passes`) - never the order agents were opened in. The review's probes, each a test.

type Row = NonNullable<Message['checked']>[number]
type Pass = NonNullable<Message['passes']>[number]
const row = (state: Row['state'], text: string, more: Partial<Row> = {}): Row => ({ kind: 'tests', state, text, command: null, guessed: false, started_at: null, counts: null, ...more })
const pass = (n: number, more: Partial<Pass> = {}): Pass => ({ n, kind: 'check', tests: 'passed', looks: [], why: null, sent: null, fixers: [], diagnosis: null, tier: null, ...more })
const looked = (agent_id: string, verdict: string | null) => ({ agent_id, role: 'Reviewer', verdict })
const passed = row('passed', 'Tests passed: python -m pytest -q - 36 passed', { command: 'python -m pytest -q', counts: { passed: 36, failed: 0, skipped: 0, unit: 'tests' } })

/** An agent of the turn, opened by a call of the Lead's (`call_…`), of KOLONİ's (`koloni_proof_<kind>_…`) or none (a room's member). */
function opened(id: string, name: string, kind: string | null, over: Partial<Agent> = {}) {
  const call = toolCall(`s${id}`, 'r', 'spawn_agent', 'succeeded', '{}', { provider_call_id: kind ? `koloni_proof_${kind}_${id}` : `call_${id}` })
  return { agent: { ...agent(id, 'completed', { role_name: over.role_name ?? 'Coder' }), run_id: 'r', depth: 1, parent_agent_id: 'r', tool_call_id: call.id, name, ...over } as Agent, call }
}

function turn(parts: ReturnType<typeof opened>[], rows: Row[], passes: Pass[], more: Agent[] = []) {
  const section: Message = { ...assistantMessage('k', 'r', ''), role: 'checked', agent_id: null, checked: rows, passes }
  return convState({
    runs: [run('r', 'completed')],
    agents: [agent('r', 'completed'), ...parts.map(one => one.agent), ...more],
    toolCalls: parts.map(one => one.call),
    messages: [assistantMessage('a', 'r', 'done'), section],
  })
}
const graphOf = (state: ReturnType<typeof convState>) => deriveGraph(state)
const loopIn = (graph: ReturnType<typeof deriveGraph>) => (graph.nodes.find(n => n.kind === 'checks')!.data as ChecksData).loop as Loop | null
const drawn = (graph: ReturnType<typeof deriveGraph>) => graph.nodes.filter(n => n.kind === 'agent').map(n => n.id)

test('S4: a room’s members, opened mid-turn, stay the Orchestrator’s - outside the box, which holds what the passes name', () => {
  const look = opened('rv', 'Reviewer', 'review', { role_name: 'Reviewer' })
  const member = opened('m1', 'Coder 2', null, { tool_call_id: null })
  const graph = graphOf(turn([opened('c1', 'Coder', null), look, member], [passed], [pass(1, { looks: [looked('rv', 'MERGE')] })]))
  expect(loopIn(graph)).toMatchObject({ agents: ['rv'], fixes: [] })
  expect(drawn(graph)).toContain('agent:m1')
})

test('A: the agent the Lead opened for KOLONİ’s ask for a test is no fix round - its own node; no loop', () => {
  const look = opened('rv', 'Reviewer', 'review', { role_name: 'Reviewer' })
  const graph = graphOf(turn([opened('c1', 'Coder', null), look, opened('c2', 'Coder 2', null)], [passed], [pass(1, { looks: [looked('rv', 'MERGE')], sent: 'ask' }), pass(2)]))
  const loop = loopIn(graph)!
  expect(loop).toMatchObject({ loop: false, agents: ['rv'], fixes: [], status: '1 look · ✓ checked' })
  expect(drawn(graph)).toContain('agent:c2')
  expect(loop.rounds.map(one => one.sent)).toEqual(['ask', null])
})

test('B: tests fail twice, then a look holds - four passes, four dots; rounds 1-3 each its one fixer', () => {
  const parts = [opened('c1', 'Coder', null), ...['cf1', 'cf2', 'cf3'].map((id, n) => opened(id, `Coder ${n + 2}`, null))]
  const looks = [opened('rv1', 'Reviewer', 'review', { role_name: 'Reviewer' }), opened('rv2', 'Reviewer 2', 'review', { role_name: 'Reviewer' })]
  const passes = [
    pass(1, { tests: 'failed', why: 'tests fail', sent: 'fix', fixers: ['cf1'] }),
    pass(2, { tests: 'failed', why: 'tests fail', sent: 'fix', fixers: ['cf2'] }),
    pass(3, { looks: [looked('rv1', 'HOLD')], why: '1 blocking finding', sent: 'fix', fixers: ['cf3'] }),
    pass(4, { looks: [looked('rv2', 'MERGE')] }),
  ]
  const loop = loopIn(graphOf(turn([...parts, ...looks], [passed], passes)))!
  expect(loop).toMatchObject({ dots: ['held', 'held', 'held', 'passed'], status: '2 looks · 3 fix rounds · ✓ checked', fixes: [{ name: 'Coder · fix', count: 3 }] })
  expect(loop.rounds.map(one => one.fixed.map(f => f.name))).toEqual([['Coder 2'], ['Coder 3'], ['Coder 4'], []])
})

test('C: a stronger tier’s diagnosis is its own kind - no look - and its fixer a fix; D: the Orchestrator fixing itself is a round with no fixer', () => {
  const parts = [opened('cf1', 'Coder 2', null), opened('dg', 'Coder 4', 'diagnose', { report: 'Diagnosis: fix-incomplete - the zero case' }), opened('sf1', 'Coder 5', 'fix')]
  const passes = [
    pass(1, { tests: 'failed', why: 'tests fail', sent: 'fix', fixers: ['cf1'] }),
    pass(2, { tests: 'failed', why: 'tests fail', sent: 'fix', fixers: [] }),
    pass(3, { tests: 'failed' }),
    pass(4, { kind: 'stronger', tier: 'balanced', tests: 'passed', why: 'tests fail', sent: 'fix', fixers: ['sf1'], diagnosis: 'dg' }),
  ]
  const loop = loopIn(graphOf(turn(parts, [passed], passes)))!
  expect(loop.status).toBe('2 fix rounds · 1 stronger round · ✓ checked')
  expect(loop.looks).toEqual([
    { agentId: 'tests:r', name: 'Tests', count: 1, said: 'pytest · 36 ✓', tone: 'ok' },
    { agentId: 'dg', name: 'Coder 4 · diagnosis', count: 1, said: 'fix-incomplete', tone: 'note' },
  ])
  expect(loop.fixes).toEqual([{ agentId: 'sf1', name: 'Coder · fix', count: 2, said: 'last: 0 files', tone: 'note' }])
  expect(loop.rounds[1]).toMatchObject({ sent: 'fix', fixed: [] })
  expect(loop.rounds[3]).toMatchObject({ kind: 'stronger', tier: 'balanced', diagnosis: { agentId: 'dg', name: 'Coder 4' }, looks: [] })
})

test('S2: a turn stopped mid-round is never “✓ checked” - no passed test line, not checked; the Tests card a test line (D2)', () => {
  const parts = [opened('c1', 'Coder', null), opened('cf1', 'Coder 2', null)]
  const passes = [pass(1, { tests: 'failed', why: 'tests fail', sent: 'fix', fixers: ['cf1'] })]
  const stopped = loopIn(graphOf(turn(parts, [row('not_run', 'Not run: the turn was stopped')], passes)))!
  expect(stopped.status).toBe('1 fix round · not checked')
  expect(stopped.status).not.toContain('✓')
  // (The section's last line is its rounds': the card says a test run's.)
  const rows = [passed, row('note', 'Sent back to fix: 1 of 2 rounds', { kind: 'rounds' })]
  expect(loopIn(graphOf(turn(parts, rows, [...passes, pass(2)])))!.looks).toEqual([{ agentId: 'tests:r', name: 'Tests', count: 1, said: 'pytest · 36 ✓', tone: 'ok' }])
})

test('E: what a fixer opened under it is drawn in the box with it - no lone node', () => {
  const fixer = opened('cf1', 'Coder 2', null)
  const kid = { ...agent('kid', 'completed', { role_name: 'Explorer' }), run_id: 'r', depth: 2, parent_agent_id: 'cf1', name: 'Explorer' } as Agent
  const graph = graphOf(turn([opened('c1', 'Coder', null), fixer], [passed], [pass(1, { tests: 'failed', why: 'tests fail', sent: 'fix', fixers: ['cf1'] }), pass(2)], [kid]))
  expect(loopIn(graph)!.agents).toEqual(['cf1', 'kid'])
  expect(drawn(graph)).not.toContain('agent:kid')
  const { positions } = layoutGraph(graph.nodes, graph.edges)
  expect(positions['agent:kid']).toBeUndefined()
})

test('keyboard: the tag is the box’s click (its panel), a card its agent’s window alone - Enter or Space, never the canvas’s own key too', async () => {
  const parts = [opened('c1', 'Coder', null), opened('rv', 'Reviewer', 'review', { role_name: 'Reviewer', findings: [{ what: 'x', kind: 'code', role: 'Orchestrator', blocking: true }] }), opened('cf1', 'Coder 2', null)]
  const passes = [pass(1, { looks: [looked('rv', 'HOLD')], why: '1 blocking finding', sent: 'fix', fixers: ['cf1'] }), pass(2)]
  const data = graphOf(turn(parts, [passed], passes)).nodes.find(n => n.kind === 'checks')!.data as ChecksData
  const openAgentWindow = vi.spyOn(useApp.getState(), 'openAgentWindow').mockImplementation(() => {})
  const [keys, clicks] = [vi.fn(), vi.fn()]
  const props = { id: 'checks:r', data, selected: false, type: 'checks', dragging: false, zIndex: 0, isConnectable: false, positionAbsoluteX: 0, positionAbsoluteY: 0, draggable: false, selectable: false, deletable: false }
  render(
    <ReactFlowProvider>
      {/* (The node's own wrapper: a key or click that reaches it would pick the node a second time.) */}
      <div onKeyDown={keys} onClick={clicks}>
        <ChecksNode {...(props as Parameters<typeof ChecksNode>[0])} />
      </div>
    </ReactFlowProvider>,
  )
  const tag = screen.getByRole('button', { name: /^Checks · KOLONİ: .* - open its panel$/ })
  expect(tag).toHaveAttribute('title', data.loop!.status)
  tag.focus()
  await userEvent.keyboard('{Enter}')
  expect(clicks).toHaveBeenCalledTimes(1) // (the node's click: the canvas picks the box - its panel)
  const card = screen.getByRole('button', { name: "Open Coder 2 · fix's window: 0 files" })
  card.focus()
  await userEvent.keyboard(' ')
  expect(openAgentWindow).toHaveBeenCalledWith('cf1')
  expect(clicks).toHaveBeenCalledTimes(1) // (no second pick: the card's window alone)
  expect(keys).not.toHaveBeenCalled()
})

test('the panel: the way to the Checked section only once it is written - a turn at work has none; its rounds say how each went back', () => {
  const parts = [opened('cf1', 'Coder 2', null), opened('dg', 'Coder 4', 'diagnose')]
  const passes = [
    pass(1, { looks: [], sent: 'ask' }),
    pass(2, { tests: 'failed', why: 'tests fail', sent: 'fix', fixers: [] }),
    pass(3, { kind: 'stronger', tier: 'balanced', why: 'tests fail', sent: 'fix', fixers: ['cf1'], diagnosis: 'dg' }),
  ]
  const state = turn(parts, [passed], passes)
  render(<Inspector state={state} selectedId="checks:r" onClose={() => {}} onOpenAgent={() => {}} />)
  const panel = screen.getByRole('complementary', { name: 'Inspector' })
  expect(within(panel).getByRole('region', { name: 'Round 1' })).toHaveTextContent('asked for a test - no fix round')
  expect(within(panel).getByRole('region', { name: 'Round 2' })).toHaveTextContent('sent back: tests fail - no agent opened for it')
  expect(within(panel).getByRole('region', { name: 'Round 3' })).toHaveTextContent('Round 3 · a stronger model (balanced)Coder 4diagnosis')
  expect(within(panel).getByRole('button', { name: 'Open the Checked section' })).toBeInTheDocument()
})

test('live, before its section: the box draws its “● looking…” and its one amber dot - not only in its data', () => {
  const look = opened('rv', 'Reviewer', 'review', { role_name: 'Reviewer', status: 'running', report: null, findings: null })
  const state = convState({ runs: [run('r', 'running')], agents: [agent('r', 'running'), opened('c1', 'Coder', null).agent, look.agent], toolCalls: [look.call] })
  const data = graphOf(state).nodes.find(n => n.kind === 'checks')!.data as ChecksData
  const props = { id: 'checks:r', data, selected: false, type: 'checks', dragging: false, zIndex: 0, isConnectable: false, positionAbsoluteX: 0, positionAbsoluteY: 0, draggable: false, selectable: false, deletable: false }
  render(
    <ReactFlowProvider>
      <ChecksNode {...(props as Parameters<typeof ChecksNode>[0])} />
    </ReactFlowProvider>,
  )
  expect(screen.getByText('● looking…')).toBeInTheDocument()
  expect(screen.getByRole('img', { name: '1 rounds: at work' }).children).toHaveLength(1)
})

test('a pass that only asked for a test has a neutral dot, never a red one', () => {
  const parts = [opened('c1', 'Coder', null), opened('cf1', 'Coder 2', null)]
  const passes = [pass(1, { tests: 'failed', why: 'tests fail', sent: 'fix', fixers: ['cf1'] }), pass(2, { sent: 'ask' }), pass(3)]
  expect(loopIn(graphOf(turn(parts, [passed], passes)))!.dots).toEqual(['held', 'asked', 'passed'])
})
