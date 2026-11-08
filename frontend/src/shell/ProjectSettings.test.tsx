import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { api, ApiError } from '../api/client'
import type { Project } from '../api/types'
import { useApp } from '../state/store'
import { ProjectSettings } from './ProjectSettings'

const project: Project = {
  id: 'p',
  name: 'demo',
  root_path: 'C:/demo',
  created_at: 't',
  exec_location: 'host',
  docker_image: null,
  docker_network: false,
  search_url: null,
  search_order: 'builtin',
  search_agy: false,
  has_notify_url: false,
  notify_format: 'slack',
  notify_desktop: false,
  turn_token_limit: null,
  max_agents: null, continue_steps: 25,
  monthly_budget: null,
  check_command: null, measure_command: null, finish_tests: null, finish_tests_auto: { on: false, command: null, reason: 'test time not known yet' }, memory_links: [], embedding_provider_id: null, embedding_model: 'text-embedding-3-small',
  git_commit: false,
  finish_way: null,
  auto_notes: false,
  observe_reports: false,
  suggest_tasks: true,
  suggest_tier: 'fast',
  day_note_at: null,
  also_in: [], read_in: [], teams_mode: 'none', teams: [],
  hide_secrets: true, canary: true, lead_work: 'delegates', when_away: 'waits', away_minutes: 10, spawn_approval: 'auto', spawn_max_depth: 2, spawn_max_agents: 6, spawn_max_parallel: 2, discussion_budget: null, room_posts: 40, room_tokens: null, room_minutes: 30, room_min_tokens: 60000, pass_env: null, held_env: [], koloni: { settings_kept: false, rules_kept: false, rules: null, broken: [], asks: {} },
}
// (Opened on Commands, the first section before tek-ev: the tests of it need no click to reach it.)
const base = { project, dockerAvailable: true, dockerError: null, desktopAvailable: true, picked: { section: 'commands' as const, n: 1 } }

test('under “This machine” the shell is named; without PowerShell 7, or with only the Store’s, what 5.1 costs and how to get 7', () => {
  const store = 'PowerShell 7 from the Store cannot be used (its commands\' child processes escape KOLONİ\'s kill): install it with winget install --id Microsoft.PowerShell -e --source winget; until then commands run in Windows PowerShell 5.1 (Set-Content writes a UTF-8 BOM)'
  const said: [string | null, string | null, string][] = [
    ['PowerShell 7', null, 'Commands are not isolated. Commands run in PowerShell 7.'],
    ['Windows PowerShell', null, 'PowerShell 7 not found: commands run in Windows PowerShell 5.1, where Set-Content writes a UTF-8 BOM — install PowerShell 7 to avoid it.'],
    ['Windows PowerShell', store, `Commands are not isolated. ${store}.`],
    [null, null, 'Commands are not isolated.'],
  ]
  for (const [shell, shellNote, line] of said) {
    const view = render(<ProjectSettings {...base} shell={shell} shellNote={shellNote} onSave={vi.fn()} />)
    const note = screen.getByLabelText(/This machine/).closest('label')!
    expect(note).toHaveTextContent(line)
    if (!shell) expect(note).not.toHaveTextContent('Commands run in')
    if (shellNote) expect(note).not.toHaveTextContent('PowerShell 7 not found')
    view.unmount()
  }
})

/** The page shows one section at a time: its row in the list is chosen first. */
const choose = (name: RegExp) => userEvent.click(screen.getByRole('button', { name }))

test('the check command and the commit of what is taken are set here, each saying when it runs; sent only when changed', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  const { unmount } = render(<ProjectSettings {...base} onSave={onSave} />)
  await choose(/^Checks/)
  const command = screen.getByLabelText('Test before adding')
  expect(command).toHaveValue('')
  // what it does, on what and where, and when it runs by itself - in sight, not behind ⓘ
  const said = screen.getByText(/^This command runs first on the sub-agent’s changes together with what the project changed meanwhile, in the sub-agent’s working copy, where this project’s commands run\./)
  expect(said.closest('.hint')).toBeNull()
  expect(said).toHaveTextContent(/Only exit code 0 passes\. If it fails, you decide; work nobody watches is not added\. Empty: no test\./)
  expect(said).toHaveTextContent(/It runs by itself only where commands do: in Full auto, and in a trigger’s run that has this very command ticked\./)
  expect(said).toHaveTextContent(/In “Ask before changes” and “Auto-edit files” the card shows the changes first and you start it there: it runs what the agent wrote\./)
  // what of its own doing is not undone: the linked folders are the project's own
  expect(said).toHaveTextContent(/What it writes into node_modules, \.venv or venv stays\./)
  // how it works is behind ⓘ, and still describes the field
  expect(command).toHaveAccessibleDescription(/venv stays\. What it writes to the copy’s own files is put back afterwards; .* the copy is kept for you\.$/)
  const commit = screen.getByLabelText(/^Save each sub-agent’s work as a git commit/)
  expect(commit).not.toBeChecked()
  // (its first sentence stands under the box; the rest of the note is behind ⓘ beside it, closed)
  const offered = screen.getByText(/^One commit per piece of work\. Offered on the card .* top folder of a git repository\.$/)
  expect(within(offered).getByText(/^Always your click: never made by itself, never in a trigger’s turn/)).not.toBeVisible()
  // The box is named as it was - by all of its note, word for word what the page shows - and not by the
  // button that opens it. It says so in its own label: a browser leaves a closed hint out of a name.
  expect(commit).toHaveAccessibleName(/^Save each sub-agent’s work as a git commit One commit per piece of work\. Offered on the card .* top folder of a git repository\. Always your click.* Nothing is pushed\.$/)
  // (less the hint's "Learn more →": a link to the guide, no part of the note)
  const shown = offered.closest('label')!.textContent!.replace('Learn more →', '')
  expect(commit.getAttribute('aria-label')!.replace(/\s+/g, '')).toBe(shown.replace(/\s+/g, ''))
  await userEvent.type(command, ' python -m pytest -q ')
  await userEvent.click(commit)
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({ check_command: 'python -m pytest -q', git_commit: true })
  unmount()
  // What is set is shown; left alone it is not sent; emptied, the check is taken away.
  onSave.mockClear()
  render(<ProjectSettings {...base} project={{ ...project, check_command: 'npm test', git_commit: true }} onSave={onSave} />)
  await choose(/^Checks/)
  expect(screen.getByLabelText('Test before adding')).toHaveValue('npm test')
  expect(screen.getByLabelText(/^Save each sub-agent’s work as a git commit/)).toBeChecked()
  // Left as it is, nothing is sent: there is nothing to save.
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  await userEvent.clear(screen.getByLabelText('Test before adding'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ check_command: '' })
})

