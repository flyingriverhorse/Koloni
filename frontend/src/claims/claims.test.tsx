import { render, screen, within } from '@testing-library/react'
import { type Node, type NodeProps, ReactFlowProvider } from '@xyflow/react'
import type { ReactNode } from 'react'
import { expect, test, vi } from 'vitest'
import { AgentWindow } from '../agents/AgentWindow'
import type { Snapshot } from '../api/types'
import { type AgentData, deriveGraph } from '../canvas/deriveGraph'
import { AgentNode } from '../canvas/nodes'
import { turnRows } from '../canvas/turns'
import { MessageList } from '../chat/MessageList'
import { Inspector } from '../inspector/Inspector'
import { RunStatus } from '../shell/RunStatus'
import { applyEvent, fromSnapshot } from '../state/applyEvent'
import { agent, assistantMessage, convState, fileChange, run, toolCall, userMessage } from '../test-fixtures'
import { callWaits, heldBy, holderOf, waitLine } from './claims'

const waitingFor = { agent_id: 'coder', agent_name: 'Coder', path: 'cart.py' }

/**
 * A lead that opened two Coders. The first changed cart.py and holds it; the second wants
 * the same file and waits: its write call has not returned.
 */
const state = convState({
  runs: [run('r', 'running')],
  agents: [
    agent('r', 'waiting', { id: 'lead' }),
    agent('r', 'running', { id: 'coder', parent_agent_id: 'lead', role_name: 'Coder', depth: 1, task: 'A' }),
    agent('r', 'blocked', { id: 'coder2', parent_agent_id: 'lead', role_name: 'Coder', name: 'Coder 2', depth: 1, task: 'B', waiting_for: waitingFor }),
  ],
  messages: [
    userMessage('r', 'go'),
    { ...assistantMessage('m1', 'r', ''), agent_id: 'coder' },
    { ...assistantMessage('m2', 'r', ''), agent_id: 'coder2' },
  ],
  toolCalls: [
    toolCall('1', 'r', 'write_file', 'succeeded', '{"path":"cart.py","content":"one"}', { agent_id: 'coder', message_id: 'm1' }),
    toolCall('2', 'r', 'write_file', 'running', '{"path":"./cart.py","content":"two"}', { agent_id: 'coder2', message_id: 'm2' }),
  ],
  fileChanges: [fileChange('f1', 'r', { agent_id: 'coder', tool_call_id: '1', path: 'cart.py' })],
  claims: [{ path: 'cart.py', agent_id: 'coder' }],
})

const agentData = (g: ReturnType<typeof deriveGraph>, id: string) => g.nodes.find(n => n.id === id)!.data as AgentData

// --- what the records say ------------------------------------------------------------------

test('an agent that waits for a file says for whom and which file; one that does not says nothing', () => {
  expect(waitLine(state.agents[2])).toBe('waits for Coder · cart.py')
  expect(waitLine(state.agents[1])).toBeNull()
  // what it waited for is only said while it waits
  expect(waitLine({ status: 'running', waiting_for: waitingFor })).toBeNull()
})

test('the files an agent holds, and who holds a file - in any case, and also an agent of another conversation', () => {
  expect(heldBy(state, 'coder')).toEqual(['cart.py'])
  expect(heldBy(state, 'coder2')).toEqual([])
  expect(holderOf(state, 'cart.py')).toBe('Coder')
  expect(holderOf(state, 'CART.PY')).toBe('Coder')
  expect(holderOf(state, 'other.py')).toBeNull()
  expect(holderOf({ ...state, claims: [{ path: 'cart.py', agent_id: 'not-here' }] }, 'cart.py')).toBe('an agent of another conversation')
})

test('only the write call of the agent that waits reads as waiting', () => {
  expect(callWaits(state, state.toolCalls[1])).toBe('waiting for Coder to finish with cart.py')
  expect(callWaits(state, state.toolCalls[0])).toBeNull() // returned
  // a running call of an agent that does not wait, and a call of the waiting agent that is no write
  expect(callWaits(state, toolCall('3', 'r', 'write_file', 'running', '{"path":"a.py"}', { agent_id: 'coder' }))).toBeNull()
  expect(callWaits(state, toolCall('4', 'r', 'read_file', 'running', '{"path":"cart.py"}', { agent_id: 'coder2' }))).toBeNull()
})

