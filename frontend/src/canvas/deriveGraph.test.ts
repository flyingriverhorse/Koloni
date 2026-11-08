import { expect, test } from 'vitest'
import type { Agent, Run } from '../api/types'
import type { ConvState } from '../state/applyEvent'
import type { SharedData } from './sharedColumn'
import {
  agent,
  assistantMessage,
  question,
  command,
  convState,
  fileChange,
  run,
  toolCall,
  userMessage,
} from '../test-fixtures'
import {
  deriveGraph,
  findingsLine,
  poSaid,
  poTokens,
  type AgentData,
  type RequestData,
} from './deriveGraph'

test('an empty conversation has no nodes', () => {
  expect(deriveGraph(convState())).toEqual({ nodes: [], edges: [] })
})

test('a run without tool calls yields request and agent only', () => {
  const g = deriveGraph(convState({ runs: [run('r')], agents: [agent('r')], messages: [userMessage('r', 'explain main.py')] }))
  expect(g.nodes.map(n => n.id)).toEqual(['request:r', 'agent:r'])
  expect(g.edges.map(e => [e.source, e.target, e.active])).toEqual([['request:r', 'agent:r', true]])
  expect((g.nodes[0].data as RequestData).text).toBe('explain main.py')
})

test('what an agent did is counted on its node: tools, commands, files, own sub-agents - none that is not there (the user’s, 5 Nov)', () => {
  const g = deriveGraph(
    convState({
      runs: [run('r')],
      agents: [agent('r')],
      messages: [userMessage('r', 'x')],
      toolCalls: [
        toolCall('1', 'r', 'read_file', 'succeeded', '{"path":"a.py"}'),
        toolCall('2', 'r', 'read_file', 'failed'),
        toolCall('3', 'r', 'search', 'running', '{"pattern":"TODO"}'),
        toolCall('4', 'r', 'claude__Agent', 'running', '{}', { origin: 'cli' }),
        toolCall('5', 'r', 'run_command', 'succeeded', '{}'),
      ],
      commands: [command('k1', 'r', { tool_call_id: '5' })],
      fileChanges: [fileChange('f1', 'r')],
    }),
  )
  expect(g.nodes.map(n => n.id)).toEqual(['request:r', 'agent:r'])
  expect((g.nodes[1].data as AgentData).summary).toBe('3 tools · 1 command · 1 file · 1 own sub-agent')
  expect((deriveGraph(convState({ runs: [run('r')], agents: [agent('r')], messages: [userMessage('r', 'x')] })).nodes[1].data as AgentData).summary).toBe('')
})

function activity(over: Partial<ConvState>, status: Run['status'] = 'running', runOver: Partial<Run> = {}) {
  const g = deriveGraph(
    convState({
      runs: [run('r', status, runOver)],
      agents: [agent('r')],
      messages: [userMessage('r', 'x')],
      ...over,
    }),
  )
  return (g.nodes.find(n => n.id === 'agent:r')!.data as AgentData).activity
}

test('agent activity comes from records, in priority order', () => {
  expect(activity({}, 'waiting_approval')).toBe('Waits for your approval')
  expect(
    activity({ toolCalls: [toolCall('1', 'r', 'read_file', 'running', '{"path":"a.py"}')] }),
  ).toBe('reading a.py')
  expect(
    activity({ messages: [userMessage('r', 'x'), assistantMessage('a', 'r', 'So', 'streaming')] }),
  ).toBe('Writing reply…')
  expect(activity({ thinkingAgents: ['r'] })).toBe('Thinking…')
  expect(activity({ thinkingAgents: ['r'], summarisingAgents: ['r'] })).toBe('Summarising its earlier work…')
  expect(activity({})).toBe('Waiting for the model…')
  // R130: its model in Qoder's queue, as its CLI says live (K-qoder-kuyruk).
  const queue = { elapsed_s: 40, max_s: 3600, available: false }
  expect(activity({ live: { r: { context: null, plan: null, queue } } })).toBe('Queued at Qoder')
})

