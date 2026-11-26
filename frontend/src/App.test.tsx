import { act, cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { App } from './App'
import { resetStoreForTests, useApp } from './state/store'
import type { Discussion } from './api/types'
import { agent, command, conversation, question, run } from './test-fixtures'

const project = {
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
  monthly_budget: null,
  git_commit: false,
  auto_notes: false,
  day_note_at: null,
  also_in: [],
  read_in: [],
  hide_secrets: true,
  lead_work: 'delegates',
  pass_env: null,
  held_env: [],
  koloni: { settings_kept: false, rules_kept: false, rules: null, broken: [], asks: {} },
}
const health = {
  desktop_available: true,
  docker_available: true,
  docker_error: null,
  error: null,
  model_base_url: 'http://x/v1',
  model_id: null,
  model_reachable: true,
  not_listed: false,
  provider_name: null,
  tools_supported: null,
  api_hash: import.meta.env.VITE_API_HASH,
  shell: 'PowerShell 7',
  shell_note: null,
}

const chat = { ...conversation, kept: false, archived_at: null }
const snapshot = {
  conversation,
  messages: [],
  runs: [],
  tool_calls: [],
  file_changes: [],
  commands: [],
  allowed_commands: [],
  agents: [],
  channel_messages: [],
  pending_roles: [],
  questions: [],
  discussions: [],
  discussion_posts: [],
  board_posts: [],
  last_event_id: 0,
}
/** What the server answers: the project, the model, one chat in the project (opened at the start) - or what `over` says of a path. */
const answer = (url: string, over: Record<string, unknown> = {}) => {
  const said: Record<string, unknown> = {
    '/api/projects': [project],
    '/api/health': health,
    '/api/conversations': [chat],
    '/api/conversations/c': snapshot,
    '/api/projects/p/board': { limit: null, running: 0, conversations: [], conflicts: [] },
    '/api/projects/p/others-instructions': { paths: [], more: 0, partial: false },
    '/api/projects/p/decisions': { rows: [], judge_fine: 0, more: false },
    '/api/board': { backlog_waiting: 0, limit: null, running: 0, conversations: [], conflicts: [] },
    '/api/hold': {
      held: false,
      since: null,
      running: 0,
      backlogs: [],
      nights: [],
      stopped: [],
      stopping: 0,
    },
    ...over,
  }
  return new Response(JSON.stringify(said[url.split('?')[0]] ?? []), { status: 200 })
}

beforeEach(() => {
  // React Flow watches its pane; jsdom has nothing to watch with.
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  vi.stubGlobal(
    'EventSource',
    class {
      addEventListener() {}
      close() {}
    },
  )
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => answer(url)),
  )
  resetStoreForTests()
})
// (Unmounted first: React Flow's late effects still reach for the stubbed ResizeObserver.)
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

