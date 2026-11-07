import { expect, test } from 'vitest'
import type { Conversation, Message, Run, Snapshot } from '../api/types'
import { agent, command } from '../test-fixtures'
import { activeRun, applyEvent, fromSnapshot, type ConvState } from './applyEvent'

const conversation: Conversation = {
  id: 'c',
  project_id: 'p',
  title: 'New conversation',
  permission_mode: 'ask',
  spawn_approval: 'auto',
  spawn_max_depth: 2,
  spawn_max_agents: 6,
  spawn_max_parallel: 2,
  discussion_budget: 200000,
  provider_id: null,
  model_id: null,
  lead_auto: false,
  plan_first: false,
  page_scripts: false,
  lead_work: 'delegates',
  lead_hands_code: true,
  when_away: 'waits',
  away_minutes: 10,
  lead_effort: null,
  room_posts: 40,
  room_tokens: 400000,
  room_minutes: 30,
  also_in: [], read_in: [], part: null,
  created_at: 't',
  updated_at: 't',
  teams_mode: 'none',
  teams: [],
  archived_at: null,
}
const run: Run = {
  id: 'r',
  conversation_id: 'c',
  status: 'running',
  error: null,
  model_id: null,
  input_tokens: null,
  output_tokens: null,
  created_at: 't',
  started_at: 't',
  ended_at: null,
  unattended: false,
  trigger_id: null,
  trigger_name: null,
  topic_id: null,
  plan_turn: false,
  plan: null,
  compare_id: null,
}
const msg: Message = {
  id: 'm',
  conversation_id: 'c',
  run_id: 'r',
  agent_id: 'a',
  role: 'assistant',
  from_agent_id: null,
  delivered_at: null,
  discussion_id: null,
  board_post_id: null,
  room_post_id: null,
  content: '',
  status: 'streaming',
  created_at: 't',
}
const snapshot: Snapshot = {
  conversation,
  messages: [],
  runs: [],
  topics: [],
  tool_calls: [],
  file_changes: [],
  commands: [],
  allowed_commands: [],
  web_requests: [],
  allowed_web: [],
  agents: [],
  channel_messages: [],
  pending_roles: [],
  pending_skills: [],
  questions: [],
  discussions: [],
  discussion_posts: [],
  rooms: [],
  room_items: [],
  room_posts: [],
  board_posts: [],
  claims: [],
  merges: [],
  attachments: [],
  away: [],
  trigger_proposals: [],
  notes_offers: [],
  warnings: [],
  last_event_id: 0,
}
const base = (): ConvState => fromSnapshot(snapshot)

test('records are upserted by id and the cursor advances', () => {
  let s = applyEvent(base(), 1, 'run.started', run)
  s = applyEvent(s, 2, 'run.updated', { ...run, model_id: 'q' })
  expect(s.runs).toHaveLength(1)
  expect(s.runs[0].model_id).toBe('q')
  expect(s.lastEventId).toBe(2)
})

test('an event at or below the cursor is ignored', () => {
  let s = applyEvent(base(), 5, 'run.started', run)
  s = applyEvent(s, 5, 'run.finished', { ...run, status: 'failed' })
  expect(s.runs[0].status).toBe('running')
})

test('deltas append to the streaming message; completion replaces the text', () => {
  let s = applyEvent(base(), 1, 'message.created', msg)
  s = applyEvent(s, null, 'message.delta', { message_id: 'm', text: 'He' })
  s = applyEvent(s, null, 'message.delta', { message_id: 'm', text: 'llo' })
  expect(s.messages[0].content).toBe('Hello')
  s = applyEvent(s, 2, 'message.completed', { ...msg, content: 'Hello!', status: 'complete' })
  expect(s.messages[0]).toMatchObject({ content: 'Hello!', status: 'complete' })
})

test('a delta for an unknown or finished message is dropped', () => {
  let s = applyEvent(base(), null, 'message.delta', { message_id: 'zz', text: 'x' })
  expect(s.messages).toEqual([])
  s = applyEvent(s, 1, 'message.created', { ...msg, content: 'done', status: 'complete' })
  s = applyEvent(s, null, 'message.delta', { message_id: 'm', text: ' late' })
  expect(s.messages[0].content).toBe('done')
})

