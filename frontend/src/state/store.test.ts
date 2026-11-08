import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { conversation } from '../test-fixtures'
import { resetStoreForTests, useApp } from './store'

/** A stand-in for the browser's EventSource that tests can drive by hand. */
class FakeEventSource {
  static all: FakeEventSource[] = []
  closed = false
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  listeners = new Map<string, (event: MessageEvent<string>) => void>()
  url: string

  constructor(url: string) {
    this.url = url
    FakeEventSource.all.push(this)
  }
  addEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
    this.listeners.set(type, listener)
  }
  close() {
    this.closed = true
  }
  emit(type: string, data: unknown, id = '') {
    this.listeners.get(type)?.({ data: JSON.stringify(data), lastEventId: id } as MessageEvent<string>)
  }
  static open() {
    return FakeEventSource.all.filter(source => !source.closed)
  }
}

const snapshot = (id: string) => ({
  conversation: { ...conversation, id },
  messages: [
    { id: 'm', conversation_id: id, run_id: 'r', role: 'assistant', content: '', status: 'streaming', created_at: 't' },
  ],
  runs: [],
  tool_calls: [],
  file_changes: [],
  board_posts: [],
  last_event_id: 3,
})

let failing = false
let pending: (() => void)[] = []
let holdResponses = false

beforeEach(() => {
  vi.useFakeTimers()
  FakeEventSource.all = []
  failing = false
  holdResponses = false
  pending = []
  vi.stubGlobal('EventSource', FakeEventSource)
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      // (The list, read again for a chat opened that it does not have yet: its tab, slice 86d.)
      if (url.endsWith('/conversations')) return new Response('[]', { status: 200 })
      if (holdResponses) await new Promise<void>(resolve => pending.push(resolve))
      if (failing) throw new TypeError('Failed to fetch')
      // (And the folders, for a chat's folder the page does not know yet.)
      if (url.endsWith('/projects')) return new Response('[]', { status: 200 })
      const id = /conversations\/([^/]+)$/.exec(url)?.[1] ?? 'c'
      return new Response(JSON.stringify(snapshot(id)), { status: 200 })
    }),
  )
  resetStoreForTests()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

test('opening a conversation twice in a row leaves exactly one live stream', async () => {
  holdResponses = true
  const first = useApp.getState().openConversation('a')
  const second = useApp.getState().openConversation('a')
  pending.forEach(resolve => resolve())
  await Promise.all([first, second])
  expect(FakeEventSource.open()).toHaveLength(1)

  FakeEventSource.open()[0].emit('message.delta', { message_id: 'm', text: 'Hi' })
  expect(useApp.getState().conv?.messages[0].content).toBe('Hi')
})

test('switching conversations mid-load shows the one asked for last', async () => {
  holdResponses = true
  const first = useApp.getState().openConversation('a')
  const second = useApp.getState().openConversation('b')
  pending.reverse().forEach(resolve => resolve())
  await Promise.all([first, second])
  expect(useApp.getState().conv?.conversation.id).toBe('b')
  expect(FakeEventSource.open().map(s => s.url)).toEqual(['/api/conversations/b/events?after=3'])
})

test('the conversation clicked last is the one that opens, though the open one’s stream reconnects meanwhile', async () => {
  await useApp.getState().openConversation('a')
  holdResponses = true
  const toB = useApp.getState().openConversation('b')
  // The stream of the conversation still on screen breaks, and its retry comes due while b is read.
  FakeEventSource.open()[0].onerror?.()
  await vi.advanceTimersByTimeAsync(1000)
  expect(pending).toHaveLength(1) // the retry asked for nothing: it would have taken b's place
  // ...and a second click, on c, before b has come.
  const toC = useApp.getState().openConversation('c')
  await vi.advanceTimersByTimeAsync(1000)
  pending.forEach(resolve => resolve())
  await Promise.all([toB, toC])
  expect(useApp.getState().conv?.conversation.id).toBe('c')
  expect(FakeEventSource.open().map(s => s.url)).toEqual(['/api/conversations/c/events?after=3'])
  // The retry of the conversation that was left went with it.
  holdResponses = false
  await vi.advanceTimersByTimeAsync(20000)
  expect(useApp.getState().conv?.conversation.id).toBe('c')
  expect(FakeEventSource.open()).toHaveLength(1)
})

test('a conversation that cannot be opened while the open one reconnects leaves that one to be retried', async () => {
  await useApp.getState().openConversation('a')
  holdResponses = true
  const gone = useApp.getState().openConversation('gone')
  FakeEventSource.open()[0].onerror?.()
  await vi.advanceTimersByTimeAsync(1000) // put off: 'gone' is being opened
  failing = true
  pending.forEach(resolve => resolve())
  holdResponses = false
  await expect(gone).rejects.toThrow('Failed to fetch')
  failing = false
  await vi.advanceTimersByTimeAsync(1000) // the retry of a, now that nothing else is being opened
  expect(useApp.getState().conv?.conversation.id).toBe('a')
  expect(FakeEventSource.open()).toHaveLength(1)
  expect(FakeEventSource.open()[0]).not.toBe(FakeEventSource.all[0])
})

// Chats a and a2 are in folder p, b has none, c is in q (slice 86e: a tab per project).
const folders: Record<string, string | null> = { a: 'p', a2: 'p', b: null, c: 'q' }
const inFolders = (ids: string[]) => ids.map(id => ({ ...conversation, id, project_id: folders[id], kept: false, backlog_task: null, wrote: false }))
function readsFolders() {
  const read = vi.mocked(fetch).getMockImplementation()!
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    const id = /conversations\/([^/]+)$/.exec(String(url))?.[1]
    if (!id || !(id in folders)) return read(url, init)
    const opened = snapshot(id)
    return new Response(JSON.stringify({ ...opened, conversation: { ...opened.conversation, project_id: folders[id] } }), { status: 200 })
  })
}

