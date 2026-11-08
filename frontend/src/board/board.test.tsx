import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import type { Board, Project, Provider } from '../api/types'
import { ModelsPage } from '../models/ModelsPage'
import { ProjectSettings } from '../shell/ProjectSettings'
import { useApp } from '../state/store'
import { when } from '../canvas/turns'
import { boardTurn } from '../test-fixtures'
import { BoardPage } from './BoardPage'
import { ConflictStrip } from './ConflictStrip'

type BoardAgent = Board['conversations'][number]['agents'][number]

const agent = (over: Partial<BoardAgent> = {}): BoardAgent => ({
  id: over.name ?? 'Lead',
  name: 'Lead',
  status: 'running',
  role: 'Lead',
  provider_name: 'Local',
  model_id: 'qwen',
  holds: [],
  copy: null,
  waiting_for: null,
  sign: null,
  last_event_at: null,
  in_tool: false,
  changes_to_approve: 0,
  questions: 0,
  ...over,
})

/**
 * Three conversations of one project. In «Docs», which works in docs/, the lead works and holds
 * a.txt, and its Coder waits for a slot; in «Tests» the lead waits for that file; in «Old»
 * nothing goes on.
 */
const board: Board = {
  backlog_waiting: 0,
  limit: 4,
  running: 3,
  conversations: [
    {
      conversation_id: 'a',
      title: 'Docs',
      merges_pending: 0, turn: null,
      agents: [
        agent({ holds: ['a.txt', 'docs/b.md'] }),
        agent({ name: 'Coder 2', role: 'Coder', status: 'queued', copy: { state: 'own' } }),
      ],
    },
    {
      conversation_id: 'b',
      title: 'Tests',
      merges_pending: 0, turn: null,
      agents: [agent({ status: 'blocked', waiting_for: { agent_id: 'x', agent_name: 'Lead', path: 'a.txt' } })],
    },
    { conversation_id: 'c', title: 'Old', merges_pending: 0, turn: null, agents: [] },
  ],
  conflicts: [
    {
      path: 'a.txt',
      holder: { conversation_id: 'a', agent_name: 'Lead' },
      waiting: [{ conversation_id: 'b', agent_name: 'Lead' }],
    },
  ],
}
const CONFLICT = 'a.txt: held by Orchestrator in «Docs», waited for by Orchestrator in «Tests»'
const page = { board, error: null, currentId: null, onLoad: vi.fn().mockResolvedValue(undefined), onOpen: vi.fn() }
/** A conversation's card, named by its title. */
const card = (title: string) => screen.getByRole('listitem', { name: title })
/** The titles of the cards a column shows open, in order. */
const titles = (column: string) =>
  within(screen.getByRole('region', { name: column }))
    .queryAllByRole('listitem')
    .filter(item => item.classList.contains('board-card') && !item.closest('details'))
    .map(item => item.querySelector('.board-title')!.textContent)

afterEach(() => {
  vi.useRealTimers()
  useApp.setState({ conv: null })
})

// --- the page --------------------------------------------------------------------------------

test('the board says how many agents are at work against the limit, and what each one is doing', () => {
  render(<BoardPage {...page} />)
  expect(screen.getByText('3 of 4 agents at work')).toBeInTheDocument()
  expect(titles('At work')).toEqual(['Docs', 'Tests'])
  const [lead, coder] = within(card('Docs')).getAllByRole('listitem')
  expect(lead).toHaveTextContent('Orchestrator')
  expect(lead).toHaveTextContent('working')
  expect(lead).toHaveTextContent('holds a.txt, docs/b.md')
  // The words are the ones an agent's own conversation uses; its role is said where its name does not.
  expect(coder).toHaveTextContent('Coder 2')
  expect(coder).toHaveTextContent('Coder')
  expect(coder).toHaveTextContent('waiting for a slot')
  // Its model and working copy are its chat's to show, not the Board's.
  expect(card('Docs')).not.toHaveTextContent('Local · qwen')
  expect(coder).not.toHaveTextContent('works in its own copy')
  // said by the one label a state has everywhere: its word, in its colour
  expect([lead, coder].map(row => row.querySelector<HTMLElement>('.status')!).map(s => [s.textContent, s.style.color])).toEqual([
    ['working', 'var(--accent)'],
    ['waiting for a slot', 'var(--muted)'],
  ])
  expect(within(card('Tests')).getByRole('listitem')).toHaveTextContent('waiting for a file')
  expect(within(card('Tests')).getByRole('listitem')).toHaveTextContent('a.txt, held by Orchestrator')
})

