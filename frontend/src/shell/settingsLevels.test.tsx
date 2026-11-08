import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { act } from 'react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import type { Project } from '../api/types'
import { useApp } from '../state/store'
import { conversation, convState } from '../test-fixtures'
import { SECTIONS } from './ProjectSettings'
import { APP_SECTIONS, Settings } from './Settings'

const project: Project = {
  id: 'p', name: 'demo', root_path: 'C:/demo', created_at: 't', exec_location: 'docker', docker_image: 'python:3.12', docker_network: false,
  search_url: null, search_order: 'builtin', search_agy: false, has_notify_url: false, notify_format: 'slack', notify_desktop: false,
  turn_token_limit: null, max_agents: null, continue_steps: 25, monthly_budget: null, check_command: null, measure_command: null, finish_tests: null,
  finish_tests_auto: { on: false, command: null, reason: 'test time not known yet' }, memory_links: [], embedding_provider_id: null, embedding_model: 'm',
  git_commit: false, finish_way: null, auto_notes: false, observe_reports: false, suggest_tasks: true, suggest_tier: 'fast', day_note_at: null, also_in: [], read_in: [], teams_mode: 'none', teams: [],
  hide_secrets: true, canary: true, lead_work: 'delegates', when_away: 'waits', away_minutes: 10, spawn_approval: 'auto', spawn_max_depth: 2, spawn_max_agents: 6,
  spawn_max_parallel: 2, discussion_budget: null, room_posts: 40, room_tokens: null, room_minutes: 30, room_min_tokens: 60000, pass_env: null, held_env: [],
  koloni: { settings_kept: false, rules_kept: false, rules: null, broken: [], asks: {} },
}
const other = { ...project, id: 'o', name: 'other' }

/** Settings as the app opens it: a place asked of the store is the one shown. */
function Opened({ folder = project as Project | null }) {
  const picked = useApp(s => s.settingsAsked)
  return <Settings project={folder} picked={picked ?? undefined} dockerAvailable dockerError={null} desktopAvailable onSave={vi.fn()} onClose={vi.fn()} />
}

beforeEach(() => {
  vi.spyOn(api, 'get').mockImplementation(async (path: string) => {
    if (path.endsWith('/map')) throw new Error('no map')
    const read: Record<string, unknown> = { '/answer-in': { answer_in: null }, '/compaction': { compact_at: 75 }, '/steps': { max_steps: 25 }, '/knowledge-limits': { max_files: 50000, max_mb: 300 }, '/folders': { never: [] }, '/storage': { db_mb: 1, backups_mb: 1, copies_mb: 1, logs_mb: 1 } }
    return (read[path] ?? (path.endsWith('/others-instructions') ? { paths: [], more: 0, partial: false } : path.endsWith('/pull-request') ? { why_not: null } : [])) as never
  })
  useApp.setState({ conv: convState(), projects: [project, other], teams: [], settingsAsked: null })
})
afterEach(() => {
  useApp.setState({ conv: null, projects: [], settingsAsked: null })
  vi.restoreAllMocks()
})

const nav = () => within(screen.getByRole('navigation', { name: 'Settings levels' }))
const levelNames = () => nav().getAllByRole('button').filter(b => b.classList.contains('settings-level')).map(b => b.textContent)
const current = () => nav().getAllByRole('button').filter(b => b.getAttribute('aria-current') === 'true').map(b => b.textContent)