test('each chat opened gets its project\'s tab, remembered in the browser; one that cannot be opened gets none; closing the open one opens its neighbour\'s chat', async () => {
  localStorage.clear()
  readsFolders()
  useApp.setState({ conversations: inFolders(['a', 'a2', 'b', 'c']) })
  for (const id of ['a', 'b', 'c', 'a2']) await useApp.getState().openConversation(id)
  expect(useApp.getState().tabs).toEqual(['p', 'none', 'q'])
  expect(JSON.parse(localStorage.getItem('koloni-open-chats')!)).toEqual(['p', 'none', 'q'])
  failing = true
  await expect(useApp.getState().openConversation('gone')).rejects.toThrow('Failed to fetch')
  failing = false
  expect(useApp.getState().tabs).toEqual(['p', 'none', 'q'])

  // A tab opens the chat opened last in its project.
  await useApp.getState().openTab('none')
  expect(useApp.getState().conv?.conversation.id).toBe('b')
  await useApp.getState().openTab('p')
  expect(useApp.getState().conv?.conversation.id).toBe('a2')
  // Another's tab closed: what is open stays.
  await useApp.getState().closeTab('none')
  expect(useApp.getState().tabs).toEqual(['p', 'q'])
  expect(useApp.getState().conv?.conversation.id).toBe('a2')
  // The open one's: its neighbour's chat opens.
  await useApp.getState().closeTab('p')
  expect(useApp.getState().tabs).toEqual(['q'])
  expect(useApp.getState().conv?.conversation.id).toBe('c')
  expect(JSON.parse(localStorage.getItem('koloni-open-chats')!)).toEqual(['q'])
  localStorage.clear()
})

test('86d\'s remembered tabs, a chat\'s id each, become their folders\' tabs once a chat opens', async () => {
  localStorage.clear()
  readsFolders()
  useApp.setState({ conversations: inFolders(['a', 'a2', 'b', 'c']), tabs: ['c', 'a', 'a2', 'deleted since'] })
  await useApp.getState().openConversation('b')
  expect(useApp.getState().tabs).toEqual(['q', 'p', 'none'])
  localStorage.clear()
})

test('a tab with no chat of its project opens a new one there', async () => {
  localStorage.clear()
  readsFolders()
  useApp.setState({ conversations: inFolders(['a']) })
  const read = vi.mocked(fetch).getMockImplementation()!
  const made: unknown[] = []
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    if (init?.method !== 'POST' || !String(url).endsWith('/conversations')) return read(url, init)
    made.push(JSON.parse(String(init.body)))
    return new Response(JSON.stringify({ ...conversation, id: 'c' }), { status: 201 })
  })
  await useApp.getState().openTab('q')
  await useApp.getState().openTab('none')
  expect(made).toEqual([{ project_id: 'q' }, { project_id: null }])
  localStorage.clear()
})

test('switching the main folder of a chat that has a turn opens a new chat there; an empty chat moves, its tab with it', async () => {
  localStorage.clear()
  readsFolders()
  useApp.setState({ conversations: inFolders(['a', 'b']) })
  const read = vi.mocked(fetch).getMockImplementation()!
  const asked: string[] = []
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    const method = init?.method ?? 'GET'
    if (method === 'GET') return read(url, init)
    asked.push(`${method} ${url} ${String(init?.body)}`)
    if (method === 'POST') return new Response(JSON.stringify({ ...conversation, id: 'c' }), { status: 201 })
    return new Response(JSON.stringify({ ...conversation, id: 'b', project_id: 'q' }), { status: 200 })
  })
  // b: a plain chat, with no turn yet - its "No folder" tab, alone there, becomes q's.
  await useApp.getState().openConversation('a')
  await useApp.getState().openConversation('b')
  expect(useApp.getState().tabs).toEqual(['p', 'none'])
  await useApp.getState().setFolder('q')
  expect(asked).toEqual([`PATCH /api/conversations/b ${JSON.stringify({ project_id: 'q' })}`])
  expect(useApp.getState().tabs).toEqual(['p', 'q'])
  expect(useApp.getState().conv?.conversation.project_id).toBe('q')

  // a has a turn: it stays in p; a new chat opens in q.
  await useApp.getState().openConversation('a')
  useApp.setState(s => ({ conv: s.conv && { ...s.conv, runs: [{ id: 'r' } as never] } }))
  asked.length = 0
  await useApp.getState().setFolder('q')
  expect(asked).toEqual([`POST /api/conversations ${JSON.stringify({ project_id: 'q' })}`])
  expect(useApp.getState().conv?.conversation.id).toBe('c')
  localStorage.clear()
})

test('a chat deleted for good gives way to the next chat of its tab', async () => {
  localStorage.clear()
  readsFolders()
  useApp.setState({ conversations: inFolders(['a', 'a2']) })
  for (const id of ['a', 'a2']) await useApp.getState().openConversation(id)
  const read = vi.mocked(fetch).getMockImplementation()!
  const parts: number[] = []
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    if (String(url).endsWith('/conversations') && init?.method === 'GET') return new Response(JSON.stringify(inFolders(['a'])), { status: 200 })
    if (!String(url).endsWith('/conversations/delete')) return read(url, init)
    const { ids } = JSON.parse(String(init?.body)) as { ids: string[] }
    parts.push(ids.length)
    return new Response(JSON.stringify({ deleted: ids.filter(id => id === 'a2'), refused: [] }), { status: 200 })
  })
  // More than the server takes at once: sent in parts of that.
  const many = ['a2', ...Array.from({ length: 500 }, (_, n) => `x${n}`)]
  expect(await useApp.getState().deleteConversations(many)).toEqual({ deleted: ['a2'], refused: [] })
  expect(parts).toEqual([500, 1])
  expect(useApp.getState().tabs).toEqual(['p'])
  expect(useApp.getState().conv?.conversation.id).toBe('a')
  localStorage.clear()
})

test('a project deleted: it and its tab go, and its open chat gives way to the first tab left - even where the list cannot be read again', async () => {
  localStorage.clear()
  readsFolders()
  useApp.setState({ conversations: inFolders(['a', 'a2', 'b', 'c']), projects: [{ id: 'p' }, { id: 'q' }] as never })
  for (const id of ['b', 'c', 'a']) await useApp.getState().openConversation(id)
  const read = vi.mocked(fetch).getMockImplementation()!
  const deleted: string[] = []
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    if (init?.method === 'DELETE') {
      deleted.push(String(url))
      return new Response(null, { status: 204 })
    }
    if (String(url).endsWith('/conversations') && init?.method === 'GET') return new Response('{"detail": "busy"}', { status: 503 })
    return read(url, init)
  })
  await expect(useApp.getState().deleteProject('p')).rejects.toThrow()
  expect(deleted).toEqual(['/api/projects/p'])
  expect(useApp.getState().conversations.map(c => c.id)).toEqual(['b', 'c'])
  expect(useApp.getState().projects.map(p => p.id)).toEqual(['q'])
  expect(useApp.getState().tabs).toEqual(['none', 'q'])
  expect(useApp.getState().conv?.conversation.id).toBe('b')
  localStorage.clear()
})