test('⚙ Settings on the rail opens Settings as a page over the canvas and closes it; a page chosen on the rail closes it too (tek-ev)', async () => {
  render(<App />)
  // The top bar has no gear and no Backup now: where commands run is still said there.
  expect(await screen.findByText('this machine')).toBeInTheDocument()
  const rail = (name: string) => within(screen.getByRole('navigation', { name: 'Main' })).getByRole('button', { name })
  const gear = rail('Settings')
  expect(screen.queryByRole('button', { name: /^Project settings for/ })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Your data' })).toBeNull()
  const message = screen.getByLabelText('Message')
  await userEvent.type(message, 'not sent yet')
  expect(gear).toHaveAttribute('aria-pressed', 'false')
  await userEvent.click(gear)
  expect(screen.getByRole('region', { name: 'Settings' })).toBeInTheDocument()
  expect(screen.getByRole('form', { name: 'Project settings' })).toBeVisible()
  expect(gear).toHaveAttribute('aria-pressed', 'true')
  // No page of the rail is the one shown while the settings are.
  expect(rail('Canvas')).toHaveAttribute('aria-pressed', 'false')
  // The canvas is hidden under it, not gone: the very same box, with what is being typed.
  expect(message.isConnected).toBe(true)
  expect(message).not.toBeVisible()
  await userEvent.click(gear)
  expect(screen.queryByRole('region', { name: 'Settings' })).toBeNull()
  expect(screen.getByLabelText('Message')).toBe(message)
  expect(message).toBeVisible()
  expect(message).toHaveValue('not sent yet')
  expect(rail('Canvas')).toHaveAttribute('aria-pressed', 'true')
  // Closed by its own button, the focus goes back to ⚙.
  await userEvent.click(gear)
  await userEvent.click(screen.getByRole('button', { name: 'Close settings' }))
  expect(screen.queryByRole('region', { name: 'Settings' })).toBeNull()
  expect(gear).toHaveFocus()
  await userEvent.click(gear)
  await userEvent.click(rail('Chats'))
  expect(screen.queryByRole('region', { name: 'Settings' })).toBeNull()
  expect(rail('Chats')).toHaveAttribute('aria-pressed', 'true')
})

test('with no folder and no chat KOLONİ opens on the canvas, not on a setup page: the folder button says "No folder", there is no gear, and To-do asks for a folder', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => answer(url, { '/api/projects': [], '/api/conversations': [] })),
  )
  render(<App />)
  expect(await screen.findByLabelText('Message')).toBeInTheDocument()
  expect(screen.queryByText('Open a project')).toBeNull()
  // (Nothing here is about a project: the box says what a plain chat is.)
  expect(screen.getByLabelText('Message')).toHaveAttribute(
    'placeholder',
    'Ask anything - pick a folder with the folder button to work on files',
  )
  expect(screen.getByRole('button', { name: 'Folder: No folder' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /^Project settings for/ })).toBeNull()
  // Nothing is made at the start: the first message makes a plain chat.
  expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
  await userEvent.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('button', { name: 'To-do' }))
  const none = screen.getByText('This chat has no folder - pick one with the folder button to use the To-do.')
  // ...with the way to one beside it: the folder button's own panel.
  expect(screen.queryByRole('button', { name: 'Open a folder…' })).toBeNull()
  await userEvent.click(within(none.parentElement!).getByRole('button', { name: 'Choose a folder' }))
  expect(screen.getByRole('button', { name: 'Open a folder…' })).toBeInTheDocument()
})

test('in a project whose conversations are all archived, none is opened, and the default model is the one a notice is about', async () => {
  const archived = {
    id: 'a',
    project_id: 'p',
    title: 'Put away',
    archived_at: '2026-10-17T08:00:00Z',
    kept: false,
    updated_at: 't',
    provider_id: null,
  }
  const down = {
    ...health,
    model_reachable: false,
    provider_id: 'p-local',
    provider_name: 'Local',
    error: 'connection refused',
  }
  // (A new chat's Orchestrator would run on the default: it is in use.)
  const inUse = {
    '/api/providers': [{ id: 'p-local', name: 'Local', kind: 'openai_compat', default_model: 'qwen', models: [] }],
    '/api/roles': [{ name: 'Lead', builtin: true, enabled: true, teams: [] }],
    '/api/roles/models': [{ role: 'Lead', provider_name: 'Local', asks_how_hard: null }],
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => answer(url, { '/api/health': down, '/api/conversations': [archived], ...inUse })),
  )
  render(<App />)
  // (First steps say it, with what to do: the top bar leaves it to them - and says it once they are hidden.)
  expect(
    await screen.findByText("Local isn't answering - add another provider, or start its model server."),
  ).toBeInTheDocument()
  expect(screen.queryByText(/Local isn't answering at/)).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Hide the first steps' }))
  expect(await screen.findByText(/Local isn't answering at/)).toBeInTheDocument()
  const asked = vi.mocked(fetch).mock.calls.map(([url]) => String(url))
  expect(asked).not.toContain('/api/conversations/a')
})