test('what an agent does now (slice 84d): a command by what it runs, a file by what is done to it, and since when; nothing while no tool runs', () => {
  const now = (over: Partial<ConvState>, status: Run['status'] = 'running') => {
    const g = deriveGraph(convState({ runs: [run('r', status)], agents: [agent('r')], messages: [userMessage('r', 'x')], ...over }))
    const { activity: said, since } = g.nodes.find(n => n.id === 'agent:r')!.data as AgentData
    return [said, since]
  }
  const started = { started_at: '2026-10-05T10:00:01Z' }
  const ran = toolCall('t1', 'r', 'run_command', 'running', '{"command":"pytest tests/test_mail.py"}', started)
  // the command's own start, not its call's: it may have waited for leave first
  expect(now({ toolCalls: [ran], commands: [command('k', 'r', { status: 'running', command: 'pytest tests/test_mail.py', ended_at: null })] })).toEqual([
    'pytest tests/test_mail.py',
    '2026-10-05T10:00:03Z',
  ])
  expect(now({ toolCalls: [toolCall('1', 'r', 'edit_file', 'running', '{"path":"mail.py"}', started)] })).toEqual(['editing mail.py', started.started_at])
  expect(now({ toolCalls: [toolCall('1', 'r', 'write_file', 'running', '{"path":"cart.py"}', started)] })).toEqual(['editing cart.py', started.started_at])
  expect(now({ toolCalls: [toolCall('1', 'r', 'search', 'running', '{"pattern":"TODO"}', started)] })).toEqual(['search "TODO"', started.started_at])
  // its model at work, waiting, or done: no tool, so no time
  expect(now({ thinkingAgents: ['r'] })).toEqual(['Thinking…', null])
  expect(now({ toolCalls: [ran] }, 'waiting_approval')).toEqual(['Waits for your approval', null])
  expect(now({ toolCalls: [{ ...ran, status: 'succeeded' }] }, 'completed')).toEqual(['Completed', null])
})

test('each agent at work says for itself whether its model is thinking or writing', () => {
  // Two sub-agents at the same time: the Coder's model is writing, the Tester's and the
  // Reviewer's are thinking. The last event of one is not put down to the others.
  const kid = (id: string, role: string) =>
    agent('r', 'running', { id, parent_agent_id: 'r', role_name: role, name: role, depth: 1 })
  const g = deriveGraph(
    convState({
      runs: [run('r', 'running')],
      agents: [agent('r', 'waiting'), kid('c', 'Coder'), kid('t', 'Tester'), kid('v', 'Reviewer'), kid('n', 'Planner')],
      messages: [userMessage('r', 'x'), { ...assistantMessage('a', 'r', 'So', 'streaming'), agent_id: 'c' }],
      thinkingRunId: 'r',
      thinkingAgentId: 'v',
      thinkingAgents: ['t', 'v'],
    }),
  )
  const says = (id: string) => (g.nodes.find(n => n.id === `agent:${id}`)!.data as AgentData).activity
  expect(['c', 't', 'v', 'n'].map(says)).toEqual(['Writing reply…', 'Thinking…', 'Thinking…', 'Waiting for the model…'])
})

test('a finished run reports how it ended', () => {
  expect(activity({}, 'completed')).toBe('Completed')
  expect(activity({}, 'failed', { error: 'step_limit' })).toBe('Stopped at its step limit')
  // K-devam-butce (B-327): stopped at the end of the steps it was given, the node says the budget, not the app's limit.
  expect(activity({ agents: [agent('r', 'failed', { error: 'stopped after the 2 steps it was given' })] }, 'failed', { error: 'stopped after the 2 steps it was given' })).toBe('Stopped after the 2 steps it was given')
  expect(activity({}, 'failed', { error: 'model server unreachable' })).toBe('Failed')
  // Where its provider said why, the node says it in plain words.
  const limited = agent('r', 'failed', { provider_name: 'Codex', failure: 'rate_limited', error: 'Codex reported an error: usage limit' })
  expect(activity({ agents: [limited] }, 'failed', { error: limited.error })).toBe('Codex: limit reached')
  expect(activity({}, 'cancelled')).toBe('Stopped')
  expect(activity({}, 'interrupted')).toBe('Interrupted')
})

test('a sub-agent stopped at the app’s step limit says so without a number: the limit is a setting, and no payload has it', () => {
  const kid = agent('r', 'failed', { id: 'k', parent_agent_id: 'r', role_name: 'Coder', name: 'Coder', depth: 1, error: 'step_limit' })
  const g = deriveGraph(convState({ runs: [run('r', 'running')], agents: [agent('r', 'running'), kid] }))
  const said = (g.nodes.find(n => n.id === 'agent:k')!.data as AgentData).activity
  expect(said).toBe('Stopped at its step limit')
  expect(said).not.toMatch(/\d/)
})