test('B-140: a file another chat holds names that chat, and says when your answer there frees it', () => {
  const elsewhere = { ...waitingFor, agent_name: 'Lead', path: 'calc.py', conversation_id: 'other', conversation_title: 'median', asks_you: true }
  const there = { ...state, agents: state.agents.map(a => (a.id === 'coder2' ? { ...a, waiting_for: elsewhere } : a)) }
  expect(callWaits(there, there.toolCalls[1])).toBe('waiting for Lead in «median» to finish with calc.py: that chat waits for your answer there')
  expect(waitLine(there.agents[2], there.conversation.id)).toBe('waits for Lead in «median» · calc.py')
})

test('who holds what comes with the snapshot, and again whenever it changes - with an id or without', () => {
  const snapshot = { claims: [{ path: 'cart.py', agent_id: 'coder' }], last_event_id: 4 } as Snapshot
  let s = fromSnapshot(snapshot)
  expect(s.claims).toEqual([{ path: 'cart.py', agent_id: 'coder' }])
  s = applyEvent(s, null, 'claims.changed', { claims: [{ path: 'cart.py', agent_id: 'coder2' }] })
  expect(s.claims).toEqual([{ path: 'cart.py', agent_id: 'coder2' }])
  s = applyEvent(s, 5, 'claims.changed', { claims: [] })
  expect(s.claims).toEqual([])
  // a server from before files were held sends none, not nothing
  expect(fromSnapshot({ last_event_id: 0 } as Snapshot).claims).toEqual([])
})

// --- the canvas ----------------------------------------------------------------------------

test('the waiting agent’s box says what it waits for, and a line joins it to the agent that holds the file', () => {
  const g = deriveGraph(state)
  expect(agentData(g, 'agent:coder2')).toMatchObject({ status: 'blocked', activity: 'waits for Coder · cart.py', attention: false, finished: false })
  expect(g.edges.find(e => e.waits)).toMatchObject({ source: 'agent:coder2', target: 'agent:coder', waits: true, active: false })
  // its own line from the agent that opened it is still that of an agent at work
  expect(g.edges.find(e => e.id === 'agent:lead>agent:coder2')).toMatchObject({ spawn: true, active: true })
  // when it has the file there is no such line any more
  const after = deriveGraph({ ...state, agents: state.agents.map(a => (a.id === 'coder2' ? { ...a, status: 'running' as const, waiting_for: null } : a)) })
  expect(after.edges.some(e => e.waits)).toBe(false)
  expect(agentData(after, 'agent:coder2').activity).not.toMatch(/waits for/)
})

test('a holder that is not on this canvas gets no line; the box still names it', () => {
  const elsewhere = { agent_id: 'far', agent_name: 'Tester', path: 'cart.py' }
  const g = deriveGraph({ ...state, agents: state.agents.map(a => (a.id === 'coder2' ? { ...a, waiting_for: elsewhere } : a)) })
  expect(g.edges.some(e => e.waits)).toBe(false)
  expect(agentData(g, 'agent:coder2').activity).toBe('waits for Tester · cart.py')
})

test('a lead that waits for a file says so too, and is not shown as at work', () => {
  const g = deriveGraph(convState({
    runs: [run('r', 'running')],
    messages: [userMessage('r', 'go')],
    agents: [agent('r', 'blocked', { waiting_for: { agent_id: 'far', agent_name: 'Coder', path: 'cart.py' } })],
  }))
  expect(agentData(g, 'agent:r')).toMatchObject({ status: 'blocked', activity: 'waits for Coder · cart.py' })
})

function draw(node: ReactNode) {
  return render(
    <ReactFlowProvider>
      {node}
    </ReactFlowProvider>,
  )
}
const props = <T,>(id: string, data: T) =>
  ({ id, data, selected: false }) as unknown as NodeProps<Node<T & Record<string, unknown>>>

test('the node says it: the agent that waits for a file', () => {
  const g = deriveGraph(state)
  draw(<AgentNode {...props('agent:coder2', agentData(g, 'agent:coder2'))} />)
  expect(screen.getByText('waits for Coder · cart.py')).toBeInTheDocument()
  // it waits for an agent, not for the user: the box is not drawn as one that asks
  expect(document.querySelector('.node')).not.toHaveClass('node-approval', 'group-attention')
  expect(document.body).not.toHaveTextContent(/waits for you|waiting for you/i)
})

