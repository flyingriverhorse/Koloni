import { render, screen } from '@testing-library/react'
import { ReactFlowProvider } from '@xyflow/react'
import { expect, test } from 'vitest'
import type { Message } from '../api/types'
import { agent, assistantMessage, command, convState, run, toolCall } from '../test-fixtures'
import { type ChecksData, checksNode, stripOf, toolOf } from './checksNode'
import { type AgentData, deriveGraph, type GraphEdge, type GraphNode } from './deriveGraph'
import { ChecksNode } from './nodes'

type Row = NonNullable<Message['checked']>[number]
const row = (state: Row['state'], text: string, more: Partial<Row> = {}): Row => ({ kind: 'tests', state, text, command: null, guessed: false, started_at: null, counts: null, ...more })
const checked = (rows: Row[]): Message => ({ ...assistantMessage('k', 'r', 'x'), role: 'checked', agent_id: null, checked: rows })
const proofCall = (id: string, status: 'running' | 'succeeded', started = '2026-10-05T10:00:03Z') =>
  toolCall(id, 'r', 'run_command', status, JSON.stringify({ command: 'python -m pytest -q' }), { provider_call_id: `koloni_proof_${id}`, started_at: started })

function drawn(state: ReturnType<typeof convState>) {
  const nodes: GraphNode[] = [{ id: 'agent:r', kind: 'agent', runId: 'r', refId: 'r', data: {} as AgentData }]
  const edges: GraphEdge[] = []
  const data = checksNode(state, run('r', 'completed'), nodes, edges)
  return { data, nodes, edges }
}

test('a test run at work shows its tool and when it started, and no number it has not got', () => {
  const { data, nodes } = drawn(convState({ runs: [run('r')], agents: [agent('r')], toolCalls: [proofCall('p1', 'running')] }))
  expect(data?.running).toEqual({ command: 'python -m pytest -q', since: '2026-10-05T10:00:03Z' })
  expect(data?.lines).toEqual([])
  expect((nodes[0].data as AgentData).checked).toBe('● checking…')
})

test('the Checked rows are its lines, with their counts where the runner gave them', () => {
  const rows = [
    row('passed', 'Tests passed: python -m pytest -q - 214 passed', { command: 'python -m pytest -q', counts: { passed: 214, failed: 0, skipped: 0, unit: 'tests' } }),
    row('note', 'Saved as this project’s test command - change it in Settings', { kind: 'found' }),
  ]
  const { data, nodes } = drawn(convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed')], messages: [checked(rows)] }))
  expect(data?.lines).toEqual([{ state: 'passed', text: 'pytest · 214 ✓' }, { state: 'note', text: rows[1].text }])
  expect((nodes[0].data as AgentData).checked).toBe('✓ checked')
})

test('a fix round is a line back to the Orchestrator, and its strip counts it', () => {
  const state = convState({
    runs: [run('r', 'completed')],
    agents: [agent('r', 'completed')],
    toolCalls: [proofCall('p1', 'succeeded'), proofCall('p2', 'succeeded', '2026-10-05T10:01:03Z')],
    commands: [command('c1', 'r', { tool_call_id: 'p1', exit_code: 1 }), command('c2', 'r', { tool_call_id: 'p2', exit_code: 0 })],
    messages: [checked([row('passed', 'Tests passed', { command: 'python -m pytest -q', counts: { passed: 4, failed: 0, skipped: 0, unit: 'tests' } })])],
  })
  const { data, edges, nodes } = drawn(state)
  expect(data?.rounds).toBe(1)
  expect(edges.find(e => e.round)).toMatchObject({ source: 'checks:r', target: 'agent:r', round: 'round 1 of 2: tests fail' })
  expect((nodes[0].data as AgentData).checked).toBe('✓ checked · 1 round')
})

test('nothing checked: no node, and the canvas draws it through deriveGraph where there is', () => {
  expect(drawn(convState({ runs: [run('r')], agents: [agent('r')] })).data).toBeNull()
  const graph = deriveGraph(convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed')], messages: [checked([row('failed', 'Tests failed')])] }))
  expect(graph.nodes.find(n => n.kind === 'checks')?.id).toBe('checks:r')
})

test('the strip says still failing or not checked; the tool is the runner, not python', () => {
  const base: ChecksData = { runId: 'r', leadId: 'r', running: null, lines: [], rounds: 2, recipe: false }
  expect(stripOf({ ...base, lines: [{ state: 'failed', text: 'x' }] })).toBe('✗ still failing · 2 rounds')
  expect(stripOf({ ...base, lines: [{ state: 'not_run', text: 'No test command' }] })).toBe('not checked')
  expect(stripOf(base)).toBeNull()
  expect(toolOf('python -m pytest -q')).toBe('pytest')
  expect(toolOf('npx vitest run')).toBe('vitest')
  expect(toolOf('go test ./...')).toBe('go')
})

test('the node shows what runs now and each line, and opens the Orchestrator’s window', () => {
  const data: ChecksData = { runId: 'r', leadId: 'agent:r', running: { command: 'python -m pytest -q', since: null }, lines: [{ state: 'failed', text: 'pytest · 12 ✓ · 2 ✗' }], rounds: 0, recipe: true }
  const props = { id: 'checks:r', data, selected: false, type: 'checks', dragging: false, zIndex: 0, isConnectable: false, positionAbsoluteX: 0, positionAbsoluteY: 0, draggable: false, selectable: false, deletable: false }
  render(
    <ReactFlowProvider>
      <ChecksNode {...(props as Parameters<typeof ChecksNode>[0])} />
    </ReactFlowProvider>,
  )
  expect(screen.getByText('● pytest')).toBeInTheDocument()
  expect(screen.getByText('✗ pytest · 12 ✓ · 2 ✗')).toHaveAttribute('data-state', 'failed')
  expect(screen.getByText('KOLONİ · end of the recipe')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Open the Orchestrator\'s window' })).toBeInTheDocument()
})
