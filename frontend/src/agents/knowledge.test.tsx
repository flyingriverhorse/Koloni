import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { Knowledge, KnowledgeItem, KnowledgeState, Role } from '../api/types'
import { AgentsPage } from './AgentsPage'
import { RoleCard } from './SpawnApproval'

// K-uzman: an expert is made from the Expert template (only what it knows and its sources). K-bilgi (sample E): a role's
// Knowledge tab is the project's knowledge, each switched on or off and, when on, Full or Map - the rest is the Knowledge page's.
const role = (over: Partial<Role>): Role => ({
  id: 'r1',
  name: 'Pay expert',
  description: 'Knows Pay.',
  instructions: '',
  tools: ['list_dir', 'read_file', 'search', 'message_agent'],
  builtin: false,
  created_by_agent: false, models: null,
  provider_id: null,
  model_id: null,
  tier: null,
  tier_min: null,
  tier_max: null,
  kind: 'plan',
  enabled: true,
  teams: [],
  pick_from: null,
  max_steps: null,
  max_tokens: null,
  effort: null,
  max_effort: null,
  context_window: null,
  mcp: [],
  skills: [],
  inside_cli: false,
  // K-bilgi: the knowledge it uses in full, on the open project's Knowledge page (`items`).
  knows: [{ knowledge_id: 'k1', mode: 'full', topic: 'Pay', project_id: 'p1' }],
  created_at: 't',
  updated_at: 't',
  ...over,
})
const PAY: Knowledge = { topic: 'Pay', sources: ['https://docs.test/pay'], max_pages: 20, max_usd: 0.5, max_code_files: 100, learn_with: null, weekly: false, search_answering: false }
const LEARNED: KnowledgeState = {
  learning: false,
  stale: null,
  failed: null,
  folder: '.koloni/knowledge/pay/',
  guide: '## What it offers\n- pay(amount)',
  learned: {
    learned_at: '2026-10-26T14:02:00+00:00',
    model: 'Claude Code · haiku',
    guide_from: 2,
    unread: 0,
    left: 0,
    cost: null,
    added: [],
    pages: [
      { source: 'https://docs.test/pay/start.md', read: true, why: null, found: false, code: false },
      { source: 'https://docs.test/pay/webhooks', read: true, why: null, found: false, code: false },
    ],
  },
}
const ITEMS: KnowledgeItem[] = [
  { id: 'k1', project_id: 'p1', knowledge: PAY, used_by: [], state: LEARNED },
  { id: 'k2', project_id: null, knowledge: { ...PAY, topic: 'MLflow' }, used_by: [], state: { ...LEARNED, learned: null, guide: null } },
]
const handlers = () => ({
  onSave: vi.fn().mockResolvedValue(undefined),
  onCreate: vi.fn().mockResolvedValue(undefined),
  onDelete: vi.fn().mockResolvedValue(undefined),
  onReset: vi.fn().mockResolvedValue(undefined),
})

async function openTab(one: Role, over: object = {}) {
  const useKnowledge = vi.fn().mockResolvedValue(undefined)
  const onOpenKnowledge = vi.fn()
  render(<AgentsPage roles={[one]} projectId="p1" knowledge={ITEMS} knowledgeActions={{ useKnowledge }} onOpenKnowledge={onOpenKnowledge} {...handlers()} {...over} />)
  await userEvent.click(screen.getByRole('button', { name: new RegExp(`^${one.name}`) }))
  await userEvent.click(screen.getByRole('tab', { name: 'Knowledge' }))
  return { useKnowledge, onOpenKnowledge }
}

test('the Expert template asks only what it knows and its sources, and makes a role that reads only', async () => {
  const h = handlers()
  const actions = { createExpert: vi.fn().mockResolvedValue({ id: 'r9' }) }
  render(<AgentsPage roles={[]} projectId="p1" knowledgeActions={actions} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: 'New role' }))
  await userEvent.click(screen.getByRole('button', { name: 'An expert' }))
  // decision 4: the form's body is the expert's own; it may only read, said once
  expect(screen.getByText(/reads only — an expert changes nothing/)).toBeInTheDocument()
  expect(screen.queryByLabelText('Instructions')).not.toBeInTheDocument()
  await userEvent.type(screen.getByLabelText('Knows'), 'Stripe')
  await userEvent.type(screen.getByLabelText('Sources'), 'https://docs.stripe.com/payments\n\ndocs/stripe.pdf')
  await userEvent.click(screen.getByRole('button', { name: 'Create expert' }))
  // K-bilgi: one request - the role, its knowledge on the project's page, the role using it in full.
  expect(h.onCreate).not.toHaveBeenCalled()
  expect(actions.createExpert).toHaveBeenCalledTimes(1)
  const [sent, knowledge] = actions.createExpert.mock.calls[0]
  expect(sent.name).toBe('Stripe expert')
  expect(sent.tools).not.toContain('write_file')
  expect(sent.tools).not.toContain('run_command')
  expect(knowledge).toEqual({ topic: 'Stripe', sources: ['https://docs.stripe.com/payments', 'docs/stripe.pdf'], max_pages: 500, max_usd: 0.5, max_code_files: 100, learn_with: null, removed: [], weekly: false, search_answering: false })
})