test('a turn a trigger started begins at the trigger’s message, named for the trigger and not for the user', () => {
  const started = { ...userMessage('n', 'Look the project over'), role: 'trigger' as const }
  const g = deriveGraph(
    convState({
      runs: [run('n', 'running', { unattended: true, trigger_id: 't', trigger_name: 'Nightly look' })],
      agents: [agent('n')],
      messages: [started],
    }),
  )
  expect(g.nodes.map(n => n.id)).toEqual(['request:n', 'agent:n'])
  expect(g.nodes[0].data).toMatchObject({ text: 'Look the project over', trigger: 'Nightly look' })
  expect(g.edges.map(e => e.id)).toEqual(['request:n>agent:n'])
  // a turn of the user's names no trigger
  const own = deriveGraph(convState({ runs: [run('r')], agents: [agent('r')], messages: [userMessage('r', 'x')] }))
  expect((own.nodes[0].data as RequestData).trigger).toBeNull()
})

test('a queued request is marked and has no agent until its turn starts', () => {
  const g = deriveGraph(
    convState({ runs: [run('q', 'queued')], messages: [userMessage('q', 'later')] }),
  )
  expect((g.nodes[0].data as RequestData).queued).toBe(true)
  expect(g.nodes.map(n => n.id)).toEqual(['request:q'])
  expect(g.edges).toEqual([])
})

test('a queued message that was removed before it ran leaves no nodes', () => {
  const g = deriveGraph(
    convState({
      runs: [run('q', 'cancelled', { started_at: null })],
      messages: [userMessage('q', 'never mind')],
    }),
  )
  expect(g.nodes).toEqual([])
})

test('the agent node carries its role and each agent owns what it did', () => {
  const g = deriveGraph(
    convState({
      runs: [run('r')],
      messages: [userMessage('r', 'x')],
      agents: [
        agent('r', 'waiting', { id: 'lead', input_tokens: 9 }),
        agent('r', 'running', { id: 'kid', parent_agent_id: 'lead', role_name: 'Tester', task: 'run tests', depth: 1 }),
      ],
      toolCalls: [toolCall('1', 'r', 'read_file', 'succeeded', '{}', { agent_id: 'kid' })],
      commands: [command('k1', 'r', { agent_id: 'kid' })],
    }),
  )
  expect(g.nodes.map(n => n.id)).toEqual(['request:r', 'agent:lead', 'agent:kid'])
  expect(g.nodes[1].data).toMatchObject({ role: 'Lead', parentId: null, summary: '' })
  expect(g.nodes[2].data).toMatchObject({ role: 'Tester', parentId: 'lead', summary: '1 tool · 1 command' })
  expect(g.edges.map(e => e.id)).toEqual(['request:r>agent:lead', 'agent:lead>agent:kid'])
})

function tree(kid: Parameters<typeof agent>[1], over: Partial<ConvState> = {}) {
  return deriveGraph(
    convState({
      runs: [run('r', kid === 'proposed' ? 'waiting_approval' : 'running')],
      messages: [userMessage('r', 'x')],
      agents: [
        agent('r', kid === 'proposed' ? 'running' : 'waiting', { id: 'lead' }),
        agent('r', kid, { id: 'kid', parent_agent_id: 'lead', role_name: 'Reviewer', task: 't', depth: 1 }),
      ],
      ...over,
    }),
  )
}
const activityOf = (g: ReturnType<typeof deriveGraph>, id: string) =>
  (g.nodes.find(n => n.id === id)!.data as AgentData).activity

test('a spawn edge is marked and active while the sub-agent waits to start or works', () => {
  const edge = (g: ReturnType<typeof deriveGraph>) => g.edges.find(e => e.id === 'agent:lead>agent:kid')!
  expect(edge(tree('running'))).toMatchObject({ spawn: true, active: true })
  expect(edge(tree('proposed'))).toMatchObject({ spawn: true, active: true })
  expect(edge(tree('completed'))).toMatchObject({ spawn: true, active: false })
  expect(tree('running').edges.find(e => e.id === 'request:r>agent:lead')?.spawn).toBeFalsy()
})

