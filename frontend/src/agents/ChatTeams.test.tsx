import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Agent, ChatTeam, Conversation, Project, Provider, Recipe, RecipeStep, Role, RoleModel, Run, Team } from '../api/types'
import { conversation } from '../test-fixtures'
import { ChatTeams } from './ChatTeams'
import { chatColours, teamColours } from './teamRun'

// (What the window reads of a team and a recipe: the rest is the Agents page's.)
const team = (id: string, name: string, recipe: string | null = null) =>
  ({ id, name, roles: [], stages: [], lead_on: true, lead_may_pick: true, default_recipe_id: recipe }) as unknown as Team
const recipe = (id: string, name: string, steps: Partial<RecipeStep>[] = []) => ({ id, name, ready: true, graph: { steps } }) as unknown as Recipe
const teams = [team('web', 'Web app', 'feature'), team('docs', 'Docs'), team('api', 'Backend / API', 'bugfix')]
const recipes = [recipe('feature', 'Feature', [{ name: 'Code review', who: { role: 'Reviewer' } }, { name: 'Build it', who: { role: 'Coder' } }]), recipe('bugfix', 'Bugfix')]
const row = (team_id: string, over: Partial<ChatTeam> = {}): ChatTeam => ({ team_id, recipe_id: null, no_recipe: false, picked_by: 'user', why: null, ...over })
// A row as the window sends it.
const sent = (team_id: string, recipe_id: string | null = null, no_recipe = false) => ({ team_id, recipe_id, no_recipe })

function show(chat: Partial<Conversation>, project: Project | null = null, agents: Partial<Agent>[] = [], models: Partial<RoleModel>[] = [], runs: Run[] = []) {
  const props = {
    conversation: { ...conversation, ...chat },
    agents: agents as Agent[],
    runs,
    onStop: vi.fn().mockResolvedValue(undefined),
    onFinish: vi.fn().mockResolvedValue(undefined),
    teams,
    onRecipes: vi.fn().mockResolvedValue(recipes),
    onChange: vi.fn().mockResolvedValue(undefined),
    project,
    onDefault: vi.fn().mockResolvedValue(undefined),
    roles: [{ id: 'rev', name: 'Reviewer' }, { id: 'cod', name: 'Coder' }] as Role[],
    providers: [{ id: 'agy', name: 'agy' }, { id: 'cop', name: 'Copilot' }, { id: 'claude', name: 'Claude' }] as Provider[],
    onRoleModels: vi.fn().mockResolvedValue(models),
    onRunOn: vi.fn().mockResolvedValue(undefined),
  }
  const { rerender } = render(<ChatTeams {...props} />)
  return { ...props, rerender: (roles: Role[]) => rerender(<ChatTeams {...props} roles={roles} />) }
}

const panel = () => screen.getByRole('dialog', { name: 'Teams for this chat' })

test('the button says the mode; the window switches it at once', async () => {
  const { onChange } = show({})
  await userEvent.click(screen.getByRole('button', { name: 'Teams for this chat: No teams' }))
  expect(within(panel()).getByRole('radiogroup', { name: 'Who picks the teams' })).toBeInTheDocument()
  expect(within(panel()).getByRole('radio', { name: /No teams/ })).toBeChecked()
  await userEvent.click(within(panel()).getByRole('radio', { name: /Manual/ }))
  expect(onChange).toHaveBeenCalledWith({ teams_mode: 'manual' })
})

test('in Manual a team is added following its default recipe, and rows are reordered and removed', async () => {
  const { onChange } = show({ teams_mode: 'manual', teams: [row('docs'), row('web', { recipe_id: 'bugfix' })] })
  await userEvent.click(screen.getByRole('button', { name: 'Teams for this chat: 2 teams, Manual' }))
  expect(await within(panel()).findAllByRole('option', { name: 'Bugfix' })).toHaveLength(2)
  expect(within(panel()).getByLabelText('Recipe for Web app')).toHaveValue('bugfix')
  expect(within(panel()).getByLabelText('Recipe for Docs')).toHaveDisplayValue('its default (none)')
  // (A team picked anew follows its default: no recipe of its own.)
  await userEvent.selectOptions(within(panel()).getByLabelText('Team 1'), 'api')
  expect(onChange).toHaveBeenLastCalledWith({ teams: [sent('api'), sent('web', 'bugfix')] })
  await userEvent.click(within(panel()).getByRole('button', { name: '+ Add a team with a recipe' }))
  expect(onChange).toHaveBeenLastCalledWith({ teams: [sent('docs'), sent('web', 'bugfix'), sent('api')] })
  await userEvent.click(within(panel()).getByRole('button', { name: 'Move Docs down' }))
  expect(onChange).toHaveBeenLastCalledWith({ teams: [sent('web', 'bugfix'), sent('docs')] })
  await userEvent.click(within(panel()).getByRole('button', { name: 'Remove Web app' }))
  expect(onChange).toHaveBeenLastCalledWith({ teams: [sent('docs')] })
  await userEvent.selectOptions(within(panel()).getByLabelText('Recipe for Docs'), 'feature')
  expect(onChange).toHaveBeenLastCalledWith({ teams: [sent('docs', 'feature'), sent('web', 'bugfix')] })
})

