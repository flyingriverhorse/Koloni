import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import type { ChannelMessage, Message } from '../api/types'
import { deriveGraph } from '../canvas/deriveGraph'
import { ChannelPanel } from '../chat/ChannelPanel'
import { MessageList } from '../chat/MessageList'
import { toolSummary } from '../chat/toolSummary'
import { agent, assistantMessage, convState, openAgentFold, run, toolCall, userMessage } from '../test-fixtures'
import { AgentWindow } from './AgentWindow'

const channel = (id: string, from: string, to: string, kind: ChannelMessage['kind'], content: string): ChannelMessage => ({
  id,
  run_id: 'r',
  from_agent_id: from,
  to_agent_id: to,
  kind,
  content,
  created_at: '2026-10-05T10:00:00Z',
})

const sent = (id: string, from: string, to: string, content: string): Message => ({
  ...assistantMessage(id, 'r', content),
  role: 'agent',
  agent_id: to,
  from_agent_id: from,
})

// The Lead opened two Reviewers; it carried on with the second, and the first asked the Lead.
const state = convState({
  runs: [run('r', 'running')],
  agents: [
    agent('r', 'running', { id: 'lead' }),
    agent('r', 'completed', { id: 'one', parent_agent_id: 'lead', tool_call_id: '1', role_name: 'Reviewer', name: 'Reviewer', task: 'Look', depth: 1 }),
    agent('r', 'completed', { id: 'two', parent_agent_id: 'lead', tool_call_id: '2', role_name: 'Reviewer', name: 'Reviewer 2', task: 'Look again', depth: 1 }),
  ],
  messages: [
    userMessage('r', 'review it'),
    { ...assistantMessage('m1', 'r', ''), agent_id: 'lead' },
    { ...assistantMessage('k1', 'r', ''), agent_id: 'one' },
    sent('in1', 'one', 'lead', 'Which file?'),
    { ...assistantMessage('m2', 'r', 'hello.py'), agent_id: 'lead' },
    sent('in2', 'lead', 'two', 'And the tests?'),
    { ...assistantMessage('k2', 'r', 'There are none.'), agent_id: 'two' },
  ],
  toolCalls: [
    toolCall('1', 'r', 'spawn_agent', 'succeeded', '{"role":"Reviewer"}', { agent_id: 'lead', message_id: 'm1' }),
    toolCall('2', 'r', 'spawn_agent', 'succeeded', '{"role":"Reviewer"}', { agent_id: 'lead', message_id: 'm1' }),
    toolCall('3', 'r', 'message_agent', 'succeeded', '{"to":"Lead","message":"Which file?"}', {
      agent_id: 'one', message_id: 'k1', result: 'Lead replied:\n\nhello.py',
    }),
    toolCall('4', 'r', 'message_agent', 'succeeded', '{"to":"Reviewer 2","message":"And the tests?"}', {
      agent_id: 'lead', message_id: 'm1', result: 'Reviewer 2 replied:\n\nThere are none.',
    }),
  ],
  channelMessages: [
    channel('c1', 'one', 'lead', 'message', 'Which file?'),
    channel('c2', 'lead', 'one', 'reply', 'hello.py'),
    channel('c3', 'lead', 'two', 'message', 'And the tests?'),
    channel('c4', 'two', 'lead', 'reply', 'There are none.'),
  ],
})

const handlers = {
  onRemoveQueued: () => {},
  onOpenChange: () => {},
  onDecide: async () => {},
  onDecideCommand: async () => {},
}

test('a message to another agent reads as who it is for', () => {
  expect(toolSummary({ name: 'message_agent', arguments: '{"to":"Reviewer 2","message":"hi"}' })).toBe(
    'message_agent Reviewer 2',
  )
})

test('the channel names agents by their own names, and shows messages and replies', () => {
  render(<ChannelPanel state={state} />)
  expect(screen.getByText('Reviewer → Orchestrator · message')).toBeInTheDocument()
  expect(screen.getByText('Orchestrator → Reviewer 2 · message')).toBeInTheDocument()
  expect(screen.getByText('Reviewer 2 → Orchestrator · reply')).toBeInTheDocument()
})

