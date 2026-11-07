import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import type { ChannelMessage, Message } from '../api/types'
import { deriveGraph } from '../canvas/deriveGraph'
import { ChannelPanel } from '../chat/ChannelPanel'
import { RunStatus } from '../shell/RunStatus'
import { agent, assistantMessage, convState, run, userMessage } from '../test-fixtures'

const sub = (id: string, role: string, status: 'running' | 'queued' | 'completed') =>
  agent('r', status, { id, parent_agent_id: 'lead', tool_call_id: id, role_name: role, name: role, task: 'x', depth: 1 })

const note = (id: string, to: string, content: string, delivered: string | null): [ChannelMessage, Message] => [
  { id: `c${id}`, run_id: 'r', from_agent_id: 'b', to_agent_id: to, kind: 'note', content, created_at: '2026-10-05T10:00:00Z' },
  { ...assistantMessage(`m${id}`, 'r', content), role: 'agent', agent_id: to, from_agent_id: 'b', delivered_at: delivered },
]

const [readNote, readMessage] = note('1', 'a', 'use tabs', '2026-10-05T10:01:00Z')
const [lostNote, lostMessage] = note('2', 'c', 'too late', null)

const state = convState({
  runs: [run('r', 'running')],
  agents: [agent('r', 'waiting', { id: 'lead' }), sub('a', 'Coder', 'running'), sub('b', 'Tester', 'running'), sub('c', 'Reviewer', 'queued')],
  messages: [userMessage('r', 'do it'), readMessage, lostMessage],
  channelMessages: [readNote, lostNote],
})

test('the top bar says how many agents are at work', () => {
  render(<RunStatus conv={state} connection="open" />)
  expect(screen.getByText(/WORKING · 2 agents/)).toBeInTheDocument()
})

test('an agent waiting for a place says so', () => {
  const node = deriveGraph(state).nodes.find(n => n.id === 'agent:c')
  expect(node?.data).toMatchObject({ status: 'queued', activity: 'Waiting for a slot' })
})

test('a lead in line with no provider to name says it waits for a slot, not a bare status', () => {
  const lead = { ...state, agents: state.agents.map(a => (a.id === 'lead' ? { ...a, status: 'queued' as const } : a)) }
  expect(deriveGraph(lead).nodes.find(n => n.id === 'agent:lead')?.data).toMatchObject({ activity: 'Waiting for a slot' })
})

test('an agent in line for a full provider says which, and how full', () => {
  const full = { ...state, agents: state.agents.map(a => (a.id === 'c' ? { ...a, queued_on: { provider: 'Codex', at_work: 2, most: 2 } } : a)) }
  const node = deriveGraph(full).nodes.find(n => n.id === 'agent:c')
  expect(node?.data).toMatchObject({ status: 'queued', activity: 'queued · Codex full (2/2)' })
})

test('the channel says whether a note has reached its agent', () => {
  render(<ChannelPanel state={state} />)
  expect(screen.getByText('Tester → Coder · note · delivered')).toBeInTheDocument()
  expect(screen.getByText('Tester → Reviewer · note · not delivered')).toBeInTheDocument()
})
