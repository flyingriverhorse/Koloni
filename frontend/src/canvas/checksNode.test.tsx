import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ReactFlowProvider } from '@xyflow/react'
import { expect, test, vi } from 'vitest'
import { api } from '../api/client'
import type { Message } from '../api/types'
import { useApp } from '../state/store'
import { agent, assistantMessage, command, convState, run, toolCall } from '../test-fixtures'
import { type ChecksData, checksNode, lineOf, linesOf, stripOf, toolOf } from './checksNode'
import { type AgentData, deriveGraph, type GraphEdge, type GraphNode } from './deriveGraph'
import { ChecksNode } from './nodes'

type Row = NonNullable<Message['checked']>[number]
const row = (state: Row['state'], text: string, more: Partial<Row> = {}): Row => ({
  kind: 'tests',
  state,
  text,
  command: null,
  guessed: false,
  started_at: null,
  counts: null,
  ...more,
})
const checked = (rows: Row[]): Message => ({
  ...assistantMessage('k', 'r', 'x'),
  role: 'checked',
  agent_id: null,
  checked: rows,
})
const proofCall = (
  id: string,
  status: 'running' | 'succeeded',
  started = '2026-10-05T10:00:03Z',
  line = 'python -m pytest -q',
) =>
  toolCall(id, 'r', 'run_command', status, JSON.stringify({ command: line }), {
    provider_call_id: `koloni_proof_${id}`,
    started_at: started,
  })

function drawn(state: ReturnType<typeof convState>) {
  const nodes: GraphNode[] = [{ id: 'agent:r', kind: 'agent', runId: 'r', refId: 'r', data: {} as AgentData }]
  const edges: GraphEdge[] = []
  const data = checksNode(state, run('r', 'completed'), nodes, edges)
  return { data, nodes, edges }
}

test('a test run at work shows its tool and when it started, and no number it has not got', () => {
  // (Its clock is its command's: the call may have waited for a free slot before it ran.)
  const waiting = drawn(convState({ runs: [run('r')], agents: [agent('r')], toolCalls: [proofCall('p1', 'running')] }))
  expect(waiting.data?.running).toEqual({ command: 'python -m pytest -q', since: null })
  const { data, nodes } = drawn(
    convState({
      runs: [run('r')],
      agents: [agent('r')],
      toolCalls: [proofCall('p1', 'running')],
      commands: [command('c1', 'r', { tool_call_id: 'p1', started_at: '2026-10-05T10:00:09Z' })],
    }),
  )
  expect(data?.running).toEqual({ command: 'python -m pytest -q', since: '2026-10-05T10:00:09Z' })
  expect(data?.lines).toEqual([])
  expect((nodes[0].data as AgentData).checked).toBe('● checking…')
})

test('S5b: a live try of KOLONİ’s - a tool’s --help, a dev server - is no test run of the turn', () => {
  const tried = (id: string, line: string) => ({
    ...proofCall(id, 'running', '2026-10-05T10:00:03Z', line),
    provider_call_id: `koloni_proof_try_${id}`,
  })
  const { data } = drawn(
    convState({
      runs: [run('r')],
      agents: [agent('r')],
      toolCalls: [proofCall('p1', 'succeeded'), tried('t1', 'npm run dev'), tried('t2', 'npm run dev')],
    }),
  )
  expect(data?.running).toBeNull()
  expect(data?.rounds).toBe(0)
})

test('the Checked rows are its lines, with their counts where the runner gave them', () => {
  const rows = [
    row('passed', 'Tests passed: python -m pytest -q - 214 passed', {
      command: 'python -m pytest -q',
      counts: { passed: 214, failed: 0, skipped: 0, unit: 'tests' },
    }),
    row('note', 'Saved as this project’s test command - change it in Settings', { kind: 'found' }),
  ]
  const { data, nodes } = drawn(
    convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed')], messages: [checked(rows)] }),
  )
  expect(data?.lines).toEqual([
    { state: 'passed', text: 'pytest · 214 ✓' },
    { state: 'note', text: rows[1].text },
  ])
  expect((nodes[0].data as AgentData).checked).toBe('✓ checked')
})