// --- the inspector, the agent's window, the chat -------------------------------------------

test('the inspector lists what an agent holds, and for the one that waits what it waits for', () => {
  const { rerender } = render(<Inspector state={state} selectedId="agent:coder" onClose={() => {}} />)
  expect(within(screen.getByRole('list', { name: 'Files it holds' })).getByText('cart.py')).toBeInTheDocument()
  expect(screen.queryByText(/Waits for/)).not.toBeInTheDocument()
  rerender(<Inspector state={state} selectedId="agent:coder2" onClose={() => {}} />)
  expect(screen.getByRole('note')).toHaveTextContent('Waits for Coder to finish with cart.py')
  expect(screen.getByRole('note')).toHaveTextContent('It goes on when Coder is done with the file.')
  // the agent it waits for may itself be waiting for the user's decision: nothing is said of that
  expect(screen.getByRole('note')).not.toHaveTextContent(/asked of you|by itself/)
  expect(screen.queryByRole('list', { name: 'Files it holds' })).not.toBeInTheDocument()
  // its state is in its header, as in its window
  expect(within(screen.getByRole('complementary', { name: 'Inspector' })).getByText('waiting for a file')).toHaveClass('status')
  // an agent that holds nothing and waits for nothing has no such part
  rerender(<Inspector state={state} selectedId="agent:lead" onClose={() => {}} />)
  expect(screen.queryByText('Holds')).not.toBeInTheDocument()
  expect(screen.queryByText(/Waits for/)).not.toBeInTheDocument()
})

test('the agent’s window says the same, and its write call reads as waiting', () => {
  const handlers = { onClose: () => {}, onOpenChange: () => {}, onSelectAgent: () => {} }
  const { rerender } = render(<AgentWindow state={state} agentId="coder2" {...handlers} />)
  expect(screen.getByRole('note')).toHaveTextContent('Waits for Coder to finish with cart.py')
  expect(screen.getByText('waiting for a file')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /write_file: waiting for Coder to finish with cart\.py/ })).toBeInTheDocument()
  rerender(<AgentWindow state={state} agentId="coder" {...handlers} />)
  expect(within(screen.getByRole('list', { name: 'Files it holds' })).getByText('cart.py')).toBeInTheDocument()
})

test('in the chat a write call that waits for a file says for whom, and is not "running"', () => {
  const lead = convState({
    runs: [run('r', 'running')],
    agents: [agent('r', 'blocked', { waiting_for: { agent_id: 'far', agent_name: 'Coder', path: 'cart.py' } })],
    messages: [userMessage('r', 'go'), assistantMessage('m1', 'r', '')],
    toolCalls: [toolCall('1', 'r', 'edit_file', 'running', '{"path":"cart.py"}', { message_id: 'm1' })],
  })
  const handlers = { onRemoveQueued: vi.fn(), onOpenChange: vi.fn(), onDecide: vi.fn(), onDecideCommand: vi.fn() }
  const { rerender } = render(<MessageList {...handlers} state={lead} />)
  const row = screen.getByRole('button', { name: /edit_file: waiting for Coder to finish with cart\.py/ })
  expect(row).toHaveTextContent('waiting')
  expect(row).not.toHaveTextContent('running')
  // once the file is its own the call is an ordinary running call again
  rerender(<MessageList {...handlers} state={{ ...lead, agents: [agent('r', 'running')] }} />)
  expect(screen.getByRole('button', { name: /edit_file cart\.py/ })).toHaveTextContent('running')
})

// --- waiting for a file asks nothing of the user ---------------------------------------------

test('a turn in which an agent waits for a file is not marked as waiting for the user: Recent, top bar', () => {
  const rows = turnRows(state)
  expect(rows[0]).toMatchObject({ ended: 'working', waits: false })
  render(<RunStatus conv={state} connection="open" />)
  expect(screen.getByText(/WORKING/)).toBeInTheDocument()
  expect(screen.queryByText(/WAITS FOR YOU/)).not.toBeInTheDocument()
  // and the group of the agent that waits does not ask for attention
  expect(deriveGraph(state).nodes.filter(n => n.kind === 'agent').every(n => !(n.data as AgentData).attention)).toBe(true)
})