test('a row’s recipe is its team’s default, No recipe in this chat, or a recipe named (K-tarifsiz)', async () => {
  const { onChange } = show({ teams_mode: 'manual', teams: [row('web'), row('api', { no_recipe: true }), row('docs', { recipe_id: 'bugfix' })] })
  await userEvent.click(screen.getByRole('button', { name: 'Teams for this chat: 3 teams, Manual' }))
  expect(await within(panel()).findByDisplayValue('its default (Feature)')).toBe(within(panel()).getByLabelText('Recipe for Web app'))
  expect(within(panel()).getByLabelText('Recipe for Backend / API')).toHaveDisplayValue('No recipe')
  expect(within(panel()).getByLabelText('Recipe for Docs')).toHaveDisplayValue('Bugfix')
  await userEvent.selectOptions(within(panel()).getByLabelText('Recipe for Web app'), 'No recipe')
  expect(onChange).toHaveBeenLastCalledWith({ teams: [sent('web', null, true), sent('api', null, true), sent('docs', 'bugfix')] })
  await userEvent.selectOptions(within(panel()).getByLabelText('Recipe for Backend / API'), 'Feature')
  expect(onChange).toHaveBeenLastCalledWith({ teams: [sent('web'), sent('api', 'feature'), sent('docs', 'bugfix')] })
  await userEvent.selectOptions(within(panel()).getByLabelText('Recipe for Docs'), 'its default (none)')
  expect(onChange).toHaveBeenLastCalledWith({ teams: [sent('web'), sent('api', null, true), sent('docs')] })
})

test('a row its recipe runs for says where it is and what its agents reported, and stops alone', async () => {
  const state = { run_id: 'r', team: 'Web app', recipe: 'Feature', status: 'running' as const, why: null, steps: [], agents: ['a', 'b'], ended_ready: false, passes: [] }
  const { onStop } = show({ teams_mode: 'manual', teams: [row('web', { state }), row('docs')] }, null, [
    { id: 'a', input_tokens: 30000, output_tokens: 1000 },
    { id: 'b', input_tokens: null, output_tokens: null },
  ])
  await userEvent.click(screen.getByRole('button', { name: 'Teams for this chat: 2 teams, Manual' }))
  // (The agent that said nothing is "–", never counted as made up.)
  expect(panel()).toHaveTextContent('Feature: running · 31k tokens + –')
  await userEvent.click(within(panel()).getByRole('button', { name: 'Stop Web app' }))
  expect(onStop).toHaveBeenCalledWith('web')
})

test('a running recipe can be finished now, its work to Ready for you; its buttons wait for the answer', async () => {
  const state = { run_id: 'r', team: 'Web app', recipe: 'Feature', status: 'running' as const, why: 'waits till 15:00 for Coder’s limit', steps: [], agents: [], ended_ready: false, passes: [] }
  const { onFinish } = show({ teams_mode: 'manual', teams: [row('web', { state })] })
  onFinish.mockReturnValue(new Promise(() => {}))
  await userEvent.click(screen.getByRole('button', { name: 'Teams for this chat: 1 team, Manual' }))
  expect(panel()).toHaveTextContent('Feature: running (waits till 15:00 for Coder’s limit)')
  await userEvent.click(within(panel()).getByRole('button', { name: 'Finish Web app now' }))
  expect(onFinish).toHaveBeenCalledWith('web')
  expect(within(panel()).getByRole('button', { name: 'Finish Web app now' })).toBeDisabled()
  expect(within(panel()).getByRole('button', { name: 'Stop Web app' })).toBeDisabled()
})

