import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import type { ChatRules, Project } from '../api/types'
import { Settings } from './Settings'

afterEach(() => vi.restoreAllMocks())

const project: Project = {
  id: 'p', name: 'demo', root_path: 'C:/demo', created_at: 't', exec_location: 'host', docker_image: null, docker_network: false,
  search_url: null, search_order: 'builtin', search_agy: false, has_notify_url: false, notify_format: 'slack', notify_desktop: false,
  turn_token_limit: null, max_agents: null, continue_steps: 25, monthly_budget: null, check_command: null, measure_command: null, finish_tests: null,
  finish_tests_auto: { on: false, command: null, reason: 'test time not known yet' }, memory_links: [], embedding_provider_id: null, embedding_model: 'm',
  git_commit: false, finish_way: null, auto_notes: false, observe_reports: false, suggest_tasks: true, suggest_tier: 'fast', day_note_at: null, also_in: [], read_in: [], teams_mode: 'none', teams: [],
  hide_secrets: true, canary: true, lead_work: 'delegates', when_away: 'waits', away_minutes: 10, spawn_approval: 'auto', spawn_max_depth: 2, spawn_max_agents: 6,
  spawn_max_parallel: 2, discussion_budget: null, room_posts: 40, room_tokens: null, room_minutes: 30, pass_env: null, held_env: [],
  koloni: { settings_kept: false, rules_kept: false, rules: null, broken: [], asks: {} },
}
const base = { dockerAvailable: true, dockerError: null, desktopAvailable: true, onClose: vi.fn() }

/** The server, by what is asked. */
function server(rules: ChatRules[] = []) {
  vi.spyOn(api, 'get').mockImplementation(async (path: string) =>
    (path === '/answer-in' ? { answer_in: null } : path === '/folders' ? { never: [] } : path === '/storage' ? { db_mb: null, backups_mb: null, copies_mb: null, logs_mb: null } : path === '/compaction' ? { compact_at: 75 } : path === '/steps' ? { max_steps: 25 } : path === '/unattended' ? { stuck_minutes: 30, turn_hours: 8 } : path === '/knowledge-limits' ? { max_files: 50000, max_mb: 300 } : path.endsWith('/allowed') ? rules : path.endsWith('/sites') ? [] : { paths: [], more: 0, partial: false }) as never,
  )
}

const levels = () => within(screen.getByRole('navigation', { name: 'Settings levels' }))
const level = (name: string) => levels().getByRole('button', { name })
const named = (kind: string) => levels().getAllByRole('button').filter(b => b.classList.contains(kind)).map(b => b.textContent)

test('Settings lists its levels in their order, This project › The app, each with its sections under it; a chat with no folder has The app only', async () => {
  server()
  const { unmount } = render(<Settings {...base} project={project} onSave={vi.fn()} />)
  // (a project's chat opens on its project)
  expect(named('settings-level')).toEqual(['This project', 'The app'])
  expect(level('This project')).toHaveAttribute('aria-current', 'true')
  expect(level('This project')).toHaveAccessibleDescription('demo · every chat of it')
  expect(screen.getByRole('form', { name: 'Project settings' })).toBeVisible()
  expect(levels().getByRole('button', { name: /^Limits and money/ })).toBeVisible()
  await userEvent.click(level('The app'))
  expect(level('The app')).toHaveAttribute('aria-current', 'true')
  expect(screen.getByRole('form', { name: 'App settings' })).toBeVisible()
  expect(screen.queryByRole('form', { name: 'Project settings' })).toBeNull()
  expect(named('conv-row')).toEqual(['Agents', 'Voice', 'Your data'])
  unmount()
  render(<Settings {...base} project={null} onSave={vi.fn()} />)
  expect(named('settings-level')).toEqual(['The app'])
  await userEvent.click(levels().getByRole('button', { name: 'Your data' }))
  expect(screen.getByRole('region', { name: 'Your data' })).toBeVisible()
})