test('message.sync replaces the text of a streaming message after a reconnect', () => {
  let s = applyEvent(base(), 1, 'message.created', { ...msg, content: 'Hel' })
  s = applyEvent(s, null, 'message.sync', { message_id: 'm', content: 'Hello wor' })
  s = applyEvent(s, null, 'message.delta', { message_id: 'm', text: 'ld' })
  expect(s.messages[0].content).toBe('Hello world')
})

test('89j: agent.live keeps the latest its CLI said, whole, and nothing once it has ended', () => {
  const context = { used: 34000, window: 100000 }
  let s = applyEvent(base(), null, 'agent.live', { agent_id: 'a', context: { used: 1, window: 100000 }, plan: null, queue: null })
  s = applyEvent(s, null, 'agent.live', { agent_id: 'a', context, plan: [{ step: 'Fix', status: 'inProgress' }], queue: null })
  expect(s.live).toEqual({ a: { context, plan: [{ step: 'Fix', status: 'inProgress' }], queue: null } })
  expect(s.lastEventId).toBe(base().lastEventId) // (on no record)
  s = applyEvent(s, null, 'agent.live', { agent_id: 'a', context: null, plan: null, queue: null })
  expect(s.live).toEqual({})
})

test('thinking is set by run.thinking and cleared by the next delta or finish', () => {
  let s = applyEvent(base(), 1, 'run.started', run)
  s = applyEvent(s, null, 'run.thinking', { run_id: 'r' })
  expect(s.thinkingRunId).toBe('r')
  s = applyEvent(s, 2, 'message.created', msg)
  s = applyEvent(s, null, 'message.delta', { message_id: 'm', text: 'a' })
  expect(s.thinkingRunId).toBeNull()
  s = applyEvent(s, null, 'run.thinking', { run_id: 'r' })
  s = applyEvent(s, 3, 'run.finished', { ...run, status: 'completed' })
  expect(s.thinkingRunId).toBeNull()
})

test('activeRun is the running run; a queued run is not active', () => {
  let s = applyEvent(base(), 1, 'run.started', run)
  s = applyEvent(s, 2, 'run.started', { ...run, id: 'q', status: 'queued' })
  expect(activeRun(s)?.id).toBe('r')
  s = applyEvent(s, 3, 'run.finished', { ...run, status: 'completed' })
  expect(activeRun(s)).toBeNull()
  s = applyEvent(s, 4, 'run.updated', { ...run, id: 'q', status: 'waiting_approval' })
  expect(activeRun(s)?.id).toBe('q')
})

test('unknown event types leave the records unchanged but advance the cursor', () => {
  const s = applyEvent(base(), 9, 'something.new', {})
  expect(s.lastEventId).toBe(9)
  expect(s.runs).toEqual([])
})

test('conversation.updated replaces the conversation', () => {
  const s = applyEvent(base(), 1, 'conversation.updated', { ...conversation, title: 'Renamed' })
  expect(s.conversation.title).toBe('Renamed')
})

test('commands are upserted and live output is appended to a running command only', () => {
  const running = command('k', 'r', { status: 'running', exit_code: null, output: '' })
  let s = applyEvent(base(), 1, 'command.created', running)
  s = applyEvent(s, null, 'command.output', { command_id: 'k', text: 'one\n' })
  s = applyEvent(s, null, 'command.output', { command_id: 'k', text: 'two\n' })
  s = applyEvent(s, null, 'command.output', { command_id: 'zz', text: 'lost' })
  expect(s.commands[0].output).toBe('one\ntwo\n')
  s = applyEvent(s, null, 'command.sync', { command_id: 'k', output: 'one\ntwo\nthree\n' })
  expect(s.commands[0].output).toBe('one\ntwo\nthree\n')
  s = applyEvent(s, 2, 'command.updated', { ...running, status: 'exited', exit_code: 0, output: 'final' })
  s = applyEvent(s, null, 'command.output', { command_id: 'k', text: 'late' })
  expect(s.commands).toHaveLength(1)
  expect(s.commands[0]).toMatchObject({ status: 'exited', output: 'final' })
})