test('a lost connection is retried until the server is back', async () => {
  await useApp.getState().openConversation('a')
  failing = true
  FakeEventSource.open()[0].onerror?.()
  expect(useApp.getState().connection).toBe('reconnecting')

  await vi.advanceTimersByTimeAsync(1000) // first retry fails
  await vi.advanceTimersByTimeAsync(2000) // second retry fails
  expect(FakeEventSource.open()).toHaveLength(0)
  expect(useApp.getState().connection).toBe('reconnecting')

  failing = false
  await vi.advanceTimersByTimeAsync(4000)
  expect(FakeEventSource.open()).toHaveLength(1)
  FakeEventSource.open()[0].onopen?.()
  expect(useApp.getState().connection).toBe('open')
})

test('a failed first load is reported instead of leaving a blank page', async () => {
  failing = true
  await useApp.getState().loadProjects()
  expect(useApp.getState().ready).toBe(false)
  expect(useApp.getState().loadError).toContain('Failed to fetch')
})

test('the Changes window opens when a run stops to ask about a file change, not for direct edits', async () => {
  await useApp.getState().openConversation('a')
  const source = FakeEventSource.open()[0]
  const change = { id: 'f1', run_id: 'r', tool_call_id: 't', path: 'a.py', kind: 'modify', diff: '', additions: 1, deletions: 0, created_at: 't', decided_at: null }
  const waiting = { id: 'r', conversation_id: 'a', status: 'waiting_approval' }

  // An edit the agent may write directly is recorded and applied without a pause.
  source.emit('file_change.created', { ...change, status: 'proposed' }, '4')
  source.emit('file_change.updated', { ...change, status: 'applied' }, '5')
  expect(useApp.getState().filesOpen).toBe(false)

  // A run that waits for a command decision has no change to show.
  source.emit('run.updated', waiting, '6')
  expect(useApp.getState().filesOpen).toBe(false)

  // A run that waits on a proposed change brings that change up.
  source.emit('file_change.created', { ...change, id: 'f2', status: 'proposed' }, '7')
  source.emit('run.updated', waiting, '8')
  expect(useApp.getState().filesOpen).toBe(true)
  expect(useApp.getState().filesAt.key).toBe('a.py')
})

test('B-127: See the changes of a file new in a copy shows its diff, not the project file it is not yet', async () => {
  await useApp.getState().openConversation('a')
  const source = FakeEventSource.open()[0]
  const change = { id: 'f1', run_id: 'r', tool_call_id: 't', path: 'config/app.yaml', kind: 'create', diff: '+a: 1', additions: 1, deletions: 0, created_at: 't', decided_at: null }
  source.emit('file_change.created', { ...change, status: 'in_copy' }, '4')
  useApp.getState().openChange('f1')
  expect(useApp.getState().filesOpen).toBe(false)
  expect(useApp.getState().selectedNodeId).toBe('file:f1')
  source.emit('file_change.updated', { ...change, status: 'applied' }, '5')
  useApp.getState().openChange('f1')
  expect(useApp.getState().filesAt.key).toBe('config/app.yaml')
})

test('choosing a permission level before any conversation exists starts one and applies it', async () => {
  const calls: [string, string, string?][] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push([init?.method ?? 'GET', url, init?.body as string | undefined])
      if (init?.method === 'POST') return new Response(JSON.stringify({ ...conversation, id: 'c9' }), { status: 201 })
      if (/\/api\/conversations$/.test(url)) return new Response('[]', { status: 200 })
      return new Response(JSON.stringify({ ...snapshot('c9'), messages: [] }), { status: 200 })
    }),
  )
  useApp.setState({ projectId: 'p', conv: null })
  await useApp.getState().setPermissionMode('full_auto')
  // (In the folder of the chat that was open; slice 86a.)
  const made = calls.findIndex(([method, url, body]) => method === 'POST' && url === '/api/conversations' && body === '{"project_id":"p"}')
  const patched = calls.findIndex(([method, url]) => method === 'PATCH' && url.endsWith('/conversations/c9'))
  expect(made).toBeGreaterThanOrEqual(0)
  expect(patched).toBeGreaterThan(made)
  expect(JSON.parse(calls[patched][2] ?? '{}')).toEqual({ permission_mode: 'full_auto' })
})

test('a new chat is made in the open chat’s folder, or the one asked for, or none; a first message with no chat makes a plain one', async () => {
  const posted: (string | undefined)[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST' && url === '/api/conversations') posted.push(init.body as string)
      if (init?.method === 'POST') return new Response(JSON.stringify({ ...conversation, id: 'c9' }), { status: 201 })
      if (url === '/api/conversations') return new Response('[]', { status: 200 })
      return new Response(JSON.stringify({ ...snapshot('c9'), conversation: { ...conversation, id: 'c9', project_id: null } }), { status: 200 })
    }),
  )
  useApp.setState({ projectId: 'p' })
  await useApp.getState().newConversation()
  await useApp.getState().newConversation('q')
  await useApp.getState().newConversation(null)
  useApp.setState({ conv: null })
  await useApp.getState().send('hello')
  expect(posted).toEqual(['{"project_id":"p"}', '{"project_id":"q"}', '{"project_id":null}', '{"project_id":null}'])
})

test('the store follows the open chat’s folder: another folder’s board, budget, memory, backlog and triggers go, and its triggers are read', async () => {
  const asked: string[] = []
  const of = (id: string, project_id: string | null) => ({ ...snapshot(id), conversation: { ...conversation, id, project_id } })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      asked.push(url)
      const id = /conversations\/([^/]+)$/.exec(url)?.[1]
      if (id) return new Response(JSON.stringify(of(id, id === 'plain' ? null : id.startsWith('inq') ? 'q' : 'p')), { status: 200 })
      return new Response(url.endsWith('/projects') ? '[{"id":"p"},{"id":"q"}]' : '[]', { status: 200 })
    }),
  )
  await useApp.getState().openConversation('inp')
  expect(useApp.getState().projectId).toBe('p')
  const old = { backlog_waiting: 0, limit: 1, running: 1, conversations: [], conflicts: [] }
  useApp.setState({ projects: [{ id: 'p' }, { id: 'q' }] as never, board: old, budget: {} as never, memory: {} as never, backlog: [], triggers: [] })
  asked.length = 0
  await useApp.getState().openConversation('inq')
  const now = useApp.getState()
  expect([now.projectId, now.budget, now.memory, now.backlog]).toEqual(['q', null, null, null])
  expect(now.board).not.toBe(old)
  expect(asked).toContain('/api/projects/q/triggers')
  expect(asked).toContain('/api/projects/q/board')
  // A chat of the same folder keeps what was read of it.
  useApp.setState({ budget: {} as never })
  await useApp.getState().openConversation('inq2')
  expect(useApp.getState().budget).not.toBeNull()
  // A plain chat has no folder: nothing of one is read.
  asked.length = 0
  await useApp.getState().openConversation('plain')
  expect([useApp.getState().projectId, useApp.getState().board, useApp.getState().triggers]).toEqual([null, null, null])
  expect(asked.filter(url => url.includes('/projects/'))).toEqual([])
})

