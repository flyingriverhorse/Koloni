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
  after_change: null,
  page_scripts: false,
  lead_work: 'delegates',
  lead_hands_code: true,
  when_away: 'waits',
  away_minutes: 10,
  lead_effort: null,
  room_posts: 40,
  room_tokens: 400000,
  room_minutes: 30,
  room_min_tokens: 60000,
  also_in: [],
  read_in: [],
  part: null,
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
  by_user: true,
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

test('a turn sent again after a restart moves under the others in every open tab: by when it was sent', () => {
  let s = applyEvent(base(), 1, 'run.started', {
    ...run,
    id: 'a',
    status: 'interrupted',
    started_at: null,
    created_at: '2026-11-21T10:00:00Z',
  })
  s = applyEvent(s, 2, 'run.started', { ...run, id: 'b', status: 'completed', created_at: '2026-11-21T10:01:00Z' })
  s = applyEvent(s, 3, 'run.updated', { ...run, id: 'a', created_at: '2026-11-21T10:02:00Z' })
  expect(s.runs.map(r => [r.id, r.status])).toEqual([
    ['b', 'completed'],
    ['a', 'running'],
  ])
  s = applyEvent(s, 4, 'run.updated', { ...run, id: 'b', model_id: 'q', created_at: '2026-11-21T10:01:00Z' })
  expect(s.runs.map(r => r.id)).toEqual(['b', 'a']) // (an update that moves nothing keeps its place)
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
  let s = applyEvent(base(), null, 'agent.live', {
    agent_id: 'a',
    context: { used: 1, window: 100000 },
    plan: null,
    queue: null,
  })
  s = applyEvent(s, null, 'agent.live', {
    agent_id: 'a',
    context,
    plan: [{ step: 'Fix', status: 'inProgress' }],
    queue: null,
  })
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
  const asked = {
    id: 'w',
    run_id: 'r',
    agent_id: 'a',
    tool_call_id: 't',
    kind: 'search',
    method: null,
    target: 'python docs',
    host: null,
    headers: [],
    body_chars: null,
    status: 'proposed',
    created_at: 't',
    decided_at: null,
  }
  let s = applyEvent(base(), 1, 'web_request.updated', asked)
  s = applyEvent(s, 2, 'web_request.updated', { ...asked, status: 'approved' })
  expect(s.webRequests).toEqual([{ ...asked, status: 'approved' }])
  const rule = { id: 'x', conversation_id: 'c', kind: 'search', host: '', ask_first: false, created_at: 't' }
  s = applyEvent(s, 3, 'allowed_web.updated', { rules: [rule] })
  expect(s.allowedWeb).toEqual([rule])
  expect(applyEvent(s, 4, 'allowed_web.updated', { rules: [] }).allowedWeb).toEqual([])
  // a server from before the web tools sends neither
  expect(base()).toMatchObject({ webRequests: [], allowedWeb: [] })
  expect(fromSnapshot({ ...snapshot, web_requests: [asked], allowed_web: [rule] } as Snapshot)).toMatchObject({
    webRequests: [asked],
    allowedWeb: [rule],
  })
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
  const message = {
    id: 'm1',
    run_id: 'r',
    from_agent_id: 'a',
    to_agent_id: 'b',
    kind: 'task' as const,
    content: 'do it',
    created_at: 't',
  }
  let s = applyEvent(base(), 1, 'channel.created', message)
  s = applyEvent(s, 1, 'channel.created', message)
  expect(s.channelMessages).toEqual([message])
  const request = {
    tool_call_id: 't1',
    run_id: 'r',
    agent_id: 'a',
    name: 'Documenter',
    description: '',
    instructions: '',
    tools: ['read_file'],
  }
  s = applyEvent(s, 2, 'role_request.created', request)
  expect(s.pendingRoles).toEqual([request])
  s = applyEvent(s, 3, 'role_request.resolved', { tool_call_id: 't1' })
  expect(s.pendingRoles).toEqual([])
})

test('a question arrives pending and is updated when answered', () => {
  const asked = {
    id: 'q',
    run_id: 'r',
    agent_id: 'a',
    tool_call_id: 't',
    question: 'Which?',
    options: ['x', 'y'],
    status: 'pending' as const,
    answer: null,
    created_at: 't',
    answered_at: null,
  }
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
  expect(s.topics.map(t => [t.id, t.title])).toEqual([
    ['t1', 'The greeting'],
    ['t2', 'Another thing'],
  ])
  // a snapshot from before topics has none, not nothing
  const { topics: _none, ...old } = snapshot
  expect(fromSnapshot(old as Snapshot).topics).toEqual([])
})