test('the measure command is set beside the test command, saying its last line is the score; sent only when changed', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  const { unmount } = render(<ProjectSettings {...base} onSave={onSave} />)
  await choose(/^Checks/)
  const measure = screen.getByLabelText('Measure command')
  expect(measure).toHaveAccessibleDescription(/^The last line of its output is a number from 0 to 100: the score .* measured in its working copy\. Empty: nothing is measured\./)
  await userEvent.type(measure, ' python measure.py ')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({ measure_command: 'python measure.py' })
  unmount()
  onSave.mockClear()
  render(<ProjectSettings {...base} project={{ ...project, measure_command: 'python measure.py' }} onSave={onSave} />)
  await choose(/^Checks/)
  expect(screen.getByLabelText('Measure command')).toHaveValue('python measure.py')
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  await userEvent.clear(screen.getByLabelText('Measure command'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ measure_command: '' })
})

test('“Finish only when the tests pass” is on or off by itself, saying why; set as it would be by itself, it is automatic again', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  vi.spyOn(api, 'get').mockImplementation(async path => (path === '/compaction' ? { compact_at: 75 } : path.endsWith('/sites') ? [] : { paths: [], more: 0, partial: false }) as never)
  const auto = { on: true, command: 'python -m pytest -q', reason: 'the tests took 12 s last time' }
  const { unmount } = render(<ProjectSettings {...base} project={{ ...project, finish_tests_auto: auto }} onSave={onSave} />)
  await choose(/^Agents/)
  const box = screen.getByRole('checkbox', { name: /^Finish only when the tests pass/ })
  expect(box).toBeChecked()
  expect(box).toHaveAccessibleName(/An agent \(the Orchestrator or a sub-agent\) on Claude Code that changed files is sent back to work, at most twice, while python -m pytest -q fails/)
  expect(screen.getByTestId('finish-tests-why')).toHaveTextContent(/^By default on: the tests took 12 s last time\.$/)
  await userEvent.click(box)
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ finish_tests: false })
  unmount()
  // The user's own choice says so; turned back to what it would be by itself, null goes: automatic.
  render(<ProjectSettings {...base} project={{ ...project, finish_tests: false, finish_tests_auto: auto }} onSave={onSave} />)
  await choose(/^Agents/)
  expect(screen.getByRole('checkbox', { name: /^Finish only when the tests pass/ })).not.toBeChecked()
  expect(screen.getByTestId('finish-tests-why')).toHaveTextContent(/^You set this; by default it would be on: the tests took 12 s last time\.$/)
  await userEvent.click(screen.getByRole('checkbox', { name: /^Finish only when the tests pass/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ finish_tests: null })
})

test('where a search and a notification go is set here, and only what was changed is sent', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  const { unmount } = render(<ProjectSettings {...base} onSave={onSave} />)
  await choose(/^Notifications/)
  expect(screen.getByText('No notification address is set.')).toBeInTheDocument()
  await choose(/^Memory and web/)
  await userEvent.type(screen.getByLabelText('Search address (SearXNG)'), ' http://localhost:8888 ')
  await userEvent.selectOptions(screen.getByLabelText('Otherwise search with'), 'A CLI first, then the built-in search')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ search_url: 'http://localhost:8888', search_order: 'cli' })
  await choose(/^Notifications/)
  await userEvent.type(screen.getByLabelText('Notification address'), 'https://hooks.example.com/x')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ notify_url: 'https://hooks.example.com/x' })
  unmount()
  // One that is set is never shown: only that there is one, and it can be replaced or removed.
  onSave.mockClear()
  render(<ProjectSettings {...base} project={{ ...project, search_url: 'http://localhost:8888', search_order: 'cli', has_notify_url: true }} onSave={onSave} />)
  await choose(/^Memory and web/)
  expect(screen.getByLabelText('Search address (SearXNG)')).toHaveValue('http://localhost:8888')
  await userEvent.clear(screen.getByLabelText('Search address (SearXNG)'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ search_url: '' })
  await choose(/^Notifications/)
  expect(screen.getByLabelText('Notification address')).toHaveValue('')
  expect(screen.getByText('A notification address is set. It is not shown again; type a new one to replace it.')).toBeInTheDocument()
  await userEvent.click(screen.getByLabelText('Remove the notification address'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ notify_url: '' })
})

test('agy searches only where the box is ticked, which says why it is a risk; it is sent only when changed', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  const { unmount } = render(<ProjectSettings {...base} onSave={onSave} />)
  await choose(/^Memory and web/)
  const box = screen.getByLabelText(/^Let agy search too/)
  expect(box).not.toBeChecked()
  expect(screen.getByText('While it searches, agy is not held to its search tool: it may read files on this machine or open pages unasked. Codex and Claude Code are held to it.')).toBeInTheDocument()
  await userEvent.click(box)
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({ search_agy: true })
  unmount()
  onSave.mockClear()
  render(<ProjectSettings {...base} project={{ ...project, search_agy: true }} onSave={onSave} />)
  await choose(/^Memory and web/)
  expect(screen.getByLabelText(/^Let agy search too/)).toBeChecked()
  // Left as it is, nothing is sent: there is nothing to save.
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  expect(onSave).not.toHaveBeenCalled()
})