test('findings handed on are a line of their own from the agent that found them, with how many; its node says them by role (slice 84c)', () => {
  const found = [
    { what: 'greet() prints "Helo"', kind: 'code' as const, role: 'Coder', blocking: true },
    { what: 'too light', kind: 'ui' as const, role: 'UI designer', blocking: true },
    { what: 'slow', kind: 'other' as const, role: null, blocking: true },
    { what: 'no test', kind: 'test' as const, role: 'Coder', blocking: true },
  ]
  const g = deriveGraph(
    convState({
      runs: [run('r')],
      messages: [userMessage('r', 'x')],
      agents: [
        agent('r', 'waiting', { id: 'lead' }),
        agent('r', 'completed', { id: 'rev', parent_agent_id: 'lead', role_name: 'Reviewer', depth: 1, findings: found }),
        agent('r', 'running', { id: 'fix', parent_agent_id: 'lead', role_name: 'Coder', depth: 1, findings: [] }),
        agent('r', 'running', { id: 'old', parent_agent_id: 'lead', role_name: 'Tester', depth: 1 }),
      ],
      channelMessages: [
        { id: 'f1', run_id: 'r', from_agent_id: 'rev', to_agent_id: 'fix', kind: 'findings', content: '- greet() prints "Helo" | kind: code | role: Coder', created_at: '2026-10-05T10:00:00Z' },
      ],
    }),
  )
  // (the Coder they were handed to is at work on them: the line flows - slice 84d)
  expect(g.edges.filter(e => e.findings !== undefined)).toEqual([
    { id: 'findings:f1', source: 'agent:rev', target: 'agent:fix', active: true, findings: 1 },
  ])
  const line = (id: string) => (g.nodes.find(n => n.id === id)!.data as AgentData).findings
  // the roles on a short line, a count only where a role has more than one; each finding under the pointer
  expect(line('agent:rev')).toEqual({
    line: '4 findings → Coder ×2, UI designer, no role',
    detail: 'greet() prints "Helo" (code) → Coder\ntoo light (ui) → UI designer\nslow (other) → no role named\nno test (test) → Coder',
  })
  expect(line('agent:fix')?.line).toBe('no findings')
  expect(line('agent:old')).toBeNull()
})

test('a findings line flows only while the agent it was handed to is at work (slice 84d)', () => {
  const flows = (fixer: Agent['status']) =>
    deriveGraph(
      convState({
        runs: [run('r')],
        messages: [userMessage('r', 'x')],
        agents: [
          agent('r', 'waiting', { id: 'lead' }),
          agent('r', 'completed', { id: 'rev', parent_agent_id: 'lead', depth: 1 }),
          agent('r', fixer, { id: 'fix', parent_agent_id: 'lead', depth: 1 }),
        ],
        channelMessages: [{ id: 'f1', run_id: 'r', from_agent_id: 'rev', to_agent_id: 'fix', kind: 'findings', content: '- x', created_at: '2026-10-05T10:00:00Z' }],
      }),
    ).edges.find(e => e.id === 'findings:f1')!.active
  expect([flows('running'), flows('queued'), flows('completed'), flows('failed')]).toEqual([true, false, false, false])
})

test('a waiting agent names who it waits for and a proposed one waits for you', () => {
  expect(activityOf(tree('running'), 'agent:lead')).toBe('Waiting for Reviewer')
  expect(activityOf(tree('running'), 'agent:kid')).toBe('Waiting for the model…')
  const asked = tree('proposed')
  expect(activityOf(asked, 'agent:kid')).toBe('Waits for your approval')
  expect((asked.nodes.find(n => n.id === 'agent:kid')!.data as AgentData).status).toBe('proposed')
})

test('the agent that asked is the one that shows the approval', () => {
  const g = tree('running', {
    runs: [run('r', 'waiting_approval')],
    fileChanges: [fileChange('f1', 'r', { status: 'proposed', agent_id: 'kid' })],
  })
  expect(activityOf(g, 'agent:kid')).toBe('Waits for your approval')
  expect(activityOf(g, 'agent:lead')).toBe('Waiting for Reviewer')
})

test('every node says which agent it belongs to', () => {
  const g = tree('running', { commands: [command('k1', 'r', { agent_id: 'kid' })] })
  expect(g.nodes.map(n => [n.id, n.agentId])).toEqual([
    ['request:r', undefined],
    ['agent:lead', 'lead'],
    ['agent:kid', 'kid'],
  ])
})