test('the Lead’s picks are shown with why, to be changed only in Manual', async () => {
  show({ teams_mode: 'lead', teams: [row('web', { picked_by: 'lead', why: 'new page work' })] })
  await userEvent.click(screen.getByRole('button', { name: 'Teams for this chat: 1 team, Orchestrator decides' }))
  expect(await within(panel()).findByText(/with Feature/)).toBeInTheDocument()
  expect(panel()).toHaveTextContent('Orchestrator’s pick: “new page work”')
  expect(within(panel()).queryByRole('combobox')).toBeNull()
  expect(within(panel()).queryByRole('button', { name: /Add a team/ })).toBeNull()
  expect(panel()).toHaveTextContent('To change them, switch to Manual')
})

test('Manual with no rows says the Lead calls any role; the choice becomes the project’s default; Plan first is the message box’s alone', async () => {
  const project = { id: 'p', teams_mode: 'none', teams: [] } as unknown as Project
  const { onDefault } = show({ teams_mode: 'manual', teams: [] }, project)
  await userEvent.click(screen.getByRole('button', { name: /^Teams for this chat/ }))
  expect(panel()).toHaveTextContent('No team picked: the Orchestrator calls any role')
  await userEvent.click(within(panel()).getByRole('button', { name: 'Use for new chats in this project' }))
  expect(onDefault).toHaveBeenCalledWith({ teams_mode: 'manual', teams: [] })
  // (one switch, under the message box: not here too)
  expect(within(panel()).queryByRole('checkbox', { name: /Plan first/ })).toBeNull()
})

test('a chat whose teams are the folder’s default says so, the backlog’s chats too (B-78)', async () => {
  const project = { id: 'p', teams_mode: 'manual', teams: [sent('web')] } as unknown as Project
  show({ teams_mode: 'manual', teams: [row('web')] }, project)
  await userEvent.click(screen.getByRole('button', { name: 'Teams for this chat: 1 team, Manual' }))
  expect(panel()).toHaveTextContent('This folder’s default for new chats, the To-do list’s too.')
  expect(within(panel()).queryByRole('button', { name: 'Use for new chats in this project' })).toBeNull()
})

test('a row with no recipe of its own says its team’s default', async () => {
  show({ teams_mode: 'manual', teams: [row('api')] })
  await userEvent.click(screen.getByRole('button', { name: 'Teams for this chat: 1 team, Manual' }))
  await within(panel()).findAllByRole('option', { name: 'Bugfix' })
  expect(within(panel()).getByLabelText('Recipe for Backend / API')).toHaveDisplayValue('its default (Bugfix)')
})

test('a row with no recipe beside one says so, not ": running"', async () => {
  const state = { run_id: 'r', team: 'Docs', recipe: '', status: 'running' as const, why: null, steps: [], agents: ['a'], ended_ready: null, passes: [] }
  show({ teams_mode: 'manual', teams: [row('docs', { state })] }, null, [{ id: 'a', input_tokens: 1000, output_tokens: 0 }])
  await userEvent.click(screen.getByRole('button', { name: 'Teams for this chat: 1 team, Manual' }))
  expect(panel()).toHaveTextContent('no recipe: running · 1k tokens')
  expect(within(panel()).queryByRole('button', { name: 'Finish Docs now' })).toBeNull()
})

