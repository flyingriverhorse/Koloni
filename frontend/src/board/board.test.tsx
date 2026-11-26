import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Board, Project, Provider } from '../api/types'
import { ModelsPage } from '../models/ModelsPage'
import { ProjectSettings } from '../shell/ProjectSettings'
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
  own_questions: 0,
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
      merges_pending: 0,
      turn: null,
      agents: [
        agent({ holds: ['a.txt', 'docs/b.md'] }),
        agent({ name: 'Coder 2', role: 'Coder', status: 'queued', copy: { state: 'own' } }),
      ],
    },
    {
      conversation_id: 'b',
      title: 'Tests',
      merges_pending: 0,
      turn: null,
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
  embedding_provider_id: null,
  embedding_model: 'text-embedding-3-small',
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
  room_posts: 40,
  room_tokens: null,
  room_minutes: 30,
  room_min_tokens: 60000,
  pass_env: null,
  held_env: [],
  koloni: { settings_kept: false, rules_kept: false, rules: null, broken: [], asks: {} },
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
  expect(
    screen.getByText(/What Continue gives an agent stopped at a step limit.*a fresh app step limit instead/),
  ).toBeInTheDocument()
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
    max_running: null,
    plan: false,
    step_down_at: null,
    day_limit: null,
    month_limit: null,
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
    id: 'p1',
    name: 'X',
    kind: 'codex_cli',
    base_url: null,
    default_model: null,
    executable: null,
    mode: 'native',
    options: null,
    for_agents: false,
    note: null,
    models: [],
    only_listed: false,
    max_running: null,
    most_at_once: 3,
    plan: false,
    step_down_at: null,
    day_limit: null,
    month_limit: null,
    has_key: false,
    position: 0,
    created_at: 't',
    updated_at: 't',
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
  const [cloud] = await field({
    ...base,
    kind: 'openai_compat',
    mode: null,
    base_url: 'https://openrouter.ai/api/v1',
    most_at_once: 8,
  })
  expect(cloud).toHaveAttribute('placeholder', 'Default: 8')
  expect(cloud).toHaveAccessibleDescription(/Empty: 8, the default for a service\./)
})
