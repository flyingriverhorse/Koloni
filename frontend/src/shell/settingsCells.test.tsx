import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import type { Project } from '../api/types'
import { ProjectSettings } from './ProjectSettings'
import { AppAgents } from './sections/AppAgents'

// 0.1.10: This project's sections in the honeycomb cells - each read in a sentence, its rows' cells, More, the save bar,
// and the places named before.

afterEach(() => vi.restoreAllMocks())

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
  notify_desktop: false,
  turn_token_limit: null,
  max_agents: null,
  continue_steps: 25,
  longest_command: 10,
  monthly_budget: null,
  measure_command: null,
  after_change: 'check',
  fix_rounds: 2,
  stronger_model: true,
  check_kinds: {},
  review_lines: 80,
  review_files: 3,
  after_change_from_off: false,
  tests_found: {},
  tests_look: null,
  test_commands: {},
  full_auto_check: 'ask',
  full_auto_judge: true,
  judge_words: false,
  judge_risky: 'refuse',
  disposable_deletes: false,
  memory_links: [],
  git_commit: false,
  finish_way: null,
  auto_notes: false,
  suggest_tasks: true,
  suggest_tier: 'fast',
  day_note_at: null,
  also_in: [],
  read_in: [],
  teams_mode: 'none',
  teams: [],
  hide_secrets: true,
  canary: true,
  lead_work: 'delegates',
  when_away: 'waits',
  away_minutes: 10,
  spawn_approval: 'auto',
  spawn_max_depth: 2,
  spawn_max_agents: 6,
  spawn_max_parallel: 2,
  discussion_budget: null,
  pass_env: null,
  held_env: [],
  koloni: { settings_kept: false, rules_kept: false, rules: null, broken: [], asks: {} },
}
// (Opened on Commands, the first section before tek-ev: the tests of it need no click to reach it.)
const base = {
  project,
  dockerAvailable: true,
  dockerError: null,
  desktopAvailable: true,
  picked: { section: 'commands' as const, n: 1 },
}

/** A section chosen, its More open: every field of it in sight. */
async function choose(name: RegExp) {
  await userEvent.click(screen.getByRole('button', { name }))
  await openMores()
}
/** Every More of the section shown, opened. */
async function openMores() {
  for (const more of Array.from(document.querySelectorAll<HTMLElement>('.set-more-button[aria-expanded="false"]')))
    await userEvent.click(more)
}

/** The cell of the row a field is on: where its value comes from, by its name. */
const cellOf = (label: string | RegExp) =>
  screen.getByLabelText(label).closest('.set-row, .set-line')!.querySelector('.cell')!.getAttribute('aria-label')
const said = () => document.querySelector('.set-said')!.textContent

