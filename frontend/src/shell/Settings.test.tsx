import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import type { ChatRules, JudgeOut, Project } from '../api/types'
import { MEASURED } from './sections/JudgeModel'
import { Settings } from './Settings'

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
const base = { dockerAvailable: true, dockerError: null, desktopAvailable: true, onClose: vi.fn() }

/** The More limits of the level shown (the other level's is in a hidden panel). */
const shownMore = () => screen.getAllByText(/^More limits/).find(one => !one.closest('[hidden]'))!
const openMore = () => userEvent.click(shownMore())

/** The Judge model as a server with two fast models (one a CLI) and a strongest one has it, none chosen. */
const LOCAL = { provider_id: 'p1', provider_name: 'Local', cli: false, measured: false }
const JUDGE: JudgeOut = {
  provider_id: null,
  model_id: null,
  now: { ...LOCAL, model_id: 'quick' },
  choices: [
    { ...LOCAL, model_id: 'quick', tier: 'fast' },
    { provider_id: 'p2', provider_name: 'Claude Code', model_id: 'haiku', cli: true, measured: true, tier: 'fast' },
    { ...LOCAL, model_id: 'big', tier: 'strongest' },
  ],
}

/** The server, by what is asked. */
function server(rules: ChatRules[] = [], judge: JudgeOut = JUDGE) {
  vi.spyOn(api, 'get').mockImplementation(
    async (path: string) =>
      (path === '/answer-in'
        ? { answer_in: null }
        : path === '/judge'
          ? judge
          : path === '/experimental-clis'
            ? { show: false }
            : path === '/folders'
              ? { never: [] }
              : path === '/storage'
                ? { db_mb: null, backups_mb: null, copies_mb: null, logs_mb: null }
                : path === '/compaction'
                  ? { compact_at: 75 }
                  : path === '/steps'
                    ? { max_steps: 25 }
                    : path === '/unattended'
                      ? { stuck_minutes: 30, turn_hours: 8 }
                      : path === '/knowledge-limits'
                        ? { max_files: 50000, max_mb: 300 }
                        : path === '/test-load'
                          ? { runs_at_once: 1, workers: 2 }
                          : path.endsWith('/allowed')
                            ? rules
                            : path.endsWith('/sites')
                              ? []
                              : { paths: [], more: 0, partial: false }) as never,
  )
}

const levels = () => within(screen.getByRole('navigation', { name: 'Settings levels' }))
const level = (name: string) => levels().getByRole('button', { name })
const named = (kind: string) =>
  levels()
    .getAllByRole('button')
    .filter(b => b.classList.contains(kind))
    .map(b => b.textContent)

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

test('Show experimental features, ticked in The app › Agents, offers Let agy search too in This project at once', async () => {
  server()
  const put = vi.spyOn(api, 'put').mockImplementation(async (_path: string, body: unknown) => body as never)
  render(<Settings {...base} project={project} onSave={vi.fn()} />)
  await userEvent.click(levels().getByRole('button', { name: /^Memory and web/ }))
  expect(screen.queryByLabelText(/^Let agy search too/)).toBeNull()
  await userEvent.click(level('The app'))
  const box = screen.getByRole('checkbox', { name: /^Show experimental features/ })
  await waitFor(() => expect(box).toBeEnabled())
  expect(box).not.toBeChecked()
  await userEvent.click(box)
  expect(put).toHaveBeenCalledWith('/experimental-clis', { show: true })
  expect(box).toBeChecked()
  // (Settings keeps its levels mounted: the project's sections follow without opening it again.)
  await userEvent.click(level('This project'))
  await userEvent.click(levels().getByRole('button', { name: /^Memory and web/ }))
  expect(await screen.findByLabelText(/^Let agy search too/)).toBeVisible()
})