test('a place asked for lands on its level and section, each time it is asked; the steps link goes between the two levels', async () => {
  server()
  const { rerender } = render(<Settings {...base} project={project} picked={{ section: 'data', n: 1 }} onSave={vi.fn()} />)
  expect(level('The app')).toHaveAttribute('aria-current', 'true')
  expect(levels().getByRole('button', { name: 'Your data' })).toHaveAttribute('aria-current', 'true')
  rerender(<Settings {...base} project={project} picked={{ section: 'limits', n: 2 }} onSave={vi.fn()} />)
  expect(level('This project')).toHaveAttribute('aria-current', 'true')
  expect(levels().getByRole('button', { name: /^Limits and money/ })).toHaveAttribute('aria-current', 'true')
  // Continue's extra steps are the project's; the step limit is the app's: each names the other, a click away.
  await userEvent.click(screen.getByRole('button', { name: 'Steps an agent may take' }))
  expect(level('The app')).toHaveAttribute('aria-current', 'true')
  expect(await screen.findByLabelText('Steps an agent may take')).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'This project › Limits and money' }))
  expect(screen.getByLabelText('Continue gives this many more steps')).toBeVisible()
  // the same place asked again, after a click elsewhere: it is shown again
  await userEvent.click(level('The app'))
  rerender(<Settings {...base} project={project} picked={{ section: 'limits', n: 3 }} onSave={vi.fn()} />)
  expect(screen.getByLabelText('Continue gives this many more steps')).toBeVisible()
})

test('The app › Your data: a backup, what KOLONİ’s data takes on this machine (“–” for a size not counted in time), and the places no agent opens', async () => {
  vi.spyOn(api, 'get').mockImplementation(async (path: string) =>
    (path === '/storage' ? { db_mb: 12.3, backups_mb: 535, copies_mb: null, logs_mb: 0.1 } : path === '/folders' ? { never: [{ path: 'C:/Users/me/.ssh', why: 'secrets' }] } : path === '/compaction' ? { compact_at: 75 } : path === '/steps' ? { max_steps: 25 } : path === '/unattended' ? { stuck_minutes: 30, turn_hours: 8 } : path === '/knowledge-limits' ? { max_files: 50000, max_mb: 300 } : { answer_in: null }) as never,
  )
  render(<Settings {...base} project={null} picked={{ section: 'data', n: 1 }} onSave={vi.fn()} />)
  expect(await screen.findByText('KOLONİ’s data: db 12.3 MB · backups 535 MB · copies – · logs 0.1 MB')).toBeVisible()
  expect(await screen.findByRole('list', { name: 'Always blocked' })).toHaveTextContent('C:/Users/me/.ssh - secrets')
})

test('App: Answer in and Summarise a long context at are every project’s, each one line with its why behind ⓘ; only what changed is sent', async () => {
  server()
  const put = vi.spyOn(api, 'put').mockImplementation(async (_path, body) => body as never)
  render(<Settings {...base} project={null} onSave={vi.fn()} />)
  const language = await screen.findByLabelText('Answer in')
  await vi.waitFor(() => expect(language).toBeEnabled())
  expect(language).toHaveAttribute('placeholder', 'Auto')
  const compact = screen.getByLabelText('Summarise a long context at (%)')
  await vi.waitFor(() => expect(compact).toHaveValue('75'))
  expect(screen.getByText(/^For every project: once an agent’s context passes this much/)).not.toBeVisible()
  const save = screen.getByRole('button', { name: 'Save' })
  expect(save).toBeDisabled()
  await userEvent.type(language, 'Türkçe. Ignore')
  expect(screen.getByText('A language’s name: at most 40 letters, spaces and hyphens.')).toBeVisible()
  expect(save).toBeDisabled()
  await userEvent.clear(language)
  await userEvent.type(language, 'Türkçe')
  await userEvent.click(save)
  expect(put).toHaveBeenCalledWith('/answer-in', { answer_in: 'Türkçe' })
  expect(put).not.toHaveBeenCalledWith('/compaction', expect.anything())
  await userEvent.clear(compact)
  await userEvent.type(compact, '96')
  expect(save).toBeDisabled()
  await userEvent.clear(compact)
  await userEvent.type(compact, '90')
  await userEvent.click(save)
  expect(put).toHaveBeenLastCalledWith('/compaction', { compact_at: 90 })
})

test('App: Steps an agent may take (B-398) is read, held to 5-200 and sent only when changed', async () => {
  server()
  const put = vi.spyOn(api, 'put').mockImplementation(async (_path, body) => body as never)
  render(<Settings {...base} project={null} onSave={vi.fn()} />)
  const steps = await screen.findByLabelText('Steps an agent may take')
  await vi.waitFor(() => expect(steps).toHaveValue('25'))
  const save = screen.getByRole('button', { name: 'Save' })
  await userEvent.clear(steps)
  await userEvent.type(steps, '4')
  expect(screen.getByText('A whole number from 5 to 200.')).toBeVisible()
  expect(save).toBeDisabled()
  await userEvent.clear(steps)
  await userEvent.type(steps, '60')
  await userEvent.click(save)
  expect(put).toHaveBeenCalledWith('/steps', { max_steps: 60 })
  expect(put).not.toHaveBeenCalledWith('/compaction', expect.anything())
})