test('a server that runs another API than the page was built against, or does not say which, is to be restarted', async () => {
  const updated = /^KOLONİ was updated: .* Build the page \(npm run build\), restart KOLONİ, then reload\.$/
  // (Hashed from generated.ts when the page is built.)
  expect(import.meta.env.VITE_API_HASH).toMatch(/^[0-9a-f]{12}$/)
  for (const [said, shown] of [
    [import.meta.env.VITE_API_HASH, false],
    ['000000000000', true],
    [null, true],
    [undefined, true],
  ] as const) {
    resetStoreForTests()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => answer(url, { '/api/health': { ...health, api_hash: said } })),
    )
    const { unmount } = render(<App />)
    await screen.findByText('this machine')
    await vi.waitFor(() => expect(useApp.getState().health).not.toBeNull())
    if (shown) expect(await screen.findByText(updated)).toBeInTheDocument()
    else expect(screen.queryByText(updated)).toBeNull()
    unmount()
  }
})

test('the model server is not asked every 15 s while the tab is hidden; it is asked once as the tab comes back', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] }) // (findBy and waitFor keep real timeouts)
  let hidden = false
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
  const asked = () => vi.mocked(fetch).mock.calls.filter(([url]) => url === '/api/health').length
  try {
    render(<App />)
    await vi.waitFor(() => expect(useApp.getState().conv?.conversation.id).toBe('c'))
    await vi.waitFor(() => expect(useApp.getState().health).not.toBeNull())
    await act(async () => void vi.advanceTimersByTime(15_000))
    const before = asked()
    expect(before).toBeGreaterThan(0)
    hidden = true
    await act(async () => void vi.advanceTimersByTime(60_000))
    expect(asked()).toBe(before)
    hidden = false
    await act(async () => void document.dispatchEvent(new Event('visibilitychange')))
    expect(asked()).toBe(before + 1)
    await act(async () => void vi.advanceTimersByTime(15_000))
    expect(asked()).toBe(before + 2)
  } finally {
    vi.useRealTimers()
    Reflect.deleteProperty(document, 'hidden')
  }
})

test('a page the server has since built anew says so, with a Reload; one of the same build says nothing (K-yenile-uyarisi)', async () => {
  const mine = Object.assign(document.createElement('script'), { type: 'module', src: '/assets/index-old.js' })
  document.head.append(mine)
  const rebuilt = /^KOLONİ's page was rebuilt: reload to use it\.$/
  try {
    for (const [served, shown] of [
      ['/assets/index-old.js', false],
      ['/assets/index-new.js', true],
    ] as const) {
      resetStoreForTests()
      const page = `<!doctype html><html><head><script type="module" crossorigin src="${served}"></script></head></html>`
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => (url === '/' ? new Response(page, { status: 200 }) : answer(url))),
      )
      const { unmount } = render(<App />)
      await screen.findByText('this machine')
      await vi.waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith('/', { cache: 'no-store' }))
      if (shown) {
        expect(await screen.findByText(rebuilt)).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument()
      } else {
        await act(() => new Promise(done => setTimeout(done, 20)))
        expect(screen.queryByText(rebuilt)).toBeNull()
      }
      unmount()
    }
  } finally {
    mine.remove()
  }
})