test('the desktop notification and the form of the posted body are set here, and sent only when changed', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  const { unmount } = render(<ProjectSettings {...base} onSave={onSave} />)
  await choose(/^Notifications/)
  const desktop = screen.getByLabelText(/^Show a desktop notification/)
  expect(desktop).not.toBeChecked()
  expect(screen.getByLabelText('Post it as')).toHaveValue('slack')
  await userEvent.click(desktop)
  await userEvent.selectOptions(screen.getByLabelText('Post it as'), 'Plain text - ntfy')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({ notify_format: 'text', notify_desktop: true })
  unmount()
  // What is set is shown, and taking the box off is sent as that.
  onSave.mockClear()
  render(<ProjectSettings {...base} project={{ ...project, notify_format: 'discord', notify_desktop: true }} onSave={onSave} />)
  await choose(/^Notifications/)
  expect(screen.getByLabelText('Post it as')).toHaveValue('discord')
  await userEvent.click(screen.getByLabelText(/^Show a desktop notification/))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({ notify_desktop: false })
})

test('where the system shows no desktop notification the box is off and says so; one that is on can be taken off', async () => {
  const { unmount } = render(<ProjectSettings {...base} desktopAvailable={false} onSave={vi.fn()} />)
  await choose(/^Notifications/)
  expect(screen.getByLabelText(/^Show a desktop notification/)).toBeDisabled()
  expect(screen.getByText('A desktop notification is not available on this system.')).toBeInTheDocument()
  unmount()
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<ProjectSettings {...base} desktopAvailable={false} project={{ ...project, notify_desktop: true }} onSave={onSave} />)
  await choose(/^Notifications/)
  await userEvent.click(screen.getByLabelText(/^Show a desktop notification/))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({ notify_desktop: false })
})

test('a limit on a turn’s tokens is set and taken away here, says what it cannot count, and takes nothing but a whole number', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  const { unmount } = render(<ProjectSettings {...base} onSave={onSave} />)
  await choose(/^Limits and money/)
  const field = screen.getByLabelText('Stop the work on a message over this many tokens')
  expect(field).toHaveValue('')
  // What the limit does, as it does it - and what it cannot hold.
  const note = screen.getByText(/Checked before each model step, and for a CLI session as its messages arrive\. Once over, whatever is still at work is stopped/)
  expect(note).toHaveTextContent(/Only what a model reports is counted: a CLI that reports no tokens is not limited by this, and one that reports only at its end can go past it\./)
  expect(note).toHaveTextContent(/Agents at work at the same time can each take one more step before the limit is seen\./)
  for (const wrong of ['0', '-5', '1.5', 'many']) {
    await userEvent.clear(field)
    await userEvent.type(field, wrong)
    expect(field).toBeInvalid()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  }
  await userEvent.clear(field)
  await userEvent.type(field, '200000')
  expect(field).toBeValid()
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({ turn_token_limit: 200000 })
  unmount()
  // One that is set is shown; left as it is, it is not sent; emptied, it is taken away.
  onSave.mockClear()
  render(<ProjectSettings {...base} project={{ ...project, turn_token_limit: 200000 }} onSave={onSave} />)
  await choose(/^Limits and money/)
  expect(screen.getByLabelText('Stop the work on a message over this many tokens')).toHaveValue('200000')
  // Left as it is, nothing is sent: there is nothing to save.
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  await userEvent.clear(screen.getByLabelText('Stop the work on a message over this many tokens'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ turn_token_limit: null })
})

test('choosing Docker needs an image before it can be saved', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<ProjectSettings {...base} onSave={onSave} />)
  expect(screen.getByLabelText(/This machine/)).toBeChecked()
  await userEvent.click(screen.getByLabelText(/Docker container/))
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  await userEvent.type(screen.getByLabelText('Image'), 'python:3.12')
  await userEvent.click(screen.getByLabelText('Allow network access'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({
    exec_location: 'docker',
    docker_image: 'python:3.12',
    docker_network: true,
  })
})

test('secret files are hidden from commands unless turned off, a secret variable is passed by name, and the held-back names are listed', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<ProjectSettings {...base} project={{ ...project, held_env: ['GITHUB_TOKEN', 'OPENAI_API_KEY'] }} onSave={onSave} />)
  const hide = screen.getByLabelText(/^Hide secret files from commands/)
  expect(hide).toBeChecked()
  // only where that is so: Docker and Copilot's sandbox; elsewhere the cards ask
  expect(
    screen.getByText('In Docker and in Copilot’s sandbox, commands see secret files (.env, keys) as empty or blocked. Elsewhere, an agent’s read or search of one asks you first. Turn off only if a command must read one.'),
  ).toBeVisible()
  const passed = screen.getByLabelText('Secret variables commands may see')
  expect(passed).toHaveValue('')
  expect(passed).toHaveAccessibleDescription(/Any other variable named like a secret is held back from commands\./)
  expect(passed).toHaveAccessibleDescription(/Held back from commands: GITHUB_TOKEN, OPENAI_API_KEY/)
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  await userEvent.click(hide)
  await userEvent.type(passed, ' OPENAI_API_KEY ')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({ exec_location: 'host', docker_image: null, docker_network: false, hide_secrets: false, pass_env: 'OPENAI_API_KEY' })
})

