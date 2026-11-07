import { act, cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { App } from './App'
import { resetStoreForTests, useApp } from './state/store'
import { conversation, question, run } from './test-fixtures'

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
  has_notify_url: false,
  notify_format: 'slack',
  notify_desktop: false,
  turn_token_limit: null,
  max_agents: null,
  monthly_budget: null,
  check_command: null,
  git_commit: false,
  auto_notes: false,
  observe_reports: false,
  day_note_at: null,
  also_in: [], read_in: [],
  hide_secrets: true, lead_work: 'delegates', pass_env: null, held_env: [], koloni: { settings_kept: false, rules_kept: false, rules: null, broken: [], asks: {} },
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
  conversation, messages: [], runs: [], tool_calls: [], file_changes: [], commands: [], allowed_commands: [], agents: [],
  channel_messages: [], pending_roles: [], questions: [], discussions: [], discussion_posts: [], board_posts: [], last_event_id: 0,
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
    '/api/board': { backlog_waiting: 0, limit: null, running: 0, conversations: [], conflicts: [] },
    '/api/hold': { held: false, since: null, running: 0, triggers: 0, backlogs: [], nights: [], stopped: [], stopping: 0 },
    ...over,
  }
  return new Response(JSON.stringify(said[url.split('?')[0]] ?? []), { status: 200 })
}

beforeEach(() => {
  // React Flow watches its pane; jsdom has nothing to watch with.
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('EventSource', class { addEventListener() {} close() {} })
  vi.stubGlobal('fetch', vi.fn(async (url: string) => answer(url)))
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

test('with no folder and no chat KOLONİ opens on the canvas, not on a setup page: the folder button says "No folder", there is no gear, and the Board asks for a folder', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => answer(url, { '/api/projects': [], '/api/conversations': [] })))
  render(<App />)
  expect(await screen.findByLabelText('Message')).toBeInTheDocument()
  expect(screen.queryByText('Open a project')).toBeNull()
  // (Nothing here is about a project: the box says what a plain chat is.)
  expect(screen.getByLabelText('Message')).toHaveAttribute('placeholder', 'Ask anything - pick a folder with the folder button to work on files')
  expect(screen.getByRole('button', { name: 'Folder: No folder' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /^Project settings for/ })).toBeNull()
  // Nothing is made at the start: the first message makes a plain chat.
  expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
  await userEvent.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('button', { name: 'Board' }))
  expect(screen.getByText('This chat has no folder - pick one with the folder button to use the Board.')).toBeInTheDocument()
})

test('in a project whose conversations are all archived, none is opened, and the default model is the one a notice is about', async () => {
  const archived = { id: 'a', project_id: 'p', title: 'Put away', archived_at: '2026-10-17T08:00:00Z', kept: false, updated_at: 't', provider_id: null }
  const down = { ...health, model_reachable: false, provider_id: 'p-local', provider_name: 'Local', error: 'connection refused' }
  // (A new chat's Orchestrator would run on the default: it is in use.)
  const inUse = { '/api/providers': [{ id: 'p-local', name: 'Local', kind: 'openai_compat', default_model: 'qwen', models: [] }], '/api/roles': [{ name: 'Lead', builtin: true, enabled: true, teams: [] }], '/api/roles/models': [{ role: 'Lead', provider_name: 'Local', asks_how_hard: null }] }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => answer(url, { '/api/health': down, '/api/conversations': [archived], ...inUse })))
  render(<App />)
  // (First steps say it, with what to do: the top bar leaves it to them - and says it once they are hidden.)
  expect(await screen.findByText("Local isn't answering - add another provider, or start its model server.")).toBeInTheDocument()
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
  for (const [said, shown] of [[import.meta.env.VITE_API_HASH, false], ['000000000000', true], [null, true], [undefined, true]] as const) {
    resetStoreForTests()
    vi.stubGlobal('fetch', vi.fn(async (url: string) => answer(url, { '/api/health': { ...health, api_hash: said } })))
    const { unmount } = render(<App />)
    await screen.findByText('this machine')
    await vi.waitFor(() => expect(useApp.getState().health).not.toBeNull())
    if (shown) expect(await screen.findByText(updated)).toBeInTheDocument()
    else expect(screen.queryByText(updated)).toBeNull()
    unmount()
  }
})

test('a page the server has since built anew says so, with a Reload; one of the same build says nothing (K-yenile-uyarisi)', async () => {
  const mine = Object.assign(document.createElement('script'), { type: 'module', src: '/assets/index-old.js' })
  document.head.append(mine)
  const rebuilt = /^KOLONİ's page was rebuilt: reload to use it\.$/
  try {
    for (const [served, shown] of [['/assets/index-old.js', false], ['/assets/index-new.js', true]] as const) {
      resetStoreForTests()
      const page = `<!doctype html><html><head><script type="module" crossorigin src="${served}"></script></head></html>`
      vi.stubGlobal('fetch', vi.fn(async (url: string) => (url === '/' ? new Response(page, { status: 200 }) : answer(url))))
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
    conversation_id: id, title, merges_pending: 0, turn: null,
    agents: [{ id: `l-${id}`, name: 'Lead', status: 'waiting_approval', role: 'Lead', provider_name: null, model_id: null, holds: [], copy: null, waiting_for: null, sign: null, last_event_at: null, in_tool: false, changes_to_approve: 0, questions: 0 }],
  })
  // (Ready for you counts each chat's cards, read whole: one question in each.)
  const read = (id: string) => ({ ...snapshot, conversation: { ...conversation, id, project_id: 'p' }, runs: [run(`r${id}`, 'waiting_approval')], questions: [question(`q${id}`, `r${id}`)] })
  const everywhere = { backlog_waiting: 0, limit: null, running: 0, conflicts: [], conversations: [asking('x', 'Fix the login')] }
  const plain = { ...chat, project_id: null }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => answer(url, { '/api/conversations': [plain], '/api/conversations/c': { ...snapshot, conversation: plain }, '/api/board': everywhere, '/api/conversations/x': read('x'), '/api/conversations/y': read('y') })),
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
  vi.stubGlobal('fetch', vi.fn(async (url: string) => answer(url, { '/api/conversations/n': { ...snapshot, conversation: plain } })))
  render(<App />)
  await screen.findByText('this machine')
  await userEvent.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('button', { name: 'Settings' }))
  expect(screen.getByRole('form', { name: 'Project settings' })).toBeInTheDocument()
  await act(() => useApp.getState().openConversation('n'))
  expect(within(screen.getByRole('navigation', { name: 'Settings levels' })).getAllByRole('button').filter(b => b.classList.contains('settings-level')).map(b => b.textContent)).toEqual(['This chat', 'The app'])
  expect(screen.queryByRole('form', { name: 'Project settings' })).toBeNull()
  await act(() => useApp.getState().openConversation('c'))
  expect(screen.getByRole('form', { name: 'Project settings' })).toBeInTheDocument()
})

test("another chat opened is a step of the browser's history: Back opens the one before (B-150)", async () => {
  const job = { ...conversation, id: 'c2', title: 'A job of the night' }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => answer(url, { '/api/conversations/c2': { ...snapshot, conversation: job } })))
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
