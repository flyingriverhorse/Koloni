import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Category, Role, RolesHistory } from '../api/types'
import { AgentsPage } from './AgentsPage'

// 0.1.0-ui (tasarim/specs/2026-11-06-agents-sayfasi-design.md): the role library's filter, New role as one form, and the
// page's History tab.
const role = (over: Partial<Role>): Role => ({
  id: 'r1',
  name: 'Coder',
  description: 'Writes code',
  instructions: 'Write it.',
  tools: ['read_file', 'write_file'],
  builtin: false,
  created_by_agent: false,
  models: null,
  provider_id: null,
  model_id: null,
  tier: null,
  tier_min: null,
  tier_max: null,
  kind: 'build',
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
  knows: [],
  created_at: 't',
  updated_at: 't',
  ...over,
})
const categories: Category[] = [
  { key: 'build', name: 'Build', colour: 'amber' },
  { key: 'check', name: 'Check', colour: 'green' },
]
const handlers = () => ({
  onSave: vi.fn().mockResolvedValue(undefined),
  onCreate: vi.fn().mockResolvedValue({ id: 'new' }),
  onDelete: vi.fn().mockResolvedValue(undefined),
  onReset: vi.fn().mockResolvedValue(undefined),
  onPatch: vi.fn().mockResolvedValue(undefined),
})
const coder = role({})
const tester = role({ id: 'r2', name: 'Tester', kind: 'check', tools: ['read_file', 'run_command'], max_steps: 40, mcp: ['github'], skills: ['tidy'], teams: ['t1'], knows: [{ knowledge_id: 'k1', mode: 'map' }] as Role['knows'] })
const summary = () => screen.getByText(/^be called/).closest('[aria-live]') as HTMLElement

test('the library keeps its filter at the top of its own scroll, and it filters', async () => {
  render(<AgentsPage roles={[coder, tester]} categories={categories} {...handlers()} />)
  const library = screen.getByRole('complementary', { name: 'Roles' })
  const filter = within(library).getByRole('searchbox', { name: 'Search roles' })
  // its head and filter are one block before the list, the block that stays (position: sticky)
  expect(filter.closest('.role-lib-top')).toBe(library.firstElementChild)
  expect(filter).toHaveAttribute('placeholder', 'Filter roles…')
  await userEvent.type(filter, 'test')
  expect(within(library).queryByRole('button', { name: /^Coder/ })).toBeNull()
  expect(within(library).getByRole('button', { name: /^Tester/ })).toBeInTheDocument()
})

test('a new role: the Orchestrator picks its model unless told, its packs tick the tiles, and the summary says what it will be', async () => {
  const h = handlers()
  render(<AgentsPage roles={[coder]} categories={categories} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: 'New role' }))
  const form = screen.getByRole('complementary', { name: 'New role' })
  expect(within(form).getByRole('radio', { name: 'Orchestrator' })).toBeChecked()
  expect(summary()).toHaveAttribute('aria-live', 'polite')
  expect(summary()).toHaveTextContent('do nothing yet: give it at least one tool')
  await userEvent.type(within(form).getByLabelText('Name'), 'Data checker')
  await userEvent.selectOptions(within(form).getByLabelText('Category'), 'check')
  await userEvent.click(within(form).getByRole('radio', { name: 'One tier' }))
  await userEvent.click(within(form).getByRole('radio', { name: 'Fast' }))
  // a pack ticks its tools, as one by one; one of its tools off unticks it
  await userEvent.click(within(form).getByRole('checkbox', { name: /^Read and search/ }))
  await userEvent.click(within(form).getByRole('checkbox', { name: /^Run commands/ }))
  expect(within(form).getByRole('checkbox', { name: /^Run commands/ })).toHaveAccessibleName(/asks/)
  await userEvent.click(within(form).getByText('Pick tools one by one'))
  for (const name of ['list_dir', 'read_file', 'search', 'view_image', 'run_command']) expect(within(form).getByRole('switch', { name })).toBeChecked()
  expect(within(form).getByRole('switch', { name: 'write_file' })).not.toBeChecked()
  await userEvent.click(within(form).getByRole('switch', { name: 'search' }))
  expect(within(form).getByRole('checkbox', { name: /^Read and search/ })).not.toBeChecked()
  await userEvent.click(within(form).getByRole('checkbox', { name: /^Read and search/ }))
  expect(within(form).getByRole('switch', { name: 'search' })).toBeChecked()
  // one sentence a line, as it is now
  expect(Array.from(summary().querySelectorAll('p'), p => p.textContent)).toEqual([
    'be called Data checker, in Check',
    'run on the first fast model of your team guide',
    'read and search · run commands; nothing else',
    'ask you first before it may run commands, as the chat’s permission level says',
  ])
  await userEvent.click(within(form).getByRole('button', { name: 'Create role' }))
  expect(h.onCreate).toHaveBeenCalledWith(expect.objectContaining({ name: 'Data checker', kind: 'check', tier: 'fast', tools: ['list_dir', 'read_file', 'search', 'view_image', 'run_command'] }))
})