test('allowed_commands.updated replaces the rule list', () => {
  const rule = { id: 'a', conversation_id: 'c', prefix: 'pytest', danger: '', created_at: 't' }
  let s = applyEvent(base(), 1, 'allowed_commands.updated', { rules: [rule] })
  expect(s.allowedCommands).toEqual([rule])
  s = applyEvent(s, 2, 'allowed_commands.updated', { rules: [] })
  expect(s.allowedCommands).toEqual([])
})

test('a search or a request that is asked about is kept, and so is what is allowed without asking', () => {
  const asked = { id: 'w', run_id: 'r', agent_id: 'a', tool_call_id: 't', kind: 'search', method: null, target: 'python docs', host: null, headers: [], body_chars: null, status: 'proposed', created_at: 't', decided_at: null }
  let s = applyEvent(base(), 1, 'web_request.updated', asked)
  s = applyEvent(s, 2, 'web_request.updated', { ...asked, status: 'approved' })
  expect(s.webRequests).toEqual([{ ...asked, status: 'approved' }])
  const rule = { id: 'x', conversation_id: 'c', kind: 'search', host: '', ask_first: false, created_at: 't' }
  s = applyEvent(s, 3, 'allowed_web.updated', { rules: [rule] })
  expect(s.allowedWeb).toEqual([rule])
  expect(applyEvent(s, 4, 'allowed_web.updated', { rules: [] }).allowedWeb).toEqual([])
  // a server from before the web tools sends neither
  expect(base()).toMatchObject({ webRequests: [], allowedWeb: [] })
  expect(fromSnapshot({ ...snapshot, web_requests: [asked], allowed_web: [rule] } as Snapshot)).toMatchObject({ webRequests: [asked], allowedWeb: [rule] })
})

test('a command update without output keeps the output streamed so far', () => {
  const running = command('k', 'r', { status: 'running', exit_code: null, output: '' })
  let s = applyEvent(base(), 1, 'command.created', running)
  s = applyEvent(s, null, 'command.output', { command_id: 'k', text: 'all of it\n' })
  const { output: _dropped, ...finished } = { ...running, status: 'exited' as const, exit_code: 0 }
  s = applyEvent(s, 2, 'command.updated', finished)
  expect(s.commands[0]).toMatchObject({ status: 'exited', exit_code: 0, output: 'all of it\n' })
  // an update for a command this client has not seen yet starts with no output
  s = applyEvent(s, 3, 'command.updated', { ...finished, id: 'new' })
  expect(s.commands[1].output).toBe('')
})

test('an agent summarising its earlier work is said so until its step goes on', () => {
  let s = applyEvent(base(), 1, 'run.started', run)
  s = applyEvent(s, null, 'run.thinking', { run_id: 'r', agent_id: 'a', summarising: true })
  expect(s.summarisingAgents).toEqual(['a'])
  expect(s.thinkingAgents).toEqual([]) // not its model thinking about its step
  s = applyEvent(s, 2, 'message.created', { ...msg, agent_id: 'a' })
  expect(s.summarisingAgents).toEqual([])
  s = applyEvent(s, null, 'run.thinking', { run_id: 'r', agent_id: 'a', summarising: true })
  s = applyEvent(s, 3, 'run.finished', { ...run, status: 'completed' })
  expect(s.summarisingAgents).toEqual([])
})