test('a conversation that never ran is folded under Ended today’s older ones, closed', () => {
  render(<BoardPage {...page} />)
  const done = screen.getByRole('region', { name: 'Ended today' })
  expect(titles('Ended today')).toEqual([])
  expect(within(done).getByText('Nothing ended today.')).toBeInTheDocument()
  const older = within(done).getByText('1 older').closest('details')!
  expect(older).not.toHaveAttribute('open')
  expect(within(older).getByRole('listitem', { name: 'Old' })).toHaveTextContent('never ran')
  expect(within(older).queryByRole('button', { name: 'Docs' })).not.toBeInTheDocument()
})

test('two conversations that want one file are named on top: the file, who holds it, who wants it, and Open', async () => {
  const onOpen = vi.fn()
  render(<BoardPage {...page} onOpen={onOpen} />)
  const conflicts = within(screen.getByRole('list', { name: 'Two conversations want one file' }))
  expect(conflicts.getByText(CONFLICT)).toBeInTheDocument()
  await userEvent.click(conflicts.getByRole('button', { name: 'Open «Docs»' }))
  expect(onOpen).toHaveBeenLastCalledWith('a')
})

test('a row opens its conversation', async () => {
  const onOpen = vi.fn()
  render(<BoardPage {...page} onOpen={onOpen} />)
  await userEvent.click(screen.getByRole('button', { name: 'Tests' }))
  expect(onOpen).toHaveBeenLastCalledWith('b')
  await userEvent.click(screen.getByRole('button', { name: 'Old' }))
  expect(onOpen).toHaveBeenLastCalledWith('c')
})

test('without a limit the board says so, and an agent that waits for the user is said to', () => {
  const asking: Board = {
    backlog_waiting: 0,
    limit: null,
    running: 1,
    conversations: [{ conversation_id: 'a', title: 'Docs', merges_pending: 0, turn: null, agents: [agent({ status: 'waiting_approval' })] }],
    conflicts: [],
  }
  render(<BoardPage {...page} board={asking} />)
  expect(screen.getByRole('status')).toHaveTextContent(/^1 agent at work · no limit$/)
  // at work, its agent saying it waits for you (what it asks is on Ready for you)
  expect(titles('At work')).toEqual(['Docs'])
  expect(within(card('Docs')).getByRole('listitem')).toHaveTextContent('waits for you')
  expect(screen.queryByRole('list', { name: 'Two conversations want one file' })).not.toBeInTheDocument()
})

test('a board with nobody at work says so, and one that could not be read says why', () => {
  const empty: Board = { backlog_waiting: 0, limit: null, running: 0, conversations: [{ conversation_id: 'c', title: 'Old', merges_pending: 0, turn: null, agents: [] }], conflicts: [] }
  const { unmount } = render(<BoardPage {...page} board={empty} />)
  expect(screen.getByText('No agent is at work in this project.')).toBeInTheDocument()
  unmount()
  render(<BoardPage {...page} board={null} error="the server did not answer" />)
  expect(screen.getByRole('alert')).toHaveTextContent('The board could not be read: the server did not answer')
})

test('the page is read when it opens and again while it is open, and no longer once it is closed', async () => {
  vi.useFakeTimers()
  const onLoad = vi.fn().mockResolvedValue(undefined)
  const { unmount } = render(<BoardPage {...page} onLoad={onLoad} />)
  expect(onLoad).toHaveBeenCalledTimes(1)
  await vi.advanceTimersByTimeAsync(5000) // (the read before it has come back by then)
  expect(onLoad).toHaveBeenCalledTimes(2)
  unmount()
  await vi.advanceTimersByTimeAsync(20000)
  expect(onLoad).toHaveBeenCalledTimes(2)
})