test('a fix round is counted on the Orchestrator’s strip - no line goes back to it (tuval-kontrol-dongusu)', () => {
  const passes = {
    runs: [run('r', 'completed')],
    agents: [agent('r', 'completed')],
    toolCalls: [proofCall('p1', 'succeeded'), proofCall('p2', 'succeeded', '2026-10-05T10:01:03Z')],
    commands: [
      command('c1', 'r', { tool_call_id: 'p1', exit_code: 1 }),
      command('c2', 'r', { tool_call_id: 'p2', exit_code: 0 }),
    ],
  }
  // (Before the Checked section says its rounds: a pass again is one; neither the Fix rounds nor why are known.)
  const live = drawn(convState(passes))
  expect(live.data?.rounds).toBe(1)
  const passed = row('passed', 'Tests passed', {
    command: 'python -m pytest -q',
    counts: { passed: 4, failed: 0, skipped: 0, unit: 'tests' },
  })
  const sent = row('note', 'Sent back to fix: 1 of 2 rounds', { kind: 'rounds' })
  const { data, edges, nodes } = drawn(convState({ ...passes, messages: [checked([sent, passed])] }))
  expect(data?.rounds).toBe(1)
  expect(edges.map(e => e.target)).toEqual(['checks:r'])
  expect((nodes[0].data as AgentData).checked).toBe('✓ checked · 1 round')
})

test('k-canli-016: until it passes - the rounds the Checked section says, on the strip', () => {
  const failed = row('failed', 'Tests failed', { command: 'pytest' })
  const sent = row('note', 'Sent back to fix: round 3 (until it passes, 3 failing → 1)', { kind: 'rounds' })
  const stop = row('failed', 'Stopped after round 3: no progress in two rounds - you decide (Fix it)', {
    kind: 'rounds',
  })
  const { data, edges, nodes } = drawn(
    convState({
      runs: [run('r', 'completed')],
      agents: [agent('r', 'completed')],
      messages: [checked([failed, sent, stop])],
    }),
  )
  expect(data?.rounds).toBe(3)
  expect(edges.map(e => e.target)).toEqual(['checks:r'])
  expect((nodes[0].data as AgentData).checked).toBe('✗ still failing · 3 rounds')
})

test('the tests run again on the test KOLONİ asked for are no fix round: at its end the Checked section counts them', () => {
  // (0.1.6's pictures: a turn sent back nowhere drew "round 1" round behind both boxes, and its strip said "1 round".)
  const passed = row('passed', 'Tests passed', {
    command: 'python -m pytest -q',
    counts: { passed: 4, failed: 0, skipped: 0, unit: 'tests' },
  })
  const { data, edges, nodes } = drawn(
    convState({
      runs: [run('r', 'completed')],
      agents: [agent('r', 'completed')],
      toolCalls: [proofCall('p1', 'succeeded'), proofCall('p2', 'succeeded', '2026-10-05T10:01:03Z')],
      commands: [
        command('c1', 'r', { tool_call_id: 'p1', exit_code: 0 }),
        command('c2', 'r', { tool_call_id: 'p2', exit_code: 0 }),
      ],
      messages: [checked([passed, row('note', 'No new test: the Orchestrator said “x”', { kind: 'test_ask' })])],
    }),
  )
  expect(data?.rounds).toBe(0)
  expect(edges).toHaveLength(1)
  expect((nodes[0].data as AgentData).checked).toBe('✓ checked')
})

test('two parts failing in one pass are one round, not two; a pass again is one', () => {
  const failing = (id: string, line: string, started: string) =>
    [proofCall(id, 'succeeded', started, line), command(`c${id}`, 'r', { tool_call_id: id, exit_code: 1 })] as const
  const [api, apiRun] = failing('p1', 'mvn test', '2026-10-05T10:00:03Z')
  const [web, webRun] = failing('p2', 'npm test', '2026-10-05T10:00:04Z')
  const one = drawn(
    convState({
      runs: [run('r', 'completed')],
      agents: [agent('r', 'completed')],
      toolCalls: [api, web],
      commands: [apiRun, webRun],
    }),
  )
  expect(one.data?.rounds).toBe(0)
  const [again, againRun] = failing('p3', 'mvn test', '2026-10-05T10:02:00Z')
  const two = drawn(
    convState({
      runs: [run('r', 'completed')],
      agents: [agent('r', 'completed')],
      toolCalls: [api, web, again],
      commands: [apiRun, webRun, againRun],
    }),
  )
  expect(two.data?.rounds).toBe(1)
  // (A pass after a round that ran nothing - the Orchestrator's own run stood: its end says so.)
  const sent = checked([
    row('note', 'Sent back to fix: 1 of 2 rounds', { kind: 'rounds' }),
    row('passed', 'Tests passed'),
  ])
  const stood = drawn(
    convState({
      runs: [run('r', 'completed')],
      agents: [agent('r', 'completed')],
      toolCalls: [api],
      commands: [apiRun],
      messages: [sent],
    }),
  )
  expect(stood.data?.rounds).toBe(1)
})

