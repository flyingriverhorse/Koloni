import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import type { Category, Role, RoleModel, RolesActivity, Team } from '../api/types'
import { ranOn } from '../shell/modelName'
import { AgentsPage } from './AgentsPage'
import { groupsOf, lastLine, mayDo, ruleText } from './chart'
import { ROLE_TOOLS } from './roleTools'

// Slice 81b: a role's lines say its tier rule and where it last ran; a role opens beside. Slice 63a: a team's lead and
// its own stages, which role sits in which. Slice 63b: Teams & roles on one screen - the roles once, by the user's own
// categories, on the left; the Lead and the teams in the middle, one open at a time; a role's teams marked while it is open.

const role = (over: Partial<Role>): Role => ({
  id: 'r1',
  name: 'Summarizer',
  description: 'Sums up',
  instructions: '',
  tools: ['read_file', 'run_command'],
  builtin: true,
  created_by_agent: false, models: null,
  provider_id: null,
  model_id: null,
  tier: null,
  tier_min: null,
  tier_max: null,
  kind: 'write',
  enabled: true,
  teams: [],
  pick_from: null,
  max_steps: null,
  max_tokens: null,
  effort: 'low',
  max_effort: 'high',
  context_window: null,
  mcp: [],
  skills: [],
  inside_cli: false,
  knows: [],
  created_at: 't',
  updated_at: 't',
  ...over,
})
const row = (over: Partial<RoleModel>): RoleModel => ({
  role: 'Summarizer',
  provider_name: 'Claude Code',
  model_id: 'haiku',
  source: 'tier',
  tier: 'balanced',
  pick_from: [],
  cannot_run: null,
  cannot_pick: {},
  run_on: [],
  asks_how_hard: null,
  level_named: false,
  ...over,
})
const categories: Category[] = [
  { key: 'plan', name: 'Plan', colour: 'violet' },
  { key: 'build', name: 'Build', colour: 'amber' },
  { key: 'check', name: 'Check', colour: 'green' },
  { key: 'write', name: 'Write & keep up', colour: 'blue' },
]
const handlers = () => ({
  onSave: vi.fn().mockResolvedValue(undefined),
  onCreate: vi.fn().mockResolvedValue(undefined),
  onDelete: vi.fn().mockResolvedValue(undefined),
  onReset: vi.fn().mockResolvedValue(undefined),
  onPatch: vi.fn().mockResolvedValue(undefined),
  categories,
  teamActions: {
    createTeam: vi.fn().mockResolvedValue(undefined),
    changeTeam: vi.fn().mockResolvedValue(undefined),
    deleteTeam: vi.fn().mockResolvedValue(undefined),
    addStage: vi.fn().mockResolvedValue(undefined),
    changeStage: vi.fn().mockResolvedValue(undefined),
    orderStages: vi.fn().mockResolvedValue(undefined),
    deleteStage: vi.fn().mockResolvedValue(undefined),
    placeRole: vi.fn().mockResolvedValue(undefined),
  },
  categoryActions: {
    addCategory: vi.fn().mockResolvedValue('k-new'),
    changeCategory: vi.fn().mockResolvedValue(undefined),
    orderCategories: vi.fn().mockResolvedValue(undefined),
    deleteCategory: vi.fn().mockResolvedValue(undefined),
  },
})

const lead = role({ id: 'lead', name: 'Lead', kind: 'plan', description: 'Talks with the user' })
const coder = role({ id: 'c', name: 'Coder', kind: 'build', teams: ['web', 'api'] })
const tester = role({ id: 't', name: 'Tester', kind: 'check', teams: ['web'], tier: 'fast' })
const devops = role({ id: 'd', name: 'DevOps', kind: 'build', enabled: false, tier_min: 'balanced' })
const mine = role({ id: 'm', name: 'Shipper', kind: 'Ship it', builtin: false })
/** A team as the server sends it: its stages (name, role ids) in order, its lead on. */
const teamOf = (id: string, name: string, stages: [string, string[]][]): Team => ({
  id,
  name,
  roles: stages.flatMap(([, ids]) => ids),
  stages: stages.map(([stage, ids], at) => ({ id: `${id}-${at}`, name: stage, together: false, roles: ids })),
  lead: role({ id: `${id}-lead`, name: `${name} lead`, kind: 'lead', builtin: false, tier_min: 'balanced', description: 'Runs its team’s stages' }),
  lead_on: true,
  lead_may_pick: true,
  default_recipe_id: null,
})
const teams: Team[] = [
  teamOf('web', 'Web app', [
    ['Plan', []],
    ['Build', ['c']],
    ['Check', ['t']],
  ]),
  teamOf('api', 'Backend / API', [['Build', ['c']]]),
]
const activity: RolesActivity = {
  last: { Coder: { provider_name: 'Claude Code', model_id: 'sonnet-4-8', tier: 'balanced' }, Lead: { provider_name: 'Claude Code', model_id: 'opus-4-8', tier: null } },
  running: { Lead: 1 },
}
const library = () => screen.getByRole('complementary', { name: 'Roles' })
const region = (name: string, inside: HTMLElement = document.body) => within(inside).getByRole('region', { name })
/** A team's row, opened (one at a time). */
const openTeam = async (name: string) => {
  await userEvent.click(within(region(name)).getByRole('button', { name: new RegExp(`^${name.replace('/', '\\/')}`) }))
  return region(name)
}
const options = () => within(screen.getByRole('listbox')).getAllByRole('option').map(o => o.querySelector('.palette-name')?.textContent)