test('App: when work nobody watches is stuck, and its ceiling (B-413), are read, held to their ranges and sent only when changed; an empty ceiling is none', async () => {
  server()
  const put = vi.spyOn(api, 'put').mockImplementation(async (_path, body) => body as never)
  render(<Settings {...base} project={null} onSave={vi.fn()} />)
  const stuck = await screen.findByLabelText('Stuck after this many minutes with no progress')
  const ceiling = screen.getByLabelText('An unattended turn runs at most (hours)')
  await vi.waitFor(() => expect(stuck).toHaveValue('30'))
  expect(ceiling).toHaveValue('8')
  const save = screen.getByRole('button', { name: 'Save' })
  await userEvent.clear(stuck)
  await userEvent.type(stuck, '2')
  expect(screen.getByText('A whole number from 5 to 1440.')).toBeVisible()
  expect(save).toBeDisabled()
  await userEvent.clear(stuck)
  await userEvent.type(stuck, '45')
  await userEvent.clear(ceiling)
  await userEvent.click(save)
  expect(put).toHaveBeenCalledWith('/unattended', { stuck_minutes: 45 })
  expect(put).toHaveBeenCalledWith('/unattended', { turn_hours: null })
  expect(put).not.toHaveBeenCalledWith('/steps', expect.anything())
})

test('App: what knowledge from a repository or a folder reads at most is read, held to its range and sent only when changed', async () => {
  server()
  const put = vi.spyOn(api, 'put').mockImplementation(async (_path, body) => body as never)
  render(<Settings {...base} project={null} onSave={vi.fn()} />)
  const files = await screen.findByLabelText('Knowledge reads at most (files)')
  const mb = screen.getByLabelText('Knowledge reads at most (MB)')
  await vi.waitFor(() => expect(files).toHaveValue('50000'))
  expect(mb).toHaveValue('300')
  const save = screen.getByRole('button', { name: 'Save' })
  await userEvent.clear(mb)
  await userEvent.type(mb, '0')
  expect(screen.getByText('A whole number from 1 to 10240.')).toBeVisible()
  expect(save).toBeDisabled()
  await userEvent.clear(mb)
  await userEvent.type(mb, '50')
  await userEvent.click(save)
  expect(put).toHaveBeenCalledWith('/knowledge-limits', { max_mb: 50 })
  expect(put).not.toHaveBeenCalledWith('/knowledge-limits', { max_files: expect.anything() })
})

test('This project › Asking and away, and Limits and money: every chat’s sub-agent settings, one line each, sent only when changed; above 8 at once is said in sight', async () => {
  server()
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<Settings {...base} project={{ ...project, discussion_budget: 200000 }} onSave={onSave} />)
  const save = () => screen.getByRole('button', { name: 'Save' })
  await userEvent.click(levels().getByRole('button', { name: /^Asking and away/ }))
  expect(screen.getByLabelText('Opening a sub-agent')).toHaveValue('auto')
  // Never asking is said in sight: it holds in every chat of the project.
  const own = 'Sub-agents open on their own, in every chat of this project.'
  expect(screen.queryByText(own)).toBeNull()
  await userEvent.selectOptions(screen.getByLabelText('Opening a sub-agent'), 'Never ask')
  expect(screen.getByText(own).closest('.hint')).toBeNull()
  await userEvent.selectOptions(screen.getByLabelText('Opening a sub-agent'), 'Always ask')
  await userEvent.click(save())
  expect(onSave).toHaveBeenLastCalledWith({ spawn_approval: 'always' })
  await userEvent.click(levels().getByRole('button', { name: /^Limits and money/ }))
  const depth = screen.getByLabelText('Sub-agent levels')
  expect(screen.getByText('Orchestrator → sub-agent → its own sub-agent')).toBeVisible()
  await userEvent.clear(depth)
  await userEvent.type(depth, '5')
  expect(save()).toBeDisabled()
  await userEvent.clear(depth)
  await userEvent.type(depth, '1')
  expect(screen.getByText('Orchestrator → sub-agent (it opens no more)')).toBeVisible()
  const parallel = screen.getByLabelText('Agents at the same time')
  await userEvent.clear(parallel)
  await userEvent.type(parallel, '9')
  // (Above 8 it may be saved, and is said - not behind ⓘ.)
  const strain = screen.getByText(/This may strain this machine and your subscription\./)
  expect(strain.closest('.hint')).toBeNull()
  const per = screen.getByLabelText('Sub-agents per request')
  await userEvent.clear(per)
  await userEvent.type(per, '21')
  expect(save()).toBeDisabled()
  await userEvent.clear(per)
  await userEvent.type(per, '4')
  // A discussion has no token limit unless one is given (the user, 6 Nov); emptied, the one kept goes.
  const talk = screen.getByLabelText('A discussion’s tokens, at most')
  expect(talk).toHaveValue('200000')
  await userEvent.clear(talk)
  await userEvent.type(talk, '1.5')
  expect(save()).toBeDisabled()
  await userEvent.clear(talk)
  await userEvent.click(save())
  expect(onSave).toHaveBeenLastCalledWith({ spawn_max_parallel: 9, spawn_max_depth: 1, spawn_max_agents: 4, discussion_budget: null })
})