test('a section first reads itself in a sentence, made from its values as they stand; the save bar is there only while something is changed, and says what', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  const { rerender } = render(<ProjectSettings {...base} picked={undefined} onSave={onSave} />)
  await choose(/^When you’re asked/)
  expect(said()).toMatch(/^At Full auto a small model .* one it finds risky is refused and its agent goes another way/)
  expect(said()).toContain('Every card waits for you, while you’re away too.')
  expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
  await userEvent.selectOptions(screen.getByLabelText('When the judge finds a command risky'), 'ask')
  // The sentence changes with it, before anything is saved.
  expect(said()).toContain('one it finds risky waits for you on a card')
  expect(screen.getByText('1 change not saved: When the judge finds a command risky')).toBeInTheDocument()
  expect(cellOf('When the judge finds a command risky')).toBe('changed, not saved')
  expect(screen.getByRole('button', { name: /^When you’re asked/ })).toHaveAccessibleDescription('not saved')
  await userEvent.selectOptions(screen.getByLabelText('When you’re away'), 'lead')
  expect(
    screen.getByText('2 changes not saved: When the judge finds a command risky, When you’re away'),
  ).toBeInTheDocument()
  expect(said()).toContain('When a card has waited 10 minutes - at once while you’re away - the Orchestrator answers')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({ judge_risky: 'ask', when_away: 'lead' })
  rerender(
    <ProjectSettings
      {...base}
      picked={undefined}
      project={{ ...project, judge_risky: 'ask', when_away: 'lead' }}
      onSave={onSave}
    />,
  )
  // Saved: the bar goes, what was saved stays said; the cells say set here.
  expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
  expect(screen.getByRole('status')).toHaveTextContent('Saved')
  expect(cellOf('When the judge finds a command risky')).toBe('set here')
  // (a new project's own is lead after 5 minutes: this one waits 10)
  expect(cellOf('When you’re away')).toBe('set here')
  expect(cellOf(/^Full auto’s judge/)).toBe('the default')
  // A value that cannot be saved: the bar says so, its Save off.
  await userEvent.clear(screen.getByLabelText('Minutes before the Orchestrator answers'))
  await userEvent.type(screen.getByLabelText('Minutes before the Orchestrator answers'), 'soon')
  expect(screen.getByText('A value here cannot be saved yet: see the field that says why.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
})

test('each row’s cell says where its value comes from - set here, the default, or changed and not saved - and the legend says what they mean', async () => {
  render(
    <ProjectSettings {...base} project={{ ...project, spawn_max_parallel: 4 }} picked={undefined} onSave={vi.fn()} />,
  )
  await choose(/^Limits and money/)
  expect(cellOf('Agents at the same time')).toBe('set here')
  expect(cellOf('Sub-agent levels')).toBe('the default')
  expect(cellOf('Monthly budget')).toBe('the default')
  await userEvent.type(screen.getByLabelText('Monthly budget'), '50')
  expect(cellOf('Monthly budget')).toBe('changed, not saved')
  expect(said()).toMatch(/^This month may cost at most 50: at 80% you are told/)
  // (one that cannot be sent is changed too)
  await userEvent.clear(screen.getByLabelText('Sub-agent levels'))
  expect(cellOf('Sub-agent levels')).toBe('changed, not saved')
  const legend = document.querySelector<HTMLElement>('.set-legend')!
  expect(legend).toHaveTextContent('set here')
  expect(legend).toHaveTextContent('the default')
  expect(legend).toHaveTextContent('changed, not saved')
  // (the legend's cells have their words beside them: a screen reader is not told twice)
  expect(within(legend).queryAllByRole('img')).toHaveLength(0)
})

test('the rarely changed settings are under a section’s More - a button that says how many and how many are set here; none is gone', async () => {
  render(<ProjectSettings {...base} picked={undefined} onSave={vi.fn()} />)
  await userEvent.click(screen.getByRole('button', { name: /^When you’re asked/ }))
  const more = screen.getByRole('button', { name: /^More ·/ })
  expect(more).toHaveAttribute('aria-expanded', 'false')
  expect(more).toHaveAccessibleName('More · 6 settings, all at their defaults')
  expect(screen.getByLabelText(/^Hide secret files from commands/)).not.toBeVisible()
  await userEvent.click(more)
  expect(more).toHaveAttribute('aria-expanded', 'true')
  for (const label of [
    /^Agents may delete what is disposable without asking/,
    /^This machine/,
    'Longest command (minutes)',
    /^Hide secret files from commands/,
    'Secret variables commands may see',
    /^Planted test key/,
  ])
    expect(screen.getByLabelText(label)).toBeVisible()
  // Runs without asking: a row, its rules a click away.
  const rules = screen.getByRole('button', { name: 'Show the rules' })
  expect(rules).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByRole('region', { name: 'Sites agents open' })).toBeNull()
})