test('The app › Agents: the Judge model is the Fast tier’s first, named, until one is chosen; kept as it is changed; a CLI says each command waits for it', async () => {
  server()
  const put = vi.spyOn(api, 'put').mockImplementation(async (_path, body) => {
    const { provider_id, model_id } = body as { provider_id: string | null; model_id: string | null }
    const picked = JUDGE.choices.find(one => one.provider_id === provider_id && one.model_id === model_id)
    return { ...JUDGE, provider_id, model_id, now: picked ?? JUDGE.now } as never
  })
  render(<Settings {...base} project={null} onSave={vi.fn()} />)
  const judge = screen.getByLabelText('Judge model')
  await waitFor(() => expect(judge).toBeEnabled())
  expect(
    within(judge)
      .getAllByRole('option')
      .map(one => one.textContent),
  ).toEqual([
    'Fast tier’s first (now: quick)',
    'Local · quick (fast)',
    'Claude Code · haiku (fast)',
    'Local · big (strongest)',
  ])
  expect(judge).toHaveDisplayValue('Fast tier’s first (now: quick)')
  const cli = 'On a CLI each such command waits for it to start.'
  expect(screen.queryByText(cli)).toBeNull()
  // (§8: a measured Judge model - haiku here - makes a ticked box for your words live: said)
  expect(screen.queryByText(MEASURED)).toBeNull()
  await userEvent.selectOptions(judge, 'Claude Code · haiku (fast)')
  expect(put).toHaveBeenLastCalledWith('/judge', { provider_id: 'p2', model_id: 'haiku' })
  expect(await screen.findByText(cli)).toBeVisible()
  expect(screen.getByText(MEASURED)).toBeVisible()
  expect(judge).toHaveDisplayValue('Claude Code · haiku (fast)')
  await userEvent.selectOptions(judge, 'Fast tier’s first (now: quick)')
  expect(put).toHaveBeenLastCalledWith('/judge', { provider_id: null, model_id: null })
  await waitFor(() => expect(screen.queryByText(cli)).toBeNull())
  expect(screen.queryByText(MEASURED)).toBeNull()
})

test('a chosen Judge model that cannot be asked now stays chosen and says so; with none to ask, the judge stands aside', async () => {
  server([], { ...JUDGE, provider_id: 'gone', model_id: 'old' })
  const { unmount } = render(<Settings {...base} project={null} onSave={vi.fn()} />)
  const judge = screen.getByLabelText('Judge model')
  await waitFor(() => expect(judge).toHaveDisplayValue('old (cannot be asked now)'))
  expect(
    screen.getByText(
      'Your choice, old, cannot be asked now - its provider is gone, closed to agents or down - so the Fast tier’s first is asked.',
    ),
  ).toBeVisible()
  unmount()
  vi.restoreAllMocks()
  server([], { ...JUDGE, now: null, choices: [] })
  render(<Settings {...base} project={null} onSave={vi.fn()} />)
  await waitFor(() => expect(screen.getByLabelText('Judge model')).toHaveDisplayValue('Fast tier’s first (now: none)'))
  expect(
    screen.getByText(/^No model can be asked: Full auto’s judge stands aside and says so in the chat\./),
  ).toBeVisible()
})