test('the chat’s folder is changed by the server: the chat and the folder followed are as it answers; a refusal leaves them, and says why', async () => {
  const sent: string[] = []
  let refuse = false
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'PATCH') {
        sent.push(String(init.body))
        if (refuse) return new Response(JSON.stringify({ detail: 'this chat changed files in p; open a new chat for q' }), { status: 409 })
        return new Response(JSON.stringify({ ...conversation, id: 'a', project_id: JSON.parse(String(init.body)).project_id }), { status: 200 })
      }
      if (url === '/api/conversations' || url.endsWith('/projects')) return new Response('[]', { status: 200 })
      return new Response(JSON.stringify(snapshot('a')), { status: 200 })
    }),
  )
  await useApp.getState().openConversation('a')
  await useApp.getState().setFolder('q')
  expect([useApp.getState().projectId, useApp.getState().conv?.conversation.project_id]).toEqual(['q', 'q'])
  await useApp.getState().setFolder(null)
  expect([useApp.getState().projectId, useApp.getState().conv?.conversation.project_id]).toEqual([null, null])
  refuse = true
  await expect(useApp.getState().setFolder('p')).rejects.toThrow('this chat changed files in p; open a new chat for q')
  expect(useApp.getState().projectId).toBeNull()
  expect(sent).toEqual(['{"project_id":"q"}', '{"project_id":null}', '{"project_id":"p"}'])
})

test('a project setting saved without the Commands section keeps the Docker image; the Commands section can still take it away', async () => {
  const bodies: unknown[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init?: RequestInit) => {
      bodies.push(JSON.parse(init?.body as string))
      return new Response(JSON.stringify({ id: 'p' }), { status: 200 })
    }),
  )
  useApp.setState({ projectId: 'p', projects: [] })
  await useApp.getState().saveProjectSettings({ notify_desktop: true })
  await useApp.getState().saveProjectSettings({ exec_location: 'host', docker_image: null, docker_network: false })
  expect(bodies).toEqual([{ notify_desktop: true }, { exec_location: 'host', docker_image: '', docker_network: false }])
})

test('Take in all that is refused part way still reads the night again: what was taken before is shown', async () => {
  const asked: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      asked.push(url)
      if (url.endsWith('/m2/approve')) return new Response(JSON.stringify({ detail: 'a.txt changed since you looked' }), { status: 409 })
      return new Response(url.endsWith('/away') ? 'null' : '{}', { status: 200 })
    }),
  )
  useApp.setState({ projectId: 'p' })
  await expect(useApp.getState().takeIn(['m1', 'm2', 'm3'])).rejects.toThrow('a.txt changed since you looked')
  expect(asked).toEqual(['/api/merges/m1/approve', '/api/merges/m2/approve', '/api/projects/p/away'])
})

test('an agent that starts on a native provider opens its own window', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({ ...snapshot('c'), messages: [], agents: [], channel_messages: [], pending_roles: [], questions: [], commands: [], allowed_commands: [] }),
          { status: 200 },
        ),
    ),
  )
  await useApp.getState().openConversation('c')
  useApp.setState({
    providers: [
      { id: 'p1', name: 'Local', kind: 'openai_compat', base_url: 'http://x/v1', default_model: null, executable: null, mode: null, options: null, for_agents: false, note: null, models: [], only_listed: false, max_running: null, plan: false, step_down_at: null, day_limit: null, month_limit: null, has_key: false, position: 0, created_at: 't', updated_at: 't' },
      { id: 'p2', name: 'Codex', kind: 'codex_cli', base_url: null, default_model: null, executable: null, mode: 'native', options: null, for_agents: false, note: null, models: [], only_listed: false, max_running: null, plan: false, step_down_at: null, day_limit: null, month_limit: null, has_key: false, position: 1, created_at: 't', updated_at: 't' },
    ],
  })
  const source = FakeEventSource.open()[0]
  const started = (id: string, provider_name: string) => ({ id, run_id: 'r', parent_agent_id: null, tool_call_id: null, provider_name, model_id: null, role_name: 'Lead', tools: [], task: null, depth: 0, status: 'running', report: null, error: null, input_tokens: null, output_tokens: null, created_at: 't', started_at: 't', ended_at: null })
  source.emit('agent.created', started('a1', 'Local'), '4')
  expect(useApp.getState().agentWindowId).toBeNull()
  source.emit('agent.created', started('a2', 'Codex'), '5')
  expect(useApp.getState().agentWindowId).toBe('a2')
  useApp.getState().closeAgentWindow()
  expect(useApp.getState().agentWindowId).toBeNull()
  useApp.getState().openAgentWindow('a1')
  expect(useApp.getState().agentWindowId).toBe('a1')
})

test('a note written on the shared notebook reaches the open conversation', async () => {
  await useApp.getState().openConversation('a')
  const source = FakeEventSource.open()[0]
  const written = { id: 'n1', run_id: 'r', agent_id: null, content: 'Leave the tests alone.', seq: 1, created_at: 't', read_by: [] }
  source.emit('board.posted', written, '4')
  expect(useApp.getState().conv?.boardPosts).toEqual([written])
})

test('the memory is read when asked for, and again when it changes - not before it was looked at', async () => {
  const asked: string[] = []
  let core: unknown[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      asked.push(`${init?.method ?? 'GET'} ${url}`)
      if (url.endsWith('/memory')) return new Response(JSON.stringify({ core, proposals: [], journal: [], past: [] }), { status: 200 })
      if (url.endsWith('/approve')) return new Response(JSON.stringify({ detail: 'source changed since it was noted: check again' }), { status: 409 })
      return new Response(JSON.stringify(snapshot('a')), { status: 200 })
    }),
  )
  useApp.setState({ projectId: 'p' })
  await useApp.getState().openConversation('a')
  const source = FakeEventSource.open()[0]
  // nobody has looked at the memory: a change to it is not fetched
  source.emit('memory.changed', { project_id: 'p' })
  expect(asked.filter(a => a.endsWith('/memory'))).toEqual([])
  expect(useApp.getState().memory).toBeNull()

  await useApp.getState().loadMemory()
  expect(useApp.getState().memory?.core).toEqual([])
  // from this conversation it comes with an id, from another without: both are heard
  core = [{ id: 'f1' }]
  source.emit('memory.changed', { project_id: 'p' }, '9')
  await vi.waitFor(() => expect(useApp.getState().memory?.core).toEqual([{ id: 'f1' }]))
  core = [{ id: 'f1' }, { id: 'f2' }]
  source.emit('memory.changed', { project_id: 'p' }, '9')
  await vi.waitFor(() => expect(useApp.getState().memory?.core).toHaveLength(2))

  // a refused decision throws the server's reason and changes nothing
  await expect(useApp.getState().approveMemory('n1')).rejects.toMatchObject({ status: 409, detail: 'source changed since it was noted: check again' })
  expect(useApp.getState().memory?.core).toHaveLength(2)
})

