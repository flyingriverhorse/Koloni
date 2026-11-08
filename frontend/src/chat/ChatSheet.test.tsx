import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import type { AllowedCommand, Project, Team } from '../api/types'
import { useApp } from '../state/store'
import { conversation, convState } from '../test-fixtures'
import { ChatSheet } from './ChatSheet'

const project = {
  id: 'p', name: 'shop-api', lead_work: 'delegates', spawn_approval: 'auto', when_away: 'lead', away_minutes: 10, max_agents: null,
  spawn_max_parallel: 2, spawn_max_depth: 2, spawn_max_agents: 6, turn_token_limit: null, monthly_budget: 40, exec_location: 'host', docker_image: null,
} as unknown as Project
const team = { id: 't1', name: 'Backend' } as Team
const rule = { id: 'r1', conversation_id: 'c', prefix: 'npm test', danger: '', created_at: 't' } as AllowedCommand

afterEach(() => {
  useApp.setState({ conv: null, projects: [], teams: [], settingsAsked: null })
  vi.restoreAllMocks()
})

function open(over: Partial<typeof conversation> = {}) {
  useApp.setState({
    conv: convState({ conversation: { ...conversation, teams_mode: 'manual', teams: [{ team_id: 't1', recipe_id: null, no_recipe: false }] as never, also_in: ['D:/lib'], ...over }, allowedCommands: [rule] }),
    projects: [project],
    teams: [team],
    settingsAsked: null,
  })
}

test('the sheet holds this chat’s own settings - teams, folders, page scripts, what runs without asking - and, read only, what it takes from its project, each a link to where it is set', async () => {
  open()
  const setPageScripts = vi.spyOn(useApp.getState(), 'setPageScripts').mockResolvedValue()
  useApp.setState({ setPageScripts })
  render(<ChatSheet sheet />)
  // Its level, Plan first and model are under the message box itself: not said again in the sheet.
  expect(screen.queryByText('Under the message box')).toBeNull()
  expect(screen.getByText('Manual: Backend')).toBeInTheDocument()
  expect(screen.getByText('shop-api · the whole project · and 1 more')).toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('Page scripts'), 'Always run in this chat')
  expect(setPageScripts).toHaveBeenCalledWith(true)
  // (Not over a canvas here: no Teams button to press, so where it is is said.)
  expect(screen.getByText('Set with the Teams button over the canvas.')).toBeInTheDocument()
  const from = screen.getByRole('region', { name: 'From shop-api' })
  expect(within(from).getByText('Who changes the files').nextSibling).toHaveTextContent('Orchestrator delegates the work')
  expect(within(from).getByText('When you’re away').nextSibling).toHaveTextContent('The Orchestrator answers what it safely can, after 10 min')
  expect(within(from).getByText('Money').nextSibling).toHaveTextContent('no token limit per message · 40 a month')
  // Each link asks Settings for its place: what runs without asking, the project's, the app's, all of them.
  for (const [name, place] of [
    ['1 run without asking →', 'rules'],
    ['Change in This project', 'agents'],
    ['Change in The app', 'app-agents'],
    ['All settings', 'chat'],
  ] as const) {
    await userEvent.click(screen.getByRole('button', { name }))
    expect(useApp.getState().settingsAsked?.section).toBe(place)
  }
})

test('the sheet presses the chat’s own Teams and folder buttons where they are', async () => {
  open()
  const teams = vi.fn()
  const folder = vi.fn()
  const buttons = (
    <>
      <button type="button" id="chat-teams-button" onClick={teams}>
        Teams
      </button>
      <button type="button" id="folder-button" onClick={folder}>
        Folder
      </button>
    </>
  )
  // (They are there before the sheet opens.)
  const { rerender } = render(buttons)
  rerender(
    <>
      {buttons}
      <ChatSheet sheet />
    </>,
  )
  await userEvent.click(screen.getByRole('button', { name: 'Change teams…' }))
  expect(teams).toHaveBeenCalledTimes(1)
  await userEvent.click(screen.getByRole('button', { name: 'Change folders…' }))
  expect(folder).toHaveBeenCalledTimes(1)
})

test('a plain chat keeps what runs without asking in it, and is told its sub-agents use KOLONİ’s defaults; on the page, the box’s own three are named', () => {
  open({ project_id: null, teams_mode: 'none', teams: [], also_in: [] })
  render(<ChatSheet />)
  expect(screen.getByText('Under the message box').nextSibling).toHaveTextContent('Ask before changes · Plan first off · the model')
  expect(screen.getByText('No folder')).toBeInTheDocument()
  expect(screen.getByText(/^No folder: sub-agents use KOLONİ’s defaults - ask when it matters, 2 at the same time, 2 levels, 6 per request\./)).toBeInTheDocument()
  expect(screen.queryByRole('region', { name: /^From / })).toBeNull()
  // (its own list, as More had it: no project to keep them in)
  expect(screen.queryByRole('button', { name: /run without asking →/ })).toBeNull()
  expect(screen.getByText('Runs without asking').nextSibling).toContainElement(screen.getByRole('button', { name: '1 rule' }))
  // (on the page: no All settings, and the panels' places are said)
  expect(screen.queryByRole('button', { name: 'All settings' })).toBeNull()
  expect(screen.getByText('Set with the folder button.')).toBeInTheDocument()
})

test('a page scripts choice the server refuses is said under it', async () => {
  open()
  const setPageScripts = vi.fn().mockRejectedValue(new Error('the chat is gone'))
  useApp.setState({ setPageScripts })
  render(<ChatSheet sheet />)
  await userEvent.selectOptions(screen.getByLabelText('Page scripts'), 'Always run in this chat')
  expect(await screen.findByRole('alert')).toHaveTextContent('the chat is gone')
})