test('a spawn call that opened an agent is that agent, not a tool', () => {
  const g = tree('running', {
    toolCalls: [
      toolCall('1', 'r', 'spawn_agent', 'running', '{}', { agent_id: 'lead' }),
      toolCall('2', 'r', 'spawn_agent', 'failed', '{"role":"Nobody"}', { agent_id: 'lead' }),
    ],
    agents: [
      agent('r', 'waiting', { id: 'lead' }),
      agent('r', 'running', { id: 'kid', parent_agent_id: 'lead', tool_call_id: '1', role_name: 'Reviewer', depth: 1 }),
    ],
  })
  expect((g.nodes.find(n => n.id === 'agent:lead')!.data as AgentData).summary).toBe('1 tool')
})

test('an agent with an open question waits for your answer', () => {
  const g = tree('running', {
    runs: [run('r', 'waiting_approval')],
    questions: [question('q', 'r', { agent_id: 'kid' }), question('old', 'r', { agent_id: 'lead', status: 'answered', answer: 'x' })],
  })
  expect(activityOf(g, 'agent:kid')).toBe('Waits for your answer')
  expect((g.nodes.find(n => n.id === 'agent:kid')!.data as AgentData).status).toBe('waiting_approval')
  expect(activityOf(g, 'agent:lead')).toBe('Waiting for Reviewer')
})

test('an agent node names the model that agent ran on, not its turn’s', () => {
  const g = deriveGraph(
    convState({
      runs: [run('r', 'running', { model_id: 'claude-sonnet' })],
      messages: [userMessage('r', 'x')],
      agents: [
        agent('r', 'waiting', { id: 'lead', provider_name: 'Claude Code', model_id: 'claude-sonnet' }),
        agent('r', 'running', { id: 'kid', parent_agent_id: 'lead', role_name: 'Reviewer', depth: 1, provider_name: 'Local', model_id: 'qwen' }),
        agent('r', 'proposed', { id: 'new', parent_agent_id: 'lead', role_name: 'Coder', depth: 1, provider_name: 'Codex', model_id: null }),
      ],
    }),
  )
  const data = (id: string) => g.nodes.find(n => n.id === id)!.data as AgentData
  expect([data('agent:lead').modelId, data('agent:kid').modelId, data('agent:new').modelId]).toEqual(['claude-sonnet', 'qwen', null])
  expect([data('agent:lead').provider, data('agent:new').provider]).toEqual(['Claude Code', 'Codex'])
})

test('an agent node says where the model’s name is from', () => {
  const g = deriveGraph(
    convState({
      runs: [run('r', 'running')],
      messages: [userMessage('r', 'x')],
      agents: [
        agent('r', 'waiting', { id: 'lead' }),
        agent('r', 'running', { id: 'kid', parent_agent_id: 'lead', role_name: 'Coder', depth: 1, provider_name: 'Codex', model_id: 'gpt-5.5-codex', model_from: 'settings', chosen: true }),
        agent('r', 'running', { id: 'own', parent_agent_id: 'lead', role_name: 'Reviewer', depth: 1 }),
      ],
    }),
  )
  const data = (id: string) => g.nodes.find(n => n.id === id)!.data as AgentData
  expect([data('agent:kid').modelFrom, data('agent:own').modelFrom]).toEqual(['settings', null])
})

// --- groups ---------------------------------------------------------------------------

const cli = { origin: 'cli' as const }
/** A turn of a CLI working natively: tools of its own, and a sub-agent of its own (call 2). */
function nativeTurn(over: Partial<ConvState> = {}, sub: Parameters<typeof toolCall>[3] = 'running') {
  return convState({
    runs: [run('r')],
    agents: [agent('r')],
    messages: [userMessage('r', 'x')],
    toolCalls: [
      toolCall('1', 'r', 'spawn_agent', 'failed', '{"role":"Nobody"}'),
      toolCall('2', 'r', 'claude__Agent', sub, '{"description":"Look around","prompt":"Read it all"}', cli),
      toolCall('3', 'r', 'claude__Read', 'succeeded', '{}', { ...cli, parent_call_id: '2' }),
      toolCall('4', 'r', 'run_command', 'succeeded', '{}', { ...cli, parent_call_id: '2' }),
      toolCall('5', 'r', 'edit_file', 'succeeded', '{"path":"src/a.py"}', { ...cli, parent_call_id: '2' }),
      toolCall('6', 'r', 'claude__Grep', 'succeeded', '{}', cli),
      toolCall('7', 'r', 'claude__mcp__sonarqube__scan', 'succeeded', '{}', cli),
      toolCall('8', 'r', 'claude__mcp__sonarqube__scan', 'failed', '{}', cli),
      toolCall('9', 'r', 'run_command', 'succeeded', '{}', cli),
    ],
    commands: [command('k1', 'r', { ...cli, tool_call_id: '4' }), command('k2', 'r', { ...cli, tool_call_id: '9' })],
    fileChanges: [fileChange('f1', 'r', { ...cli, tool_call_id: '5' })],
    ...over,
  })
}