test('with no secret variable held back, none is listed', () => {
  render(<ProjectSettings {...base} onSave={vi.fn()} />)
  expect(screen.queryByText(/Held back from commands/)).not.toBeInTheDocument()
})

test('a server older than the page, without the secret fields, does not break it; unchanged, they are not sent', async () => {
  // (K-ayar-cokme: the page crashed on held_env before KOLONİ was restarted)
  const { hide_secrets: _h, pass_env: _p, held_env: _e, lead_work: _w, ...older } = project
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<ProjectSettings {...base} project={older as Project} onSave={onSave} />)
  expect(screen.getByLabelText(/^Hide secret files from commands/)).toBeChecked()
  expect(screen.queryByText(/Held back from commands/)).not.toBeInTheDocument()
  await userEvent.click(screen.getByLabelText(/Docker container/))
  await userEvent.type(screen.getByLabelText('Image'), 'python:3.12')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({ exec_location: 'docker', docker_image: 'python:3.12', docker_network: false })
})

test('when Docker is not available the option is off and says why', () => {
  render(
    <ProjectSettings {...base} dockerAvailable={false} dockerError="Docker is not running" onSave={vi.fn()} />,
  )
  expect(screen.getByLabelText(/Docker container/)).toBeDisabled()
  expect(screen.getByText('Docker is not running')).toBeInTheDocument()
})

test('a project already on Docker can switch back even when Docker is down', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(
    <ProjectSettings
      {...base}
      project={{ ...project, exec_location: 'docker', docker_image: 'alpine' }}
      dockerAvailable={false}
      dockerError="Docker is not running"
      onSave={onSave}
    />,
  )
  expect(screen.getByLabelText(/Docker container/)).toBeChecked()
  await userEvent.click(screen.getByLabelText(/This machine/))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({ exec_location: 'host', docker_image: 'alpine', docker_network: false })
})

test('a refused save shows the reason and keeps the panel open', async () => {
  const onSave = vi.fn().mockRejectedValue({ detail: 'choose a Docker image first' })
  render(<ProjectSettings {...base} onSave={onSave} />)
  await userEvent.click(screen.getByLabelText(/Docker container/))
  await userEvent.type(screen.getByLabelText('Image'), 'python:3.12')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('choose a Docker image first')
})

test('a successful save keeps the page open, with what another section has not saved yet', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<ProjectSettings {...base} onSave={onSave} />)
  await choose(/^Memory/)
  await userEvent.click(screen.getByLabelText(/^Note what the work found, by itself/))
  await choose(/^Limits and money/)
  await userEvent.type(screen.getByLabelText('Stop the work on a message over this many tokens'), '5000')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({ turn_token_limit: 5000 })
  expect(screen.getByRole('form', { name: 'Project settings' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /^Memory/ })).toHaveTextContent('not saved')
  await choose(/^Memory/)
  expect(screen.getByLabelText(/^Note what the work found, by itself/)).toBeChecked()
})

test('noting what a turn found is switched here, says what it costs and that nothing goes into the core by itself; sent only when changed', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  const { unmount } = render(<ProjectSettings {...base} onSave={onSave} />)
  await choose(/^Memory/)
  const box = screen.getByLabelText(/^Note what the work found, by itself/)
  expect(box).not.toBeChecked()
  // what it costs, what it holds up and what it does not do are in sight; how it is made is behind ⓘ, closed
  const said = screen.getByText(/^After each message’s work, a fast model writes at most three notes of what it found\./)
  expect(said.closest('.hint')).toBeNull()
  expect(said).toHaveTextContent(/one more model request after every message, on your plan or your bill; Usage shows it under that model/)
  expect(said).toHaveTextContent(/Nothing goes into the core by itself: that stays your decision\./)
  expect(said).toHaveTextContent(/While it runs \(at most 90 seconds\) it holds a place like any model step, so the next message may wait for one\./)
  const rest = screen.getByText(/^It is the first model you gave the fast tier in the team guide, with no tools\./)
  expect(rest).not.toBeVisible()
  expect(rest).not.toHaveTextContent(/90 seconds/)
  // the box is named by all of its note, and not by the hint's button
  expect(box).toHaveAccessibleName(/^Note what the work found, by itself After each message’s work, .* The Memory page shows how the last one went\.$/)
  expect(box.getAttribute('aria-label')!.replace(/\s+/g, '')).toBe(said.closest('label')!.textContent!.replace('Learn more →', '').replace(/\s+/g, ''))
  // Left as it is, nothing is sent: there is nothing to save.
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  expect(onSave).not.toHaveBeenCalled()
  await userEvent.click(box)
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ auto_notes: true })
  unmount()
  render(<ProjectSettings {...base} project={{ ...project, auto_notes: true }} onSave={onSave} />)
  await choose(/^Memory/)
  await userEvent.click(screen.getByLabelText(/^Note what the work found, by itself/))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ auto_notes: false })
})

// --- slice 35: a page of sections -------------------------------------------------------------

const rows = () => screen.getAllByRole('button').filter(button => button.classList.contains('conv-row'))

test('the list has the eleven sections of Settings › This project (sample A), by name, in a navigable list', () => {
  render(<ProjectSettings {...base} picked={undefined} onSave={vi.fn()} />)
  expect(screen.getByRole('navigation', { name: 'Project settings sections' })).toBeInTheDocument()
  expect(rows().map(row => row.textContent)).toEqual([
    'Agents', 'Asking and away', 'New chats start with', 'Limits and money', 'Commands and secrets', 'Runs without asking', 'Checks and git', 'Memory and web', 'Notifications', 'Slash commands', 'This folder',
  ])
  // The page opens on the first.
  expect(rows()[0]).toHaveAttribute('aria-current', 'true')
})