test('in a plain chat what waits in another folder’s chat is counted on the rail and said in a toast', async () => {
  const asking = (id: string, title: string) => ({
    conversation_id: id,
    title,
    merges_pending: 0,
    turn: null,
    agents: [
      {
        id: `l-${id}`,
        name: 'Lead',
        status: 'waiting_approval',
        role: 'Lead',
        provider_name: null,
        model_id: null,
        holds: [],
        copy: null,
        waiting_for: null,
        sign: null,
        last_event_at: null,
        in_tool: false,
        changes_to_approve: 0,
        questions: 0,
      },
    ],
  })
  // (Ready for you counts each chat's cards, read whole: one question in each.)
  const read = (id: string) => ({
    ...snapshot,
    conversation: { ...conversation, id, project_id: 'p' },
    runs: [run(`r${id}`, 'waiting_approval')],
    questions: [question(`q${id}`, `r${id}`)],
  })
  const everywhere = {
    backlog_waiting: 0,
    limit: null,
    running: 0,
    conflicts: [],
    conversations: [asking('x', 'Fix the login')],
  }
  const plain = { ...chat, project_id: null }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      answer(url, {
        '/api/conversations': [plain],
        '/api/conversations/c': { ...snapshot, conversation: plain },
        '/api/board': everywhere,
        '/api/conversations/x': read('x'),
        '/api/conversations/y': read('y'),
      }),
    ),
  )
  render(<App />)
  expect(await screen.findByText('1 waiting')).toBeInTheDocument()
  everywhere.conversations = [...everywhere.conversations, asking('y', 'Tidy the docs')]
  await act(() => useApp.getState().loadBoard())
  expect(await screen.findByText('Orchestrator waits for you · Tidy the docs')).toBeInTheDocument()
  expect(await screen.findByText('2 waiting')).toBeInTheDocument()
})

test('Settings in a plain chat has This chat and The app; back in the folder’s chat, the project is there again', async () => {
  const plain = { ...chat, id: 'n', project_id: null }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => answer(url, { '/api/conversations/n': { ...snapshot, conversation: plain } })),
  )
  render(<App />)
  await screen.findByText('this machine')
  await userEvent.click(
    within(screen.getByRole('navigation', { name: 'Main' })).getByRole('button', { name: 'Settings' }),
  )
  expect(screen.getByRole('form', { name: 'Project settings' })).toBeInTheDocument()
  await act(() => useApp.getState().openConversation('n'))
  expect(
    within(screen.getByRole('navigation', { name: 'Settings levels' }))
      .getAllByRole('button')
      .filter(b => b.classList.contains('settings-level'))
      .map(b => b.textContent),
  ).toEqual(['This chat', 'The app'])
  expect(screen.queryByRole('form', { name: 'Project settings' })).toBeNull()
  await act(() => useApp.getState().openConversation('c'))
  expect(screen.getByRole('form', { name: 'Project settings' })).toBeInTheDocument()
})

test("another chat opened is a step of the browser's history: Back opens the one before (B-150)", async () => {
  const job = { ...conversation, id: 'c2', title: 'A job of the night' }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => answer(url, { '/api/conversations/c2': { ...snapshot, conversation: job } })),
  )
  render(<App />)
  await vi.waitFor(() => expect(useApp.getState().conv?.conversation.id).toBe('c'))
  const steps = history.length
  expect(history.state).toEqual({ chat: 'c' })
  await act(() => useApp.getState().openConversation('c2'))
  expect([history.state, history.length]).toEqual([{ chat: 'c2' }, steps + 1])
  // (The browser has moved back by then: nothing is pushed again.)
  history.replaceState({ chat: 'c' }, '')
  act(() => void window.dispatchEvent(new PopStateEvent('popstate', { state: { chat: 'c' } })))
  await vi.waitFor(() => expect(useApp.getState().conv?.conversation.id).toBe('c'))
  expect(history.length).toBe(steps + 1)
})