test('This project › New chats start with: the teams and other folders a new chat starts with, and what a room may spend (no token limit by default; emptied, no limit)', async () => {
  server()
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<Settings {...base} project={{ ...project, also_in: ['D:/lib'], read_in: ['D:/notes'] }} onSave={onSave} />)
  await userEvent.click(levels().getByRole('button', { name: /^New chats start with/ }))
  expect(screen.getByLabelText('New chats’ teams')).toHaveValue('none')
  expect(within(screen.getByRole('list', { name: 'New chats’ other folders' })).getAllByRole('listitem').map(li => li.textContent)).toEqual(['D:/lib read and write', 'D:/notes read only'])
  expect(screen.getByLabelText('Posts, at most')).toHaveValue('40')
  expect(screen.getByLabelText('Tokens, at most')).toHaveValue('')
  expect(screen.getByLabelText('Tokens, at most')).toHaveAttribute('placeholder', 'No limit')
  await userEvent.type(screen.getByLabelText('Tokens, at most'), '400000')
  await userEvent.clear(screen.getByLabelText('Minutes, at most'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ room_tokens: 400000, room_minutes: null })
  await userEvent.selectOptions(screen.getByLabelText('New chats’ teams'), 'Orchestrator decides')
  await userEvent.click(screen.getByRole('button', { name: 'Remove D:/notes from new chats' }))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ teams_mode: 'lead', teams: [], also_in: ['D:/lib'], read_in: [], room_tokens: 400000, room_minutes: null })
})

test('Project › Runs without asking: the project’s sites first, then each chat’s commands by its title, each removed here; the open chat is there even with none', async () => {
  const rules: ChatRules[] = [
    { conversation_id: 'c1', title: 'Fix the login', commands: [{ id: 'r1', conversation_id: 'c1', prefix: 'npm test', danger: '', created_at: 't' }], web: [{ id: 'w1', conversation_id: 'c1', project_id: null, kind: 'host', host: 'example.com', ask_first: false, created_at: 't' }] },
  ]
  server(rules)
  const remove = vi.spyOn(api, 'delete').mockResolvedValue(undefined as never)
  const post = vi.spyOn(api, 'post').mockResolvedValue(undefined as never)
  render(<Settings {...base} project={project} picked={{ section: 'rules', n: 1 }} chat={{ id: 'c9', title: 'Open one' }} onSave={vi.fn()} />)
  const sites = screen.getByRole('region', { name: 'Sites agents open' })
  const chats = screen.getByRole('region', { name: 'Commands and requests by chat' })
  expect(sites.compareDocumentPosition(chats) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  const login = await within(chats).findByRole('group', { name: 'Fix the login' })
  // (counted as the chat's own link counts them: its commands and requests, and the project's sites - none here)
  expect(login).toHaveTextContent('Fix the login · 2 run without asking')
  expect(within(chats).getByRole('group', { name: 'Open one' })).toBeInTheDocument()
  await userEvent.click(within(login).getByRole('button', { name: 'Remove rule npm test' }))
  expect(remove).toHaveBeenCalledWith('/allowed-commands/r1')
  await userEvent.click(within(login).getByRole('button', { name: 'Remove rule GET example.com' }))
  expect(remove).toHaveBeenLastCalledWith('/allowed-web/w1')
  await userEvent.type(screen.getByLabelText('Allow GET to a host in Open one'), 'api.example.com{Enter}')
  expect(post).toHaveBeenCalledWith('/conversations/c9/allowed-web', { host: 'api.example.com' })
  // (no Save: each is saved as it is done)
  expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
})