test('a count with none passed or failed is the row’s own words; go counts packages', () => {
  const skipped = row('passed', 'Tests passed: npx jest (guessed) - 2 skipped', {
    command: 'npx jest',
    counts: { passed: 0, failed: 0, skipped: 2, unit: 'tests' },
  })
  expect(lineOf(skipped)).toEqual({ state: 'passed', text: skipped.text })
  const go = row('failed', 'Tests failed', {
    command: 'go test ./...',
    counts: { passed: 3, failed: 1, skipped: 0, unit: 'packages' },
  })
  expect(lineOf(go)).toEqual({ state: 'failed', text: 'go · 3 packages ✓ · 1 ✗' })
})

test('nothing checked: no node, and the canvas draws it through deriveGraph where there is', () => {
  expect(drawn(convState({ runs: [run('r')], agents: [agent('r')] })).data).toBeNull()
  const graph = deriveGraph(
    convState({
      runs: [run('r', 'completed')],
      agents: [agent('r', 'completed')],
      messages: [checked([row('failed', 'Tests failed')])],
    }),
  )
  expect(graph.nodes.find(n => n.kind === 'checks')?.id).toBe('checks:r')
})

test('the strip says still failing or not checked; the tool is the runner, not python', () => {
  const base: ChecksData = {
    runId: 'r',
    leadId: 'r',
    running: null,
    lines: [],
    stoppable: false,
    rounds: 2,
    recipe: false,
  }
  expect(stripOf({ ...base, lines: [{ state: 'failed', text: 'x' }] })).toBe('✗ still failing · 2 rounds')
  expect(stripOf({ ...base, lines: [{ state: 'not_run', text: 'No test command' }] })).toBe('not checked')
  expect(stripOf(base)).toBeNull()
  // (S6: a whole suite still running is no "checked"; one stopped leaves the related tests' pass alone said)
  const related = { state: 'passed', text: 'related tests · 12 passed' } as const
  expect(stripOf({ ...base, rounds: 0, lines: [related, { state: 'running', text: 'full tests', since: 'x' }] })).toBe(
    '● checking…',
  )
  expect(
    stripOf({
      ...base,
      rounds: 0,
      lines: [related, { state: 'not_run', text: 'full tests · stopped by you at 1:02 - not checked' }],
    }),
  ).toBe('✓ checked · related only')
  expect(toolOf('python -m pytest -q')).toBe('pytest')
  expect(toolOf('npx vitest run')).toBe('vitest')
  expect(toolOf('go test ./...')).toBe('go')
  expect(toolOf('npx --no c8 --reporter=json --report-dir ".koloni/tmp/coverage-1" npm test')).toBe('c8')
  // (Code handed to an interpreter on the line: its program and flag, never its quoted code.)
  expect(toolOf(`python -c "import time; time.sleep(20); print('3 passed')"`)).toBe('python -c')
  expect(toolOf(`node -e "require('./check')"`)).toBe('node -e')
  expect(toolOf('bash -c "make test -m x"')).toBe('bash -c')
  expect(toolOf('/usr/bin/python3 -c "print(1)"')).toBe('python3 -c')
  expect(toolOf('pytest -c pytest.ini -q')).toBe('pytest')
  expect(toolOf('python -m pytest -c pytest.ini')).toBe('pytest')
})

test('S9: the coverage row is a line like the others, and no test run of its own', () => {
  const rows = [
    row('passed', 'Tests passed: python -m pytest -q - 4 passed', {
      command: 'python -m pytest -q',
      counts: { passed: 4, failed: 0, skipped: 0, unit: 'tests' },
    }),
    row('note', 'Coverage: 67% of the changed lines are run by tests (pytest-cov)', {
      kind: 'coverage',
      command: 'python -m pytest -q',
    }),
  ]
  const { data, nodes } = drawn(
    convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed')], messages: [checked(rows)] }),
  )
  expect(data?.lines).toEqual([
    { state: 'passed', text: 'pytest · 4 ✓' },
    { state: 'note', text: rows[1].text },
  ])
  expect((nodes[0].data as AgentData).checked).toBe('✓ checked')
})