test('while the default does not answer, First steps offers another provider for new chats without asking anything of it; its button makes it the default, and the step is done once that one answers', async () => {
  const down = {
    ...health,
    model_reachable: false,
    provider_id: 'p-local',
    provider_name: 'Local',
    error: 'connection refused',
  }
  const local = { id: 'p-local', name: 'Local', kind: 'openai_compat', default_model: 'qwen', models: [] }
  const cli = { ...local, id: 'p-cli', name: 'Claude Code', kind: 'claude_cli' }
  // (The server's side of the press: the list turned round, and the default's reading the other one's.)
  let pressed = false
  const fetched = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST' && url.endsWith('/default')) pressed = true
    const now = pressed
      ? {
          '/api/health': { ...health, provider_id: 'p-cli', provider_name: 'Claude Code' },
          '/api/providers': [cli, local],
        }
      : { '/api/health': down, '/api/providers': [local, cli] }
    return answer(url, {
      '/api/projects': [],
      '/api/conversations': [],
      '/api/providers/p-cli/limits': { unknown: true },
      ...now,
    })
  })
  vi.stubGlobal('fetch', fetched)
  // (A test above hid the steps: the store of the page is one for the file.)
  localStorage.removeItem('koloni-first-steps')
  render(<App />)
  const steps = await screen.findByRole('region', { name: 'First steps' })
  const use = await within(steps).findByRole('button', { name: 'Use Claude Code for new chats' })
  expect(use.closest('li')).toHaveTextContent(
    "Local isn't answering, and new chats run on it. Claude Code is set up too.",
  )
  // (Not done by the offer: nothing is known to answer yet.)
  expect(use.closest('li')).toHaveAttribute('aria-current', 'step')
  // No provider is asked whether it answers but the one the chat runs on: such a reading may send its model a request.
  const asked = () => fetched.mock.calls.map(([url, init]) => `${init?.method ?? 'GET'} ${url}`)
  expect(asked().filter(call => call.includes('provider_id='))).toEqual([])
  expect(asked().some(call => call.startsWith('POST'))).toBe(false)
  await userEvent.click(use)
  expect(asked()).toContain('POST /api/providers/p-cli/default')
  // The new default answers: the step is done, its note and offer are gone, and the focus is on the page, not nowhere.
  expect(await within(steps).findByText('A provider is set up.')).toBeInTheDocument()
  expect(within(steps).queryByText(/isn't answering/)).toBeNull()
  expect(
    within(steps)
      .getAllByRole('button')
      .map(button => button.textContent),
  ).toEqual(['Choose a folder', 'Hide the first steps'])
  await vi.waitFor(() => expect(document.activeElement).toHaveClass('main'))
  expect(asked().filter(call => call.includes('provider_id='))).toEqual([])
})

/** A server whose pages read nothing yet: what is not a list is not there, the usage and the day are refused. */
const emptyPages = (over: Record<string, unknown> = {}) => {
  const none = [
    '/api/recipes',
    '/api/tiers',
    '/api/projects/p/away',
    '/api/projects/p/budget',
    '/api/projects/p/memory',
  ]
  const refused = ['/api/usage', '/api/projects/p/day']
  return vi.fn(async (url: string) => {
    const path = url.split('?')[0]
    if (none.includes(path)) return new Response('null', { status: 200 })
    if (refused.includes(path)) return new Response('{"detail":"down"}', { status: 500 })
    return answer(url, over)
  })
}
test('each page of the rail is the one in the workspace; a page of a folder, in a plain chat, asks for a folder, and Usage has no day', async () => {
  // (The canvas is known by its first steps: a test above may have hidden them.)
  localStorage.removeItem('koloni-first-steps')
  vi.stubGlobal('fetch', emptyPages())
  const { container } = render(<App />)
  await screen.findByText('this machine')
  const rail = (name: string) => within(screen.getByRole('navigation', { name: 'Main' })).getByRole('button', { name })
  /** The page in the workspace: its box's class and its heading, else its first words. */
  const shown = () => {
    const page = container.querySelector('.workspace')!.firstElementChild as HTMLElement
    return [page.className, (page.querySelector('h1, h2') ?? page.querySelector('p'))?.textContent]
  }
  /** Each page of the rail chosen in turn, and shown as said. */
  const visit = async (pages: [string, string, string][]) => {
    for (const [name, ...said] of pages) {
      await userEvent.click(rail(name))
      await vi.waitFor(() => expect([name, ...shown()]).toEqual([name, ...said]))
    }
  }
  await visit([
    ['Agents', 'paged', 'Agents'],
    ['Models', 'paged', 'Models'],
    ['Tools', 'memory-page tools-page', 'Tools'],
    ['Ready', 'memory-page ready-page', 'Ready for you · 0, oldest first'],
    ['To-do', 'memory-page', 'To-do'],
    ['Usage', 'memory-page', 'Usage'],
    ['Memory', 'memory-page', 'Reading the project’s memory…'],
    ['Knowledge', 'triggers-page knowledge-page', 'Knowledge'],
    ['Chats', 'conv-page', 'Conversations'],
    ['Canvas', 'stage', 'First steps'],
  ])
  await userEvent.click(rail('Usage'))
  expect(await screen.findByText(/^The day could not be read/)).toBeInTheDocument()
  const plain = { ...chat, id: 'n', project_id: null }
  vi.stubGlobal('fetch', emptyPages({ '/api/conversations/n': { ...snapshot, conversation: plain } }))
  await act(() => useApp.getState().openConversation('n'))
  const noFolder = (page: string) => `This chat has no folder - pick one with the folder button to use the ${page}.`
  await visit([
    ['Agents', 'paged', 'Agents'],
    ['Models', 'paged', 'Models'],
    ['Tools', 'memory-page tools-page', 'Tools'],
    ['Ready', 'memory-page ready-page', 'Ready for you · 0, oldest first'],
    ['To-do', 'memory-page', noFolder('To-do')],
    ['Usage', 'memory-page', 'Usage'],
    ['Memory', 'memory-page', noFolder('Memory')],
    ['Knowledge', 'memory-page', noFolder('Knowledge page')],
    ['Chats', 'conv-page', 'Conversations'],
    ['Canvas', 'stage', 'First steps'],
  ])
  // (The day of a folder says it is read as soon as it is drawn: here there is none.)
  await visit([['Usage', 'memory-page', 'Usage']])
  expect(screen.queryByText(/^Reading the day…$|^The day could not be read/)).toBeNull()
})