test('a place named before 0.1.10 lands in the section that holds it now, with what it named open', async () => {
  vi.spyOn(api, 'get').mockImplementation(
    async path => (path.endsWith('/others-instructions') ? { paths: [], more: 0, partial: false } : []) as never,
  )
  const { rerender } = render(<ProjectSettings {...base} picked={{ section: 'rules', n: 1 }} onSave={vi.fn()} />)
  expect(screen.getByRole('button', { name: /^When you’re asked/ })).toHaveAttribute('aria-current', 'true')
  expect(screen.getByRole('button', { name: 'Hide the rules' })).toHaveAttribute('aria-expanded', 'true')
  expect(await screen.findByRole('region', { name: 'Sites agents open' })).toBeInTheDocument()
  rerender(<ProjectSettings {...base} picked={{ section: 'own-commands', n: 2 }} onSave={vi.fn()} />)
  expect(screen.getByRole('button', { name: /^How agents work/ })).toHaveAttribute('aria-current', 'true')
  expect(screen.getByRole('heading', { name: 'Slash commands' })).toBeVisible()
  rerender(<ProjectSettings {...base} picked={{ section: 'commands', n: 3 }} onSave={vi.fn()} />)
  expect(screen.getByLabelText(/^Planted test key/)).toBeVisible()
  rerender(<ProjectSettings {...base} picked={{ section: 'more-limits', n: 4 }} onSave={vi.fn()} />)
  expect(screen.getByLabelText('Continue gives this many more steps')).toBeVisible()
  vi.restoreAllMocks()
})

test('Enter in a field of what saves itself - your slash commands, under More - never saves the section', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<ProjectSettings {...base} picked={undefined} onSave={onSave} />)
  await choose(/^How agents work/)
  await userEvent.selectOptions(screen.getByLabelText('Who changes the files'), 'itself')
  expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
  await userEvent.type(screen.getByLabelText('Name'), 'tests{Enter}')
  await userEvent.type(screen.getByLabelText('What it does'), 'Write tests{Enter}')
  expect(onSave).not.toHaveBeenCalled()
  // (its own Save still saves it)
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({ lead_work: 'itself' })
})

/** The server as these tests need it: the Judge model asked now, measured or not; nothing else. */
function judgeServer(measured: boolean, rules: unknown[] = [], sites: unknown[] = []) {
  vi.spyOn(api, 'get').mockImplementation(async (path: string) => {
    if (path === '/judge')
      return {
        provider_id: null,
        model_id: null,
        now: { provider_id: 'x', model_id: 'm', measured },
        choices: [],
      } as never
    if (path.endsWith('/others-instructions')) return { paths: [], more: 0, partial: false } as never
    if (path.endsWith('/allowed')) return rules as never
    if (path.endsWith('/sites')) return sites as never
    return [] as never
  })
}

test('Enter in the rules that run without asking - a box of theirs too - never saves the section', async () => {
  judgeServer(true)
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<ProjectSettings {...base} picked={undefined} onSave={onSave} />)
  await userEvent.click(screen.getByRole('button', { name: /^When you’re asked/ }))
  await userEvent.click(screen.getByRole('checkbox', { name: /^Full auto’s judge/ }))
  const rules = screen.getByRole('button', { name: 'Show the rules' })
  // (it controls the rules only once they are there)
  expect(rules).not.toHaveAttribute('aria-controls')
  await userEvent.click(rules)
  expect(rules).toHaveAttribute('aria-controls', 'rules-without-asking')
  const ask = await screen.findByRole('checkbox', { name: 'Ask first for the new site' })
  ask.focus()
  await userEvent.keyboard('{Enter}')
  expect(onSave).not.toHaveBeenCalled()
})

test('the rules are counted on their row without opening them', async () => {
  const rule = { id: 'r1', conversation_id: 'c1', prefix: 'npm test', danger: '', created_at: 't' }
  judgeServer(true, [{ conversation_id: 'c1', title: 'Fix', commands: [rule], web: [] }], [{ id: 's' }])
  render(<ProjectSettings {...base} picked={undefined} onSave={vi.fn()} />)
  await userEvent.click(screen.getByRole('button', { name: /^When you’re asked/ }))
  expect(await screen.findByText(/^2 rules: The project’s sites/)).toBeInTheDocument()
})

