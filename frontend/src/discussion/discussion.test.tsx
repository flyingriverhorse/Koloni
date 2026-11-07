import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { AgentWindow } from '../agents/AgentWindow'
import type { Discussion, DiscussionPost } from '../api/types'
import { deriveGraph } from '../canvas/deriveGraph'
import { MessageList } from '../chat/MessageList'
import { applyEvent } from '../state/applyEvent'
import { agent, assistantMessage, convState, openAgentFold, run, toolCall, userMessage } from '../test-fixtures'
import { DiscussionWindow } from './DiscussionWindow'

const talk = (over: Partial<Discussion> = {}): Discussion => ({
  id: 'd',
  run_id: 'r',
  agent_id: 'lead',
  tool_call_id: '9',
  topic: 'Ship it?',
  max_rounds: 3,
  round: 2,
  status: 'running',
  outcome: null,
  created_at: '2026-10-05T10:00:00Z',
  ended_at: null,
  members: [
    { agent_id: 'coder', status: 'in', opened_here: false },
    { agent_id: 'rev', status: 'in', opened_here: true },
    { agent_id: 'lead', status: 'in', opened_here: false },
  ],
  ...over,
})

const post = (id: string, agentId: string | null, round: number, content: string, over: Partial<DiscussionPost> = {}): DiscussionPost => ({
  id,
  discussion_id: 'd',
  agent_id: agentId,
  round,
  kind: 'said',
  content,
  passed: false,
  created_at: '2026-10-05T10:00:00Z',
  ...over,
})

const sub = (id: string, name: string, status: 'running' | 'completed' | 'waiting') =>
  agent('r', status, { id, parent_agent_id: 'lead', tool_call_id: id === 'coder' ? '1' : null, role_name: name, name, task: 'x', depth: 1 })

const state = convState({
  runs: [run('r', 'running')],
  agents: [agent('r', 'waiting', { id: 'lead' }), sub('coder', 'Coder', 'completed'), sub('rev', 'Reviewer', 'running')],
  messages: [
    userMessage('r', 'decide'),
    { ...assistantMessage('m1', 'r', ''), agent_id: 'lead' },
    { ...assistantMessage('s1', 'r', 'Yes, ship it.'), agent_id: 'lead', discussion_id: 'd' },
    { ...assistantMessage('s2', 'r', 'Tests first.'), agent_id: 'coder', discussion_id: 'd' },
  ],
  toolCalls: [
    toolCall('1', 'r', 'spawn_agent', 'succeeded', '{"role":"Coder"}', { agent_id: 'lead', message_id: 'm1' }),
    toolCall('9', 'r', 'discuss', 'running', '{"topic":"Ship it?","with":["Coder","Reviewer"]}', { agent_id: 'lead', message_id: 'm1' }),
  ],
  discussions: [talk()],
  discussionPosts: [
    post('p1', 'coder', 1, 'Tests first.'),
    post('p2', 'rev', 1, 'PASS', { passed: true }),
    post('p3', 'lead', 1, 'Yes, ship it.'),
    post('p4', null, 2, 'Add a changelog.'),
  ],
})

const handlers = {
  onRemoveQueued: () => {},
  onOpenChange: () => {},
  onDecide: async () => {},
  onDecideCommand: async () => {},
}

test('discussions and what is said in them arrive as events', () => {
  let next = applyEvent(convState(), 1, 'discussion.created', talk({ round: 0 }))
  next = applyEvent(next, 2, 'discussion_post.created', post('p1', 'coder', 1, 'Tests first.'))
  next = applyEvent(next, 3, 'discussion.updated', talk({ status: 'ended', outcome: 'agreed' }))
  expect(next.discussions).toHaveLength(1)
  expect(next.discussions[0].outcome).toBe('agreed')
  expect(next.discussionPosts.map(p => p.content)).toEqual(['Tests first.'])
})

test('the canvas has the shared place as a node, joined to everyone in it', () => {
  const { nodes, edges } = deriveGraph(state)
  const node = nodes.find(n => n.kind === 'discussion')
  expect(node).toMatchObject({ id: 'discussion:d', refId: 'd', agentId: 'lead' })
  expect(node?.data).toMatchObject({
    topic: 'Ship it?',
    line: 'Round 2 of 3',
    members: ['Coder', 'Reviewer', 'Lead'],
    speaking: 'Reviewer',
    running: true,
  })
  expect((node?.data as { last: { who: string; text: string }[] }).last).toEqual([
    { who: 'Lead', text: 'Yes, ship it.' },
    { who: 'You', text: 'Add a changelog.' },
  ])
  const joined = edges.filter(e => e.target === 'discussion:d')
  expect(joined.map(e => e.source).sort()).toEqual(['agent:coder', 'agent:lead', 'agent:rev'])
  expect(joined.find(e => e.source === 'agent:rev')?.active).toBe(true)  // the one speaking
  expect(joined.find(e => e.source === 'agent:coder')?.active).toBe(false)
  // the call that opened it is drawn as the discussion, not counted as a tool
  expect(nodes.flatMap(n => (n.data as { summary?: string }).summary || [])).toEqual([])
})

