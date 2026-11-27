import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { act } from 'react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import type { Project } from '../api/types'
import { useApp } from '../state/store'
import { conversation, convState } from '../test-fixtures'
import { OLD_NAMES, SECTIONS } from './ProjectSettings'
import { APP_SECTIONS, Settings } from './Settings'

const project: Project = {
  id: 'p',
  name: 'demo',
  root_path: 'C:/demo',
  created_at: 't',
  exec_location: 'docker',
  docker_image: 'python:3.12',
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
const other = { ...project, id: 'o', name: 'other' }

/** Settings as the app opens it: a place asked of the store is the one shown. */
function Opened({ folder = project as Project | null }) {
  const picked = useApp(s => s.settingsAsked)
  return (
    <Settings
      project={folder}
      picked={picked ?? undefined}
      dockerAvailable
      dockerError={null}
      desktopAvailable
      onSave={vi.fn()}
      onClose={vi.fn()}
    />
  )
}

beforeEach(() => {
  vi.spyOn(api, 'get').mockImplementation(async (path: string) => {
    if (path.endsWith('/map')) throw new Error('no map')
    const read: Record<string, unknown> = {
      '/answer-in': { answer_in: null },
      '/compaction': { compact_at: 75 },
      '/steps': { max_steps: 25 },
      '/unattended': { stuck_minutes: 30, turn_hours: 8 },
      '/knowledge-limits': { max_files: 50000, max_mb: 300 },
      '/test-load': { runs_at_once: 1, workers: 2 },
      '/folders': { never: [] },
      '/storage': { db_mb: 1, backups_mb: 1, copies_mb: 1, logs_mb: 1 },
    }
    return (read[path] ??
      (path.endsWith('/others-instructions')
        ? { paths: [], more: 0, partial: false }
        : path.endsWith('/pull-request')
          ? { why_not: null }
          : [])) as never
  })
  useApp.setState({ conv: convState(), projects: [project, other], teams: [], settingsAsked: null })
})
afterEach(() => {
  useApp.setState({ conv: null, projects: [], settingsAsked: null })
  vi.restoreAllMocks()
})

const nav = () => within(screen.getByRole('navigation', { name: 'Settings levels' }))
const levelNames = () =>
  nav()
    .getAllByRole('button')
    .filter(b => b.classList.contains('settings-level'))
    .map(b => b.textContent)
const current = () =>
  nav()
    .getAllByRole('button')
    .filter(b => b.getAttribute('aria-current') === 'true')
    .map(b => b.textContent)

test('three levels in a fixed order - This chat › This project › The app - each saying what it covers; a plain chat has no project level', async () => {
  const { unmount } = render(<Opened />)
  expect(levelNames()).toEqual(['This chat', 'This project', 'The app'])
  expect(nav().getByRole('button', { name: 'This chat' })).toHaveAccessibleDescription('Fix greeting')
  expect(nav().getByRole('button', { name: 'This project' })).toHaveAccessibleDescription('demo · every chat of it')
  expect(nav().getByRole('button', { name: 'The app' })).toHaveAccessibleDescription('every project')
  // ⚙ opens This project; the chat's level shows what it takes from it, read only, with the way up.
  expect(current()).toEqual(['This project', 'How agents work'])
  await userEvent.click(nav().getByRole('button', { name: 'This chat' }))
  const from = screen.getByRole('region', { name: 'From demo' })
  expect(within(from).queryByRole('combobox')).toBeNull()
  expect(within(from).queryByRole('textbox')).toBeNull()
  await userEvent.click(within(from).getByRole('button', { name: 'Change in This project' }))
  expect(current()).toEqual(['This project', 'How agents work'])
  unmount()
  useApp.setState({ conv: convState({ conversation: { ...conversation, project_id: null } }) })
  render(<Opened folder={null} />)
  expect(levelNames()).toEqual(['This chat', 'The app'])
  expect(current()).toEqual(['The app', 'Agents'])
})

test('moving between levels, by a level’s button or a link in another level, keeps the focus: on the level now shown', async () => {
  render(<Opened />)
  nav().getByRole('button', { name: 'The app' }).focus()
  await userEvent.keyboard('{Enter}')
  expect(current()).toEqual(['The app', 'Agents'])
  expect(nav().getByRole('button', { name: 'The app' })).toHaveFocus()
  // (the levels in their order, the keys going up them: This project is just above)
  await userEvent.tab({ shift: true })
  expect(nav().getByRole('button', { name: 'This project' })).toHaveFocus()
  await userEvent.keyboard('{Enter}')
  expect(nav().getByRole('button', { name: 'This project' })).toHaveFocus()
  await userEvent.click(nav().getByRole('button', { name: /^Limits and money/ }))
  await userEvent.click(screen.getByRole('button', { name: /^More limits/ }))
  screen.getByRole('button', { name: 'Steps an agent may take' }).focus()
  await userEvent.keyboard('{Enter}')
  expect(current()).toEqual(['The app', 'Agents'])
  expect(nav().getByRole('button', { name: 'The app' })).toHaveFocus()
})

test('each place a link or Ctrl+K asks for lands on its level and its section', () => {
  render(<Opened />)
  const places: [string, string[]][] = [
    ['chat', ['This chat']],
    ...SECTIONS.map(([key, name]) => [key, ['This project', name]] as [string, string[]]),
    ...APP_SECTIONS.map(([key, name]) => [key, ['The app', name]] as [string, string[]]),
  ]
  for (const [place, shown] of places) {
    act(() => useApp.getState().askSettings(place as never))
    expect(current(), place).toEqual(shown)
  }
})

/**
 * Every setting Settings has a field for, by its field's name, and where it is since 0.1.10's regroup (its section
 * before, after #): each is found once, walking every level and section with its More open. (The chat's level, Plan
 * first and model stay under the message box; its teams and folders in their own panels; the project map's tests,
 * slash commands and runs without asking are rows.)
 */
const WHERE: [string | RegExp, string][] = [
  ['Page scripts', 'This chat'],
  ['Who changes the files', 'This project › How agents work'], // # Agents
  [/^Suggest follow-up tasks after each turn/, 'This project › How agents work'], // # Agents
  ['Follow-up tasks from', 'This project › How agents work'], // # Agents
  ['New chats’ teams', 'This project › How agents work'], // # New chats start with
  ['Name', 'This project › How agents work'], // # Slash commands, under More
  [/^Full auto’s judge/, 'This project › When you’re asked'], // # Asking and away
  ['When the judge finds a command risky', 'This project › When you’re asked'], // # Asking and away
  [/^It also lets a delete or a push run/, 'This project › When you’re asked'], // # Asking and away
  ['When you’re away', 'This project › When you’re asked'], // # Asking and away
  ['Minutes before the Orchestrator answers', 'This project › When you’re asked'], // # Asking and away
  ['Opening a sub-agent', 'This project › When you’re asked'], // # Asking and away
  [/^Agents may delete what is disposable/, 'This project › When you’re asked'], // # Asking and away, under More
  [/^This machine/, 'This project › When you’re asked'], // # Commands and secrets, under More
  [/^Docker container/, 'This project › When you’re asked'], // # Commands and secrets, under More
  ['Image', 'This project › When you’re asked'], // # Commands and secrets, under More
  ['Allow network access', 'This project › When you’re asked'], // # Commands and secrets, under More
  ['Longest command (minutes)', 'This project › When you’re asked'], // # Commands and secrets, under More
  [/^Hide secret files from commands/, 'This project › When you’re asked'], // # Commands and secrets, under More
  ['Secret variables commands may see', 'This project › When you’re asked'], // # Commands and secrets, under More
  [/^Planted test key/, 'This project › When you’re asked'], // # Commands and secrets, under More
  ['After a change', 'This project › When the work is done'], // # Checks and git
  ['Fix rounds', 'This project › When the work is done'], // # Checks and git
  [/^Then a stronger model/, 'This project › When the work is done'], // # Checks and git
  [/^Save each sub-agent’s work as a git commit/, 'This project › When the work is done'], // # Checks and git
  [/Merge here/, 'This project › When the work is done'], // # Checks and git
  [/Open a pull request/, 'This project › When the work is done'], // # Checks and git
  ['Documents', 'This project › When the work is done'], // # Checks and git (Check by kind of work), under More
  ['Measure command', 'This project › When the work is done'], // # Checks and git, under More
  ['Monthly budget', 'This project › Limits and money'],
  ['Stop the work on a message over this many tokens', 'This project › Limits and money'],
  ['At most this many agents at work in this project', 'This project › Limits and money'], // under More limits
  ['Agents at the same time', 'This project › Limits and money'], // under More limits
  ['Sub-agent levels', 'This project › Limits and money'], // under More limits
  ['Sub-agents per request', 'This project › Limits and money'], // under More limits
  ['Continue gives this many more steps', 'This project › Limits and money'], // under More limits
  ['A discussion’s tokens, at most', 'This project › Limits and money'], // under More limits
  [/^Note what the work found, by itself/, 'This project › Memory and web'],
  ['Search address (SearXNG)', 'This project › Memory and web'],
  ['Otherwise search with', 'This project › Memory and web'],
  ['Also look in the memory of other', 'This project › Memory and web'], // under More
  [/^Show a desktop notification/, 'This project › Notifications'],
  ['Send the day’s summary at', 'This project › Notifications'],
  ['Answer in', 'The app › Agents'],
  ['Summarise a long context at (%)', 'The app › Agents'],
  ['Judge model', 'The app › Agents'],
  [/^Show experimental features/, 'The app › Agents'],
  ['Steps an agent may take', 'The app › Agents'], // under More limits
  ['Stuck after this many minutes with no progress', 'The app › Agents'], // under More limits
  ['An unattended turn runs at most (hours)', 'The app › Agents'], // under More limits
  ['Knowledge reads at most (files)', 'The app › Agents'], // under More limits
  ['Knowledge reads at most (MB)', 'The app › Agents'], // under More limits
  ['KOLONİ’s test runs at once', 'The app › Agents'], // under More limits
  ['Test processes per run', 'The app › Agents'], // under More limits
  [/^Whole answer/, 'The app › Voice'],
  [/^Short summary/, 'The app › Voice'],
  ['Dictation language', 'The app › Voice'],
  ['Voice', 'The app › Voice'],
  ['Rate', 'The app › Voice'],
  ['Pitch', 'The app › Voice'],
  [/How the Orchestrator speaks/, 'The app › Voice'],
]

test('each setting is set in one place, the one it moved to: walking every level and section with its More open, each field is found exactly once', async () => {
  render(<Opened />)
  const seen = new Map<string | RegExp, string[]>(WHERE.map(([label]) => [label, []]))
  const look = (where: string) => {
    for (const [label] of WHERE) {
      const found = screen
        .queryAllByLabelText(label)
        .filter(field => field.matches('input, select, textarea') && !field.closest('[hidden]'))
      if (found.length) seen.get(label)!.push(`${where} ×${found.length}`)
    }
  }
  const visit = async (level: string, sections: string[]) => {
    await userEvent.click(nav().getByRole('button', { name: level }))
    if (sections.length === 0) look(level)
    for (const section of sections) {
      await userEvent.click(nav().getByRole('button', { name: new RegExp(`^${section}`) }))
      for (const more of Array.from(document.querySelectorAll<HTMLElement>('.set-more-button[aria-expanded="false"]')))
        if (!more.closest('[hidden]')) await userEvent.click(more)
      look(`${level} › ${section}`)
    }
  }
  await visit('This chat', [])
  await visit(
    'This project',
    SECTIONS.map(([, name]) => name),
  )
  await visit(
    'The app',
    APP_SECTIONS.map(([, name]) => name),
  )
  for (const [label, where] of WHERE) expect(seen.get(label), String(label)).toEqual([`${where} ×1`])
})

/** What a hint or note names as "Settings › …" in the app's own words, read from the source. */
const sources = import.meta.glob(['../**/*.tsx', '!../**/*.test.tsx'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

test('every “Settings › …” the app’s words point to is a level there is, and a section of it - by its name, or one it had before 0.1.10 that Ctrl+K still finds it by', () => {
  const sections: Record<string, string[]> = {
    'This chat': [],
    'This project': SECTIONS.flatMap(([key, name]) => [name, ...(OLD_NAMES[key] ?? [])]),
    'The app': APP_SECTIONS.map(([, name]) => name),
  }
  // (A level is one or two words; after it, the words go on past the section's name: the section is the one they start with.)
  const named = Object.entries(sources).flatMap(([file, text]) =>
    [...text.matchAll(/Settings › (This \w+|The \w+|[A-Z]\w*)(?: › ([^\n]{1,60}))?/g)].map(
      m => [file, m[1], m[2]] as const,
    ),
  )
  expect(named.length).toBeGreaterThan(5)
  for (const [file, level, rest] of named) {
    expect(Object.keys(sections), `${file}: Settings › ${level}`).toContain(level)
    if (rest)
      expect(
        sections[level].some(name => rest.startsWith(name)),
        `${file}: Settings › ${level} › ${rest}`,
      ).toBe(true)
  }
})