test('a chosen section alone is shown, each field under its label as before', async () => {
  render(<ProjectSettings {...base} desktopAvailable onSave={vi.fn()} />)
  const fields: [RegExp, (string | RegExp)[]][] = [
    [/^Commands/, [/This machine/, /Docker container/]],
    [/^Agents/, ['Who changes the files', /^Finish only when the tests pass/]],
    [/^Asking and away/, ['Opening a sub-agent', 'When you’re away']],
    [/^New chats start with/, ['New chats’ teams', 'Posts, at most', 'Minutes, at most', 'Tokens, at most']],
    [/^Checks/, ['Test before adding', /^Save each sub-agent’s work as a git commit/]],
    [/^Memory and web/, [/^Note what the work found, by itself/, 'Search by meaning with', 'Search address (SearXNG)', 'Otherwise search with', /^Let agy search too/]],
    [/^Notifications/, ['Notification address', 'Post it as', /^Show a desktop notification/]],
    [/^Limits and money/, ['At most this many agents at work in this project', 'Agents at the same time', 'Continue gives this many more steps', 'Stop the work on a message over this many tokens']],
  ]
  for (const [section, labels] of fields) {
    await choose(section)
    expect(screen.getByRole('button', { name: section })).toHaveAttribute('aria-current', 'true')
    for (const label of labels) expect(screen.getByLabelText(label)).toBeInTheDocument()
    // and nothing of any other section
    for (const [other, theirs] of fields) if (other !== section) for (const label of theirs) expect(screen.queryByLabelText(label)).toBeNull()
  }
})

test('a section’s Save sends that section alone; a change elsewhere waits where it is, marked as not saved', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  const { rerender } = render(<ProjectSettings {...base} onSave={onSave} />)
  expect(screen.queryByText('not saved')).toBeNull()
  await choose(/^Limits and money/)
  await userEvent.type(screen.getByLabelText('Stop the work on a message over this many tokens'), '5000')
  await choose(/^Notifications/)
  await userEvent.click(screen.getByLabelText(/^Show a desktop notification/))
  // Both are marked; the list's lines still say what is saved.
  expect(screen.getByRole('button', { name: /^Limits and money/ })).toHaveTextContent('Limits and moneynot saved')
  // (said to a screen reader as the row's state, not as part of its name)
  expect(screen.getByRole('button', { name: /^Limits and money/ })).toHaveAccessibleName('Limits and money')
  expect(screen.getByRole('button', { name: /^Limits and money/ })).toHaveAccessibleDescription('not saved')
  expect(screen.getByRole('button', { name: /^Notifications/ })).toHaveTextContent('not saved')
  expect(screen.getByRole('button', { name: /^Commands/ })).not.toHaveTextContent('not saved')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledTimes(1)
  expect(onSave).toHaveBeenCalledWith({ notify_desktop: true })
  // The project as saved comes back: that section's mark goes, its line says so; the other's change is still there.
  rerender(<ProjectSettings {...base} project={{ ...project, notify_desktop: true }} onSave={onSave} />)
  expect(screen.getByRole('button', { name: /^Notifications/ })).not.toHaveTextContent('not saved')
  expect(screen.getByRole('button', { name: /^Limits and money/ })).toHaveTextContent('not saved')
  await choose(/^Limits and money/)
  expect(screen.getByLabelText('Stop the work on a message over this many tokens')).toHaveValue('5000')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ turn_token_limit: 5000 })
})

test('a value that cannot be sent is marked as not saved, and keeps only its own section from saving', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<ProjectSettings {...base} onSave={onSave} />)
  await choose(/^Limits and money/)
  await userEvent.type(screen.getByLabelText('At most this many agents at work in this project'), 'lots')
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  expect(screen.getByRole('button', { name: /^Limits and money/ })).toHaveTextContent('not saved')
  await choose(/^Memory/)
  await userEvent.click(screen.getByLabelText(/^Note what the work found, by itself/))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({ auto_notes: true })
})

test('a notification address once saved is cleared from its field, and the section is no longer marked', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  const { rerender } = render(<ProjectSettings {...base} onSave={onSave} />)
  await choose(/^Notifications/)
  await userEvent.type(screen.getByLabelText('Notification address'), 'https://hooks.example.com/x')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({ notify_url: 'https://hooks.example.com/x' })
  rerender(<ProjectSettings {...base} project={{ ...project, has_notify_url: true }} onSave={onSave} />)
  expect(screen.getByLabelText('Notification address')).toHaveValue('')
  expect(screen.getByRole('button', { name: /^Notifications/ })).not.toHaveTextContent('not saved')
})

test('Docker not running is one line under the Docker choice, with what Docker said behind ⓘ, and nowhere else', async () => {
  const said = 'Docker is not running (failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine)'
  render(<ProjectSettings {...base} dockerAvailable={false} dockerError={said} onSave={vi.fn()} />)
  const line = screen.getByText(/^Docker is not running: a container cannot be chosen\.$/).parentElement!
  // Under the Docker choice, and before anything else of the section: the sentence, and ⓘ beside it.
  expect(screen.getByLabelText(/Docker container/).closest('label')!.nextElementSibling).toBe(line)
  expect(line).toHaveClass('docker-down')
  expect(Array.from(line.children).map(child => child.className)).toEqual(['', 'hint'])
  expect(within(line).getByText(said)).not.toBeVisible()
  await userEvent.click(within(line).getByRole('button', { name: 'About this' }))
  expect(within(line).getByText(said)).toBeVisible()
  for (const section of [/^Agents/, /^New chats start with/, /^Checks/, /^Memory and web/, /^Notifications/, /^Limits and money/]) {
    await choose(section)
    expect(screen.queryByText(/Docker is not running/)).toBeNull()
  }
})