test('a role’s Knowledge tab switches each knowledge of the project on, as a map, and to Full; the rest is on the Knowledge page', async () => {
  const { useKnowledge, onOpenKnowledge } = await openTab(role({ knows: [] }))
  // Only the switches: no sources, limits, Learn or pages here.
  expect(screen.queryByLabelText('Sources')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Learn/ })).not.toBeInTheDocument()
  expect(screen.queryByText(/^Pages:/)).not.toBeInTheDocument()
  expect(screen.getByText(/2 pages read/)).toBeInTheDocument()
  expect(screen.getByText(/not learned · every project/)).toBeInTheDocument()
  const pay = screen.getByRole('switch', { name: 'Knowledge Pay' })
  expect(pay).not.toBeChecked()
  expect(screen.queryByRole('group', { name: 'Pay: how' })).not.toBeInTheDocument()
  await userEvent.click(pay)
  expect(useKnowledge).toHaveBeenCalledWith('k1', 'r1', 'map')
  expect(await screen.findByText('Pay: Map, saved.')).toHaveAttribute('role', 'status')
  await userEvent.click(screen.getByRole('button', { name: 'on Knowledge →' }))
  expect(onOpenKnowledge).toHaveBeenCalled()
})

test('a knowledge on: Full or Map, and off; an expert says what it knows', async () => {
  const { useKnowledge } = await openTab(role({}))
  expect(screen.getByText('knows: Pay')).toBeInTheDocument()
  const how = screen.getByRole('group', { name: 'Pay: how' })
  expect(within(how).getByRole('button', { name: 'Full' })).toHaveAttribute('aria-pressed', 'true')
  await userEvent.click(within(how).getByRole('button', { name: 'Map' }))
  expect(useKnowledge).toHaveBeenLastCalledWith('k1', 'r1', 'map')
  await userEvent.click(screen.getByRole('switch', { name: 'Knowledge Pay' }))
  expect(useKnowledge).toHaveBeenLastCalledWith('k1', 'r1', null)
})

test('Full is off where the role cannot take it, and says why; the server’s refusal is shown as it is', async () => {
  const writer = role({ id: 'r2', name: 'Coder', tools: ['read_file', 'write_file'], knows: [{ knowledge_id: 'k1', mode: 'map', topic: 'Pay', project_id: 'p1' }] })
  const { unmount } = render(<AgentsPage roles={[writer]} projectId="p1" knowledge={ITEMS} knowledgeActions={{ useKnowledge: vi.fn() }} {...handlers()} />)
  await userEvent.click(screen.getByRole('button', { name: /^Coder/ }))
  await userEvent.click(screen.getByRole('tab', { name: 'Knowledge' }))
  const full = within(screen.getByRole('group', { name: 'Pay: how' })).getByRole('button', { name: 'Full' })
  expect(full).toBeDisabled()
  expect(full).toHaveAttribute('title', 'an expert advises and reads only: it has no write_file')
  unmount()
  const builtin = role({ id: 'r3', name: 'Reviewer', builtin: true, knows: [{ knowledge_id: 'k1', mode: 'map', topic: 'Pay', project_id: 'p1' }] })
  const refused = vi.fn().mockRejectedValue(new ApiError(409, 'it is learning: try again once it is done'))
  render(<AgentsPage roles={[builtin]} projectId="p1" knowledge={ITEMS} knowledgeActions={{ useKnowledge: refused }} {...handlers()} />)
  await userEvent.click(screen.getByRole('button', { name: /^Reviewer/ }))
  await userEvent.click(screen.getByRole('tab', { name: 'Knowledge' }))
  expect(within(screen.getByRole('group', { name: 'Pay: how' })).getByRole('button', { name: 'Full' })).toHaveAttribute('title', 'only a role of your own can be an expert')
  await userEvent.click(screen.getByRole('switch', { name: 'Knowledge MLflow' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('it is learning: try again once it is done')
})

test('every role has the Knowledge tab; with no folder open it says knowledge is a project’s', async () => {
  render(<AgentsPage roles={[role({})]} projectId={null} {...handlers()} />)
  await userEvent.click(screen.getByRole('button', { name: /^Pay expert/ }))
  await userEvent.click(screen.getByRole('tab', { name: 'Knowledge' }))
  expect(screen.getByText('Open a folder: knowledge is a project’s, added on its Knowledge page.')).toBeInTheDocument()
})

test('the card of an expert the Lead asks for says what it knows and where it learns it, and no cost', () => {
  render(
    <RoleCard
      role={{ tool_call_id: 'c', run_id: 'r', agent_id: 'a', name: 'Stripe expert', description: '', instructions: '', tools: ['read_file'], knowledge: { topic: 'Stripe', sources: ['https://docs.stripe.com/payments'], max_pages: 20, max_usd: 0.5, max_code_files: 100, learn_with: null, weekly: false, search_answering: false } }}
      onDecide={vi.fn()}
    />,
  )
  expect(screen.getByText('knows: Stripe')).toBeInTheDocument()
  expect(screen.getByText(/Learns from: https:\/\/docs.stripe.com\/payments \(at most 20 pages, 0.5 USD\)/)).toBeInTheDocument()
  expect(screen.queryByText(/≈/)).not.toBeInTheDocument()
})

test('a new expert of a topic to research may search while answering, unless unticked', async () => {
  const h = handlers()
  const actions = { createExpert: vi.fn().mockResolvedValue({ id: 'r9' }) }
  render(<AgentsPage roles={[]} projectId="p1" knowledgeActions={actions} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: 'New role' }))
  await userEvent.click(screen.getByRole('button', { name: 'An expert' }))
  expect(screen.getByLabelText(/Agents may search the web/)).not.toBeChecked()
  await userEvent.type(screen.getByLabelText('Knows'), 'tomli')
  await userEvent.type(screen.getByLabelText('Sources'), 'research: tomli toml')
  expect(screen.getByLabelText(/Agents may search the web/)).toBeChecked()
  await userEvent.click(screen.getByRole('button', { name: 'Create expert' }))
  expect(actions.createExpert.mock.calls[0][1].search_answering).toBe(true)
})