// --- every event, and what it leaves as it was ----------------------------------------------------

/** The slices an event made anew: every other is the very object it was (a selector on it draws nothing again). */
const changed = (was: ConvState, now: ConvState) =>
  (Object.keys(now) as (keyof ConvState)[]).filter(key => now[key] !== was[key])

test('each record’s event puts it in its own list - added at the end, replaced in its place - and makes no other list anew', () => {
  const lists: [string[], keyof ConvState][] = [
    [['run.started', 'run.updated'], 'runs'],
    [['agent.created', 'agent.updated'], 'agents'],
    [['channel.created'], 'channelMessages'],
    [['discussion.created', 'discussion.updated'], 'discussions'],
    [['discussion_post.created'], 'discussionPosts'],
    [['room.created', 'room.updated'], 'rooms'],
    [['room_item.created', 'room_item.updated'], 'roomItems'],
    [['room_post.created', 'room_post.updated'], 'roomPosts'],
    [['board.posted'], 'boardPosts'],
    [['question.created', 'question.updated'], 'questions'],
    [['tool_call.created', 'tool_call.updated'], 'toolCalls'],
    [['file_change.created', 'file_change.updated'], 'fileChanges'],
    [['web_request.updated'], 'webRequests'],
    [['topic.created', 'topic.updated'], 'topics'],
    [['merge.updated'], 'merges'],
    [['attachment.created', 'attachment.updated'], 'attachments'],
  ]
  for (const [types, key] of lists) {
    for (const type of types) {
      const start = {
        ...base(),
        [key]: [
          { id: 'a', n: 0 },
          { id: 'b', n: 0 },
        ],
      } as ConvState
      const added = applyEvent(start, 1, type, { id: 'c', n: 1 })
      expect([type, added[key]]).toEqual([
        type,
        [
          { id: 'a', n: 0 },
          { id: 'b', n: 0 },
          { id: 'c', n: 1 },
        ],
      ])
      expect([type, changed(start, added)]).toEqual([type, [key, 'lastEventId']])
      const replaced = applyEvent(added, 2, type, { id: 'a', n: 2 })
      expect([type, replaced[key]]).toEqual([
        type,
        [
          { id: 'a', n: 2 },
          { id: 'b', n: 0 },
          { id: 'c', n: 1 },
        ],
      ])
      expect([type, changed(added, replaced), replaced.lastEventId]).toEqual([type, [key, 'lastEventId'], 2])
      // (With no id - never stored - it is applied as it arrives, and the cursor stays.)
      expect([type, changed(start, applyEvent(start, null, type, { id: 'c', n: 1 }))]).toEqual([type, [key]])
    }
  }
})

test('an event that changes nothing hands back the very state it was given', () => {
  const s = applyEvent(
    applyEvent(base(), 4, 'message.created', { ...msg, status: 'complete' }),
    5,
    'command.created',
    command('k', 'r', { status: 'exited' }),
  )
  expect(applyEvent(s, 5, 'run.started', run)).toBe(s)
  expect(applyEvent(s, 3, 'view.shown', {})).toBe(s)
  for (const type of [
    'role.created',
    'skill.created',
    'memory.changed',
    'backlog.changed',
    'triggers.changed',
    'notes.offered',
    'constructor',
    'toString',
    '',
  ])
    expect(applyEvent(s, null, type, {})).toBe(s)
  // A message that is not being written, a command that does not run, one not known.
  for (const id of ['m', 'none']) {
    expect(applyEvent(s, null, 'message.delta', { message_id: id, text: 'x' })).toBe(s)
    expect(applyEvent(s, null, 'message.sync', { message_id: id, content: 'x' })).toBe(s)
  }
  for (const id of ['k', 'none']) {
    expect(applyEvent(s, null, 'command.output', { command_id: id, text: 'x' })).toBe(s)
    expect(applyEvent(s, null, 'command.sync', { command_id: id, output: 'x' })).toBe(s)
  }
  expect(applyEvent(s, null, 'injection.warned', { rule: 'r' })).toBe(s)
  // (Stored, such an event still moves the cursor - and nothing else.)
  expect(changed(s, applyEvent(s, 9, 'message.delta', { message_id: 'm', text: 'x' }))).toEqual(['lastEventId'])
  expect(changed(s, applyEvent(s, 9, 'command.output', { command_id: 'k', text: 'x' }))).toEqual(['lastEventId'])
  expect(changed(s, applyEvent(s, 9, 'memory.changed', {}))).toEqual(['lastEventId'])
})