// --- the turn the canvas draws (slice 18a) ---------------------------------------------------

const started = (id: string, status: string, over: object = {}) => ({
  id, conversation_id: 'a', status, error: null, model_id: null, input_tokens: null, output_tokens: null,
  created_at: 't', started_at: status === 'queued' ? null : 't', ended_at: null, unattended: false, trigger_id: null, trigger_name: null, ...over,
})

test('a turn the user picked stays picked when a trigger starts a turn, and gives way when a turn of the user’s starts', async () => {
  await useApp.getState().openConversation('a')
  const source = FakeEventSource.open()[0]
  source.emit('run.started', started('r1', 'running'), '4')
  source.emit('run.finished', started('r1', 'completed'), '5')
  useApp.getState().showTurn('r1')

  // a trigger's turn: on record, and the canvas stays where the user is looking
  source.emit('run.started', started('n1', 'running', { unattended: true, trigger_id: 't', trigger_name: 'Nightly' }), '6')
  expect(useApp.getState().conv?.runs.map(r => r.id)).toEqual(['r1', 'n1'])
  expect(useApp.getState().turnId).toBe('r1')
  source.emit('run.finished', started('n1', 'completed', { unattended: true }), '7')
  expect(useApp.getState().turnId).toBe('r1')

  // a message of the user's that only joins the queue changes nothing yet
  source.emit('run.started', started('r2', 'queued'), '8')
  expect(useApp.getState().turnId).toBe('r1')
  // its turn starts: the canvas goes to it
  source.emit('run.updated', started('r2', 'running'), '9')
  expect(useApp.getState().turnId).toBeNull()

  // news of a turn already at work is not a new turn
  useApp.getState().showTurn('r1')
  source.emit('run.updated', started('r2', 'waiting_approval'), '10')
  source.emit('run.finished', started('r2', 'completed'), '11')
  expect(useApp.getState().turnId).toBe('r1')
  // a turn started while nothing was at work is drawn at once
  source.emit('run.started', started('r3', 'running'), '12')
  expect(useApp.getState().turnId).toBeNull()
})

test('a turn of another conversation is drawn by opening that conversation first; another conversation forgets the pick', async () => {
  await useApp.getState().openConversation('a')
  useApp.getState().showTurn('r1')
  await useApp.getState().openTurn('b', 'r9')
  expect(useApp.getState().conv?.conversation.id).toBe('b')
  expect(useApp.getState().turnId).toBe('r9')
  // within the conversation that is open nothing is read again
  const asked = vi.mocked(fetch).mock.calls.length
  await useApp.getState().openTurn('b', 'r8')
  expect(vi.mocked(fetch).mock.calls).toHaveLength(asked)
  expect(useApp.getState().turnId).toBe('r8')
  await useApp.getState().openConversation('a')
  expect(useApp.getState().turnId).toBeNull()
})

// --- triggers (slice 18a) ----------------------------------------------------------------------

test('a trigger in a chat made since the list was read reads the list again: it is not gone (B-353)', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.endsWith('/triggers/paused')) return new Response(JSON.stringify({ paused: false }), { status: 200 })
      if (url.endsWith('/triggers/changes')) return new Response('[]', { status: 200 })
      if (url.endsWith('/triggers')) return new Response(JSON.stringify([{ id: 't1', conversation_id: 'made' }]), { status: 200 })
      if (url.endsWith('/conversations')) return new Response(JSON.stringify([{ ...conversation, id: 'made' }]), { status: 200 })
      throw new Error(`unexpected ${url}`)
    }),
  )
  useApp.setState({ projectId: 'p', conversations: [] })
  await useApp.getState().loadTriggers()
  await vi.waitFor(() => expect(useApp.getState().conversations.map(c => c.id)).toEqual(['made']))
})

test('the triggers are read with whether they are paused, read again when the server says they changed, and a request from the chat is kept until taken', async () => {
  const asked: string[] = []
  let kept: { id: string }[] = [{ id: 't1' }]
  let paused = false
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      asked.push(`${init?.method ?? 'GET'} ${url}`)
      if (url.endsWith('/triggers/paused')) {
        if (init?.method === 'PUT') paused = JSON.parse(String(init.body)).paused
        return new Response(JSON.stringify({ paused }), { status: 200 })
      }
      if (url.endsWith('/run')) return new Response(JSON.stringify({ run_id: 'r9' }), { status: 202 })
      if (url.endsWith('/triggers') && init?.method === 'POST') return new Response(JSON.stringify({ id: 't2', key: 'secret' }), { status: 201 })
      if (url.endsWith('/triggers')) return new Response(JSON.stringify(kept), { status: 200 })
      if (url.endsWith('/triggers/changes')) return new Response(JSON.stringify(kept.map(t => ({ id: `made-${t.id}`, what: 'created' }))), { status: 200 })
      if (url.endsWith('/allowed-commands')) return new Response(JSON.stringify({ id: 'r2', prefix: 'make test' }), { status: 201 })
      return new Response(JSON.stringify({ ...snapshot('a'), allowed_commands: [{ id: 'r1', prefix: 'pytest' }] }), { status: 200 })
    }),
  )
  useApp.setState({ projectId: 'p' })
  expect(useApp.getState().triggers).toBeNull()
  await useApp.getState().loadTriggers()
  expect(useApp.getState().triggers).toEqual([{ id: 't1' }])
  expect(useApp.getState().triggersPaused).toBe(false)
  // with what was made and changed on them: the project's record, read at the same time
  expect(asked).toContain('GET /api/projects/p/triggers/changes')
  expect(useApp.getState().triggerChanges).toEqual([{ id: 'made-t1', what: 'created' }])

  // a trigger came due, or was changed elsewhere: the server says so on the conversation's stream
  await useApp.getState().openConversation('a')
  kept = [{ id: 't1' }, { id: 't3' }]
  FakeEventSource.open()[0].emit('triggers.changed', { project_id: 'p' })
  await vi.waitFor(() => expect(useApp.getState().triggers).toHaveLength(2))
  expect(useApp.getState().triggerChanges).toHaveLength(2)

  // made: the answer - with a webhook's key, said this once - is handed on, and kept nowhere in the store
  const created = await useApp.getState().createTrigger({ name: 'T' } as never)
  expect(created).toMatchObject({ id: 't2', key: 'secret' })
  expect(JSON.stringify(useApp.getState())).not.toContain('secret')
  expect(await useApp.getState().runTrigger('t1')).toBe('r9')
  expect(asked).toContain('POST /api/triggers/t1/run')

  await useApp.getState().pauseTriggers(true)
  expect(asked).toContain('PUT /api/triggers/paused')
  expect(useApp.getState().triggersPaused).toBe(true)

  // a conversation's allow list: the open one's is at hand, another's is read; a command is added to the one named
  expect(await useApp.getState().allowedCommandsOf('a')).toEqual([{ id: 'r1', prefix: 'pytest' }])
  const before = asked.length
  expect(await useApp.getState().allowedCommandsOf('b')).toEqual([{ id: 'r1', prefix: 'pytest' }])
  expect(asked.slice(before)).toEqual(['GET /api/conversations/b'])
  expect(await useApp.getState().addAllowedCommand('b', 'make test')).toEqual({ id: 'r2', prefix: 'make test' })
  expect(asked).toContain('POST /api/conversations/b/allowed-commands')

  useApp.getState().allowInTrigger('t1', { write: true })
  expect(useApp.getState().triggerDraft).toEqual({ triggerId: 't1', allow: { write: true } })
  useApp.getState().clearTriggerDraft()
  expect(useApp.getState().triggerDraft).toBeNull()
})

