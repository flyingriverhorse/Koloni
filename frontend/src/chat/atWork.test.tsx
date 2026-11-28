import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { useApp } from '../state/store'
import { agent, command, convState, fileChange, question, run, toolCall } from '../test-fixtures'
import { atWorkLine, waitsFor } from './atWork'
import { AtWorkLine } from './AtWorkLine'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  useApp.setState({ conv: null, showReady: useApp.getInitialState().showReady })
})

const child = (id: string, status: 'running' | 'waiting' | 'queued' | 'completed' | 'proposed' = 'running') =>
  agent(id, status, {
    id,
    run_id: 'r',
    name: id[0].toUpperCase() + id.slice(1),
    role_name: 'Coder',
    parent_agent_id: 'r',
    depth: 1,
    tool_call_id: `call-${id}`,
  })

const plan = [
  { step: 'Read', status: 'completed' as const },
  { step: 'Plan', status: 'completed' as const },
  { step: 'Build', status: 'inProgress' as const },
  { step: 'Test', status: 'pending' as const },
  { step: 'Review', status: 'pending' as const },
  { step: 'Ship', status: 'pending' as const },
]

const busy = (over = {}) =>
  convState({
    runs: [run('r', 'running')],
    agents: [agent('r', 'running'), child('coder'), child('tester', 'waiting'), child('scout', 'queued')],
    toolCalls: ['coder', 'tester', 'scout'].map(id => toolCall(`call-${id}`, 'r', 'spawn_agent', 'running')),
    commands: [command('c1', 'r', { status: 'proposed', agent_id: 'r' })],
    live: { r: { context: null, plan } },
    ...over,
  })

test('the line says each part, joined by a dot: agents at work, step, what waits for you, what it cost', () => {
  expect(atWorkLine(busy(), { spent: 0.4, currency: 'USD', at_least: false })).toBe(
    '3 agents at work · step 3 of 6 · 1 waits for you · ≈ 0.40 USD',
  )
})

test('no plan, no step; no price, no money; nothing at work, no line', () => {
  const one = busy({ agents: [agent('r', 'running'), child('coder'), child('old', 'completed')], live: {} })
  expect(atWorkLine(one, { spent: null, currency: null, at_least: false })).toBe('1 agent at work · 1 waits for you')
  expect(atWorkLine(busy({ agents: [agent('r', 'running')], commands: [], live: {} }), null)).toBeNull()
  expect(atWorkLine(busy({ runs: [run('r', 'completed')] }), null)).toBeNull()
  // (a turn waiting for your answer on a card still has its agents at work: the line stays)
  expect(atWorkLine(busy({ runs: [run('r', 'waiting_approval')], live: {} }), null)).toBe(
    '3 agents at work · 1 waits for you',
  )
})

test('the line reads what the turn cost, and opens At work in this turn with Stop and Message on each agent', async () => {
  const asked = vi.fn(async (url: string) =>
    url.endsWith('/spent')
      ? new Response(JSON.stringify({ spent: 0.4, currency: 'USD', at_least: true }), {
          headers: { 'Content-Type': 'application/json' },
        })
      : new Response(null, { status: 204 }),
  )
  vi.stubGlobal('fetch', asked)
  const showReady = vi.fn()
  const conv = busy()
  useApp.setState({ conv, showReady })
  render(<AtWorkLine conv={conv} />)
  const line = await screen.findByRole('button', {
    name: '3 agents at work · step 3 of 6 · 1 waits for you · ≥ 0.40 USD',
  })
  expect(asked).toHaveBeenCalledWith('/api/runs/r/spent', expect.anything())
  await userEvent.click(line)
  const panel = screen.getByRole('region', { name: 'At work in this turn' })
  expect(panel).toHaveTextContent(/Coder · working · since \d\d:\d\d/)
  expect(panel).toHaveTextContent(/Scout · waiting for a slot · since/)
  expect(within(panel).getByText('Plan (its own words)')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Stop Coder' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Message Tester' })).toBeInTheDocument()
  expect(screen.getByRole('list', { name: 'Plan (its own words)' })).toHaveTextContent('▸ Build')
  await userEvent.click(screen.getByRole('button', { name: 'Stop Coder' }))
  await waitFor(() =>
    expect(asked).toHaveBeenCalledWith('/api/agents/coder/stop', expect.objectContaining({ method: 'POST' })),
  )
  await userEvent.click(screen.getByRole('button', { name: 'Open Ready for you' }))
  expect(showReady).toHaveBeenCalledWith(true)
})

test('explain_wait: what each agent waits for, from the records alone - null where they say nothing', () => {
  const coder = child('coder', 'waiting')
  const one = (over = {}) => busy({ agents: [agent('r', 'running'), coder], commands: [], ...over })
  expect(
    waitsFor(
      one({ commands: [command('c', 'r', { agent_id: 'coder', status: 'proposed', command: 'npm test' })] }),
      coder,
    ),
  ).toBe('your yes on its command “npm test”')
  expect(
    waitsFor(
      one({ fileChanges: [fileChange('f', 'r', { agent_id: 'coder', status: 'proposed', path: 'a.py' })] }),
      coder,
    ),
  ).toBe('your yes on its change to “a.py”')
  const asked = question('q', 'r', { agent_id: 'coder', status: 'pending', question: 'Which greeting?' })
  expect(waitsFor(one({ questions: [asked] }), coder)).toBe('an answer to its question “Which greeting?”')
  expect(waitsFor(one({ questions: [{ ...asked, leave: true }] }), coder)).toBe(
    'an answer on a card of KOLONİ’s: “Which greeting?”',
  )
  const running = command('c', 'r', { agent_id: 'coder', status: 'running', command: 'pytest -q', started_at: null })
  expect(waitsFor(one({ commands: [running] }), coder)).toBe('its command “pytest -q”, running')
  const blocked = {
    ...child('blocked'),
    status: 'blocked' as const,
    waiting_for: { agent_id: 'x', agent_name: 'Tester', path: 'b.py' },
  }
  expect(waitsFor(one(), blocked)).toBe('Tester, which holds “b.py”')
  const queued = { ...child('q', 'queued'), queued_on: { provider: 'Local', at_work: 1, most: 1 } }
  expect(waitsFor(one(), queued)).toBe('a place at Local (1 of 1 at work there)')
  expect(waitsFor(one(), child('q2', 'queued'))).toBe('a place among the turn’s agents at work')
  const helper = { ...child('helper'), parent_agent_id: 'coder' }
  expect(waitsFor(one({ agents: [agent('r', 'running'), coder, helper] }), coder)).toBe(
    'its own agents at work: Helper',
  )
  expect(waitsFor(one(), child('free'))).toBeNull()
})

test('At work in this turn says what an agent waits for, where its records say it', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ spent: null, currency: null, at_least: false }))),
  )
  const conv = busy({ commands: [command('c1', 'r', { agent_id: 'coder', status: 'running', command: 'pytest -q' })] })
  useApp.setState({ conv })
  render(<AtWorkLine conv={conv} />)
  await userEvent.click(screen.getByRole('button', { name: /^3 agents at work/ }))
  const panel = screen.getByRole('region', { name: 'At work in this turn' })
  expect(panel).toHaveTextContent(/Coder · working · since \d\d:\d\d · waits for its command “pytest -q”, running/)
  expect(panel).toHaveTextContent(/Scout · waiting for a slot · since \d\d:\d\d · waits for a place among/)
})