test('a read that has not come back is not asked for again on top of itself', async () => {
  vi.useFakeTimers()
  let answer: () => void = () => {}
  const onLoad = vi.fn(() => new Promise<void>(resolve => (answer = resolve)))
  render(<BoardPage {...page} onLoad={onLoad} />)
  await vi.advanceTimersByTimeAsync(16000)
  expect(onLoad).toHaveBeenCalledTimes(1)
  answer()
  await vi.advanceTimersByTimeAsync(5000)
  expect(onLoad).toHaveBeenCalledTimes(2)
})

test('a conversation that cannot be opened is said on the board, which is read again', async () => {
  const onLoad = vi.fn().mockResolvedValue(undefined)
  const onOpen = vi.fn().mockRejectedValueOnce({ detail: 'conversation not found' }).mockResolvedValue(undefined)
  render(<BoardPage {...page} onLoad={onLoad} onOpen={onOpen} />)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Old' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('That conversation could not be opened: conversation not found')
  expect(onLoad).toHaveBeenCalledTimes(2)
  // The next one that opens takes the words away.
  await userEvent.click(screen.getByRole('button', { name: 'Tests' }))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

// --- the strip above a conversation ------------------------------------------------------------

test('both conversations that want one file show it above themselves; another shows nothing', () => {
  for (const id of ['a', 'b']) {
    const { unmount } = render(<ConflictStrip board={board} conversationId={id} />)
    expect(screen.getByRole('status', { name: 'Another conversation wants the same file' })).toHaveTextContent(CONFLICT)
    unmount()
  }
  const { container } = render(<ConflictStrip board={board} conversationId="c" />)
  expect(container).toBeEmptyDOMElement()
  render(<ConflictStrip board={null} conversationId="a" />)
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

// --- the limits ----------------------------------------------------------------------------------

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

test('how many agents may be at work in the project is set in its settings: a whole number, or none', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  const base = { dockerAvailable: true, dockerError: null, desktopAvailable: true, onClose: vi.fn(), onSave }
  // (Its section's Save sends that section alone: the Commands section's three fields are not in it.)
  const sent = {}
  const { unmount } = render(<ProjectSettings {...base} project={project} />)
  await userEvent.click(screen.getByRole('button', { name: /^Limits and money/ }))
  const field = screen.getByLabelText('At most this many agents at work in this project')
  expect(field).toHaveValue('')
  for (const bad of ['0', '-1', '1.5', 'two', '1001']) {
    await userEvent.clear(field)
    await userEvent.type(field, bad)
    expect(field).toBeInvalid()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  }
  await userEvent.clear(field)
  await userEvent.type(field, '4')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ ...sent, max_agents: 4 })
  unmount()
  // One that is set is shown; left as it is, it is not sent; emptied, it is taken away.
  render(<ProjectSettings {...base} project={{ ...project, max_agents: 4 }} />)
  await userEvent.click(screen.getByRole('button', { name: /^Limits and money/ }))
  expect(screen.getByLabelText('At most this many agents at work in this project')).toHaveValue('4')
  // (left as it is, there is nothing to save)
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  expect(onSave).toHaveBeenCalledTimes(1)
  await userEvent.clear(screen.getByLabelText('At most this many agents at work in this project'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ ...sent, max_agents: null })
})

test('K-devam-butce: how many more steps Continue gives is set beside it, a whole number from 1 to 200', async () => {
  const onSave = vi.fn().mockResolvedValue(undefined)
  const base = { dockerAvailable: true, dockerError: null, desktopAvailable: true, onClose: vi.fn(), onSave }
  render(<ProjectSettings {...base} project={project} />)
  await userEvent.click(screen.getByRole('button', { name: /^Limits and money/ }))
  const field = screen.getByLabelText('Continue gives this many more steps')
  expect(field).toHaveValue('25')
  expect(screen.getByText(/What Continue gives an agent stopped at a step limit.*a fresh app step limit instead/)).toBeInTheDocument()
  // (left as it is, there is nothing to save)
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  for (const bad of ['', '0', '201', '2.5']) {
    await userEvent.clear(field)
    if (bad) await userEvent.type(field, bad)
    expect(field).toBeInvalid()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  }
  await userEvent.clear(field)
  await userEvent.type(field, '40')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ continue_steps: 40 })
})