test('which agents are thinking is kept for each of them, until its own model writes or its step ends', () => {
  const of = (id: string, agentId: string): Message => ({ ...msg, id, agent_id: agentId })
  let s = applyEvent(base(), 1, 'run.started', run)
  s = applyEvent(s, 2, 'message.created', of('ma', 'a'))
  s = applyEvent(s, 3, 'message.created', of('mb', 'b'))
  s = applyEvent(s, null, 'run.thinking', { run_id: 'r', agent_id: 'a' })
  s = applyEvent(s, null, 'run.thinking', { run_id: 'r', agent_id: 'b' })
  s = applyEvent(s, null, 'run.thinking', { run_id: 'r', agent_id: 'a' })
  expect(s.thinkingAgents).toEqual(['a', 'b'])
  // b's model starts to write: a is still thinking
  s = applyEvent(s, null, 'message.delta', { message_id: 'mb', text: 'So' })
  expect(s.thinkingAgents).toEqual(['a'])
  // a's step ends without a word (a tool call, a stop): it is not thinking any more
  s = applyEvent(s, 4, 'message.completed', { ...of('ma', 'a'), status: 'complete' })
  expect(s.thinkingAgents).toEqual([])
  // a note handed to an agent is not the end of its step
  s = applyEvent(s, null, 'run.thinking', { run_id: 'r', agent_id: 'b' })
  s = applyEvent(s, 5, 'message.completed', { ...of('note', 'b'), role: 'agent', status: 'complete' })
  expect(s.thinkingAgents).toEqual(['b'])
  s = applyEvent(s, 6, 'run.finished', { ...run, status: 'completed' })
  expect(s.thinkingAgents).toEqual([])
  // an event that names no agent says nothing about any of them
  s = applyEvent(s, null, 'run.thinking', { run_id: 'r' })
  expect(s.thinkingAgents).toEqual([])
})

test('agents are upserted and thinking names the agent', () => {
  let s = applyEvent(base(), 1, 'agent.created', agent('r'))
  s = applyEvent(s, 2, 'agent.updated', agent('r', 'completed'))
  expect(s.agents.map(a => a.status)).toEqual(['completed'])
  s = applyEvent(s, null, 'run.thinking', { run_id: 'r', agent_id: 'r' })
  expect([s.thinkingRunId, s.thinkingAgentId]).toEqual(['r', 'r'])
  s = applyEvent(s, 3, 'run.finished', run)
  expect(s.thinkingAgentId).toBeNull()
})

test('channel messages are kept and a role request comes and goes', () => {
  const message = { id: 'm1', run_id: 'r', from_agent_id: 'a', to_agent_id: 'b', kind: 'task' as const, content: 'do it', created_at: 't' }
  let s = applyEvent(base(), 1, 'channel.created', message)
  s = applyEvent(s, 1, 'channel.created', message)
  expect(s.channelMessages).toEqual([message])
  const request = { tool_call_id: 't1', run_id: 'r', agent_id: 'a', name: 'Documenter', description: '', instructions: '', tools: ['read_file'] }
  s = applyEvent(s, 2, 'role_request.created', request)
  expect(s.pendingRoles).toEqual([request])
  s = applyEvent(s, 3, 'role_request.resolved', { tool_call_id: 't1' })
  expect(s.pendingRoles).toEqual([])
})

test('a question arrives pending and is updated when answered', () => {
  const asked = { id: 'q', run_id: 'r', agent_id: 'a', tool_call_id: 't', question: 'Which?', options: ['x', 'y'], status: 'pending' as const, answer: null, created_at: 't', answered_at: null }
  let s = applyEvent(base(), 1, 'question.created', asked)
  s = applyEvent(s, 2, 'question.updated', { ...asked, status: 'answered', answer: 'x' })
  expect(s.questions.map(q => [q.status, q.answer])).toEqual([['answered', 'x']])
})

test('a command that arrives without its output field still has one', () => {
  const { output: _dropped, ...bare } = command('k9', 'r', { status: 'running' })
  const s = applyEvent(base(), 1, 'command.created', bare)
  expect(s.commands[0].output).toBe('')
})

// --- topics (slice 18b) ------------------------------------------------------------------------

test('a conversation’s topics come with its snapshot; a new one and a new name arrive as events', () => {
  const first = { id: 't1', conversation_id: 'c', title: 'Fix the greeting', trigger_id: null, created_at: 't' }
  let s = fromSnapshot({ ...snapshot, topics: [first] })
  expect(s.topics).toEqual([first])
  s = applyEvent(s, 1, 'topic.created', { ...first, id: 't2', title: 'Another thing' })
  s = applyEvent(s, 2, 'topic.updated', { ...first, title: 'The greeting' })
  expect(s.topics.map(t => [t.id, t.title])).toEqual([['t1', 'The greeting'], ['t2', 'Another thing']])
  // a snapshot from before topics has none, not nothing
  const { topics: _none, ...old } = snapshot
  expect(fromSnapshot(old as Snapshot).topics).toEqual([])
})