test('a place asked for lands on its level and section, each time it is asked; the steps link goes between the two levels', async () => {
  server()
  const { rerender } = render(
    <Settings {...base} project={project} picked={{ section: 'data', n: 1 }} onSave={vi.fn()} />,
  )
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
  vi.spyOn(api, 'get').mockImplementation(
    async (path: string) =>
      (path === '/storage'
        ? { db_mb: 12.3, backups_mb: 535, copies_mb: null, logs_mb: 0.1 }
        : path === '/folders'
          ? { never: [{ path: 'C:/Users/me/.ssh', why: 'secrets' }] }
          : path === '/compaction'
            ? { compact_at: 75 }
            : path === '/steps'
              ? { max_steps: 25 }
              : path === '/unattended'
                ? { stuck_minutes: 30, turn_hours: 8 }
                : path === '/knowledge-limits'
                  ? { max_files: 50000, max_mb: 300 }
                  : path === '/judge'
                    ? JUDGE
                    : { answer_in: null }) as never,
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
  await openMore()
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
  await openMore()
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

test('App: KOLONİ’s test runs at once and the test processes each may start save within their ranges (S6)', async () => {
  server()
  const put = vi.spyOn(api, 'put').mockImplementation(async (_path, body) => body as never)
  render(<Settings {...base} project={null} onSave={vi.fn()} />)
  const runs = await screen.findByLabelText('KOLONİ’s test runs at once')
  const workers = screen.getByLabelText('Test processes per run')
  await vi.waitFor(() => expect(runs).toHaveValue('1'))
  expect(workers).toHaveValue('2')
  await openMore()
  const save = screen.getByRole('button', { name: 'Save' })
  await userEvent.clear(runs)
  await userEvent.type(runs, '5')
  expect(screen.getByText('A whole number from 1 to 4.')).toBeVisible()
  expect(save).toBeDisabled()
  await userEvent.clear(runs)
  await userEvent.type(runs, '2')
  await userEvent.click(save)
  expect(put).toHaveBeenCalledWith('/test-load', { runs_at_once: 2 })
  expect(put).not.toHaveBeenCalledWith('/test-load', { workers: expect.anything() })
})

test('App: what knowledge from a repository or a folder reads at most is read, held to its range and sent only when changed', async () => {
  server()
  const put = vi.spyOn(api, 'put').mockImplementation(async (_path, body) => body as never)
  render(<Settings {...base} project={null} onSave={vi.fn()} />)
  const files = await screen.findByLabelText('Knowledge reads at most (files)')
  const mb = screen.getByLabelText('Knowledge reads at most (MB)')
  await vi.waitFor(() => expect(files).toHaveValue('50000'))
  expect(mb).toHaveValue('300')
  await openMore()
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
  await openMore()
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
  expect(onSave).toHaveBeenLastCalledWith({
    spawn_max_parallel: 9,
    spawn_max_depth: 1,
    spawn_max_agents: 4,
    discussion_budget: null,
  })
})

test('This project › Limits and money: the monthly budget and a job’s budget up front, every other limit under More limits - closed, and “set” on it where one is not its default (the user, 26 Nov)', async () => {
  server()
  const { unmount } = render(<Settings {...base} project={project} onSave={vi.fn()} />)
  await userEvent.click(levels().getByRole('button', { name: /^Limits and money/ }))
  const more = shownMore().closest('details')!
  expect(more).not.toHaveAttribute('open')
  expect(shownMore()).toHaveTextContent(/^More limits$/)
  for (const label of ['Monthly budget', 'Stop the work on a message over this many tokens'])
    expect(screen.getByLabelText(label).closest('details'), label).toBeNull()
  for (const label of [
    'At most this many agents at work in this project',
    'Agents at the same time',
    'Sub-agent levels',
    'Sub-agents per request',
    'Continue gives this many more steps',
    'A discussion’s tokens, at most',
  ])
    expect(screen.getByLabelText(label).closest('details'), label).toBe(more)
  expect(screen.getByLabelText('Monthly budget')).toBeVisible()
  expect(screen.getByLabelText('Agents at the same time')).not.toBeVisible()
  unmount()
  render(<Settings {...base} project={{ ...project, spawn_max_parallel: 4 }} onSave={vi.fn()} />)
  await userEvent.click(levels().getByRole('button', { name: /^Limits and money/ }))
  expect(shownMore()).toHaveTextContent('More limits · set')
})

test('a value under More limits that cannot be saved keeps it open - the field that says why stays in sight while Save is off; fixed, it closes again (N7)', async () => {
  server()
  render(<Settings {...base} project={project} onSave={vi.fn()} />)
  await userEvent.click(levels().getByRole('button', { name: /^Limits and money/ }))
  const more = shownMore().closest('details')!
  await openMore()
  expect(more).toHaveAttribute('open')
  const steps = screen.getByLabelText('Continue gives this many more steps')
  await userEvent.clear(steps)
  await userEvent.type(steps, '0')
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  await openMore() // (closed by the user)
  await waitFor(() => expect(more).toHaveAttribute('open'))
  expect(steps).toBeVisible()
  expect(screen.getByText(/A whole number from 1 to 200/)).toBeVisible()
  await userEvent.clear(steps)
  await userEvent.type(steps, '7')
  expect(more).toHaveAttribute('open') // (fixed: not shut under the cursor)
  expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
  await openMore()
  await waitFor(() => expect(more).not.toHaveAttribute('open'))
})

test('The app › Agents: a step limit that cannot be saved keeps its More limits open (N7)', async () => {
  server()
  render(<Settings {...base} project={null} onSave={vi.fn()} />)
  const steps = await screen.findByLabelText('Steps an agent may take')
  await vi.waitFor(() => expect(steps).toHaveValue('25'))
  const more = shownMore().closest('details')!
  await openMore()
  await userEvent.clear(steps)
  await userEvent.type(steps, '1')
  await openMore()
  await waitFor(() => expect(more).toHaveAttribute('open'))
  expect(steps).toBeVisible()
})

test('The app › Agents: the step limit, the unattended limits, and what knowledge and KOLONİ’s tests may take are under More limits, closed; the language and when a context is summarised stay in sight', async () => {
  server()
  render(<Settings {...base} project={null} onSave={vi.fn()} />)
  const steps = await screen.findByLabelText('Steps an agent may take')
  await vi.waitFor(() => expect(steps).toHaveValue('25'))
  const more = shownMore().closest('details')!
  expect(more).not.toHaveAttribute('open')
  expect(shownMore()).toHaveTextContent(/^More limits$/)
  for (const label of ['Answer in', 'Summarise a long context at (%)'])
    expect(screen.getByLabelText(label).closest('details'), label).toBeNull()
  for (const label of [
    'Steps an agent may take',
    'Stuck after this many minutes with no progress',
    'An unattended turn runs at most (hours)',
    'Knowledge reads at most (files)',
    'Knowledge reads at most (MB)',
    'KOLONİ’s test runs at once',
    'Test processes per run',
  ])
    expect(screen.getByLabelText(label).closest('details'), label).toBe(more)
  // A limit typed away from its default says so on it.
  await userEvent.clear(steps)
  await userEvent.type(steps, '40')
  expect(shownMore()).toHaveTextContent('More limits · set')
})

test('This project › New chats start with: the teams and other folders a new chat starts with (rooms and their limits are gone, 0.1.10)', async () => {
  server()
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<Settings {...base} project={{ ...project, also_in: ['D:/lib'], read_in: ['D:/notes'] }} onSave={onSave} />)
  await userEvent.click(levels().getByRole('button', { name: /^New chats start with/ }))
  expect(screen.getByLabelText('New chats’ teams')).toHaveValue('none')
  expect(
    within(screen.getByRole('list', { name: 'New chats’ other folders' }))
      .getAllByRole('listitem')
      .map(li => li.textContent),
  ).toEqual(['D:/lib read and write', 'D:/notes read only'])
  expect(screen.queryByText('A room’s limits')).toBeNull()
  expect(screen.queryByLabelText('Posts, at most')).toBeNull()
  await userEvent.selectOptions(screen.getByLabelText('New chats’ teams'), 'Orchestrator decides')
  await userEvent.click(screen.getByRole('button', { name: 'Remove D:/notes from new chats' }))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({
    teams_mode: 'lead',
    teams: [],
    also_in: ['D:/lib'],
    read_in: [],
  })
})

test('Project › Runs without asking: the project’s sites first, then each chat’s commands by its title, each removed here; the open chat is there even with none', async () => {
  const rules: ChatRules[] = [
    {
      conversation_id: 'c1',
      title: 'Fix the login',
      commands: [{ id: 'r1', conversation_id: 'c1', prefix: 'npm test', danger: '', created_at: 't' }],
      web: [
        {
          id: 'w1',
          conversation_id: 'c1',
          project_id: null,
          kind: 'host',
          host: 'example.com',
          ask_first: false,
          created_at: 't',
        },
      ],
    },
  ]
  server(rules)
  const remove = vi.spyOn(api, 'delete').mockResolvedValue(undefined as never)
  const post = vi.spyOn(api, 'post').mockResolvedValue(undefined as never)
  render(
    <Settings
      {...base}
      project={project}
      picked={{ section: 'rules', n: 1 }}
      chat={{ id: 'c9', title: 'Open one' }}
      onSave={vi.fn()}
    />,
  )
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

test('App: Answer in is sent tidied - spaces between words once; “auto” in any case is Auto, and nothing to save when that is what is kept', async () => {
  server()
  const put = vi.spyOn(api, 'put').mockImplementation(async (_path, body) => body as never)
  render(<Settings {...base} project={null} onSave={vi.fn()} />)
  const language = await screen.findByLabelText('Answer in')
  await vi.waitFor(() => expect(language).toBeEnabled())
  const save = screen.getByRole('button', { name: 'Save' })
  await userEvent.clear(language)
  await userEvent.type(language, '  Brazilian   Portuguese ')
  expect(language).not.toHaveAttribute('aria-invalid')
  await userEvent.click(save)
  expect(put).toHaveBeenLastCalledWith('/answer-in', { answer_in: 'Brazilian Portuguese' })
  await vi.waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/^Saved$/))
  await userEvent.clear(language)
  await userEvent.type(language, 'x'.repeat(41))
  expect(language).toHaveAttribute('aria-invalid', 'true')
  expect(save).toBeDisabled()
  expect(screen.getByRole('status')).toHaveTextContent(/^$/)
  await userEvent.clear(language)
  await userEvent.type(language, ' AUTO ')
  expect(language).not.toHaveAttribute('aria-invalid')
  await userEvent.click(save)
  expect(put).toHaveBeenLastCalledWith('/answer-in', { answer_in: null })
})