// --- topics (slice 18b) ------------------------------------------------------------------------

test('a message is sent to the topic it is said to go to, or as a new one; a topic’s new name is put down as the server answers it', async () => {
  const sent: [string, string, unknown][] = []
  const topic = { id: 't1', conversation_id: 'a', title: 'Fix the greeting', trigger_id: null, created_at: 't' }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method && init.method !== 'GET') sent.push([init.method, url, JSON.parse(String(init.body ?? '{}'))])
      if (init?.method === 'PATCH') return new Response(JSON.stringify({ ...topic, title: 'The greeting' }), { status: 200 })
      if (init?.method === 'POST') return new Response('{}', { status: 201 })
      if (url.endsWith('/conversations')) return new Response('[]', { status: 200 })
      return new Response(JSON.stringify({ ...snapshot('a'), topics: [topic] }), { status: 200 })
    }),
  )
  await useApp.getState().openConversation('a')
  expect(useApp.getState().conv?.topics).toEqual([topic])
  await useApp.getState().send('go on', { topic_id: 't1' })
  await useApp.getState().send('something else', { new_topic: true })
  await useApp.getState().send('hello')
  expect(sent).toEqual([
    ['POST', '/api/conversations/a/messages', { content: 'go on', topic_id: 't1' }],
    ['POST', '/api/conversations/a/messages', { content: 'something else', new_topic: true }],
    ['POST', '/api/conversations/a/messages', { content: 'hello' }],
  ])
  await useApp.getState().renameTopic('t1', 'The greeting')
  expect(sent.at(-1)).toEqual(['PATCH', '/api/topics/t1', { title: 'The greeting' }])
  expect(useApp.getState().conv?.topics[0].title).toBe('The greeting')
})

// --- the board (slice 26) ----------------------------------------------------------------------

test('a conversation that cannot be opened leaves the open one open, with its events, and the caller is told', async () => {
  await useApp.getState().openConversation('a')
  failing = true
  await expect(useApp.getState().openConversation('gone')).rejects.toThrow('Failed to fetch')
  expect(useApp.getState().conv?.conversation.id).toBe('a')
  expect(FakeEventSource.open().map(s => s.url)).toEqual(['/api/conversations/a/events?after=3'])
})

test('the board shown is the answer to the read asked for last, of the project that is open', async () => {
  const board = (running: number) => ({ limit: null, running, conversations: [], conflicts: [] })
  const asked: { answer: (running: number) => void; fail: () => void }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) =>
      // (Every chat's board, read with it, is answered at once: these are the folder's.)
      url === '/api/board'
        ? Promise.resolve(new Response(JSON.stringify(board(0)), { status: 200 }))
        : new Promise<Response>((resolve, reject) =>
            asked.push({
              answer: running => resolve(new Response(JSON.stringify(board(running)), { status: 200 })),
              fail: () => reject(new TypeError('Failed to fetch')),
            }),
          ),
    ),
  )
  useApp.setState({ projectId: 'p' })
  const reads = [useApp.getState().loadBoard(), useApp.getState().loadBoard()]
  // The later read's answer comes first; the earlier one's, late, is not put over it.
  asked[1].answer(2)
  asked[0].answer(1)
  await Promise.all(reads)
  expect(useApp.getState().board?.running).toBe(2)

  // Nor is a late failure of an earlier read said over a later answer...
  const again = [useApp.getState().loadBoard(), useApp.getState().loadBoard()]
  asked[3].answer(3)
  asked[2].fail()
  await Promise.all(again)
  expect([useApp.getState().board?.running, useApp.getState().boardError]).toEqual([3, null])

  // ...and neither an answer nor a failure of a project that was left is this one's.
  const left = [useApp.getState().loadBoard()]
  useApp.setState({ projectId: 'q', board: null })
  asked[4].fail()
  await Promise.all(left)
  expect([useApp.getState().board, useApp.getState().boardError]).toEqual([null, null])
  useApp.setState({ projectId: 'p' })
  const failed = useApp.getState().loadBoard()
  asked[5].fail()
  await failed
  expect(useApp.getState().boardError).toContain('Failed to fetch')
})

test('a board read again that says the same keeps the board it had: nothing that reads it is drawn again', async () => {
  const said = { limit: null, running: 1, conversations: [], conflicts: [] }
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(said), { status: 200 })))
  useApp.setState({ projectId: 'p' })
  await useApp.getState().loadBoard()
  const first = useApp.getState().board
  await useApp.getState().loadBoard()
  expect(useApp.getState().board).toBe(first)
  said.running = 2
  await useApp.getState().loadBoard()
  expect(useApp.getState().board).not.toBe(first)
})