test('a provider’s own limit is set on the Models page and sent only when it was changed', async () => {
  const local: Provider = {
    id: 'p1',
    name: 'Local',
    kind: 'openai_compat',
    base_url: 'http://127.0.0.1:8080/v1',
    default_model: null,
    executable: null,
    mode: null,
    options: null,
    for_agents: false,
    note: null,
    models: [],
    only_listed: false,
    max_running: null, plan: false, step_down_at: null, day_limit: null, month_limit: null,
    has_key: false,
    position: 0,
    created_at: 't',
    updated_at: 't',
  }
  const handlers = {
    onCreate: vi.fn().mockResolvedValue(undefined),
    onSave: vi.fn().mockResolvedValue(undefined),
    onDelete: vi.fn().mockResolvedValue(undefined),
    onTest: vi.fn().mockResolvedValue({ ok: true, model_id: 'qwen', tools_supported: true, error: null }),
  }
  // A llama-server on this machine whose /props said 4 slots: what an empty field holds is the server's word.
  const { unmount } = render(<ModelsPage providers={[{ ...local, most_at_once: 4 }]} picked="p1" {...handlers} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  const field = screen.getByLabelText('At most this many agents at once')
  expect(field).toHaveValue('')
  expect(field).toHaveAttribute('placeholder', 'Default: 4')
  expect(field).toHaveAccessibleDescription(/Empty: a llama-server’s slots, read from its \/props .* 8 until then\./)
  // What is not a number above zero is said to be none, and is not sent.
  await userEvent.type(field, '0')
  expect(field).toBeInvalid()
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(handlers.onSave.mock.lastCall?.[1]).not.toHaveProperty('max_running')
  await userEvent.clear(field)
  await userEvent.type(field, '2')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(handlers.onSave).toHaveBeenLastCalledWith('p1', expect.objectContaining({ max_running: 2 }))
  unmount()
  render(<ModelsPage providers={[{ ...local, max_running: 2, most_at_once: 2 }]} picked="p1" {...handlers} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  expect(screen.getByLabelText('At most this many agents at once')).toHaveValue('2')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(handlers.onSave.mock.lastCall?.[1]).not.toHaveProperty('max_running')
  await userEvent.clear(screen.getByLabelText('At most this many agents at once'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(handlers.onSave).toHaveBeenLastCalledWith('p1', expect.objectContaining({ max_running: null }))
})

test('an empty provider limit says what it is by kind: a CLI 3, a service out there 8', async () => {
  const base: Provider = {
    id: 'p1', name: 'X', kind: 'codex_cli', base_url: null, default_model: null, executable: null, mode: 'native', options: null,
    for_agents: false, note: null, models: [], only_listed: false, max_running: null, most_at_once: 3, plan: false,
    step_down_at: null, day_limit: null, month_limit: null, has_key: false, position: 0, created_at: 't', updated_at: 't',
  }
  const handlers = { onCreate: vi.fn(), onSave: vi.fn(), onDelete: vi.fn(), onTest: vi.fn() }
  const field = async (provider: Provider) => {
    const shown = render(<ModelsPage providers={[provider]} picked="p1" {...handlers} />)
    await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
    return [screen.getByLabelText('At most this many agents at once'), shown.unmount] as const
  }
  const [cli, gone] = await field(base)
  expect(cli).toHaveAttribute('placeholder', 'Default: 3')
  expect(cli).toHaveAccessibleDescription(/Empty: 3, the default for a CLI/)
  gone()
  const [cloud] = await field({ ...base, kind: 'openai_compat', mode: null, base_url: 'https://openrouter.ai/api/v1', most_at_once: 8 })
  expect(cloud).toHaveAttribute('placeholder', 'Default: 8')
  expect(cloud).toHaveAccessibleDescription(/Empty: 8, the default for a service\./)
})

// --- slice 38d: the line on top ---------------------------------------------------------------

test('Board is now: agents at work against the limit, one line to Ready for you, then At work and Ended today', async () => {
  const onReady = vi.fn()
  const { rerender } = render(<BoardPage {...page} waiting={7} onReady={onReady} />)
  expect(screen.getByRole('heading', { name: 'Board' })).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent(/^3 of 4 agents at work$/)
  expect(screen.getByText('7 things wait for you')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Open Ready for you →' }))
  expect(onReady).toHaveBeenCalledTimes(1)
  expect(screen.getAllByRole('region').map(r => r.getAttribute('aria-label'))).toEqual(['At work', 'Ended today'])
  // Today, its switch and the To-do line are gone: the day's numbers are on Usage, what waits on Ready for you.
  expect(screen.queryByRole('button', { name: 'Today' })).toBeNull()
  expect(screen.queryByText(/Backlog page/)).toBeNull()
  rerender(<BoardPage {...page} waiting={1} onReady={onReady} />)
  expect(screen.getByText('1 thing waits for you')).toBeInTheDocument()
  rerender(<BoardPage {...page} waiting={0} onReady={onReady} />)
  expect(screen.queryByRole('button', { name: 'Open Ready for you →' })).toBeNull()
})

test('how the board works is one line in sight, what Re-run sends; the rest behind ⓘ', () => {
  render(<BoardPage {...page} />)
  expect(screen.queryByText('How this works')).toBeNull()
  expect(screen.getByText(/^“Re-run the ones that failed” sends a new message asking its Orchestrator to open just those again/)).toBeVisible()
  expect(screen.getByText(/^For when several conversations work in one project at the same time\./)).not.toBeVisible()
  expect(screen.getByRole('button', { name: 'About this' })).toHaveAccessibleDescription(/did nothing, timed out, went silent or failed is tagged so/)
})

// --- slice 60b: the cards ------------------------------------------------------------------------

test('a turn that ended today is a row of Ended today: how many agents, and when; its tokens are Usage’s', () => {
  const ended = new Date()
  ended.setHours(0, 1)
  const done: Board = {
    ...board,
    conversations: [
      { ...board.conversations[2], conversation_id: 'd', title: 'Done', turn: boardTurn('r1', 'completed', ended.toISOString(), { agents: 2, provider_name: 'Local', model_id: 'qwen', tokens: 9397 }) },
      { ...board.conversations[2], conversation_id: 'u', title: 'Unknown', turn: boardTurn('r2', 'completed', ended.toISOString()) },
    ],
    conflicts: [],
  }
  render(<BoardPage {...page} board={done} />)
  expect(titles('Ended today')).toEqual(['Done', 'Unknown'])
  expect(screen.getByRole('region', { name: 'Ended today' })).toHaveTextContent(/^Ended today · 2/)
  expect(card('Done').querySelector('.board-facts')).toHaveTextContent(`2 agents · ${when(ended.toISOString())}`)
  expect(card('Done')).not.toHaveTextContent('tokens')
  expect(card('Unknown')).toHaveTextContent('0 agents')
})

test('a turn that failed or was stopped today ended today, labelled so, with when it ended; one of an earlier day is older, labelled too', () => {
  const now = new Date().toISOString()
  const day = new Date()
  day.setDate(day.getDate() - 1)
  const yesterday = day.toISOString()
  const broke: Board = {
    ...board,
    conversations: [
      { ...board.conversations[2], conversation_id: 'f', title: 'Failed', turn: boardTurn('r1', 'failed', now) },
      { ...board.conversations[2], conversation_id: 's', title: 'Stopped', turn: boardTurn('r2', 'cancelled', now) },
      { ...board.conversations[2], conversation_id: 'o', title: 'Old failure', turn: boardTurn('r3', 'failed', yesterday) },
      { ...board.conversations[2], conversation_id: 'y', title: 'Yesterday', turn: boardTurn('r4', 'completed', yesterday) },
    ],
    conflicts: [],
  }
  render(<BoardPage {...page} board={broke} />)
  expect(titles('Ended today')).toEqual(['Failed', 'Stopped'])
  expect(within(card('Failed')).getByText('failed')).toHaveStyle({ color: 'var(--del)' })
  expect(within(card('Stopped')).getByText('stopped')).toBeInTheDocument()
  expect(card('Failed').querySelector('.board-facts')).toHaveTextContent(`failed0 agents · ${when(now)}`)
  const older = within(screen.getByText('2 older').closest('details')!)
  expect(within(older.getByRole('listitem', { name: 'Old failure' })).getByText('failed')).toBeInTheDocument()
  expect(older.getByRole('listitem', { name: 'Yesterday' })).not.toHaveTextContent('failed')
})

test('a turn whose plan waits for a yes ended today (the plan is on Ready for you); a turn still queued is at work, and says so', () => {
  const plans: Board = {
    ...board,
    conversations: [
      { ...board.conversations[2], conversation_id: 'p', title: 'Plan', turn: boardTurn('r1', 'completed', new Date().toISOString(), { plan_waits: true }) },
      { ...board.conversations[2], conversation_id: 'q', title: 'Queued', turn: boardTurn('r2', 'queued', null) },
    ],
    conflicts: [],
  }
  render(<BoardPage {...page} board={plans} />)
  expect(titles('Ended today')).toEqual(['Plan'])
  expect(titles('At work')).toEqual(['Queued'])
  expect(within(card('Queued')).getByText('queued')).toBeInTheDocument()
})

test('a server older than the page sends a finished turn without its counts: the row says when, not a crash', () => {
  const ended = new Date().toISOString()
  const old = { id: 'r', status: 'completed', ended_at: ended } as unknown as Board['conversations'][number]['turn']
  render(<BoardPage {...page} board={{ ...board, conversations: [{ conversation_id: 'x', title: 'Older server', merges_pending: 0, turn: old, agents: [] }] }} />)
  expect(card('Older server').querySelector('.board-facts')).toHaveTextContent(when(ended))
  expect(card('Older server')).not.toHaveTextContent('undefined')
})

// --- how its sub-agents came out (K-board-sonuc) -------------------------------------------

type Outcome = NonNullable<Board['conversations'][number]['turn']>['outcomes'][number]
const ended = (name: string, outcome: Outcome['outcome'], status: Outcome['status'] = 'failed'): Outcome => ({
  id: name,
  name,
  role: name,
  provider_name: 'Local',
  model_id: 'qwen',
  status,
  outcome,
  rerun: status === 'failed',
})
const ran = (outcomes: Outcome[]): Board => ({
  ...board,
  conversations: [{ conversation_id: 'd', title: 'Greeting', merges_pending: 0, agents: [], turn: boardTurn('r', 'completed', new Date().toISOString(), { outcomes }) }],
  conflicts: [],
})

test('a sub-agent of the last turn that came to nothing, timed out, went silent or failed says so in a tag', () => {
  render(<BoardPage {...page} board={ran([ended('Reviewer', 'nothing', 'completed'), ended('Coder', 'silent'), ended('Tester', 'timed_out'), ended('Writer', 'error')])} onRerun={vi.fn()} />)
  const rows = within(card('Greeting')).getAllByRole('listitem')
  expect(rows.map(row => [row.querySelector('.board-agent-name')!.textContent, row.querySelector('.status')!.textContent, row.querySelector('.tag')!.textContent])).toEqual([
    ['Reviewer', 'done', 'did nothing'],
    ['Coder', 'failed', 'went silent'],
    ['Tester', 'failed', 'timed out'],
    ['Writer', 'failed', 'error'],
  ])
  // in the house's tags: a failure's red, a cut one's amber, one that did nothing plain
  expect(rows.map(row => row.querySelector('.tag')!.className)).toEqual(['tag', 'tag tag-warn', 'tag tag-warn', 'tag tag-del'])
})

test('"Re-run the ones that failed" is there only for a card with one that failed, and says why it could not', async () => {
  const onRerun = vi.fn().mockRejectedValueOnce({ detail: 'this project is over this month’s budget' }).mockResolvedValue(undefined)
  // Not for one that did nothing, nor one that finished with a report that starts with an error.
  const { rerender } = render(<BoardPage {...page} board={ran([ended('Reviewer', 'nothing', 'completed'), ended('Writer', 'error', 'completed')])} onRerun={onRerun} />)
  expect(screen.queryByRole('button', { name: 'Re-run the ones that failed' })).not.toBeInTheDocument()
  rerender(<BoardPage {...page} board={ran([ended('Reviewer', 'nothing', 'completed'), ended('Coder', 'silent')])} onRerun={onRerun} />)
  await userEvent.click(screen.getByRole('button', { name: 'Re-run the ones that failed' }))
  expect(onRerun).toHaveBeenCalledWith('d')
  expect(await within(card('Greeting')).findByRole('alert')).toHaveTextContent('They could not be re-run: this project is over this month’s budget')
  await userEvent.click(screen.getByRole('button', { name: 'Re-run the ones that failed' }))
  expect(within(card('Greeting')).queryByRole('alert')).not.toBeInTheDocument()
})