test('a new role from a copy: its fields, tools and limits, then its servers, skills and knowledge; not its teams', async () => {
  const h = handlers()
  const useKnowledge = vi.fn().mockResolvedValue(undefined)
  render(<AgentsPage roles={[coder, tester]} categories={categories} knowledgeActions={{ useKnowledge }} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: 'New role' }))
  const form = screen.getByRole('complementary', { name: 'New role' })
  await userEvent.click(within(form).getByRole('button', { name: 'A copy' }))
  expect(within(form).queryByLabelText('Name')).toBeNull()
  await userEvent.selectOptions(within(form).getByLabelText('Copy of'), 'Tester')
  expect(within(form).getByLabelText('Name')).toHaveValue('Tester copy')
  expect(within(form).getByLabelText('What it does')).toHaveValue('Writes code')
  expect(within(form).getByLabelText('Category')).toHaveValue('check')
  expect(within(form).getByLabelText('At most this many steps')).toHaveValue('40')
  // its folded safety stops say they are set
  expect(within(form).getByText('Safety stops for one agent').closest('summary')).toHaveTextContent('Safety stops for one agent · set')
  await userEvent.click(within(form).getByRole('button', { name: 'Create role' }))
  const sent = h.onCreate.mock.calls[0][0]
  expect(sent).toEqual(expect.objectContaining({ name: 'Tester copy', tools: ['read_file', 'run_command'], max_steps: 40 }))
  expect(sent.teams).toBeUndefined()
  await vi.waitFor(() => expect(useKnowledge).toHaveBeenCalledWith('k1', 'new', 'map'))
  expect(h.onPatch).toHaveBeenCalledWith('new', { mcp: ['github'] })
  expect(h.onPatch).toHaveBeenCalledWith('new', { skills: ['tidy'] })
})