test('an agent says when something it or its own sub-agent did waits for the user, and when it is finished', () => {
  const lead = (g: ReturnType<typeof deriveGraph>) => g.nodes.find(n => n.id === 'agent:r')!.data as AgentData
  const waits = deriveGraph(
    nativeTurn({
      runs: [run('r', 'waiting_approval')],
      commands: [command('k1', 'r', { ...cli, tool_call_id: '4', status: 'proposed', exit_code: null })],
    }),
  )
  expect(lead(waits).attention).toBe(true)
  // leave asked in words, for the sub-agent or for a tool of its own
  for (const callId of ['2', '3', '6']) expect(lead(deriveGraph(nativeTurn({ questions: [question('q', 'r', { tool_call_id: callId })] }))).attention).toBe(true)

  const done = deriveGraph(nativeTurn({ runs: [run('r', 'completed')], agents: [agent('r', 'completed')] }, 'succeeded'))
  expect([lead(done).finished, lead(done).attention]).toEqual([true, false])
  expect(done.edges.map(e => e.id)).toEqual(['request:r>agent:r'])
})

// --- the project's memory (slice 17) ------------------------------------------------------

const memoryTurn = () =>
  convState({
    runs: [run('r', 'completed'), run('s', 'completed')],
    messages: [userMessage('r', 'x'), userMessage('s', 'y')],
    agents: [
      agent('r', 'completed', { id: 'lead', facts_given: ['f1', 'f2'] }),
      agent('r', 'completed', { id: 'kid', parent_agent_id: 'lead', depth: 1, role_name: 'Reviewer', facts_given: ['f1', 'f2'] }),
      agent('r', 'completed', { id: 'kid2', parent_agent_id: 'lead', depth: 1, role_name: 'Tester', facts_given: null }),
      agent('r', 'completed', { id: 'kid3', parent_agent_id: 'lead', depth: 1, role_name: 'Coder', facts_given: ['f2', 'f3'] }),
      agent('s', 'completed', { id: 'plain' }),
    ],
    toolCalls: [
      toolCall('1', 'r', 'remember', 'succeeded', '{"text":"The port is 8790.","about":"port"}', { agent_id: 'kid2' }),
      toolCall('2', 'r', 'remember', 'failed', '{"text":"always use tabs"}', { agent_id: 'kid2' }),
      toolCall('3', 'r', 'recall', 'succeeded', '{"query":"port"}', { agent_id: 'kid' }),
      toolCall('4', 'r', 'remember', 'succeeded', '{"text":"Docs are in docs/."}', { agent_id: 'kid3' }),
      toolCall('5', 's', 'read_file', 'succeeded', '{"path":"a.py"}', { agent_id: 'plain' }),
    ],
  })

const memoryOf = (graph: ReturnType<typeof deriveGraph>, id: string) =>
  (graph.nodes.find(n => n.id === id)?.data as SharedData | undefined)?.rows.filter(row => row.kind === 'memory').map(row => row.text)