test('three levels in a fixed order - This chat › This project › The app - each saying what it covers; a plain chat has no project level', async () => {
  const { unmount } = render(<Opened />)
  expect(levelNames()).toEqual(['This chat', 'This project', 'The app'])
  expect(nav().getByRole('button', { name: 'This chat' })).toHaveAccessibleDescription('Fix greeting')
  expect(nav().getByRole('button', { name: 'This project' })).toHaveAccessibleDescription('demo · every chat of it')
  expect(nav().getByRole('button', { name: 'The app' })).toHaveAccessibleDescription('every project')
  // ⚙ opens This project; the chat's level shows what it takes from it, read only, with the way up.
  expect(current()).toEqual(['This project', 'Agents'])
  await userEvent.click(nav().getByRole('button', { name: 'This chat' }))
  const from = screen.getByRole('region', { name: 'From demo' })
  expect(within(from).queryByRole('combobox')).toBeNull()
  expect(within(from).queryByRole('textbox')).toBeNull()
  await userEvent.click(within(from).getByRole('button', { name: 'Change in This project' }))
  expect(current()).toEqual(['This project', 'Agents'])
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
 * Every setting of the old screens (ayarlar/index.html) that Settings has a field for, by its field's name here: each is
 * found once, walking every level and section. (The chat's level, Plan first and model stay under the message box; its
 * teams and folders in their own panels; the project map's tests, slash commands and runs without asking are rows.)
 */
const ONCE: (string | RegExp)[] = [
  'Page scripts',
  'Who changes the files', /^Finish only when the tests pass/, /^Have a model look over each sub-agent’s report/,
  'Opening a sub-agent', 'When you’re away', 'Minutes before the Orchestrator answers',
  'New chats’ teams', 'Posts, at most', 'Minutes, at most', 'Tokens, at most',
  'At most this many agents at work in this project', 'Agents at the same time', 'Sub-agent levels', 'Sub-agents per request',
  'Continue gives this many more steps', 'Stop the work on a message over this many tokens', 'A discussion’s tokens, at most', 'Monthly budget',
  /^This machine/, /^Docker container/, 'Image', 'Allow network access', /^Hide secret files from commands/, 'Secret variables commands may see', /^Planted test key/,
  'Test before adding', 'Measure command', /^Save each sub-agent’s work as a git commit/, /Merge here/, /Open a pull request/,
  /^Note what the work found, by itself/, 'Search by meaning with', 'Embedding model', 'Also look in the memory of other',
  'Search address (SearXNG)', 'Otherwise search with', /^Let agy search too/,
  'Notification address', 'Post it as', /^Show a desktop notification/, 'Send the day’s summary at',
  'Answer in', 'Steps an agent may take', 'Summarise a long context at (%)',
  /^Whole answer/, /^Short summary/, 'Dictation language', 'Voice', 'Rate', 'Pitch', /How the Orchestrator speaks/,
]

test('each setting is set in one place: walking every level and section, each field is found exactly once', async () => {
  render(<Opened />)
  const seen = new Map<string | RegExp, string[]>(ONCE.map(label => [label, []]))
  const look = (where: string) => {
    for (const label of ONCE) {
      const found = screen.queryAllByLabelText(label).filter(field => field.matches('input, select, textarea') && !field.closest('[hidden]'))
      if (found.length) seen.get(label)!.push(`${where} ×${found.length}`)
    }
  }
  const visit = async (level: string, sections: string[]) => {
    await userEvent.click(nav().getByRole('button', { name: level }))
    if (sections.length === 0) look(level)
    for (const section of sections) {
      await userEvent.click(nav().getByRole('button', { name: new RegExp(`^${section}`) }))
      look(`${level} › ${section}`)
    }
  }
  await visit('This chat', [])
  await visit('This project', SECTIONS.map(([, name]) => name))
  await visit('The app', APP_SECTIONS.map(([, name]) => name))
  for (const [label, where] of seen) expect(where, String(label)).toHaveLength(1)
  for (const [label, where] of seen) expect(where[0], String(label)).toMatch(/×1$/)
})

/** What a hint or note names as "Settings › …" in the app's own words, read from the source. */
const sources = import.meta.glob(['../**/*.tsx', '!../**/*.test.tsx'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>

test('every “Settings › …” the app’s words point to is a level there is, and a section of it', () => {
  const sections: Record<string, string[]> = {
    'This chat': [],
    'This project': SECTIONS.map(([, name]) => name),
    'The app': APP_SECTIONS.map(([, name]) => name),
  }
  // (A level is one or two words; after it, the words go on past the section's name: the section is the one they start with.)
  const named = Object.entries(sources).flatMap(([file, text]) => [...text.matchAll(/Settings › (This \w+|The \w+|[A-Z]\w*)(?: › ([^\n]{1,60}))?/g)].map(m => [file, m[1], m[2]] as const))
  expect(named.length).toBeGreaterThan(5)
  for (const [file, level, rest] of named) {
    expect(Object.keys(sections), `${file}: Settings › ${level}`).toContain(level)
    if (rest) expect(sections[level].some(name => rest.startsWith(name)), `${file}: Settings › ${level} › ${rest}`).toBe(true)
  }
})