test('the box for your words says nothing in the sentence until its measurement has passed', async () => {
  judgeServer(false)
  render(<ProjectSettings {...base} project={{ ...project, judge_words: true }} picked={undefined} onSave={vi.fn()} />)
  await userEvent.click(screen.getByRole('button', { name: /^When you’re asked/ }))
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(said()).not.toContain('It also lets a delete or a push run')
})

test('what More folds that lets more run or shows more is named - on More’s button and in the sentence', async () => {
  judgeServer(true)
  render(
    <ProjectSettings
      {...base}
      project={{ ...project, disposable_deletes: true, hide_secrets: false, canary: false, pass_env: 'AWS_SECRET_KEY' }}
      picked={undefined}
      onSave={vi.fn()}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: /^When you’re asked/ }))
  const folded =
    'agents delete what is disposable without asking, secret files are not hidden from commands, commands see AWS_SECRET_KEY, no planted test key'
  expect(screen.getByRole('button', { name: /^More ·/ })).toHaveAccessibleName(
    `More · 6 settings, 4 set here: ${folded}`,
  )
  expect(said()).toContain(`Under More: ${folded.replace(/, /g, '; ')}.`)
})

test('after Save the focus is on what says so, not lost with the bar; Enter with nothing changed sends nothing', async () => {
  judgeServer(true)
  const onSave = vi.fn().mockResolvedValue(undefined)
  const { rerender } = render(<ProjectSettings {...base} picked={undefined} onSave={onSave} />)
  await userEvent.click(screen.getByRole('button', { name: /^When you’re asked/ }))
  await userEvent.selectOptions(screen.getByLabelText('When the judge finds a command risky'), 'ask')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  rerender(
    <ProjectSettings {...base} picked={undefined} project={{ ...project, judge_risky: 'ask' }} onSave={onSave} />,
  )
  expect(screen.getByRole('status')).toHaveTextContent('Saved')
  expect(screen.getByRole('status')).toHaveFocus()
  // (an Enter in a field now: nothing to send)
  screen.getByLabelText('Minutes before the Orchestrator answers').focus()
  await userEvent.keyboard('{Enter}')
  expect(onSave).toHaveBeenCalledTimes(1)
})

test('Forget it is sent while there is something to forget: saved, the bar goes', async () => {
  judgeServer(true)
  const onSave = vi.fn().mockResolvedValue(undefined)
  const found = { '.': { command: 'pytest', from: 'agent', at: '2026-11-20' } }
  const { rerender } = render(
    <ProjectSettings {...base} picked={undefined} project={{ ...project, tests_found: found }} onSave={onSave} />,
  )
  await choose(/^When the work is done/)
  await userEvent.click(screen.getByRole('checkbox', { name: /^Forget it/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({ forget_tests_found: true })
  rerender(<ProjectSettings {...base} picked={undefined} project={{ ...project, tests_found: {} }} onSave={onSave} />)
  expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
  expect(screen.getByRole('button', { name: /^When the work is done/ })).not.toHaveTextContent('not saved')
})

test('a More that cannot fold says why on it', async () => {
  render(<ProjectSettings {...base} picked={undefined} onSave={vi.fn()} />)
  await choose(/^Limits and money/)
  await userEvent.clear(screen.getByLabelText('Sub-agent levels'))
  expect(screen.getByRole('button', { name: /^More limits/ })).toHaveAccessibleName(
    /open while a value in it cannot be saved$/,
  )
})

test('The app’s rows have no cell until their value is read: none is said to come from anywhere before', async () => {
  vi.spyOn(api, 'get').mockImplementation(() => new Promise(() => {}))
  render(<AppAgents />)
  await userEvent.click(screen.getByRole('button', { name: /^More limits/ }))
  expect(document.querySelectorAll('.set-row .cell, .set-line .cell')).toHaveLength(0)
  expect(document.querySelectorAll('.set-row, .set-line').length).toBeGreaterThan(8)
})