test("the top bar's pill says what the Lead decided for you when nothing waits; it opens and shuts Ready for you, but not on the Ready page", async () => {
  const decided = question('q', 'r', {
    status: 'answered',
    answer: 'yes',
    lead_why: 'as your rules say',
    answered_at: 't',
  })
  vi.stubGlobal(
    'fetch',
    emptyPages({ '/api/conversations/c': { ...snapshot, runs: [run('r', 'completed')], questions: [decided] } }),
  )
  render(<App />)
  const pill = await screen.findByRole('button', { name: '1 decided for you' })
  expect(pill).toHaveTextContent(/^1 decided$/)
  expect(pill).toHaveAttribute('aria-expanded', 'false')
  expect(document.getElementById('ready-panel')).toBeNull()
  await userEvent.click(pill)
  expect(pill).toHaveAttribute('aria-expanded', 'true')
  expect(document.getElementById('ready-panel')).not.toBeNull()
  await userEvent.click(pill)
  expect(document.getElementById('ready-panel')).toBeNull()
  await userEvent.click(pill)
  await userEvent.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('button', { name: 'Ready' }))
  expect(pill).toHaveAttribute('aria-expanded', 'false')
  expect(document.getElementById('ready-panel')).toBeNull()
  await userEvent.click(pill)
  expect(useApp.getState().readyPanel.open).toBe(true)
  expect(document.getElementById('ready-panel')).toBeNull()
})

/** A command Full auto's judge refused in chat c, as the chat has it and as the project's decision log says it. */
function refusedByTheJudge() {
  const judged = { kind: 'risk' as const, verdict: 'refuse' as const, quote: '', source: '' as const }
  const refused = command('k', 'r', {
    status: 'refused',
    judged: { ...judged, why: 'It sends .env away.', model: 'Fast · quick', seen: false },
  })
  const row = {
    id: 'command:k',
    // (a month old: older than any period but Not seen)
    at: new Date(Date.now() - 30 * 24 * 3600 * 1000).toISOString(),
    kind: 'command',
    who: 'judge',
    what: "KOLONİ's judge did not run a command; the agent went on",
    quote: 'python gen.py',
    answer: null,
    options: null,
    why: 'It sends .env away.',
    conversation_id: 'c',
    chat: 'Chat',
    link: { kind: 'command', id: 'k' },
    undo: 'none',
    undo_reason: 'it did not run',
    seen: false,
  }
  return { refused, log: { rows: [row], judge_fine: 2, more: false } }
}