function shown(data: ChecksData) {
  const props = {
    id: 'checks:r',
    data,
    selected: false,
    type: 'checks',
    dragging: false,
    zIndex: 0,
    isConnectable: false,
    positionAbsoluteX: 0,
    positionAbsoluteY: 0,
    draggable: false,
    selectable: false,
    deletable: false,
  }
  return render(
    <ReactFlowProvider>
      <ChecksNode {...(props as Parameters<typeof ChecksNode>[0])} />
    </ReactFlowProvider>,
  )
}

test('the node shows what runs now and each line; its ⋯ stops the check and opens its log', async () => {
  const post = vi.spyOn(api, 'post').mockResolvedValue({} as never)
  const opened = vi.fn()
  useApp.setState({ openAgentWindow: opened })
  try {
    shown({
      runId: 'r',
      leadId: 'r',
      running: { command: 'python -m pytest -q', since: null },
      lines: [{ state: 'failed', text: 'pytest · 12 ✓ · 2 ✗' }],
      stoppable: true,
      rounds: 0,
      recipe: true,
    })
    expect(screen.getByText('● pytest')).toBeInTheDocument()
    expect(screen.getByText('✗ pytest · 12 ✓ · 2 ✗')).toHaveAttribute('data-state', 'failed')
    expect(screen.getByText('KOLONİ · end of the recipe')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Checks: more' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Stop this check' }))
    expect(post).toHaveBeenCalledWith('/runs/r/check/stop')
    await userEvent.click(screen.getByRole('button', { name: 'Checks: more' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Open its log' }))
    expect(opened).toHaveBeenCalledWith('r')
  } finally {
    vi.restoreAllMocks()
  }
})

test('with nothing running the menu has no Stop', async () => {
  shown({
    runId: 'r',
    leadId: 'r',
    running: null,
    lines: [{ state: 'passed', text: 'pytest · 4 ✓' }],
    stoppable: false,
    rounds: 0,
    recipe: false,
  })
  await userEvent.click(screen.getByRole('button', { name: 'Checks: more' }))
  expect(screen.queryByRole('menuitem', { name: 'Stop this check' })).toBeNull()
  expect(screen.getByRole('menuitem', { name: 'Open its log' })).toBeInTheDocument()
})

test('S6 rows on the node: the related step, the whole suite running after the answer with its clock, waiting, stopped', () => {
  const related = row('passed', 'Related tests passed: pytest -q t.py - 12 passed in 2s', {
    command: 'pytest -q t.py',
    counts: { passed: 12, failed: 0, skipped: 0, unit: 'tests' },
  })
  expect(lineOf(related)).toEqual({ state: 'passed', text: 'related tests · 12 passed' })
  const waiting = row('running', 'Full tests waiting for another test run to end: pytest -q', { command: 'pytest -q' })
  expect(lineOf(waiting)).toEqual({ state: 'running', text: 'full tests · waiting for another test run to end' })
  const stopped = row('not_run', 'Full tests stopped by you at 1:02 - not checked', { command: 'pytest -q' })
  expect(lineOf(stopped)).toEqual({ state: 'not_run', text: 'full tests · stopped by you at 1:02 - not checked' })
  const going = row('running', 'Full tests running: pytest -q', {
    command: 'pytest -q',
    started_at: '2026-11-22T10:00:00+00:00',
  })
  // (Once the Checked section is written, the suite still running is its row - not a second "running" line - and Stop is offered.)
  const { data } = drawn(
    convState({
      runs: [run('r', 'completed')],
      agents: [agent('r', 'completed')],
      toolCalls: [proofCall('p1', 'running', '2026-11-22T09:59:00Z', 'pytest -q')],
      messages: [checked([related, going])],
    }),
  )
  expect(data?.running).toBeNull()
  expect(data?.lines[1]).toEqual({ state: 'running', text: 'full tests', since: '2026-11-22T10:00:00+00:00' })
  expect(data?.stoppable).toBe(true)
  vi.useFakeTimers({ now: Date.parse('2026-11-22T10:01:02Z'), toFake: ['Date', 'setInterval', 'clearInterval'] })
  try {
    shown(data!)
    const line = () => document.querySelector('.node-line[data-state=running]')
    expect(line()).toHaveTextContent('● full tests · 1:02 …')
    act(() => vi.advanceTimersByTime(2000))
    expect(line()).toHaveTextContent('● full tests · 1:04 …')
  } finally {
    vi.useRealTimers()
  }
})

test('a turn of a chat with checks off: no node - the Orchestrator’s strip says it', () => {
  const nodes: GraphNode[] = [{ id: 'agent:r', kind: 'agent', runId: 'r', refId: 'r', data: {} as AgentData }]
  const edges: GraphEdge[] = []
  const state = convState({
    runs: [run('r', 'completed')],
    agents: [agent('r', 'completed')],
    messages: [checked([row('note', 'Not checked: off for this chat', { kind: 'chat_off' })])],
  })
  expect(checksNode(state, run('r', 'completed'), nodes, edges)).toBeNull()
  expect(nodes.map(node => node.kind)).toEqual(['agent'])
  expect((nodes[0].data as AgentData).checked).toBe('not checked · off for this chat')
  expect(deriveGraph(state).nodes.some(node => node.kind === 'checks')).toBe(false)
})

test('a turn of a project whose After a change is Nothing: no node, and no strip - the Checked section says it', () => {
  // (CI, 0.1.6: the e2e project at Nothing drew a Checks node for a turn KOLONİ checked nothing in; then its strip took the
  // agent node's last line, "3 files" - the project's standing choice is not said on every Orchestrator)
  const nodes: GraphNode[] = [{ id: 'agent:r', kind: 'agent', runId: 'r', refId: 'r', data: {} as AgentData }]
  const rows = [
    row('note', 'Not checked: After a change is set to Nothing', { kind: 'not_checked' }),
    row('note', 'Last test run: pytest -q, passed, after the last change', { kind: 'tests' }),
  ]
  const state = convState({
    runs: [run('r', 'completed')],
    agents: [agent('r', 'completed')],
    messages: [checked(rows)],
  })
  expect(checksNode(state, run('r', 'completed'), nodes, [])).toBeNull()
  expect((nodes[0].data as AgentData).checked).toBeUndefined()
  expect(deriveGraph(state).nodes.some(node => node.kind === 'checks')).toBe(false)
})

test('the menu turns checks off for this chat - not where they are off already', async () => {
  const off = vi.fn().mockResolvedValue(undefined)
  const conv = convState({})
  useApp.setState({
    conv: { ...conv, conversation: { ...conv.conversation, after_change: null } },
    setAfterChange: off,
  })
  const data: ChecksData = {
    runId: 'r',
    leadId: 'r',
    running: null,
    lines: [{ state: 'passed', text: 'pytest · 4 ✓' }],
    stoppable: false,
    rounds: 0,
    recipe: false,
  }
  const { unmount } = shown(data)
  await userEvent.click(screen.getByRole('button', { name: 'Checks: more' }))
  await userEvent.click(screen.getByRole('menuitem', { name: 'Off for this chat' }))
  expect(off).toHaveBeenCalledWith('off')
  unmount()
  useApp.setState({ conv: { ...conv, conversation: { ...conv.conversation, after_change: 'off' } } })
  shown(data)
  await userEvent.click(screen.getByRole('button', { name: 'Checks: more' }))
  expect(screen.queryByRole('menuitem', { name: 'Off for this chat' })).toBeNull()
})

test('S3: KOLONİ’s Reviewer is drawn in the Checks box, not as a node of its own; no round goes back as a line', () => {
  const state = convState({
    runs: [run('r', 'completed')],
    agents: [
      agent('r', 'completed'),
      {
        ...agent('rv', 'completed', { role_name: 'Reviewer' }),
        run_id: 'r',
        depth: 1,
        parent_agent_id: 'r',
        tool_call_id: 'look',
      },
    ],
    toolCalls: [
      proofCall('p1', 'succeeded'),
      toolCall('look', 'r', 'spawn_agent', 'succeeded', '{}', { provider_call_id: 'koloni_proof_review_1' }),
    ],
    messages: [
      {
        ...checked([
          row('passed', 'Tests passed'),
          row('note', 'Sent back to fix: 2 of 3 rounds (tests fail; 2 blocking findings)', { kind: 'rounds' }),
        ]),
        passes: [
          {
            n: 1,
            kind: 'check',
            tests: 'passed',
            looks: [{ agent_id: 'rv', role: 'Reviewer', verdict: 'MERGE' }],
            why: null,
            sent: null,
            fixers: [],
            diagnosis: null,
            tier: null,
          },
        ],
      },
    ],
  })
  const graph = deriveGraph(state)
  expect(graph.nodes.some(n => n.id === 'agent:rv')).toBe(false)
  expect(graph.edges.some(e => e.source === 'agent:rv' || e.target === 'agent:rv')).toBe(false)
  expect(graph.edges.filter(e => e.target === 'checks:r' || e.source === 'checks:r').map(e => e.id)).toEqual([
    'agent:r>checks:r',
  ])
  expect((graph.nodes.find(n => n.kind === 'checks')!.data as ChecksData).loop).toMatchObject({
    agents: ['rv'],
    looks: [{ agentId: 'rv', name: 'Reviewer' }],
  })
  // (Its spawn is no test run: the node runs nothing now.)
  expect(graph.nodes.find(n => n.kind === 'checks')?.data).toMatchObject({ running: null })
})

test('S5a: a kind of work is one line, as a test run is - its files that passed and failed; switched off, not checked', () => {
  const rows = [
    row('note', 'No tests: only documents, slides, diagrams or data changed'),
    row('passed', 'README.md: 3 links, all found', { kind: 'docs' }),
    row('failed', 'guide.md: link to x.md not found', { kind: 'docs' }),
    row('note', 'Spelling: not checked', { kind: 'docs' }),
    row('passed', 'a.csv: 3 rows × 2 columns', { kind: 'data' }),
    row('note', 'Not checked: slides switched off for this project', { kind: 'slides' }),
  ]
  expect(linesOf(rows)).toEqual([
    { state: 'note', text: rows[0].text },
    { state: 'failed', text: 'documents · 1 ✓ · 1 ✗' },
    { state: 'passed', text: 'data · 1 ✓' },
    { state: 'note', text: 'slides · not checked' },
  ])
  const { data, nodes } = drawn(
    convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed')], messages: [checked(rows)] }),
  )
  expect(data?.lines).toHaveLength(4)
  expect((nodes[0].data as AgentData).checked).toBe('✗ still failing')
})

test('S5c: a recipe’s turn whose Checks step checks nothing: no node - the strip says so', () => {
  const nodes: GraphNode[] = [{ id: 'agent:r', kind: 'agent', runId: 'r', refId: 'r', data: {} as AgentData }]
  const rows = [row('note', "Not checked: this recipe's Checks step checks nothing", { kind: 'recipe_off' })]
  const state = convState({
    runs: [run('r', 'completed')],
    agents: [agent('r', 'completed')],
    messages: [checked(rows)],
  })
  expect(checksNode(state, run('r', 'completed'), nodes, [])).toBeNull()
  expect((nodes[0].data as AgentData).checked).toBe('not checked · off in the recipe’s Checks step')
})

test('k-canli-016: tests passed and a Reviewer holds - the strip says on hold, not still failing', () => {
  const passed = row('passed', 'Tests passed', {
    command: 'python -m pytest -q',
    counts: { passed: 11, failed: 0, skipped: 0, unit: 'tests' },
  })
  const hold = row('failed', 'Still on hold after round 1: not settled by the last look - you decide (Fix it)', {
    kind: 'review',
  })
  const sent = row('note', 'Sent back to fix: 1 of 2 rounds (3 blocking findings)', { kind: 'rounds' })
  const held = drawn(
    convState({
      runs: [run('r', 'completed')],
      agents: [agent('r', 'completed')],
      messages: [checked([passed, sent, hold])],
    }),
  )
  expect((held.nodes[0].data as AgentData).checked).toBe('✗ on hold · 1 round')
  const failing = drawn(
    convState({
      runs: [run('r', 'completed')],
      agents: [agent('r', 'completed')],
      messages: [checked([row('failed', 'Tests failed', { command: 'pytest' }), hold])],
    }),
  )
  expect((failing.nodes[0].data as AgentData).checked).toBe('✗ still failing')
})