test('K-shared-bagli: what each agent was given from the memory, looked up and wrote is a row of its block; the Lead’s at the top', () => {
  const graph = deriveGraph(memoryTurn())
  expect(memoryOf(graph, 'shared:r:top')).toEqual(['2 facts given'])
  expect(memoryOf(graph, 'shared:r:agent:kid')).toEqual(['2 facts given · 1 lookup'])
  // (Of its two tries one went through: one written.)
  expect(memoryOf(graph, 'shared:r:agent:kid2')).toEqual(['1 written'])
  expect(memoryOf(graph, 'shared:r:agent:kid3')).toEqual(['2 facts given · 1 written'])
  // On hover, what was written - a refused note ("always use tabs") is not.
  const titles = (id: string) => (graph.nodes.find(n => n.id === id)?.data as SharedData).rows.filter(row => row.kind === 'memory').map(row => row.title)
  expect([...titles('shared:r:agent:kid2'), ...titles('shared:r:agent:kid3')]).toEqual(['Tester: The port is 8790.', 'Coder: Docs are in docs/.'])
  expect(titles('shared:r:agent:kid')).toEqual([undefined])
  // Each joined to its own box, the top block to the Lead's; the calls are counted on their agents' nodes as well.
  expect(graph.edges.filter(e => e.shared).map(e => e.source)).toEqual(['agent:lead', 'agent:kid', 'agent:kid2', 'agent:kid3'])
  expect(graph.nodes.find(n => n.id === 'agent:kid2')?.data).toMatchObject({ summary: '2 tools' })
})

test('a turn in which memory played no part has no card', () => {
  const { nodes } = deriveGraph(memoryTurn())
  expect(nodes.some(n => n.kind === 'shared' && n.runId === 's')).toBe(false)
  // facts_given empty or absent, and no remember or recall: nothing
  const none = convState({
    runs: [run('r')],
    messages: [userMessage('r', 'x')],
    agents: [agent('r', 'running', { facts_given: [] }), agent('r', 'running', { id: 'k', parent_agent_id: 'r', depth: 1, facts_given: null })],
  })
  expect(deriveGraph(none).nodes.some(n => n.kind === 'shared')).toBe(false)
})

test('a turn about something else - its agents given nothing, neither tool called - has no card, whatever the turn before had', () => {
  // As it is on record since a fact goes only to an agent whose work names its subject:
  // the first turn's agents were given one, the second turn's were not and did other work.
  const state = convState({
    runs: [run('r', 'completed'), run('s', 'completed')],
    messages: [userMessage('r', 'what is the port?'), userMessage('s', 'count the lines of hello.py')],
    agents: [
      agent('r', 'completed', { id: 'first', facts_given: ['f1'] }),
      agent('s', 'completed', { id: 'lead', facts_given: [] }),
      agent('s', 'completed', { id: 'kid', parent_agent_id: 'lead', depth: 1, role_name: 'Reviewer', facts_given: [] }),
    ],
    toolCalls: [
      toolCall('1', 's', 'read_file', 'succeeded', '{"path":"hello.py"}', { agent_id: 'lead' }),
      toolCall('2', 's', 'search', 'succeeded', '{"pattern":"print"}', { agent_id: 'kid' }),
    ],
  })
  expect(deriveGraph(state).nodes.filter(n => n.kind === 'shared').map(n => n.runId)).toEqual(['r'])
})

test('a lookup alone is a part memory played: the Lead’s, at the top', () => {
  const state = convState({
    runs: [run('r')],
    messages: [userMessage('r', 'x')],
    agents: [agent('r')],
    toolCalls: [toolCall('1', 'r', 'recall', 'succeeded', '{"query":"port"}')],
  })
  const graph = deriveGraph(state)
  expect(memoryOf(graph, 'shared:r:top')).toEqual(['1 lookup'])
  expect(graph.edges.filter(e => e.shared).map(e => [e.source, e.target])).toEqual([['agent:r', 'shared:r:top']])
})

// --- plan first (slice 49) -----------------------------------------------------------------

test('a plan turn has a small Plan node at its start, after the request; another turn has none', () => {
  const plan = { text: 'x', status: 'proposed' as const, model_id: 'big-model', strongest: true }
  const state = convState({
    runs: [run('p', 'running', { plan_turn: true }), run('d', 'completed', { plan_turn: true, plan }), run('w')],
    agents: [agent('p'), agent('d'), agent('w')],
    messages: [userMessage('p', 'a'), userMessage('d', 'b'), userMessage('w', 'c')],
  })
  const { nodes, edges } = deriveGraph(state)
  const plans = nodes.filter(n => n.kind === 'plan')
  expect(plans.map(n => [n.id, n.refId, n.data])).toEqual([
    ['plan:p', 'p', { status: 'writing', by: null }],
    ['plan:d', 'd', { status: 'proposed', by: 'Planned by big-model · the team’s strongest model' }],
  ])
  expect(edges.filter(e => e.target === 'plan:d').map(e => e.source)).toEqual(['request:d'])
})