// (The team open is the browser's: each test begins with none.)
beforeEach(() => localStorage.clear())

test('a role’s lines: the tier rule, then whose rule it is, where it last ran, or that it has not', () => {
  const providers = [{ id: 'p', name: 'Claude Code' }]
  expect(ruleText(coder, providers)).toBe('Orchestrator · fast–strongest')
  expect(ruleText(devops, providers)).toBe('Orchestrator · balanced–strongest')
  expect(ruleText(tester, providers)).toBe('Always fast')
  expect(ruleText(role({ tier_min: 'strongest' }), providers)).toBe('Always strongest') // a range of one
  expect(ruleText(role({ provider_id: 'p' }), providers)).toBe('Claude Code · its default')
  expect(ruleText(role({ provider_id: 'p', model_id: 'opus' }), providers)).toBe('Claude Code · opus')
  expect(ruleText(role({ tier: 'conversation' }), providers)).toBe('As the chat')
  expect(ruleText(role({}), providers, true)).toBe('As the chat') // the Lead's own none
  expect(lastLine(role({ tier: 'conversation' }), undefined)).toBe('your rule')
  expect(lastLine(coder, activity.last.Coder)).toBe('Last: sonnet-4-8, balanced')
  expect(lastLine(coder, { provider_name: 'Local', model_id: null, tier: null })).toBe('Last: Local')
  expect(lastLine(coder, undefined)).toBe('Not used yet')
  expect(lastLine(tester, activity.last.Coder)).toBe('your rule')
  expect(mayDo(['read_file', 'write_file', 'run_command'])).toBe('read and search · write files · run commands')
})

test('the library’s groups: the categories in their order, an empty one too, then a kind no category has', () => {
  expect(groupsOf([coder, tester, devops, mine], categories).map(g => [g.name, g.roles.map(r => r.name), g.listed])).toEqual([
    ['Plan', [], true],
    ['Build', ['Coder', 'DevOps'], true],
    ['Check', ['Tester'], true],
    ['Write & keep up', [], true],
    ['Ship it', ['Shipper'], false],
  ])
})