test('a copy whose skills or knowledge are refused is made all the same: the form closes and says what was not given', async () => {
  const h = { ...handlers(), onCreate: vi.fn().mockResolvedValue({ ...tester, id: 'new', name: 'Tester copy' }) }
  h.onPatch.mockImplementation((_id: string, change: object) => ('skills' in change ? Promise.reject({ detail: 'unknown skill' }) : Promise.resolve()))
  const useKnowledge = vi.fn().mockRejectedValue({ detail: 'no such knowledge' })
  render(<AgentsPage roles={[coder, tester]} categories={categories} knowledgeActions={{ useKnowledge }} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: 'New role' }))
  const form = screen.getByRole('complementary', { name: 'New role' })
  await userEvent.click(within(form).getByRole('button', { name: 'A copy' }))
  await userEvent.selectOptions(within(form).getByLabelText('Copy of'), 'Tester')
  await userEvent.click(within(form).getByRole('button', { name: 'Create role' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Made Tester copy; not given: its skills — unknown skill; a knowledge — no such knowledge')
  expect(h.onPatch).toHaveBeenCalledWith('new', { mcp: ['github'] })
  expect(screen.queryByRole('complementary', { name: 'New role' })).toBeNull()
  expect(h.onCreate).toHaveBeenCalledTimes(1)
})

test('editing a role is the same form, filled, opened at the section its Edit names; it has no "Start from"', async () => {
  const h = handlers()
  render(<AgentsPage roles={[coder]} picked="r1" categories={categories} {...h} />)
  const panel = screen.getByRole('complementary', { name: 'Role Coder' })
  // the header: its face, name, whether on, what it does once
  expect(within(panel).getByRole('heading', { level: 2 })).toHaveTextContent('CCoderon')
  expect(within(panel).getAllByText('Writes code')).toHaveLength(1)
  await userEvent.click(within(panel).getByRole('button', { name: 'Edit may' }))
  expect(within(panel).getByText('Pick tools one by one').closest('details')).toHaveAttribute('open')
  expect(within(panel).getByRole('switch', { name: 'write_file' })).toBeChecked()
  for (const title of ['Model', 'It may', 'This role will']) expect(within(panel).getByRole('region', { name: title })).toBeInTheDocument()
  expect(within(panel).getByLabelText('Name')).toHaveValue('Coder')
  expect(within(panel).getByRole('radio', { name: 'Orchestrator' })).toBeChecked()
  expect(within(panel).queryByRole('group', { name: 'Start from' })).toBeNull()
  expect(within(panel).queryByRole('button', { name: 'Create role' })).toBeNull()
  await userEvent.click(within(panel).getByRole('checkbox', { name: /^Use the web/ }))
  await userEvent.click(within(panel).getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenCalledWith('r1', expect.objectContaining({ tools: ['read_file', 'write_file', 'web_search', 'http_request'] }))
})

const history: RolesHistory = {
  days: 30,
  lead_turns: 9,
  jobs_limit: 200,
  roles: [
    { name: 'Coder', done: 6, failed: 1, running: 1 },
    { name: 'Tester', done: 0, failed: 2, running: 0 },
  ],
  teams: [{ name: 'Web app', done: 3, failed: 1, running: 0 }],
  recipes: [{ name: 'Feature', done: 2, failed: 0, running: 1 }],
  jobs: [
    { id: 'a1', role_name: 'Coder', conversation_id: 'c1', conversation_title: 'Paginate the notes', status: 'completed', provider_name: 'Local', model_id: 'qwen', created_at: '2026-11-03T10:00:00Z', teams: ['Web app'], recipes: ['Feature'] },
    { id: 'a2', role_name: 'Tester', conversation_id: 'c2', conversation_title: 'Flaky login test', status: 'failed', provider_name: 'Local', model_id: null, created_at: '2026-11-02T10:00:00Z', teams: [], recipes: [] },
    { id: 'a3', role_name: 'Coder', conversation_id: 'c3', conversation_title: 'Tags on notes', status: 'running', provider_name: null, model_id: null, created_at: '2026-11-01T10:00:00Z', teams: ['Web app'], recipes: [] },
  ],
}

test('History: totals, a box each for roles, teams and recipes with how they ended, the Lead apart; the jobs filtered, each opening its chat', async () => {
  const onHistory = vi.fn().mockResolvedValue(history)
  const onOpenConversation = vi.fn()
  render(<AgentsPage roles={[coder, tester]} onHistory={onHistory} onOpenConversation={onOpenConversation} {...handlers()} />)
  await userEvent.click(screen.getByRole('tab', { name: 'History' }))
  expect(onHistory).toHaveBeenLastCalledWith(30)
  const stats = await screen.findByText('agents opened')
  // 10 opened; of the 9 that ended, 6 done
  expect(stats.closest('.history-stats')).toHaveTextContent('10agents opened67%ended done4team runs3recipe runs')
  const roles = screen.getByRole('region', { name: 'Roles' })
  expect(within(roles).getByText('Coder').closest('.history-row')).toHaveTextContent('8 · 86%: 6 done, 1 failed or stopped, 1 in progress')
  expect(within(roles).getByText('Tester').closest('.history-row')).toHaveTextContent('2 · 0%')
  expect(roles).toHaveTextContent('9 turns led by the Orchestrator')
  expect(screen.getByRole('region', { name: 'Teams' })).toHaveTextContent('Web app4 · 75%')
  expect(screen.getByRole('region', { name: 'Recipes' })).toHaveTextContent('Feature3 · 100%')
  const jobs = screen.getByRole('region', { name: 'Jobs' })
  const titles = () => within(jobs).queryAllByRole('button').map(b => b.textContent)
  expect(titles()).toEqual(['Paginate the notes', 'Flaky login test', 'Tags on notes'])
  await userEvent.selectOptions(within(jobs).getByRole('combobox', { name: 'Team' }), 'Web app')
  expect(titles()).toEqual(['Paginate the notes', 'Tags on notes'])
  await userEvent.selectOptions(within(jobs).getByRole('combobox', { name: 'Recipe' }), 'Feature')
  expect(titles()).toEqual(['Paginate the notes'])
  await userEvent.click(within(jobs).getByRole('button', { name: 'Paginate the notes' }))
  expect(onOpenConversation).toHaveBeenCalledWith('c1')
  await userEvent.selectOptions(within(jobs).getByRole('combobox', { name: 'Team' }), '')
  await userEvent.selectOptions(within(jobs).getByRole('combobox', { name: 'Recipe' }), '')
  await userEvent.click(within(jobs).getByRole('checkbox', { name: 'Failed only' }))
  expect(titles()).toEqual(['Flaky login test'])
  await userEvent.selectOptions(within(jobs).getByRole('combobox', { name: 'Role' }), 'Coder')
  expect(jobs).toHaveTextContent('No job like that in this period.')
  // the period
  await userEvent.selectOptions(screen.getByLabelText('Period'), '7')
  expect(onHistory).toHaveBeenLastCalledWith(7)
})

test('History says when it could not be read, and shows no number', async () => {
  render(<AgentsPage roles={[coder]} onHistory={vi.fn().mockRejectedValue({ detail: 'down' })} {...handlers()} />)
  await userEvent.click(screen.getByRole('tab', { name: 'History' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('The history could not be read: down')
  expect(screen.queryByText('agents opened')).toBeNull()
})