test('the work turn of an approved plan has that plan over its Lead; a rejected plan, no plan or a later turn, none', () => {
  const plan = (status: 'approved' | 'rejected') => ({ text: 'x', status, model_id: 'big-model', strongest: false })
  const turns = (first: ReturnType<typeof plan> | null) => {
    const ids = ['p', 'w', 'x']
    const state = convState({
      runs: ids.map((id, i) => run(id, 'completed', i === 0 ? { plan_turn: true, plan: first } : {})),
      agents: ids.map(id => agent(id, 'completed')),
      messages: ids.map(id => userMessage(id, id)),
    })
    return deriveGraph(state).nodes.filter(n => n.kind === 'plan').map(n => [n.id, n.runId, n.refId, (n.data as { status: string }).status])
  }
  // The plan turn keeps its own node; the work turn right after it gets one too, pointing at the plan; the turn after that, none.
  expect(turns(plan('approved'))).toEqual([
    ['plan:p', 'p', 'p', 'approved'],
    ['planned:p', 'w', 'p', 'approved'],
  ])
  expect(turns(plan('rejected'))).toEqual([['plan:p', 'p', 'p', 'rejected']])
  expect(turns(null)).toEqual([])
})

test('an approved plan has one line of its own down to the Lead of its work turn; none before that turn has a Lead', () => {
  const plan = { text: 'x', status: 'approved' as const, model_id: 'big-model', strongest: false }
  const graph = (agents: string[]) =>
    deriveGraph(
      convState({
        runs: [run('p', 'completed', { plan_turn: true, plan }), run('w')],
        agents: agents.map(id => agent(id)),
        messages: [userMessage('p', 'p'), userMessage('w', 'w')],
      }),
    )
  const { edges } = graph(['p', 'w'])
  expect(edges.filter(e => e.plan)).toEqual([{ id: 'planned:p>agent:w', source: 'planned:p', target: 'agent:w', active: false, plan: true }])
  // (No other line meets it: not a work, talk or spawn line.)
  expect(edges.filter(e => [e.source, e.target].includes('planned:p'))).toHaveLength(1)
  expect(graph(['p']).edges.filter(e => e.plan)).toEqual([])
})

test('the user’s (7 Nov): the Assistant PO is a node under the turn’s Lead, on its own dashed line, only where it was asked', () => {
  const po = { provider_name: 'Fast', model_id: 'gpt-6-luna', heard: true, input_tokens: 3000, output_tokens: 100, proposed: 2, dropped: [{ title: 'Docs', why: 'like the open task' }], dropped_more: 0 }
  const graph = (asked: typeof po | null) =>
    deriveGraph(convState({ runs: [run('r', 'completed', { po: asked })], agents: [agent('r')], messages: [userMessage('r', 'x')] }))
  const { nodes, edges } = graph(po)
  expect(nodes.find(n => n.kind === 'po')).toMatchObject({ id: 'po:r', runId: 'r', refId: 'r', data: po })
  expect(edges.filter(e => e.target === 'po:r')).toEqual([{ id: 'agent:r>po:r', source: 'agent:r', target: 'po:r', active: false, plan: true, po: true }])
  expect([poSaid(po), poTokens(po)]).toEqual(['2 proposed · 1 dropped', '3k tokens'])
  // not asked: no node, no line
  expect(graph(null).nodes.some(n => n.kind === 'po')).toBe(false)
  // sent and not heard out, and what it spent not said: never 0
  const lost = { ...po, heard: false, input_tokens: null, output_tokens: null, proposed: 0, dropped: [] }
  expect([poSaid(lost), poTokens(lost)]).toEqual(['Sent, not heard out', '– tokens'])
  // at Full auto, the Lead's word; past the nine listed, counted
  expect(poSaid({ ...po, proposed: 3, dropped_more: 6, lead_added: 1 })).toBe('3 proposed · 7 dropped · Orchestrator added 1')
})

test('B-192: a suggestion is said apart from a finding left on the node line', () => {
  const said = (what: string, blocking: boolean) => ({ what, kind: 'code' as const, role: 'Coder', blocking })
  expect(findingsLine([said('greet says Helo', true), said('rename x', false)])?.line).toBe('1 finding left, 1 suggestion → Coder ×2')
  expect(findingsLine([said('rename x', false)])?.line).toBe('1 suggestion → Coder')
  expect(findingsLine([said('a', true), said('b', true)])?.line).toBe('2 findings → Coder ×2')
})