test('a turn’s, a message’s and a command’s events change their own slices and no other', () => {
  const s = {
    ...base(),
    thinkingRunId: 'r',
    thinkingAgentId: 'a',
    thinkingAgents: ['a', 'b'],
    summarisingAgents: ['a'],
  }
  const finished = applyEvent(s, 1, 'run.finished', run)
  expect(changed(s, finished)).toEqual([
    'runs',
    'lastEventId',
    'thinkingRunId',
    'thinkingAgentId',
    'thinkingAgents',
    'summarisingAgents',
  ])
  expect(finished).toMatchObject({
    runs: [run],
    thinkingRunId: null,
    thinkingAgentId: null,
    thinkingAgents: [],
    summarisingAgents: [],
  })
  // Thinking with no agent named: who thinks stays as it was, the very list.
  const thinking = applyEvent(s, null, 'run.thinking', { run_id: 'q' })
  expect(changed(s, thinking)).toEqual(['thinkingRunId', 'thinkingAgentId'])
  expect(thinking).toMatchObject({ thinkingRunId: 'q', thinkingAgentId: null })
  expect(applyEvent(s, null, 'run.thinking', { run_id: 'q', summarising: true })).toMatchObject({
    thinkingRunId: 'q',
    thinkingAgentId: null,
    summarisingAgents: ['a'],
  })
  expect(changed(s, applyEvent(s, null, 'run.thinking', { run_id: 'q', agent_id: 'c' }))).toEqual([
    'thinkingRunId',
    'thinkingAgentId',
    'thinkingAgents',
  ])
  expect(applyEvent(s, null, 'run.thinking', { run_id: 'q', agent_id: 'a' }).thinkingAgents).toEqual(['a', 'b'])
  const summarising = applyEvent(s, null, 'run.thinking', { run_id: 'q', agent_id: 'c', summarising: true })
  expect(changed(s, summarising)).toEqual(['summarisingAgents'])
  expect(summarising.summarisingAgents).toEqual(['a', 'c'])
  // A message of the user's, or of an agent that was not thinking: who thinks is the very list it was.
  for (const type of ['message.created', 'message.completed']) {
    expect(changed(s, applyEvent(s, null, type, { ...msg, role: 'user' }))).toEqual(['messages'])
    expect(changed(s, applyEvent(s, null, type, { ...msg, agent_id: 'z' }))).toEqual(['messages'])
    expect(changed(s, applyEvent(s, null, type, { ...msg, agent_id: null }))).toEqual(['messages'])
    const own = applyEvent(s, null, type, msg)
    expect(changed(s, own)).toEqual(['messages', 'thinkingAgents', 'summarisingAgents'])
    expect([own.thinkingAgents, own.summarisingAgents, own.thinkingRunId]).toEqual([['b'], [], 'r'])
  }
  const writing = applyEvent(s, null, 'message.created', msg)
  const delta = applyEvent(writing, null, 'message.delta', { message_id: 'm', text: 'Hi' })
  expect(changed(writing, delta)).toEqual(['messages', 'thinkingRunId', 'thinkingAgentId'])
  expect(delta).toMatchObject({ messages: [{ ...msg, content: 'Hi' }], thinkingRunId: null, thinkingAgentId: null })
  expect(changed(delta, applyEvent(delta, null, 'message.sync', { message_id: 'm', content: 'Hello' }))).toEqual([
    'messages',
  ])
  const ran = applyEvent(s, null, 'command.created', command('k', 'r', { status: 'running', output: 'a' }))
  expect(changed(s, ran)).toEqual(['commands'])
  for (const [type, payload, output] of [
    ['command.output', { command_id: 'k', text: 'b' }, 'ab'],
    ['command.sync', { command_id: 'k', output: 'z' }, 'z'],
  ] as const) {
    const now = applyEvent(ran, null, type, payload)
    expect([changed(ran, now), now.commands[0].output]).toEqual([['commands'], output])
  }
  const { output: _none, ...update } = command('k', 'r', { status: 'exited' })
  expect(applyEvent(ran, null, 'command.updated', update).commands).toEqual([{ ...update, output: 'a' }])
  expect(applyEvent(s, null, 'command.updated', update).commands).toEqual([{ ...update, output: '' }])
  expect(applyEvent(ran, null, 'command.updated', { ...update, output: 'all' }).commands[0].output).toBe('all')
})