test('KOLONİ opens on the newest chat not archived, of any folder or of none, and its folder is the one open; with every one archived, on none, and nothing is made', async () => {
  const listed = (id: string, archived: boolean, project_id: string | null = 'p') => ({ ...conversation, id, project_id, archived_at: archived ? '2026-10-17T08:00:00Z' : null, kept: false, backlog_task: null })
  for (const [list, opened, folder] of [
    [[listed('a', true), listed('b', false, 'q'), listed('d', false)], 'b', 'q'],
    [[listed('e', false, null), listed('b', false, 'q')], 'e', null],
    [[listed('a', true), listed('c', true)], undefined, null],
  ] as const) {
    resetStoreForTests()
    const asked: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        asked.push(`${init?.method ?? 'GET'} ${url}`)
        if (url.endsWith('/projects')) return new Response(JSON.stringify([{ id: 'p' }, { id: 'q' }]), { status: 200 })
        if (url === '/api/conversations') return new Response(JSON.stringify(list), { status: 200 })
        const id = /conversations\/([^/?]+)$/.exec(url)?.[1]
        const one = list.find(c => c.id === id)
        return new Response(one ? JSON.stringify({ ...snapshot(one.id), conversation: one }) : '[]', { status: 200 })
      }),
    )
    await useApp.getState().loadProjects()
    expect([useApp.getState().conv?.conversation.id, useApp.getState().projectId]).toEqual([opened, folder])
    expect(asked).not.toContain('GET /api/conversations/a')
    expect(asked.filter(call => call.startsWith('POST'))).toEqual([])
  }
})

test('the page is ready only once the newest chat is open: a message typed before would be kept for a new chat and lost', async () => {
  let open = () => {}
  const held = new Promise<void>(go => (open = go))
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.endsWith('/projects')) return new Response('[]', { status: 200 })
      if (url === '/api/conversations') return new Response(JSON.stringify([{ ...conversation, id: 'a', archived_at: null, kept: false, backlog_task: null }]), { status: 200 })
      if (url === '/api/conversations/a') await held
      return new Response(JSON.stringify(url === '/api/conversations/a' ? snapshot('a') : []), { status: 200 })
    }),
  )
  const loading = useApp.getState().loadProjects()
  await vi.waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith('/api/conversations/a', expect.anything()))
  expect(useApp.getState().ready).toBe(false)
  open()
  await loading
  expect([useApp.getState().ready, useApp.getState().conv?.conversation.id]).toEqual([true, 'a'])
})

test('what waits anywhere is read with the board, of every folder and of none: in a plain chat too, where there is no folder’s board', async () => {
  const asked: string[] = []
  const everywhere = { backlog_waiting: 2, limit: null, running: 0, conversations: [], conflicts: [] }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      asked.push(url)
      return new Response(JSON.stringify(url === '/api/board' ? everywhere : { ...everywhere, backlog_waiting: 0 }), { status: 200 })
    }),
  )
  useApp.setState({ projectId: 'p' })
  await useApp.getState().loadBoard()
  expect(asked.sort()).toEqual(['/api/board', '/api/projects/p/board'])
  expect([useApp.getState().everywhere?.backlog_waiting, useApp.getState().board?.backlog_waiting]).toEqual([2, 0])
  asked.length = 0
  useApp.setState({ projectId: null, board: null })
  await useApp.getState().loadBoard()
  expect(asked).toEqual(['/api/board'])
  expect(useApp.getState().board).toBeNull()
})

test('a folder change the server answers after another chat was opened leaves that chat and its folder alone', async () => {
  let answer: (() => void) | null = null
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'PATCH') {
        await new Promise<void>(resolve => (answer = resolve))
        return new Response(JSON.stringify({ ...conversation, id: 'a', project_id: 'q' }), { status: 200 })
      }
      if (url === '/api/conversations' || url === '/api/projects') return new Response('[]', { status: 200 })
      const id = /conversations\/([^/]+)$/.exec(url)?.[1] ?? 'c'
      return new Response(JSON.stringify(snapshot(id)), { status: 200 })
    }),
  )
  await useApp.getState().openConversation('a')
  const moving = useApp.getState().setFolder('q')
  await vi.waitFor(() => expect(answer).not.toBeNull())
  await useApp.getState().openConversation('b')
  answer!()
  await moving
  expect([useApp.getState().conv?.conversation.id, useApp.getState().projectId]).toEqual(['b', 'p'])
})

test('the own commands are the open folder’s and every folder’s, or in a plain chat every folder’s; a late answer of a folder left is not shown', async () => {
  const answers: Record<string, (body: unknown) => void> = {}
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => new Promise<Response>(resolve => (answers[url] = body => resolve(new Response(JSON.stringify(body), { status: 200 }))))),
  )
  useApp.setState({ projectId: 'p' })
  const ofP = useApp.getState().loadOwnCommands()
  useApp.setState({ projectId: null })
  const plain = useApp.getState().loadOwnCommands()
  answers['/api/own-commands']([{ id: 'everywhere' }])
  await plain
  answers['/api/own-commands?project_id=p']([{ id: 'of p' }])
  await ofP
  expect(useApp.getState().ownCommands).toEqual([{ id: 'everywhere' }])
})

test("health is asked of the open conversation's provider; a late reading of another is not kept (K-model-seridi)", async () => {
  const answers: Record<string, (body: unknown) => void> = {}
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) =>
      // (The top bar's roles and providers: none here.)
      url.startsWith('/api/health')
        ? new Promise<Response>(resolve => (answers[url] = body => resolve(new Response(JSON.stringify(body), { status: 200 }))))
        : Promise.resolve(new Response('[]', { status: 200 })),
    ),
  )
  const on = (provider_id: string | null) => useApp.setState({ conv: { conversation: { ...conversation, provider_id } } as never })
  on('p-claude')
  const claude = useApp.getState().loadHealth()
  on(null)
  const plain = useApp.getState().loadHealth()
  answers['/api/health']({ provider_id: 'p-local' })
  await plain
  answers['/api/health?provider_id=p-claude']({ provider_id: 'p-claude' })
  await claude
  expect(useApp.getState().health).toEqual({ provider_id: 'p-local' })
  expect(useApp.getState().inUse).toEqual({ of: conversation.id, readings: [], cannot: [] })
})

test("the top bar's readings are of the providers the chat's roles would run on: the default, used by none, is not asked (sample A)", async () => {
  const rows = [
    { role: 'Lead', provider_name: 'Copilot', asks_how_hard: null },
    { role: 'Coder', provider_name: 'Claude Code', asks_how_hard: null },
  ]
  const roles = [
    { name: 'Lead', builtin: true, enabled: true, teams: [] },
    { name: 'Coder', builtin: false, enabled: true, teams: [] },
  ]
  const providers = [{ id: 'p-local', name: 'Local' }, { id: 'p-copilot', name: 'Copilot' }, { id: 'p-claude', name: 'Claude Code' }]
  const said: Record<string, unknown> = { '/api/roles': roles, '/api/teams': [], '/api/categories': [], '/api/providers': providers, [`/api/roles/models?conversation_id=${conversation.id}`]: rows }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const id = new URL(url, 'http://x').searchParams.get('provider_id')
      const body = url.startsWith('/api/health') ? { provider_id: id ?? 'p-local', model_reachable: id !== 'p-copilot' } : said[url]
      return new Response(JSON.stringify(body), { status: 200 })
    }),
  )
  useApp.setState({ conv: { conversation: { ...conversation, provider_id: null } } as never })
  await useApp.getState().loadHealth()
  const asked = vi.mocked(fetch).mock.calls.map(([url]) => String(url))
  expect(asked.filter(url => url.startsWith('/api/health'))).toEqual(['/api/health', '/api/health?provider_id=p-copilot', '/api/health?provider_id=p-claude'])
  expect(useApp.getState().inUse).toEqual({
    of: conversation.id,
    readings: [
      { provider_id: 'p-copilot', model_reachable: false },
      { provider_id: 'p-claude', model_reachable: true },
    ],
    cannot: [],
  })
})

