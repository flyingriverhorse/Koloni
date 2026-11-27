import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { type Node, type NodeProps, ReactFlowProvider } from '@xyflow/react'
import { afterEach, expect, test, vi } from 'vitest'
import type { Provider } from '../api/types'
import { AgentWindow } from '../agents/AgentWindow'
import { useApp } from '../state/store'
import { agent, conversation, convState, run, toolCall } from '../test-fixtures'
import { canStop } from './agentStop'
import type { AgentData } from './deriveGraph'
import { AgentNode } from './nodes'

afterEach(() => {
  vi.unstubAllGlobals()
  useApp.setState({ conv: null, providers: [] })
})

const coder = (over = {}) =>
  agent('coder', 'running', { run_id: 'r', name: 'Coder', parent_agent_id: 'r', tool_call_id: 's1', ...over })

const state = (one = coder(), calls = [toolCall('s1', 'r', 'spawn_agent', 'running')]) =>
  convState({ runs: [run('r', 'running')], agents: [agent('r', 'running'), one], toolCalls: calls })

const data: AgentData = {
  role: 'Coder',
  name: 'Coder',
  parentId: 'agent:r',
  provider: 'Local',
  modelId: 'qwen',
  modelFrom: null,
  status: 'running',
  activity: 'Working',
  since: null,
  wrote: null,
  kind: null,
  sign: null,
  signStopped: false,
  findings: null,
  inside: 0,
  summary: '',
  attention: false,
  finished: false,
  open: true,
}

function node() {
  const props = { id: 'agent:coder', data, selected: false } as unknown as NodeProps<
    Node<AgentData & Record<string, unknown>>
  >
  render(
    <ReactFlowProvider>
      <AgentNode {...props} />
    </ReactFlowProvider>,
  )
}

test('an agent may be stopped alone only while at work, below the Orchestrator, opened with spawn_agent - not a check, nor a recipe step', () => {
  expect(canStop(state(), coder())).toBe(true)
  for (const status of ['queued', 'waiting', 'blocked'] as const) expect(canStop(state(), coder({ status }))).toBe(true)
  for (const status of ['proposed', 'completed', 'failed', 'cancelled'] as const)
    expect(canStop(state(), coder({ status }))).toBe(false)
  expect(canStop(state(), coder({ parent_agent_id: null }))).toBe(false) // the Orchestrator: the turn's Stop
  expect(canStop(state(), coder({ tool_call_id: null }))).toBe(false)
  const look = [toolCall('s1', 'r', 'spawn_agent', 'running', '{}', { provider_call_id: 'koloni_proof_review_1' })]
  expect(canStop(state(coder(), look), coder())).toBe(false) // KOLONİ's own look: Stop this check
  const asked = [toolCall('s1', 'r', 'request_work', 'running')]
  expect(canStop(state(coder(), asked), coder())).toBe(false)
  const recipe = {
    ...state(),
    conversation: {
      ...conversation,
      teams: [
        {
          team_id: 't',
          recipe_id: 'x',
          no_recipe: false,
          picked_by: 'user' as const,
          why: null,
          state: {
            run_id: 'r',
            team: 'Web',
            recipe: 'Build',
            status: 'running' as const,
            agents: ['coder'],
            steps: [],
            passes: [],
          },
        },
      ],
    },
  }
  expect(canStop(recipe, coder())).toBe(false) // its team's Stop
})

test('Stop and Message on a node at work: Stop asks the server, Message opens its window at Tell', async () => {
  const asked = vi.fn(async () => new Response(null, { status: 204 }))
  vi.stubGlobal('fetch', asked)
  const opened = vi.fn()
  useApp.setState({ conv: state(), openAgentWindow: opened })
  node()
  await userEvent.click(screen.getByRole('button', { name: 'Stop Coder' }))
  expect(asked).toHaveBeenCalledWith('/api/agents/coder/stop', expect.objectContaining({ method: 'POST' }))
  await userEvent.click(screen.getByRole('button', { name: 'Message Coder' }))
  expect(opened).toHaveBeenCalledWith('coder')
  cleanup()
  // Over: its window's button alone, as before.
  useApp.setState({ conv: state(coder({ status: 'completed' })) })
  node()
  expect(screen.queryByRole('button', { name: 'Stop Coder' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Message Coder' })).toBeNull()
  expect(screen.getByRole('button', { name: "Open Coder's window" })).toBeInTheDocument()
})

test('a refused Stop says why on the node', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ detail: 'Coder has finished' }), { status: 409 })),
  )
  useApp.setState({ conv: state() })
  node()
  await userEvent.click(screen.getByRole('button', { name: 'Stop Coder' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Coder has finished')
})

test("an agy agent hears nothing while it works: its window's box tells the Orchestrator instead", async () => {
  const asked = vi.fn(async () => new Response(null, { status: 204 }))
  vi.stubGlobal('fetch', asked)
  const one = coder({ provider_name: 'Agy', provider_mode: 'native' })
  const s = state(one)
  useApp.setState({ conv: s, providers: [{ name: 'Agy', kind: 'agy_cli' }] as Provider[] })
  render(<AgentWindow state={s} agentId="coder" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(
    screen.getByText(
      "Coder can't hear messages while it works (Agy). Tell the Orchestrator instead - it can stop it and start it again.",
    ),
  ).toBeInTheDocument()
  expect(screen.queryByRole('textbox', { name: 'Tell Coder' })).toBeNull()
  const box = screen.getByRole('textbox', { name: 'Tell the Orchestrator about Coder' })
  expect(box).toHaveAttribute('placeholder', 'Tell the Orchestrator about Coder…')
  await userEvent.type(box, 'use blue')
  await userEvent.click(screen.getByRole('button', { name: 'Send to Coder' }))
  expect(asked).toHaveBeenCalledWith(
    '/api/agents/coder/tell',
    expect.objectContaining({ method: 'POST', body: JSON.stringify({ words: 'use blue', to_lead: true }) }),
  )
  expect(await screen.findByText('Sent to the Orchestrator')).toHaveAttribute('role', 'status')
  // Its window's head has its Stop too.
  expect(screen.getByRole('button', { name: 'Stop Coder' })).toBeInTheDocument()
})