test('requests for a role or a skill, files taken off, warnings, what was shown and who holds what', () => {
  const s = base()
  for (const [kind, key] of [
    ['role_request', 'pendingRoles'],
    ['skill_request', 'pendingSkills'],
  ] as const) {
    let now = applyEvent(s, 1, `${kind}.created`, { tool_call_id: 't1', name: 'A' })
    now = applyEvent(now, 2, `${kind}.created`, { tool_call_id: 't2', name: 'B' })
    // Asked again by the same call: its request once, the newest, at the end.
    const again = applyEvent(now, 3, `${kind}.created`, { tool_call_id: 't1', name: 'A2' })
    expect(again[key]).toEqual([
      { tool_call_id: 't2', name: 'B' },
      { tool_call_id: 't1', name: 'A2' },
    ])
    expect(changed(now, again)).toEqual([key, 'lastEventId'])
    const resolved = applyEvent(again, 4, `${kind}.resolved`, { tool_call_id: 't2' })
    expect(resolved[key]).toEqual([{ tool_call_id: 't1', name: 'A2' }])
    expect(changed(again, resolved)).toEqual([key, 'lastEventId'])
  }
  const files = applyEvent(applyEvent(s, 1, 'attachment.created', { id: 'f1' }), 2, 'attachment.created', { id: 'f2' })
  const off = applyEvent(files, 3, 'attachment.deleted', { id: 'f1' })
  expect(off.attachments).toEqual([{ id: 'f2' }])
  expect(changed(files, off)).toEqual(['attachments', 'lastEventId'])
  // A warning is kept by its event's id, once: a snapshot read meanwhile may have it already.
  const warned = applyEvent(s, 7, 'injection.warned', { rule: 'orders', where: 'a.md' })
  expect(warned.warnings).toEqual([{ rule: 'orders', where: 'a.md', id: 7 }])
  expect(changed(s, warned)).toEqual(['warnings', 'lastEventId'])
  const known = { ...s, warnings: warned.warnings }
  expect(changed(known, applyEvent(known, 7, 'injection.warned', { rule: 'orders', where: 'a.md' }))).toEqual([
    'lastEventId',
  ])
  expect(applyEvent(warned, 8, 'injection.warned', { rule: 'more', where: 'b.md' }).warnings.map(w => w.id)).toEqual([
    7, 8,
  ])
  const shown = applyEvent(applyEvent(s, null, 'view.shown', {}), null, 'view.shown', {})
  expect([shown.shown, changed(s, shown)]).toEqual([2, ['shown']])
  const held = [{ path: 'a.py', agent_id: 'a' }]
  const claimed = applyEvent(s, null, 'claims.changed', { claims: held })
  expect(claimed.claims).toBe(held)
  expect(changed(s, claimed)).toEqual(['claims'])
  for (const [type, key] of [
    ['allowed_commands.updated', 'allowedCommands'],
    ['allowed_web.updated', 'allowedWeb'],
  ] as const) {
    const rules = [{ id: 'r1' }]
    const now = applyEvent(s, null, type, { rules })
    expect(now[key]).toBe(rules)
    expect(changed(s, now)).toEqual([key])
  }
})

test('conversation.updated: a turn keeps its teams’ rows as last seen; a turn none of the rows is of stays the very record', () => {
  const state = {
    run_id: 'r',
    team: 'Web app',
    recipe: 'Feature',
    status: 'running' as const,
    why: null,
    steps: [],
    agents: [],
    ended_ready: null,
    passes: [],
  }
  const other = { ...run, id: 'q' }
  const s = { ...base(), runs: [run, other] }
  const teams = [{ team_id: 'web', recipe_id: null, no_recipe: false, picked_by: 'user' as const, why: null, state }]
  const now = applyEvent(s, null, 'conversation.updated', { ...conversation, teams })
  expect(changed(s, now)).toEqual(['conversation', 'runs'])
  expect(now.runs[0]).toEqual({ ...run, teams })
  expect(now.runs[1]).toBe(other)
  expect(now.conversation.teams).toBe(teams)
  const live = applyEvent(s, null, 'agent.live', {
    agent_id: 'a',
    context: { used: 1, window: 2 },
    plan: null,
    queue: null,
  })
  expect([changed(s, live), live.live]).toEqual([
    ['live'],
    { a: { context: { used: 1, window: 2 }, plan: null, queue: null } },
  ])
  expect(applyEvent(live, null, 'agent.live', { agent_id: 'a', context: null, plan: null, queue: null }).live).toEqual(
    {},
  )
  expect(
    applyEvent(live, null, 'agent.live', {
      agent_id: 'b',
      context: null,
      plan: null,
      queue: { elapsed_s: 1, max_s: null, available: null },
    }).live,
  ).toMatchObject({ a: {}, b: {} })
})