test('a recipe step whose role cannot be a step where it runs says so on its row; the role is run elsewhere only where it could be that step, asked first', async () => {
  const agy = {
    role: 'Reviewer',
    provider_name: 'agy',
    cannot_run: null,
    cannot_step: 'agy works with tools of its own in the project itself',
    cannot_room: null,
    run_on: [
      { provider_id: 'agy', model_id: null, step: false, room: false },
      { provider_id: 'cop', model_id: null, step: false, room: false },
      { provider_id: 'claude', model_id: 'sonnet', step: true, room: false },
    ],
  }
  const { onRunOn, onRoleModels } = show({ teams_mode: 'manual', teams: [row('web')] }, null, [], [agy, { role: 'Coder', provider_name: 'Claude', cannot_run: null, cannot_step: null, cannot_room: null, run_on: [] }])
  // B-337: KOLONİ's own question in the window, never the browser's.
  const confirm = vi.spyOn(window, 'confirm')
  const asked = () => within(panel()).queryByRole('alertdialog', { name: 'Run Reviewer on Claude in every chat? Its agents run there wherever they are opened, and its tier rule goes.' })
  try {
    await userEvent.click(screen.getByRole('button', { name: 'Teams for this chat: 1 team, Manual' }))
    expect(await within(panel()).findByText('⚠ Code review: Reviewer: Not as a recipe’s step: agy works with tools of its own in the project itself')).toBeVisible()
    expect(within(panel()).queryByText(/Build it/)).toBeNull()
    const pick = within(panel()).getByRole('combobox', { name: 'Run Reviewer on another provider, in every chat' })
    // (neither where it runs now, nor another CLI that works in the project itself)
    expect(within(pick).getAllByRole('option').map(one => one.textContent)).toEqual(['Run Reviewer on another provider (in every chat)…', 'Claude (sonnet)'])
    await userEvent.selectOptions(pick, 'claude')
    expect(asked()).toBeInTheDocument()
    await userEvent.click(within(asked()!).getByRole('button', { name: 'Cancel' }))
    expect(asked()).toBeNull()
    expect(onRunOn).not.toHaveBeenCalled()
    onRoleModels.mockResolvedValue([{ ...agy, provider_name: 'Claude', cannot_step: null }])
    await userEvent.selectOptions(pick, 'claude')
    await userEvent.click(within(asked()!).getByRole('button', { name: 'Run it on Claude' }))
    expect(onRunOn).toHaveBeenCalledWith('rev', 'claude', 'sonnet')
    expect(confirm).not.toHaveBeenCalled()
    await waitFor(() => expect(within(panel()).queryByText(/Code review/)).toBeNull())
  } finally {
    confirm.mockRestore()
  }
})

test('who uses what is read again as a role changes elsewhere while the window is open (R57)', async () => {
  const warned = { role: 'Reviewer', provider_name: 'agy', cannot_run: null, cannot_step: 'agy works with tools of its own in the project itself', cannot_room: null, run_on: [] }
  const props = show({ teams_mode: 'manual', teams: [row('web')] }, null, [], [warned])
  await userEvent.click(screen.getByRole('button', { name: 'Teams for this chat: 1 team, Manual' }))
  expect(await within(panel()).findByText(/⚠ Code review: Reviewer/)).toBeVisible()
  props.onRoleModels.mockResolvedValue([{ ...warned, provider_name: 'Claude', cannot_step: null }])
  props.rerender([...props.roles])
  await waitFor(() => expect(within(panel()).queryByText(/⚠ Code review/)).toBeNull())
})

test('who uses what is read only where a row has a recipe', async () => {
  const { onRoleModels } = show({ teams_mode: 'manual', teams: [row('docs')] })
  await userEvent.click(screen.getByRole('button', { name: 'Teams for this chat: 1 team, Manual' }))
  expect(onRoleModels).not.toHaveBeenCalled()
})

test('a table that cannot be read leaves the window without an error', async () => {
  const props = show({ teams_mode: 'manual', teams: [row('web')] })
  props.onRoleModels.mockRejectedValue(new Error('no provider at all'))
  await userEvent.click(screen.getByRole('button', { name: 'Teams for this chat: 1 team, Manual' }))
  await waitFor(() => expect(props.onRoleModels).toHaveBeenCalled())
  expect(within(panel()).queryByRole('alert')).toBeNull()
})

test('B-103: a team’s dot is its colour on the chat’s canvas - one set for the chat, its turns’ teams too', async () => {
  // ("ml" and "web" want one colour: the turn had both, the chat has only Web app now.)
  const turn = { id: 'r', teams: [row('ml'), row('web')] } as unknown as Run
  show({ teams_mode: 'manual', teams: [row('web')] }, null, [], [], [turn])
  await userEvent.click(screen.getByRole('button', { name: /Teams for this chat/ }))
  const dot = within(panel()).getByLabelText('Team 1').parentElement!.querySelector('.team-dot') as HTMLElement
  const canvas = chatColours({ conversation: { ...conversation, teams: [row('web')] }, runs: [turn] }).get('web')!
  const same = document.createElement('i')
  same.style.background = canvas // (as the page says a colour)
  expect(dot.style.background).toBe(same.style.background)
  expect(canvas).not.toBe(teamColours(['web']).get('web'))
})