test("a provider's reading that fails keeps its last one; an older loadHealth answered late does not put its readings over a newer one's", async () => {
  const rows = [{ role: 'Lead', provider_name: 'Copilot', asks_how_hard: null, cannot_run: null }]
  const said: Record<string, unknown> = {
    '/api/roles': [{ name: 'Lead', builtin: true, enabled: true, teams: [] }],
    '/api/teams': [],
    '/api/categories': [],
    '/api/providers': [{ id: 'p-local', name: 'Local' }, { id: 'p-copilot', name: 'Copilot' }],
    [`/api/roles/models?conversation_id=${conversation.id}`]: rows,
  }
  let copilot: (() => Promise<Response>) | null = null
  const held: (() => void)[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/health?provider_id=p-copilot' && copilot) return copilot()
      const body = url.startsWith('/api/health') ? { provider_id: url.includes('p-copilot') ? 'p-copilot' : 'p-local', model_reachable: false } : said[url]
      return new Response(JSON.stringify(body), { status: 200 })
    }),
  )
  useApp.setState({ conv: { conversation: { ...conversation, provider_id: null } } as never })
  await useApp.getState().loadHealth()
  const first = { of: conversation.id, readings: [{ provider_id: 'p-copilot', model_reachable: false }], cannot: [] }
  expect(useApp.getState().inUse).toEqual(first)
  // one glitch: the last reading stands
  copilot = async () => new Response('', { status: 502 })
  await useApp.getState().loadHealth()
  expect(useApp.getState().inUse).toEqual(first)
  // an older run held, a newer one answered meanwhile: the older's is not kept
  copilot = () => new Promise(resolve => held.push(() => resolve(new Response(JSON.stringify({ provider_id: 'p-copilot', model_reachable: true }), { status: 200 }))))
  const older = useApp.getState().loadHealth()
  await vi.waitFor(() => expect(held).toHaveLength(1))
  copilot = null
  await useApp.getState().loadHealth()
  held[0]()
  await older
  expect(useApp.getState().inUse).toEqual(first)
})

test('a room that opens opens its window; one that opens while another is open comes as a tab; another chat starts with none', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.endsWith('/conversations') || url.endsWith('/projects')) return new Response('[]', { status: 200 })
      const id = /conversations\/([^/]+)$/.exec(url)?.[1] ?? 'c'
      return new Response(JSON.stringify({ ...snapshot(id), messages: [], rooms: [] }), { status: 200 })
    }),
  )
  await useApp.getState().openConversation('c')
  const source = FakeEventSource.open()[0]
  const room = (id: string) => ({ id, run_id: 'r', goal: 'g', agent_id: null, status: 'sharing', outcome: null, why: null, budget: { posts: null, tokens: null, minutes: null }, spent: { posts: 0, tokens: null, minutes: 0 }, summary: null, members: [], created_at: 't', ended_at: null })
  source.emit('room.created', room('o1'), '4')
  expect(useApp.getState().roomWindows).toEqual({ o1: 'open' })
  // (the user may be writing in that one: it is not made small under them)
  source.emit('room.created', room('o2'), '5')
  expect(useApp.getState().roomWindows).toEqual({ o1: 'open', o2: 'small' })
  useApp.getState().showRoom('o2')
  expect(useApp.getState().roomWindows).toEqual({ o1: 'small', o2: 'open' })
  await useApp.getState().openConversation('d')
  expect(useApp.getState().roomWindows).toEqual({})
})

test('Run the backlog waits for its choice being saved: a model name is saved as its field is left, by that click', async () => {
  useApp.setState({ projectId: 'p' })
  const read = vi.mocked(fetch).getMockImplementation()!
  let saved = () => {}
  const order: string[] = []
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    const path = String(url)
    if (path.endsWith('/backlog/choice')) {
      await new Promise<void>(resolve => (saved = resolve))
      order.push('choice')
      return new Response(JSON.stringify({ on: false, halt: null, permission_mode: 'ask', provider_id: 'x', model_id: 'm' }), { status: 200 })
    }
    if (path.endsWith('/backlog/next')) order.push('next')
    return read(url, init)
  })
  const choosing = useApp.getState().setBacklogChoice({ permission_mode: 'ask', provider_id: 'x', model_id: 'm' })
  const running = useApp.getState().runBacklog().catch(() => {})
  await vi.advanceTimersByTimeAsync(0)
  expect(order).toEqual([])
  saved()
  await choosing
  await running
  expect(order).toEqual(['choice', 'next'])
})

test('a slow read of the conversations list does not overwrite a later one', async () => {
  const answers: ((list: unknown[]) => void)[] = []
  vi.mocked(fetch).mockImplementation(
    () => new Promise<Response>(done => answers.push(list => done(new Response(JSON.stringify(list), { status: 200 })))),
  )
  const first = useApp.getState().loadConversations()
  const second = useApp.getState().loadConversations()
  answers[1]([{ ...conversation, id: 'new' }])
  await second
  answers[0]([{ ...conversation, id: 'old' }])
  await first
  expect(useApp.getState().conversations.map(c => c.id)).toEqual(['new'])
})

test('the first load does not overwrite the conversations list read after it asked', async () => {
  const read = vi.mocked(fetch).getMockImplementation()!
  const held = new Map<string, ((body: unknown) => void)[]>()
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    const path = String(url)
    if (!path.endsWith('/conversations') && !path.endsWith('/projects')) return read(url, init)
    const body = await new Promise(done => held.set(path, [...(held.get(path) ?? []), done]))
    return new Response(JSON.stringify(body), { status: 200 })
  })
  const loading = useApp.getState().loadProjects()
  const later = useApp.getState().loadConversations()
  await vi.waitFor(() => expect(held.get('/api/conversations')).toHaveLength(2))
  held.get('/api/conversations')![1]([{ ...conversation, id: 'new' }])
  await later
  held.get('/api/conversations')![0]([{ ...conversation, id: 'old' }])
  held.get('/api/projects')![0]([])
  await loading
  expect(useApp.getState().conversations.map(c => c.id)).toEqual(['new'])
})