test('the list and then the fields are reached in turn by the keyboard, each “why” on the way', async () => {
  render(<ProjectSettings {...base} picked={undefined} onSave={vi.fn()} />)
  for (const row of rows()) {
    await userEvent.tab()
    expect(row).toHaveFocus()
  }
  // (a field's ⓘ is reached before the field)
  await userEvent.tab()
  expect(screen.getAllByRole('button', { name: 'About this' })[0]).toHaveFocus()
  await userEvent.tab()
  expect(screen.getByLabelText('Who changes the files')).toHaveFocus()
  // A section is chosen from the keyboard too.
  for (let i = 0; i < 4; i++) await userEvent.tab({ shift: true })
  expect(rows()[8]).toHaveFocus()
  await userEvent.keyboard('{Enter}')
  expect(screen.getByLabelText('Notification address')).toBeInTheDocument()
})

test('a section whose Save is refused keeps what was said: it is not shown under another one chosen meanwhile', async () => {
  let refuse: (reason: unknown) => void = () => {}
  const onSave = vi.fn(() => new Promise<void>((_, reject) => (refuse = reject)))
  render(<ProjectSettings {...base} onSave={onSave} />)
  await choose(/^Memory/)
  await userEvent.click(screen.getByLabelText(/^Note what the work found, by itself/))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  await choose(/^Limits and money/)
  refuse({ detail: 'no fast model in the team guide' })
  await screen.findByLabelText('Stop the work on a message over this many tokens')
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(screen.queryByRole('alert')).toBeNull()
  await choose(/^Memory/)
  expect(screen.getByRole('alert')).toHaveTextContent('no fast model in the team guide')
})

test('a section saved says so beside its Save, until it is changed again', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  const { rerender } = render(<ProjectSettings {...base} onSave={onSave} />)
  await choose(/^Memory/)
  expect(screen.getByRole('status')).toHaveTextContent('')
  await userEvent.click(screen.getByLabelText(/^Note what the work found, by itself/))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  // The project as saved comes back.
  rerender(<ProjectSettings {...base} project={{ ...project, auto_notes: true }} onSave={onSave} />)
  expect(screen.getByRole('status')).toHaveTextContent('Saved')
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  await userEvent.click(screen.getByLabelText(/^Note what the work found, by itself/))
  expect(screen.getByRole('status')).toHaveTextContent('')
  expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
})

test('an image typed for Docker and then left for this machine is still sent with the Commands section', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<ProjectSettings {...base} onSave={onSave} />)
  await userEvent.click(screen.getByLabelText(/Docker container/))
  await userEvent.type(screen.getByLabelText('Image'), 'python:3.12')
  await userEvent.click(screen.getByLabelText(/This machine/))
  expect(screen.getByRole('button', { name: /^Commands/ })).toHaveTextContent('not saved')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({ exec_location: 'host', docker_image: 'python:3.12', docker_network: false })
})

test('a model looking over each sub-agent’s report is the user’s to switch on, and is said to spend', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<ProjectSettings {...base} onSave={onSave} />)
  await choose(/^Agents/)
  const box = screen.getByRole('checkbox', { name: /^Have a model look over each sub-agent’s report/ })
  expect(box).not.toBeChecked()
  expect(box).toHaveAccessibleName(/One more model request after every sub-agent’s report, on your plan or your bill/)
  await userEvent.click(box)
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ observe_reports: true })
})

test('follow-up tasks after each turn are on by default, say what they cost, and come from the tier chosen', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<ProjectSettings {...base} onSave={onSave} />)
  await choose(/^Agents/)
  const box = screen.getByRole('checkbox', { name: /^Suggest follow-up tasks after each turn/ })
  expect(box).toBeChecked()
  expect(box.closest('label')).toHaveTextContent('One small model request after each turn that did something')
  await userEvent.selectOptions(screen.getByLabelText('Follow-up tasks from'), 'balanced')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ suggest_tier: 'balanced' })
  await userEvent.click(box)
  expect(screen.queryByLabelText('Follow-up tasks from')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ suggest_tasks: false }))
})

test('the switch says what the observer is sent, and to which model, in sight', async () => {
  render(<ProjectSettings {...base} onSave={vi.fn()} />)
  await choose(/^Agents/)
  const shown = screen.getByText(/^One more model request after every sub-agent’s report/)
  expect(shown.closest('.hint')).toBeNull()
  expect(shown).toHaveTextContent(/The Observer role’s model \(set on the Agents page\) is sent the task, the report, the diffs of the changed files and the test’s output, with the secrets KOLONİ knows masked\./)
  expect(screen.getByRole('checkbox', { name: /^Have a model look over/ })).toHaveAccessibleName(
    /the diffs of the changed files and the test’s output, with the secrets KOLONİ knows masked/,
  )
})

test('the day’s summary is sent at a time set here; emptied, it is not sent any more', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  const { unmount } = render(<ProjectSettings {...base} onSave={onSave} />)
  await choose(/^Notifications/)
  const at = screen.getByLabelText('Send the day’s summary at')
  expect(at).toHaveValue('')
  await userEvent.type(at, '18:30')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ day_note_at: '18:30' })
  unmount()
  render(<ProjectSettings {...base} project={{ ...project, day_note_at: '18:30' }} onSave={onSave} />)
  await choose(/^Notifications/)
  await userEvent.clear(screen.getByLabelText('Send the day’s summary at'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ day_note_at: null })
})

test('the first save that puts settings into the folder’s .koloni/ says so, once', async () => {
  // (As the store does: the project as saved comes back - and now .koloni/settings.json is there.)
  const kept = { ...project, koloni: { ...project.koloni, settings_kept: true } }
  const onSave = vi.fn().mockImplementation(async (values: Partial<Project>) => rerender(<ProjectSettings {...base} project={{ ...kept, ...values }} onSave={onSave} />))
  const { rerender } = render(<ProjectSettings {...base} onSave={onSave} />)
  await choose(/^Memory and web/)
  await userEvent.selectOptions(screen.getByLabelText('Otherwise search with'), 'cli')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(screen.getByRole('status')).toHaveTextContent(/^Saved in \.koloni\/ in this folder \(kept in git\)$/)
  // Once: kept there already, a save is only saved.
  await userEvent.selectOptions(screen.getByLabelText('Otherwise search with'), 'builtin')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(screen.getByRole('status')).toHaveTextContent(/^Saved$/)
})