test('the canvas names agents and marks who talked with whom', () => {
  const { nodes, edges } = deriveGraph(state)
  const names = nodes.filter(n => n.kind === 'agent').map(n => (n.data as { name: string }).name)
  expect(names).toEqual(['Orchestrator', 'Reviewer', 'Reviewer 2'])
  // A message between an agent and the one that opened it, and its reply, are counted on the line they share.
  expect(edges.find(e => e.id === 'agent:lead>agent:one')).toMatchObject({ spawn: true, messages: 2, last: 'hello.py' })
  expect(edges.find(e => e.id === 'agent:lead>agent:two')).toMatchObject({ spawn: true, messages: 2 })
  // A message is not a tool like the others: it is not counted among an agent's tools.
  expect(nodes.flatMap(n => (n.data as { summary?: string }).summary || [])).toEqual([])
  // Only a request from the user starts a row.
  expect(nodes.filter(n => n.kind === 'request')).toHaveLength(1)
})

test('agents that are not parent and child get a line of their own when they talk', () => {
  const siblings = {
    ...state,
    channelMessages: [channel('c9', 'two', 'one', 'message', 'What did you find?')],
  }
  const talk = deriveGraph(siblings).edges.find(e => e.talk)
  expect(talk).toMatchObject({ source: 'agent:two', target: 'agent:one', messages: 1 })
})

test('an agent waiting for a reply says whose', () => {
  const waiting = {
    ...state,
    agents: state.agents.map(a => (a.id === 'lead' ? { ...a, status: 'waiting' as const } : a)),
    toolCalls: state.toolCalls.map(t => (t.id === '4' ? { ...t, status: 'running' as const } : t)),
  }
  const lead = deriveGraph(waiting).nodes.find(n => n.id === 'agent:lead')
  expect((lead?.data as { activity: string }).activity).toBe('Waiting for Reviewer 2')
})

test('the chat shows a message from a sub-agent as its own, and the Lead’s messages as one row', async () => {
  const { container } = render(<MessageList {...handlers} state={state} />)
  // What the Reviewer asked the Lead is not something the user said.
  expect(container.querySelectorAll('.msg-user')).toHaveLength(1)
  expect(screen.getByText('from Reviewer')).toBeInTheDocument()
  expect(screen.getByText('Which file?')).toBeInTheDocument()
  // What was sent to a sub-agent belongs to that agent's conversation, not to the chat.
  expect(screen.queryByText('from Orchestrator')).not.toBeInTheDocument()

  const row = screen.getByRole('button', { name: /Orchestrator → Reviewer 2/ })
  expect(row).toHaveTextContent('done')
  await userEvent.click(row)
  expect(screen.getAllByText('And the tests?')).toHaveLength(2)  // the row's head, and in full
  expect(screen.getByText('There are none.')).toBeInTheDocument()
})

test('an agent’s window shows what it was sent and by whom', async () => {
  render(<AgentWindow state={state} agentId="two" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(screen.getByText('Reviewer 2')).toBeInTheDocument()
  await openAgentFold('Every step as recorded')
  expect(screen.getByText('from Orchestrator')).toBeInTheDocument()
  const text = document.body.textContent ?? ''
  expect(text.indexOf('And the tests?')).toBeLessThan(text.indexOf('There are none.'))
})

test('a message from nobody is KOLONİ’s own word - the user’s said while it works among them (89d C) - in its window and the chat', async () => {
  const told = { ...sent('t1', 'x', 'two', 'The user tells you while you work - their own word: "use blue"'), from_agent_id: null }
  const toLead = { ...sent('t2', 'x', 'lead', 'KOLONİ: Reviewer finished its turn before it read your message'), from_agent_id: null }
  const said = convState({ ...state, messages: [...state.messages, told, toLead] })
  const { unmount } = render(<AgentWindow state={said} agentId="two" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  await openAgentFold('Every step as recorded')
  expect(screen.getByText('from Orchestrator')).toBeInTheDocument()
  expect(screen.getByText('from KOLONİ')).toBeInTheDocument()
  expect(screen.queryByText('from Agent')).toBeNull()
  unmount()
  render(<MessageList {...handlers} state={said} />)
  expect(screen.getByText('from KOLONİ')).toBeInTheDocument()
  expect(screen.getByText('from Reviewer')).toBeInTheDocument()
})