test("the pill counts a command Full auto's judge refused; the chat says it in one line, and Ready for you has its OK", async () => {
  const { refused, log } = refusedByTheJudge()
  const read = emptyPages({
    '/api/conversations/c': { ...snapshot, runs: [run('r', 'completed')], commands: [refused] },
    '/api/projects/p/decisions': log,
    '/api/commands/k/seen': { ...refused, judged: { ...refused.judged, seen: true } },
  })
  vi.stubGlobal('fetch', read)
  render(<App />)
  await userEvent.click(await screen.findByRole('button', { name: '1 decided for you' }))
  const panel = document.getElementById('ready-panel')!
  expect(within(panel).getByText('While you were away, 1 thing was decided for you.')).toBeInTheDocument()
  await userEvent.click(within(panel).getByRole('button', { name: 'Open in Ready for you' }))
  const decided = await screen.findByRole('region', { name: /^Decided for you 1, 1 not seen/ })
  await vi.waitFor(() => expect(decided).toHaveFocus())
  // (at Not seen: the chat counted one that waits for your OK, whatever its age)
  expect(within(decided).getByRole('button', { name: 'Not seen' })).toHaveAttribute('aria-pressed', 'true')
  const unseen = (read.mock.calls as unknown as [string][]).map(([url]) => url)
  expect(unseen).toContain('/api/projects/p/decisions?unseen=true')
  expect(within(decided).getByText("KOLONİ's judge")).toHaveClass('who-judge')
  expect(within(decided).getByText('It sends .env away.').tagName).toBe('Q')
  expect(decided).toHaveTextContent('The judge let 2 commands run.')
  await userEvent.click(within(decided).getByRole('button', { name: 'OK' }))
  const calls = read.mock.calls as unknown as [string, RequestInit | undefined][]
  const asked = calls.map(([url, init]) => `${init?.method ?? 'GET'} ${url}`)
  expect(asked).toContain('POST /api/commands/k/seen')
  // (the open chat's: told at once - the pill has nothing more)
  await vi.waitFor(() => expect(screen.queryByRole('button', { name: '1 decided for you' })).toBeNull())
})

test("Usage's Today says the day's decisions in one line; Open in Ready for you brings its Decided for you in view, once", async () => {
  const { refused, log } = refusedByTheJudge()
  const pages = emptyPages({
    '/api/conversations/c': { ...snapshot, runs: [run('r', 'completed')], commands: [refused] },
    '/api/projects/p/decisions': log,
  })
  const day = { turns: 0, agents: [], changed_files: [], waiting: 0, failed: 0, conversations: [] }
  const read = vi.fn(async (url: string) =>
    url.startsWith('/api/projects/p/day') ? new Response(JSON.stringify(day), { status: 200 }) : pages(url),
  )
  vi.stubGlobal('fetch', read)
  render(<App />)
  await screen.findByRole('button', { name: '1 decided for you' })
  const rail = (name: string) => within(screen.getByRole('navigation', { name: 'Main' })).getByRole('button', { name })
  await userEvent.click(rail('Usage'))
  expect(await screen.findByText("1 decision was made for you today, 1 of them you haven't seen.")).toBeInTheDocument()
  // (Usage keeps no list of them any more)
  expect(screen.queryByRole('region', { name: /Decisions|Decided for you/ })).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Open in Ready for you' }))
  const decided = await screen.findByRole('region', { name: /^Decided for you/ })
  await vi.waitFor(() => expect(decided).toHaveFocus())
  // The ask was taken: Ready for you opened later, from the rail, is as any.
  await userEvent.click(rail('Canvas'))
  await userEvent.click(rail('Ready'))
  const again = await screen.findByRole('region', { name: /^Decided for you/ })
  await within(again).findByText("KOLONİ's judge")
  expect(again).not.toHaveFocus()
})