test('what the folder’s settings ask for is used only on “Use them”; “Not now” leaves it', async () => {
  const asking = { ...project, koloni: { ...project.koloni, settings_kept: true, asks: { exec_location: 'docker' as const, docker_image: 'other:1', docker_network: true } } }
  const used = { ...asking, exec_location: 'docker' as const, docker_image: 'other:1', docker_network: true, koloni: { ...asking.koloni, asks: {} } }
  const onUseKoloni = vi.fn().mockResolvedValue(used)
  const { unmount } = render(<ProjectSettings {...base} project={asking} onSave={vi.fn()} onUseKoloni={onUseKoloni} />)
  const ask = screen.getByRole('group', { name: 'This folder’s settings' })
  expect(ask).toHaveTextContent('This folder’s settings ask to run commands in Docker image other:1, with network access — use them?')
  await userEvent.click(within(ask).getByRole('button', { name: 'Not now' }))
  expect(screen.queryByRole('group', { name: 'This folder’s settings' })).not.toBeInTheDocument()
  expect(onUseKoloni).not.toHaveBeenCalled()
  expect(screen.getByLabelText(/This machine/)).toBeChecked()
  unmount()

  const { rerender } = render(<ProjectSettings {...base} project={asking} onSave={vi.fn()} onUseKoloni={onUseKoloni} />)
  await userEvent.click(screen.getByRole('button', { name: 'Use them' }))
  // What the card showed is what is sent: the server takes it only while the file still says it.
  expect(onUseKoloni).toHaveBeenCalledExactlyOnceWith(asking.koloni.asks)
  rerender(<ProjectSettings {...base} project={used} onSave={vi.fn()} onUseKoloni={onUseKoloni} />)
  expect(screen.queryByRole('group', { name: 'This folder’s settings' })).not.toBeInTheDocument()
  // The form shows them as saved, with nothing left to save.
  expect(screen.getByLabelText(/Docker container/)).toBeChecked()
  expect(screen.getByLabelText('Image')).toHaveValue('other:1')
  expect(screen.getByRole('button', { name: /^Commands/ })).not.toHaveTextContent('not saved')
})

test('when the folder’s settings changed since the card showed them, it says so and nothing is used', async () => {
  const asking = { ...project, koloni: { ...project.koloni, settings_kept: true, asks: { docker_image: 'shown:1' } } }
  const onUseKoloni = vi.fn().mockRejectedValue(new ApiError(409, 'the folder’s settings changed since they were shown: look at them again'))
  render(<ProjectSettings {...base} project={asking} onSave={vi.fn()} onUseKoloni={onUseKoloni} />)
  const ask = screen.getByRole('group', { name: 'This folder’s settings' })
  expect(ask).toHaveTextContent('This folder’s settings ask to use the Docker image shown:1 — use them?')
  await userEvent.click(within(ask).getByRole('button', { name: 'Use them' }))
  expect(await within(ask).findByRole('alert')).toHaveTextContent('changed since they were shown')
  expect(screen.getByLabelText(/This machine/)).toBeChecked()
})

test('a file of .koloni/ that is not read is said, and the folder’s rules are shown under This folder', async () => {
  const broken = '.koloni/settings.json is not read - it is not valid JSON (Expecting value: line 1 column 1 (char 0)): the settings saved in KOLONİ are used, and a save here does not change the file'
  // (the map beside them: none here)
  vi.spyOn(api, 'get').mockImplementation(async path => (path.endsWith('/map') ? Promise.reject(new Error('no map')) : { paths: [], more: 0, partial: false }) as never)
  render(<ProjectSettings {...base} project={{ ...project, koloni: { ...project.koloni, rules_kept: true, rules: 'Use tabs.', broken: [broken] } }} onSave={vi.fn()} />)
  expect(screen.getByText(broken)).toBeInTheDocument()
  await choose(/^This folder/)
  const rules = screen.getByRole('region', { name: 'This folder’s rules' })
  expect(rules).toHaveTextContent('Use tabs.')
  expect(rules).toHaveTextContent(/From \.koloni\/rules\.md, kept in git: every agent working here is given them\. You change them on the Memory page\./)
})

test('who changes the files is every chat’s, three ways, each said behind ⓘ; sent only when changed (K-devret, tek-ev)', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<ProjectSettings {...base} onSave={onSave} />)
  await choose(/^Agents/)
  expect(screen.getByText('Every chat of this project follows these, the ones made before too.')).toBeInTheDocument()
  const work = screen.getByLabelText('Who changes the files')
  expect(work).toHaveValue('delegates')
  expect(screen.getByText(/^Orchestrator delegates the work: The Orchestrator plans, asks and checks; sub-agents change the files\. Orchestrator decides: A small change/)).not.toBeVisible()
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  await userEvent.selectOptions(work, 'Orchestrator decides')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({ lead_work: 'decides' })
})

