import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import type { Folders, Project } from '../api/types'
import { useApp } from '../state/store'
import { Settings } from './Settings'

const project: Project = {
  id: 'p', name: 'demo', root_path: 'C:\\work\\demo', created_at: 't', exec_location: 'host', docker_image: null,
  docker_network: false, search_url: null, search_order: 'builtin', search_agy: false, has_notify_url: false,
  notify_format: 'slack', notify_desktop: false, turn_token_limit: null, max_agents: null, continue_steps: 25, monthly_budget: null,
  check_command: null, measure_command: null, finish_tests: null, finish_tests_auto: { on: false, command: null, reason: 'test time not known yet' }, memory_links: [], embedding_provider_id: null, embedding_model: 'text-embedding-3-small', git_commit: false, finish_way: null, auto_notes: false, observe_reports: false, suggest_tasks: true, suggest_tier: 'fast', day_note_at: null,
  teams_mode: 'none', teams: [], also_in: [], read_in: ['D:\\notes'], hide_secrets: true, canary: true, lead_work: 'delegates', when_away: 'waits', away_minutes: 10, spawn_approval: 'auto', spawn_max_depth: 2, spawn_max_agents: 6, spawn_max_parallel: 2, discussion_budget: null, room_posts: 40, room_tokens: null, room_minutes: 30, room_min_tokens: 60000, pass_env: null, held_env: [], koloni: { settings_kept: false, rules_kept: false, rules: null, broken: [], asks: {} },
}
const shared: Folders = { never: [{ path: 'C:\\Users\\me\\.ssh', why: "it holds the user's settings and secrets" }] }
const base = { project, dockerAvailable: true, dockerError: null, desktopAvailable: true, onClose: vi.fn() }

beforeEach(() => {
  useApp.setState({ projects: [project] })
  vi.spyOn(api, 'get').mockImplementation(path =>
    // (the map is beside the folders since tek-ev: none here)
    (path.endsWith('/map') ? Promise.reject(new Error('no map')) : Promise.resolve(path === '/folders' ? shared : path.endsWith('/others-instructions') ? { paths: [], more: 0, partial: false } : path === '/answer-in' ? { answer_in: null } : path === '/storage' ? { db_mb: null, backups_mb: null, copies_mb: null, logs_mb: null } : path.startsWith('/') && !path.startsWith('/projects') ? {} : [])) as never,
  )
})
afterEach(() => vi.restoreAllMocks())

test('the places never opened are The app’s, shown with why (Your data); a new chat’s other folders are This project’s, with what a CLI is given of them', async () => {
  render(<Settings {...base} picked={{ section: 'data', n: 1 }} onSave={vi.fn()} />)
  const never = await screen.findByRole('list', { name: 'Always blocked' })
  expect(within(never).getByRole('listitem')).toHaveTextContent("C:\\Users\\me\\.ssh - it holds the user's settings and secrets")
  expect(screen.queryByText('In every project')).not.toBeInTheDocument()
  expect(screen.queryByText('In this project')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'This project' }))
  await userEvent.click(screen.getByRole('button', { name: /^New chats start with/ }))
  expect(within(screen.getByRole('list', { name: 'New chats’ other folders' })).getByRole('listitem')).toHaveTextContent('D:\\notes read only')
  // B-58: Codex and Copilot ask before their changes now; what they are given, their own tools write in
  expect(screen.getByText(/given no folder to Read/)).toHaveTextContent(
    'Codex, agy and Copilot are given no folder to Read: a folder Codex or Copilot is given, its own tools may write in, and agy is given none outside the project.',
  )
})