/** A night of project p that ended and is not seen yet. */
const endedNight = {
  id: 'a1',
  project_id: 'p',
  conversation_id: 'c',
  run_id: 'r',
  status: 'ended',
  jobs: [],
  kept_out: [],
  until: null,
  money: null,
  started_at: new Date(Date.now() - 6 * 3600 * 1000).toISOString(),
  ended_at: new Date(Date.now() - 3600 * 1000).toISOString(),
  why: null,
  seen_at: null,
  tried: [],
  slipped: [],
  spent: null,
  currency: 'USD',
  job_minutes: null,
  at_least: false,
  counts: {},
  proposed: [],
  decided: [],
}

test('after a night while you were away KOLONİ opens on Ready for you, where its strip is, and marks it seen', async () => {
  const read = vi.fn(async (url: string) =>
    url === '/api/projects/p/away' ? new Response(JSON.stringify(endedNight), { status: 200 }) : answer(url),
  )
  vi.stubGlobal('fetch', read)
  render(<App />)
  expect(await screen.findByRole('heading', { name: /^Ready for you/ })).toBeInTheDocument()
  expect(screen.getByRole('region', { name: /^Last night/ })).toBeInTheDocument()
  await vi.waitFor(() => expect(read.mock.calls.some(([url]) => url === '/api/away/a1/seen')).toBe(true))
})

test('a page you opened before the night was read is never taken from you: the morning leaves it (M1)', async () => {
  let release = () => {}
  const held = new Promise<void>(go => (release = go))
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url !== '/api/projects/p/away') return answer(url)
      await held
      return new Response(JSON.stringify(endedNight), { status: 200 })
    }),
  )
  render(<App />)
  const rail = (name: string) => within(screen.getByRole('navigation', { name: 'Main' })).getByRole('button', { name })
  await screen.findByText('this machine')
  await userEvent.click(rail('To-do'))
  release()
  await vi.waitFor(() => expect(useApp.getState().away?.id).toBe('a1'))
  await act(async () => {})
  expect(rail('To-do')).toHaveAttribute('aria-pressed', 'true')
  expect(screen.queryByRole('heading', { name: /^Ready for you/ })).toBeNull()
})

test("an agent's window and a discussion's open over the canvas only with a chat; selecting a node opens the inspector", async () => {
  render(<App />)
  await vi.waitFor(() => expect(useApp.getState().conv?.conversation.id).toBe('c'))
  const lead = agent('r', 'running', { name: 'Lead' })
  const talk: Discussion = {
    id: 'd',
    run_id: 'r',
    agent_id: 'r',
    tool_call_id: '9',
    topic: 'Which way?',
    max_rounds: 3,
    round: 1,
    status: 'running',
    outcome: null,
    created_at: '2026-10-05T10:00:00Z',
    ended_at: null,
    members: [{ agent_id: 'r', status: 'in', opened_here: false }],
  }
  act(() =>
    useApp.setState(s => ({
      conv: { ...s.conv!, runs: [run('r')], agents: [lead], discussions: [talk] },
      agentWindowId: 'r',
    })),
  )
  expect(await screen.findByRole('region', { name: 'Agent window' })).toBeInTheDocument()
  act(() => useApp.setState({ agentWindowId: null, discussionWindowId: 'd' }))
  expect(screen.queryByRole('region', { name: 'Agent window' })).toBeNull()
  expect(await screen.findByRole('region', { name: 'Discussion' })).toBeInTheDocument()
  act(() => useApp.getState().select('agent:r'))
  expect(await screen.findByRole('complementary', { name: 'Inspector' })).toBeInTheDocument()
  act(() => useApp.setState({ conv: null, agentWindowId: 'r' }))
  expect(screen.queryByRole('region', { name: 'Agent window' })).toBeNull()
  expect(screen.queryByRole('region', { name: 'Discussion' })).toBeNull()
  expect(screen.queryByRole('complementary', { name: 'Inspector' })).toBeNull()
})