test('who answers while you are away is every chat’s, said in sight to use your plan on a CLI; sent only when changed (K-cli-vekil, tek-ev)', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<ProjectSettings {...base} onSave={onSave} />)
  await choose(/^Asking and away/)
  const away = screen.getByLabelText('When you’re away')
  expect(away).toHaveValue('waits')
  expect(screen.queryByText('An Orchestrator on a CLI uses one request of your plan for each answer.')).toBeNull()
  await userEvent.selectOptions(away, 'The Orchestrator answers what it safely can')
  const plan = screen.getByText('An Orchestrator on a CLI uses one request of your plan for each answer.')
  expect(plan).toBeVisible()
  expect(plan.closest('.hint')).toBeNull()
  await userEvent.clear(screen.getByLabelText('Minutes before the Orchestrator answers'))
  await userEvent.type(screen.getByLabelText('Minutes before the Orchestrator answers'), '5000')
  expect(screen.getByText('0 (at once) to 1440 minutes.')).toBeInTheDocument()
  await userEvent.clear(screen.getByLabelText('Minutes before the Orchestrator answers'))
  await userEvent.type(screen.getByLabelText('Minutes before the Orchestrator answers'), '30')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({ when_away: 'lead', away_minutes: 30 })
})

test('another project’s agent instructions below this folder are said, with how many more, whatever section is open (K-yabanci-talimat)', async () => {
  const found = { paths: ['vendor/lib/CLAUDE.md', 'sub/.claude/'], more: 3, partial: false }
  const get = vi.spyOn(api, 'get').mockImplementation(async () => found as never)
  const { unmount } = render(<ProjectSettings {...base} onSave={vi.fn()} />)
  expect(await screen.findByText(/^Another project’s agent instructions/)).toHaveTextContent(
    /^Another project’s agent instructions are in this folder: vendor\/lib\/CLAUDE\.md, sub\/\.claude\/ \+3 more \(CLI agents load them by themselves\)$/,
  )
  expect(get).toHaveBeenCalledWith('/projects/p/others-instructions')
  unmount()
  // A walk cut short says so; none found says nothing.
  get.mockImplementation(async () => ({ ...found, more: 0, partial: true }) as never)
  const again = render(<ProjectSettings {...base} onSave={vi.fn()} />)
  expect(await screen.findByText(/^Another project’s/)).toHaveTextContent(/sub\/\.claude\/ \(CLI agents load them by themselves\)\. Not every folder was looked in$/)
  again.unmount()
  get.mockImplementation(async () => ({ paths: [], more: 0, partial: true }) as never)
  render(<ProjectSettings {...base} onSave={vi.fn()} />)
  await act(async () => {}) // (the answer is in)
  expect(screen.queryByText(/^Another project’s/)).toBeNull()
})

// --- 22c: another project's memory --------------------------------------------------------------

test('the other projects of this KOLONİ are offered to look in, read only; the whole list is sent only when changed', async () => {
  useApp.setState({
    projects: [project, { ...project, id: 'q', name: 'Other one', root_path: 'C:/other' }, { ...project, id: 'z', name: 'Third', root_path: 'C:/third' }],
  })
  const onSave = vi.fn().mockResolvedValue(undefined)
  const { unmount } = render(<ProjectSettings {...base} onSave={onSave} />)
  await choose(/^Memory/)
  expect(screen.getByText(/^An agent’s recall also finds their notes, facts and earlier messages/)).toHaveTextContent('nothing is written there')
  // not itself
  expect(screen.queryByLabelText('Also look in the memory of demo')).toBeNull()
  await userEvent.click(screen.getByLabelText('Also look in the memory of Other one'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ memory_links: ['q'] })
  unmount()
  render(<ProjectSettings {...base} project={{ ...project, memory_links: ['q'] }} onSave={onSave} />)
  await choose(/^Memory/)
  expect(screen.getByLabelText('Also look in the memory of Other one')).toBeChecked()
  await userEvent.click(screen.getByLabelText('Also look in the memory of Other one'))
  await userEvent.click(screen.getByLabelText('Also look in the memory of Third'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ memory_links: ['z'] })
  useApp.setState({ projects: [] })
})

test('101: the planted test key is on by default under Commands, says what it does not catch, and is sent only when changed', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  vi.spyOn(api, 'get').mockImplementation(async path => (path.endsWith('/sites') ? [] : { paths: [], more: 0, partial: false }) as never)
  render(<ProjectSettings {...base} onSave={onSave} />)
  const box = screen.getByRole('checkbox', { name: /^Planted test key \(canary\)/ })
  expect(box).toBeChecked()
  expect(box).toHaveAccessibleName(/A command, web request, browser or MCP call that would send it out is refused and the work stops/)
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  await userEvent.click(box)
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ exec_location: 'host', docker_image: null, docker_network: false, canary: false })
})


test('K-dal-takim D2: how a finished branch reaches yours - a pull request greyed out with why, sent only when changed', async () => {
  let whyNot: string | null = 'gh is not logged in: run gh auth login'
  const get = vi.spyOn(api, 'get').mockImplementation(async (path: string) => {
    if (path.endsWith('/pull-request')) return { why_not: whyNot }
    throw new ApiError(404, 'not here')
  })
  const onSave = vi.fn().mockResolvedValue(undefined)
  const view = render(<ProjectSettings {...base} onSave={onSave} />)
  await choose(/^Checks/)
  const pr = await screen.findByRole('radio', { name: /Open a pull request/ })
  expect(pr).toBeDisabled()
  expect(screen.getByText(/Not now: gh is not logged in: run gh auth login/)).toBeInTheDocument()
  expect(screen.getByText(/Not chosen yet: the first finished branch on a GitHub project asks/)).toBeInTheDocument()
  expect(screen.getByText(/A pushed branch runs the repository’s own CI/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('radio', { name: /Merge here/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ finish_way: 'merge' })
  view.unmount()
  whyNot = null
  render(<ProjectSettings {...base} project={{ ...project, finish_way: 'merge' }} onSave={onSave} />)
  await choose(/^Checks/)
  await act(async () => {})
  await userEvent.click(screen.getByRole('radio', { name: /Open a pull request/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ finish_way: 'pull_request' })
  get.mockRestore()
})