test('the library: every role once by category, how many teams each is in, on / off; found by name, in no team, off', async () => {
  const h = handlers()
  render(<AgentsPage roles={[lead, coder, tester, devops, mine]} teams={teams} {...h} />)
  const lib = library()
  expect(within(lib).getByRole('heading', { level: 3 })).toHaveTextContent('Roles')
  expect(lib).toHaveTextContent('Roles4 · 1 off')
  expect(within(lib).getAllByRole('region').map(r => r.getAttribute('aria-label'))).toEqual(['Plan', 'Build', 'Check', 'Write & keep up', 'Ship it'])
  const build = region('Build', lib)
  expect(within(build).getByRole('button', { name: /^Build/, expanded: true })).toHaveTextContent('Build2 · 1 off')
  expect(within(build).getByRole('button', { name: /^Coder/ })).toHaveTextContent('Coder2 teams')
  expect(within(build).getByRole('button', { name: /^DevOps/ })).toHaveTextContent('DevOpsno team')
  expect(within(build).getByText('no team')).toHaveClass('lib-uses-none')
  expect(within(build).getByRole('button', { name: /^DevOps/ }).closest('.lib-row')).toHaveClass('lib-row-off')
  // the Lead is on its strip, not in the library; its switch is none
  expect(within(lib).queryByRole('button', { name: /^Lead/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('switch', { name: 'Lead on' })).not.toBeInTheDocument()
  // a switch saves at once
  await userEvent.click(within(lib).getByRole('switch', { name: 'DevOps on' }))
  expect(h.onPatch).toHaveBeenCalledWith('d', { enabled: true })
  // a group folds
  await userEvent.click(within(build).getByRole('button', { name: /^Build/, expanded: true }))
  expect(within(build).queryByRole('button', { name: /^Coder/ })).not.toBeInTheDocument()
  // the filters, with their counts; looking for some leaves out the categories with none
  await userEvent.click(within(lib).getByRole('button', { name: 'In no team · 2' }))
  expect(within(lib).getAllByRole('region').map(r => r.getAttribute('aria-label'))).toEqual(['Build', 'Ship it'])
  expect(within(lib).getByRole('button', { name: /^DevOps/ })).toBeInTheDocument()
  expect(within(lib).queryByRole('button', { name: /^Coder/ })).not.toBeInTheDocument()
  await userEvent.click(within(lib).getByRole('button', { name: 'Off · 1' }))
  expect(within(lib).getAllByRole('button', { name: /teams?$/ }).map(b => b.querySelector('.lib-row-name')?.textContent)).toEqual(['DevOps'])
  await userEvent.click(within(lib).getByRole('button', { name: 'All' }))
  await userEvent.type(within(lib).getByLabelText('Search roles'), 'test')
  expect(within(lib).getAllByRole('region').map(r => r.getAttribute('aria-label'))).toEqual(['Check'])
})

test('the tabs: Teams & roles, Recipes and History, with the arrows, Home and End; the head makes a role and a team', async () => {
  const h = handlers()
  render(<AgentsPage roles={[lead, coder, tester]} teams={teams} {...h} />)
  expect(screen.getAllByRole('tab').map(t => t.textContent)).toEqual(['Teams & roles', 'Recipes', 'History'])
  expect(screen.getByRole('tab', { name: 'Teams & roles' })).toHaveAttribute('aria-selected', 'true')
  screen.getByRole('tab', { name: 'Teams & roles' }).focus()
  await userEvent.keyboard('{End}')
  expect(screen.getByRole('tab', { name: 'History' })).toHaveFocus()
  expect(screen.queryByRole('button', { name: 'New team' })).not.toBeInTheDocument()
  await userEvent.keyboard('{ArrowLeft}')
  expect(screen.getByRole('tab', { name: 'Recipes' })).toHaveFocus()
  expect(screen.getByRole('tab', { name: 'Recipes' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.queryByRole('button', { name: 'New team' })).not.toBeInTheDocument()
  await userEvent.keyboard('{Home}')
  expect(screen.getByRole('tab', { name: 'Teams & roles' })).toHaveAttribute('aria-selected', 'true')
  await userEvent.click(screen.getByRole('button', { name: 'New team' }))
  await userEvent.type(screen.getByLabelText('New team’s name'), 'Game{Enter}')
  expect(h.teamActions.createTeam).toHaveBeenCalledWith('Game')
  await userEvent.click(screen.getByRole('button', { name: 'New role' }))
  expect(screen.getByRole('complementary', { name: 'New role' })).toBeInTheDocument()
  expect(screen.getByLabelText('Category')).toHaveDisplayValue('Build')
})

test('the Lead’s strip and the folded teams: their stages and counts, faces, default recipe and lead; one opens at a time, as the browser remembers', async () => {
  const h = handlers()
  const { unmount } = render(<AgentsPage roles={[lead, coder, tester]} teams={teams} {...h} onActivity={() => Promise.resolve(activity)} />)
  expect(await screen.findByText(/· Talks with the user · Last: opus-4-8/)).toBeInTheDocument()
  expect(screen.getByText('now')).toBeInTheDocument()
  expect(screen.getByText('2 teams · one open at a time · drag a role from the left into a stage')).toBeInTheDocument()
  const web = region('Web app')
  const toggle = within(web).getByRole('button', { name: /^Web app/, expanded: false })
  // its stages in order with their roles' counts, the roles' faces, no default recipe
  expect(toggle).toHaveTextContent('▸Web appPlan→Build 1→Check 1CTno recipe')
  expect(within(web).queryByRole('region', { name: 'Stage 1, Plan' })).not.toBeInTheDocument()
  // its lead's switch is on the folded row, and saves at once
  await userEvent.click(within(web).getByRole('switch', { name: 'Web app lead on' }))
  expect(h.teamActions.changeTeam).toHaveBeenCalledWith('web', { lead_on: false })
  await userEvent.click(toggle)
  expect(within(web).getAllByRole('region').map(r => r.getAttribute('aria-label'))).toEqual(['Stage 1, Plan', 'Stage 2, Build', 'Stage 3, Check'])
  // another opened, this one folds
  await openTeam('Backend / API')
  expect(within(web).queryByRole('region', { name: 'Stage 1, Plan' })).not.toBeInTheDocument()
  expect(localStorage.getItem('koloni-agents-team')).toBe('api')
  unmount()
  render(<AgentsPage roles={[lead, coder, tester]} teams={teams} {...h} />)
  expect(within(region('Backend / API')).getByRole('region', { name: 'Stage 1, Build' })).toBeInTheDocument()
  // the Lead opens from its strip
  await userEvent.click(screen.getByRole('button', { name: 'Open the Lead' }))
  expect(screen.getByRole('complementary', { name: 'Role Lead' })).toBeInTheDocument()
})

test('an open team: its lead as a line, saying when it steps in, its stages with their roles, and its foot', async () => {
  const h = handlers()
  render(<AgentsPage roles={[lead, coder, tester]} teams={teams} {...h} />)
  const web = await openTeam('Web app')
  const name = within(web).getByRole('button', { name: 'Web app lead' })
  expect(name.closest('.team-lead-row')).toHaveTextContent('Orchestrator · balanced–strongest')
  expect(name.closest('.team-lead-row')).toHaveTextContent('Steps in only when this team works beside another team; else the Orchestrator runs it.')
  const recipe = within(web).getByRole('combobox', { name: "Web app's default recipe" })
  expect(recipe.closest('label')).toHaveTextContent(/^Default recipe/)
  expect(recipe).toHaveDisplayValue('none')
  const check = region('Stage 3, Check', web)
  expect(within(check).getByRole('button', { name: 'Tester' })).toBeInTheDocument()
  expect(within(check).getByRole('heading', { level: 4 })).toHaveTextContent(/^3Check$/)
  expect(within(check).getByRole('checkbox', { name: 'Check: all at once' })).not.toBeChecked()
  expect(region('Stage 1, Plan', web)).toHaveTextContent('No role yet: drop one here, or add one')
  await userEvent.click(within(web).getByRole('checkbox', { name: 'The Orchestrator may pick Web app' }))
  expect(h.teamActions.changeTeam).toHaveBeenCalledWith('web', { lead_may_pick: false })
  // a role taken out of the team from its chip
  await userEvent.click(within(check).getByRole('button', { name: 'Take Tester out of Web app' }))
  expect(h.onPatch).toHaveBeenCalledWith('t', { teams: [] })
  expect(await screen.findByText('Tester is out of Web app now.')).toHaveAttribute('role', 'status')
  // its lead's links open its panel on that tab; no category, no teams, no switch of its own; its name is its team's
  await userEvent.click(within(web).getByRole('button', { name: 'Web app lead: Instructions' }))
  const panel = screen.getByRole('complementary', { name: 'Role Web app lead' })
  expect(within(panel).getByRole('tab', { name: 'Instructions' })).toHaveAttribute('aria-selected', 'true')
  expect(panel).not.toHaveTextContent('Category')
  expect(panel).not.toHaveTextContent('In teams')
  expect(within(panel).queryByRole('switch')).not.toBeInTheDocument()
  await userEvent.click(within(panel).getByRole('button', { name: 'Edit' }))
  expect(within(panel).getByLabelText('Name')).toHaveAttribute('readonly')
  expect(within(panel).queryByRole('button', { name: 'Delete role' })).not.toBeInTheDocument()
})

test('a role whose kind no category has is in a group of that name, and a role as any other: its team decides who is a lead', async () => {
  const captain = role({ id: 'k', name: 'Captain', kind: 'lead', builtin: false })
  render(<AgentsPage roles={[lead, captain]} teams={teams} {...handlers()} />)
  const own = region('lead', library())
  expect(within(own).queryByRole('button', { name: 'lead: more' })).not.toBeInTheDocument()
  expect(within(own).getByRole('switch', { name: 'Captain on' })).toBeInTheDocument()
  await userEvent.click(within(own).getByRole('button', { name: /^Captain/ }))
  const panel = screen.getByRole('complementary', { name: 'Role Captain' })
  expect(within(panel).getByLabelText("Captain's category")).toHaveDisplayValue('lead')
  expect(within(panel).getByRole('switch', { name: 'Captain on' })).toBeInTheDocument()
  await userEvent.click(within(panel).getByRole('tab', { name: 'Instructions' }))
  await userEvent.click(within(panel).getByRole('button', { name: 'Edit' }))
  expect(within(panel).getByLabelText('Name')).not.toHaveAttribute('readonly')
  expect(within(panel).getByRole('button', { name: 'Delete role' })).toBeInTheDocument()
})

test('an off lead says the Lead runs the team itself', async () => {
  render(<AgentsPage roles={[lead, coder]} teams={[{ ...teams[1], lead_on: false }]} {...handlers()} />)
  const api = await openTeam('Backend / API')
  const line = within(api).getByRole('button', { name: 'Backend / API lead' }).closest('.team-lead-row')
  expect(line).toHaveTextContent('Off: the Orchestrator always runs Backend / API itself')
  expect(line).toHaveClass('team-lead-off')
  expect(within(api).getByText('lead off')).toBeInTheDocument()
})

test('a team’s stages: added, renamed, all at once, moved, removed - its roles going to the first, which is said', async () => {
  const h = handlers()
  render(<AgentsPage roles={[lead, coder, tester]} teams={teams} {...h} />)
  const web = await openTeam('Web app')
  await userEvent.click(within(web).getByRole('button', { name: '+ Add a stage' }))
  await userEvent.type(within(web).getByLabelText('New stage’s name'), 'Ship{Enter}')
  expect(h.teamActions.addStage).toHaveBeenCalledWith('web', 'Ship')
  await userEvent.click(within(web).getByRole('button', { name: 'Rename stage Build' }))
  await userEvent.clear(within(web).getByLabelText('Stage’s new name'))
  await userEvent.type(within(web).getByLabelText('Stage’s new name'), 'Code{Enter}')
  expect(h.teamActions.changeStage).toHaveBeenCalledWith('web', 'web-1', { name: 'Code' })
  await userEvent.click(within(web).getByRole('checkbox', { name: 'Check: all at once' }))
  expect(h.teamActions.changeStage).toHaveBeenCalledWith('web', 'web-2', { together: true })
  expect(within(web).getByRole('button', { name: 'Move Plan up' })).toBeDisabled()
  await userEvent.click(within(web).getByRole('button', { name: 'Move Plan down' }))
  expect(h.teamActions.orderStages).toHaveBeenCalledWith('web', ['web-1', 'web-0', 'web-2'])
  await userEvent.click(within(web).getByRole('button', { name: 'Remove stage Check' }))
  expect(h.teamActions.deleteStage).toHaveBeenCalledWith('web', 'web-2')
  expect(await screen.findByText('Check removed: Tester is in Plan now.')).toHaveAttribute('role', 'status')
  // a team keeps one stage at least
  const api = await openTeam('Backend / API')
  expect(within(api).getByRole('button', { name: 'Remove stage Build' })).toBeDisabled()
})

test('a role goes in a stage from its list, from the library by a drag, or from another stage; the open team says where it lands', async () => {
  const h = handlers()
  render(<AgentsPage roles={[lead, coder, tester, devops]} teams={teams} {...h} />)
  const web = await openTeam('Web app')
  const build = region('Stage 2, Build', web)
  await userEvent.click(within(build).getByRole('button', { name: '+ Add a role' }))
  expect(options()).toEqual(['Tester', 'DevOps', 'New role…'])
  expect(screen.getByRole('option', { name: /^DevOps/ })).toHaveTextContent('Build, off')
  await userEvent.click(screen.getByRole('option', { name: /^Tester/ }))
  expect(h.teamActions.placeRole).toHaveBeenCalledWith('web', 't', 'web-1')
  // B-170: said to a screen reader, not drawn: the page does not move as it comes and goes.
  expect(await screen.findByText('Tester is in Build now, not Check.')).toHaveClass('visually-hidden')
  // dragged from the library: while it is, each stage says it may land there
  const plan = region('Stage 1, Plan', web)
  const row = within(library()).getByRole('button', { name: /^DevOps/ }).closest('.lib-row')!
  fireEvent.dragStart(row, { dataTransfer: { setData: () => undefined } })
  await vi.waitFor(() => expect(plan).toHaveTextContent('Drop: DevOps joins Plan'))
  fireEvent.drop(plan, { dataTransfer: { getData: () => 'library d' } })
  fireEvent.dragEnd(row)
  expect(h.teamActions.placeRole).toHaveBeenLastCalledWith('web', 'd', 'web-0')
  expect(plan).not.toHaveTextContent('Drop:')
  // dragged from Build to Plan; one from another team is not taken
  fireEvent.drop(plan, { dataTransfer: { getData: () => 'web c' } })
  expect(h.teamActions.placeRole).toHaveBeenLastCalledWith('web', 'c', 'web-0')
  fireEvent.drop(plan, { dataTransfer: { getData: () => 'api c' } })
  expect(h.teamActions.placeRole).toHaveBeenCalledTimes(3)
})

test('the stage’s list is used from the keyboard: arrows, Enter, Esc; the focus goes back to its button', async () => {
  const h = handlers()
  render(<AgentsPage roles={[lead, coder, tester, devops]} teams={teams} {...h} />)
  const add = within(region('Stage 1, Plan', await openTeam('Web app'))).getByRole('button', { name: '+ Add a role' })
  add.focus()
  await userEvent.keyboard('{Enter}')
  const box = screen.getByRole('combobox', { name: 'Find a role to add to Web app, Plan' })
  expect(box).toHaveFocus()
  expect(box).toHaveAttribute('aria-activedescendant', screen.getByRole('option', { name: /^Coder/ }).id)
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  expect(add).toHaveFocus()
  await userEvent.keyboard('{Enter}')
  await userEvent.keyboard('{ArrowDown}{Enter}')
  expect(h.teamActions.placeRole).toHaveBeenCalledWith('web', 't', 'web-0')
  expect(add).toHaveFocus()
})

test('a team is renamed and deleted from its foot, after saying its roles stay', async () => {
  const h = handlers()
  render(<AgentsPage roles={[lead, coder]} teams={teams} {...h} />)
  const web = await openTeam('Web app')
  await userEvent.click(within(web).getByRole('button', { name: 'Rename Web app' }))
  await userEvent.clear(within(web).getByLabelText('Team’s new name'))
  await userEvent.type(within(web).getByLabelText('Team’s new name'), 'Site{Enter}')
  expect(h.teamActions.changeTeam).toHaveBeenCalledWith('web', { name: 'Site' })
  await userEvent.click(within(web).getByRole('button', { name: 'Delete Web app' }))
  expect(web).toHaveTextContent('Delete Web app? Its roles stay and its lead goes; its conversations will use every team.')
  expect(h.teamActions.deleteTeam).not.toHaveBeenCalled()
  await userEvent.click(within(web).getByRole('button', { name: 'Delete team' }))
  expect(h.teamActions.deleteTeam).toHaveBeenCalledWith('web')
})

test('a role open beside marks the teams it is in, and says it; the others are faded', async () => {
  render(<AgentsPage roles={[lead, coder, tester]} teams={[...teams, teamOf('ops', 'Ops', [['Plan', []]])]} {...handlers()} />)
  await userEvent.click(within(library()).getByRole('button', { name: /^Tester/ }))
  expect(screen.getByText('Tester is in 1 of 3 teams · the others are faded while it is open')).toBeInTheDocument()
  expect(region('Web app')).toHaveClass('team-box-hit')
  expect(region('Ops')).toHaveClass('team-box-dim')
  expect(within(region('Web app')).getByRole('button', { name: /^Web app/ })).toHaveTextContent('Check 1 · Tester')
  expect(within(library()).getByRole('button', { name: /^Tester/ })).toHaveAttribute('aria-current', 'true')
  await userEvent.click(screen.getByRole('button', { name: 'Close the role' }))
  expect(region('Ops')).not.toHaveClass('team-box-dim')
})

test('categories: renamed and recoloured, put in order, a new one added; KOLONİ’s four and one with roles are not deleted, an empty one is', async () => {
  const h = handlers()
  const scout = role({ id: 'x', name: 'Scout', kind: 'k1', builtin: false })
  const mineToo = [...categories, { key: 'k1', name: 'Research', colour: 'rose' as const }, { key: 'k2', name: 'Ops', colour: 'teal' as const }]
  render(<AgentsPage roles={[lead, coder, tester, scout]} teams={teams} {...h} categories={mineToo} />)
  const lib = library()
  // Check says what its key does beyond a label
  expect(region('Check', lib)).toHaveTextContent('Roles here report findings')
  await userEvent.click(within(lib).getByRole('button', { name: 'Check: more' }))
  expect(within(lib).getByRole('button', { name: 'Delete — one of KOLONİ’s four: rename it instead' })).toBeDisabled()
  await userEvent.click(within(lib).getByRole('button', { name: 'Rename…' }))
  await userEvent.clear(within(lib).getByLabelText('Category’s name'))
  await userEvent.type(within(lib).getByLabelText('Category’s name'), 'Review')
  await userEvent.click(within(lib).getByRole('radio', { name: 'teal' }))
  await userEvent.click(within(lib).getByRole('button', { name: 'Save' }))
  expect(h.categoryActions.changeCategory).toHaveBeenCalledWith('check', { name: 'Review', colour: 'teal' })
  await userEvent.click(within(lib).getByRole('button', { name: 'Check: more' }))
  await userEvent.click(within(lib).getByRole('button', { name: 'Move up' }))
  expect(h.categoryActions.orderCategories).toHaveBeenCalledWith(['plan', 'check', 'build', 'write', 'k1', 'k2'])
  await userEvent.click(within(lib).getByRole('button', { name: 'Research: more' }))
  expect(within(lib).getByRole('button', { name: 'Delete — move its role first' })).toBeDisabled()
  await userEvent.click(within(lib).getByRole('button', { name: 'Research: more' }))
  await userEvent.click(within(lib).getByRole('button', { name: 'Ops: more' }))
  expect(within(lib).getByRole('button', { name: 'Move down' })).toBeDisabled()
  await userEvent.click(within(lib).getByRole('button', { name: 'Delete' }))
  expect(h.categoryActions.deleteCategory).toHaveBeenCalledWith('k2')
  await userEvent.click(within(lib).getByRole('button', { name: '+ New category' }))
  await userEvent.type(within(lib).getByLabelText('Category’s name'), 'Docs{Enter}')
  expect(h.categoryActions.addCategory).toHaveBeenCalledWith('Docs', 'rose')
  // the server's refusal is said
  h.categoryActions.deleteCategory.mockRejectedValue({ detail: 'Ops holds 1 role: move them to another category first' })
  await userEvent.click(within(lib).getByRole('button', { name: 'Ops: more' }))
  await userEvent.click(within(lib).getByRole('button', { name: 'Delete' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Ops holds 1 role: move them to another category first')
})

test('a role dropped on a category’s heading is put in it, and that is said; a kind no category has takes none', async () => {
  const h = handlers()
  render(<AgentsPage roles={[lead, coder, tester, mine]} teams={teams} {...h} />)
  fireEvent.drop(region('Ship it', library()), { dataTransfer: { getData: () => 'library c' } })
  expect(h.onPatch).not.toHaveBeenCalled()
  fireEvent.drop(region('Check', library()), { dataTransfer: { getData: () => 'library c' } })
  expect(h.onPatch).toHaveBeenCalledWith('c', { kind: 'check' })
  expect(await screen.findByText('Coder is in Check now.')).toHaveAttribute('role', 'status')
})

test('a narrow window’s library is a drawer: “Roles ▸ N” opens it and the focus goes in; its × or Esc closes it, the focus back on the button', async () => {
  render(<AgentsPage roles={[lead, coder, tester]} teams={teams} {...handlers()} />)
  const toggle = screen.getByRole('button', { name: 'Roles ▸ 2' })
  await userEvent.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  expect(library()).toHaveClass('role-lib-open')
  expect(within(library()).getByLabelText('Search roles')).toHaveFocus()
  await userEvent.keyboard('{Escape}')
  expect(library()).not.toHaveClass('role-lib-open')
  expect(toggle).toHaveFocus()
  await userEvent.click(toggle)
  await userEvent.click(screen.getByRole('button', { name: 'Close the roles' }))
  expect(library()).not.toHaveClass('role-lib-open')
})

test('the panel’s tabs go with the arrow keys, the chosen one alone in the Tab order', async () => {
  render(<AgentsPage roles={[lead, coder]} {...handlers()} />)
  await userEvent.click(screen.getByRole('button', { name: /^Coder/ }))
  const overview = screen.getByRole('tab', { name: 'Overview' })
  expect(screen.getByRole('tab', { name: 'Knowledge' })).toHaveAttribute('tabindex', '-1')
  overview.focus()
  await userEvent.keyboard('{ArrowRight}')
  expect(screen.getByRole('tab', { name: 'Instructions' })).toHaveFocus()
  expect(screen.getByRole('tab', { name: 'Instructions' })).toHaveAttribute('aria-selected', 'true')
  await userEvent.keyboard('{ArrowLeft}{ArrowLeft}')
  expect(screen.getByRole('tab', { name: 'Knowledge' })).toHaveFocus()
})

test('the Lead has no range to be picked in: always a tier, a model, or the conversation’s (its own default)', async () => {
  render(<AgentsPage roles={[lead, coder]} {...handlers()} />)
  await userEvent.click(screen.getByRole('button', { name: 'Open the Lead' }))
  await userEvent.click(screen.getByRole('button', { name: 'Edit model' }))
  const uses = screen.getByRole('radiogroup', { name: 'Who picks it?' })
  expect(within(uses).getByRole('radio', { name: 'As the chat' })).toBeChecked()
  expect(within(uses).getAllByRole('radio').map(o => o.closest('label')?.textContent)).toEqual(['As the chat', 'One tier', 'One model'])
  expect(screen.queryByLabelText('From')).not.toBeInTheDocument()
})

test('the Planner, which the Lead always needs, has no switch', () => {
  render(<AgentsPage roles={[lead, role({ id: 'p', name: 'Planner', kind: 'plan' }), coder]} {...handlers()} />)
  expect(screen.getByRole('button', { name: /^Planner/ })).toBeInTheDocument()
  expect(screen.queryByRole('switch', { name: 'Planner on' })).not.toBeInTheDocument()
  expect(screen.getByRole('switch', { name: 'Coder on' })).toBeChecked()
})

test('the role panel: its category, the teams it is in with their stages, tiers, thinking and what it may do', async () => {
  const h = handlers()
  render(<AgentsPage roles={[lead, coder]} teams={[...teams, teamOf('ops', 'Ops', [['Plan', []]])]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: /^Coder/ }))
  const panel = screen.getByRole('complementary', { name: 'Role Coder' })
  // 0.1.0-ui: its history is the page's History tab; no "Last picks" or "30 days" here
  expect(within(panel).getAllByRole('tab').map(t => t.textContent)).toEqual(['Overview', 'Instructions', 'Tools', 'Knowledge'])
  expect(panel).not.toHaveTextContent('Last picks')
  expect(panel).not.toHaveTextContent('30 days')
  expect(within(panel).getByLabelText("Coder's category")).toHaveDisplayValue('Build')
  expect(panel).toHaveTextContent('In teamsWeb app · BuildBackend / API · Build')
  expect(panel).toHaveTextContent('Which modelOrchestrator · fast–strongest')
  expect(panel).toHaveTextContent('How hard it thinksLow, up to HighHow much')
  expect(panel).toHaveTextContent('Mayread and search · run commands')
  // teams: taken out, and put in, at once
  await userEvent.click(within(panel).getByRole('button', { name: 'Take Coder out of Web app' }))
  expect(h.onPatch).toHaveBeenLastCalledWith('c', { teams: ['api'] })
  await userEvent.selectOptions(within(panel).getByLabelText('Put Coder in a team'), 'ops')
  expect(h.onPatch).toHaveBeenLastCalledWith('c', { teams: ['web', 'api', 'ops'] })
  // its category: another, or a new one it is put in
  await userEvent.selectOptions(within(panel).getByLabelText("Coder's category"), 'check')
  expect(h.onPatch).toHaveBeenLastCalledWith('c', { kind: 'check' })
  await userEvent.selectOptions(within(panel).getByLabelText("Coder's category"), '+ New category…')
  await userEvent.type(within(panel).getByLabelText('Category’s name'), 'Research')
  await userEvent.click(within(panel).getByRole('button', { name: 'Add' }))
  expect(h.categoryActions.addCategory).toHaveBeenCalledWith('Research', 'rose')
  await vi.waitFor(() => expect(h.onPatch).toHaveBeenLastCalledWith('c', { kind: 'k-new' }))
})

test('a role’s model part says where it runs now, then its sections; a new role’s every tool is one switch', async () => {
  const onRoleModels = vi.fn().mockResolvedValue([row({ cannot_run: 'Claude Code does not run with the model "haiku" here' })])
  render(<AgentsPage roles={[role({})]} {...handlers()} onRoleModels={onRoleModels} />)
  await userEvent.click(screen.getByRole('button', { name: /^Summarizer/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Edit model' }))
  expect(await screen.findByText(/^Runs on/)).toHaveTextContent(
    'Runs on Claude Code · haiku, thinking Low, up to High — the first balanced model of your team guide, where the Orchestrator names no tier. It would not run there now: Claude Code does not run with the model "haiku" here',
  )
  // 0.1.0-ui: the whole form, the same as a new role's, opened at its model
  expect(screen.getAllByRole('region').filter(r => r.classList.contains('role-section')).map(s => document.getElementById(s.getAttribute('aria-labelledby')!)?.textContent)).toEqual(['Model', 'It may', 'This role will'])
  // the safety stops after them, folded and closed: they are no money limit
  const stops = screen.getByText('Safety stops for one agent').closest('details')!
  expect(stops).not.toHaveAttribute('open')
  expect(screen.getByRole('region', { name: 'It may' }).compareDocumentPosition(stops) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  // a new role's tools: packs, and every tool one switch behind "Pick tools one by one"
  await userEvent.click(screen.getByRole('button', { name: 'New role' }))
  const tools = screen.getByRole('region', { name: 'It may' })
  expect(within(tools).getAllByRole('heading').map(h => h.textContent)).toEqual(['It may', 'Files', 'Commands', 'Web', 'Browser', 'Team', 'To-do', 'Memory'])
  const switches = within(tools).getAllByRole('switch')
  expect(switches.map(s => s.getAttribute('aria-label')).sort()).toEqual(ROLE_TOOLS.map(t => t.name).sort())
  expect(within(tools).getByRole('switch', { name: 'run_command' })).not.toBeChecked()
})

test('why a role runs where it does, where its tier did not give its first model, is said as its agent’s card says it (B-314)', async () => {
  const moved = 'Copilot cannot be chosen now: the conversation’s model'
  const onRoleModels = vi.fn().mockResolvedValue([row({ source: 'conversation', moved })])
  render(<AgentsPage roles={[role({})]} {...handlers()} onRoleModels={onRoleModels} />)
  await userEvent.click(screen.getByRole('button', { name: /^Summarizer/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Edit model' }))
  expect(await screen.findByText(/^Runs on/)).toHaveTextContent(`Runs on the conversation’s model, thinking Low, up to High — ${moved}.`)
})

test('what stands in a role’s way where it runs is said before any run: on its panel, and marked on its team’s stage (B-89)', async () => {
  const step = 'agy works with tools of its own in the project itself: a recipe’s work stays in its copy'
  const room = 'Codex works with tools of its own here: the Coder cannot be a member on it'
  const tools = 'The Tester role cannot work on Codex: write files and run commands'
  const onRoleModels = vi.fn().mockResolvedValue([row({ role: 'Coder', cannot_step: step, cannot_room: room }), row({ role: 'Tester', cannot_run: tools })])
  render(<AgentsPage roles={[lead, coder, tester]} teams={teams} {...handlers()} onRoleModels={onRoleModels} />)
  const web = await openTeam('Web app')
  // (No recipe of the team's own: its stages' roles are no steps, only what stops any agent is marked.)
  expect(await within(region('Stage 3, Check', web)).findByRole('img', { name: `It would not run there now: ${tools}` })).toBeInTheDocument()
  expect(within(region('Stage 2, Build', web)).queryByRole('img')).toBeNull()
  expect(web.querySelector('.team-flow .team-st-warn')).toHaveAttribute('title', `Tester: It would not run there now: ${tools}`)
  await userEvent.click(within(library()).getByRole('button', { name: /^Coder/ }))
  const said = within(screen.getByRole('list', { name: 'Will not run' })).getAllByRole('listitem').map(item => item.textContent)
  expect(said).toEqual([`⚠ Not as a recipe’s step: ${step}`, `⚠ Not in a room: ${room}`])
})

test('where an agent ran says its tier between its model and its level; with none known, none', () => {
  expect(ranOn('Claude Code', 'Opus 4.8', null, 'high', 'strongest')).toBe('Claude Code · Opus 4.8 · strongest · High')
  expect(ranOn('Claude Code', 'Opus 4.8', null, 'high', null)).toBe('Claude Code · Opus 4.8 · High')
})

test('a stage’s "New role…" makes a role in that team beside the teams, and puts it in that stage', async () => {
  const h = handlers()
  h.onCreate.mockResolvedValue(role({ id: 's', name: 'Scout', kind: 'build' }))
  render(<AgentsPage roles={[lead, coder, tester]} teams={teams} {...h} />)
  await userEvent.click(within(region('Stage 1, Plan', await openTeam('Web app'))).getByRole('button', { name: '+ Add a role' }))
  await userEvent.click(screen.getByRole('option', { name: 'New role…' }))
  const made = screen.getByRole('complementary', { name: 'New role' })
  await userEvent.type(within(made).getByLabelText('Name'), 'Scout')
  await userEvent.selectOptions(within(made).getByLabelText('Category'), 'plan')
  await userEvent.click(within(made).getByRole('switch', { name: 'read_file' }))
  await userEvent.click(within(made).getByRole('button', { name: 'Create role' }))
  expect(h.onCreate).toHaveBeenCalledWith(expect.objectContaining({ name: 'Scout', teams: ['web'], kind: 'plan' }))
  // in the stage it was asked from
  await vi.waitFor(() => expect(h.teamActions.placeRole).toHaveBeenCalledWith('web', 's', 'web-0'))
})