test('an ended discussion says how it ended', () => {
  const ended = { ...state, discussions: [talk({ status: 'ended', outcome: 'agreed' })] }
  const node = deriveGraph(ended).nodes.find(n => n.kind === 'discussion')
  expect(node?.data).toMatchObject({ line: 'Ended: nothing left to say', running: false, speaking: null })
})

test('a discussion that ended at its budget says so on its node, in its window and in the chat', () => {
  const spent = { ...state, discussions: [talk({ status: 'ended', outcome: 'budget' })] }
  expect(deriveGraph(spent).nodes.find(n => n.kind === 'discussion')?.data).toMatchObject({ line: 'Ended: at its budget' })
  render(<DiscussionWindow state={spent} discussionId="d" onClose={() => {}} onSay={async () => {}} onEnd={async () => {}} />)
  expect(screen.getByText('Ended: at its budget')).toBeInTheDocument()
  render(<MessageList {...handlers} state={spent} onOpenDiscussion={() => {}} />)
  expect(screen.getByRole('button', { name: /Discussion.*Ship it\?/ })).toHaveTextContent('3 agents · ended: at its budget')
})

test('the chat shows the discussion as one row and not what the lead said in it', async () => {
  const onOpenDiscussion = vi.fn()
  render(<MessageList {...handlers} state={state} onOpenDiscussion={onOpenDiscussion} />)
  expect(screen.queryByText('Yes, ship it.')).not.toBeInTheDocument()
  const row = screen.getByRole('button', { name: /Discussion.*Ship it\?/ })
  expect(row).toHaveTextContent('3 agents')
  expect(row).toHaveTextContent('round 2 of 3')
  await userEvent.click(row)
  expect(onOpenDiscussion).toHaveBeenCalledWith('d')
})

test('an agent’s own window leaves out what it said in the shared place', () => {
  render(<AgentWindow state={state} agentId="coder" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(screen.queryByText('Tests first.')).not.toBeInTheDocument()
})

test('the discussion window shows everything said, and the user can speak and end it', async () => {
  const onSay = vi.fn(async () => {})
  const onEnd = vi.fn(async () => {})
  render(<DiscussionWindow state={state} discussionId="d" onClose={() => {}} onSay={onSay} onEnd={onEnd} />)
  const region = screen.getByRole('region', { name: 'Discussion' })
  const text = region.textContent ?? ''
  const order = ['Ship it?', 'Coder · Reviewer · Lead', 'Round 1', 'Tests first.', 'Reviewer has nothing to add', 'Yes, ship it.', 'You', 'Add a changelog.']
  expect(screen.getByText('Round 2')).toBeInTheDocument()  // the divider; the header says "Round 2 of 3"
  expect(order.map(piece => text.indexOf(piece)).every((at, i, all) => at >= 0 && (i === 0 || at >= all[i - 1]))).toBe(true)
  expect(screen.getByText('Reviewer is speaking…')).toBeInTheDocument()

  await userEvent.type(screen.getByLabelText('Say something to everyone'), 'What about docs?')
  await userEvent.click(screen.getByRole('button', { name: 'Say' }))
  expect(onSay).toHaveBeenCalledWith('d', 'What about docs?')
  expect(screen.getByLabelText('Say something to everyone')).toHaveValue('')
  await userEvent.click(screen.getByRole('button', { name: 'End discussion' }))
  expect(onEnd).toHaveBeenCalledWith('d')
})

test('a discussion that is over can only be read', () => {
  const over = {
    ...state,
    discussions: [talk({ status: 'ended', outcome: 'round_limit', members: [
      { agent_id: 'coder', status: 'left', opened_here: false },
      { agent_id: 'lead', status: 'in', opened_here: false },
    ] })],
    discussionPosts: [post('p1', 'coder', 1, 'model server unreachable', { kind: 'left' })],
  }
  render(<DiscussionWindow state={over} discussionId="d" onClose={() => {}} onSay={async () => {}} onEnd={async () => {}} />)
  expect(screen.getByText('Ended: the round limit was reached')).toBeInTheDocument()
  expect(screen.getByText(/Coder left the discussion: model server unreachable/)).toBeInTheDocument()
  expect(screen.queryByLabelText('Say something to everyone')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'End discussion' })).not.toBeInTheDocument()
})

test('the raw steps of an agent leave out what it said in a discussion', async () => {
  const own = { ...state, messages: [...state.messages, { ...assistantMessage('o1', 'r', 'My own report.'), agent_id: 'coder' }] }
  render(<AgentWindow state={own} agentId="coder" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  const steps = await openAgentFold('Every step as recorded')
  expect(within(steps).getByText('My own report.')).toBeInTheDocument()
  expect(screen.queryByText('Tests first.')).not.toBeInTheDocument()
})
