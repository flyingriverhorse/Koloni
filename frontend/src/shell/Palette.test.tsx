import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { App } from '../App'
import { Palette } from './Palette'
import { resetStoreForTests } from '../state/store'
import { conversation, projectMemory, run } from '../test-fixtures'

// Ctrl+K and the first steps, in the app as it is put together (slice 38f-1).

const project = {
  id: 'p', name: 'demo', root_path: 'C:/demo', created_at: 't', exec_location: 'host', docker_image: null, docker_network: false,
  search_url: null, search_order: 'builtin', search_agy: false, has_notify_url: false, notify_format: 'slack', notify_desktop: false,
  turn_token_limit: null, max_agents: null, monthly_budget: null, check_command: null, git_commit: false, auto_notes: false, observe_reports: false, day_note_at: null, also_in: [], read_in: [],
  hide_secrets: true, lead_work: 'delegates', pass_env: null, held_env: [], koloni: { settings_kept: false, rules_kept: false, rules: null, broken: [], asks: {} },
}
const health = {
  desktop_available: true, docker_available: true, docker_error: null, error: null, model_base_url: 'http://127.0.0.1:8080/v1',
  model_id: 'qwen', model_reachable: true, not_listed: false, provider_name: 'Local', tools_supported: true,
  api_hash: import.meta.env.VITE_API_HASH, shell: 'PowerShell 7', shell_note: null,
}
const role = (id: string, name: string) => ({
  id, name, description: '', instructions: `${name}'s instructions`, tools: ['read_file'], builtin: false, created_by_agent: false, models: null,
  provider_id: null, model_id: null, tier: null, tier_min: null, tier_max: null, kind: 'build', enabled: true, teams: [], pick_from: null, max_steps: null, max_tokens: null, mcp: [], created_at: 't', updated_at: 't',
})
const listed = (id: string, title: string) => ({ ...conversation, id, title, kept: false, created_at: '2026-10-17T10:00:00Z', updated_at: '2026-10-17T10:00:00Z' })
const snapshot = (id: string, messages: unknown[] = []) => ({
  conversation: { ...conversation, id }, messages, runs: messages.length ? [run('r', 'completed')] : [], tool_calls: [], file_changes: [], commands: [], allowed_commands: [], agents: [],
  channel_messages: [], pending_roles: [], questions: [], discussions: [], discussion_posts: [], board_posts: [], last_event_id: 0,
})
const said = { id: 'm', conversation_id: 'c1', run_id: 'r', role: 'user', content: 'hello', status: 'completed', created_at: 't' }

let answers: Record<string, unknown>
let asked: string[]

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('EventSource', class { addEventListener() {} close() {} })
  answers = {
    '/api/projects': [project],
    '/api/health': health,
    '/api/roles': [role('r1', 'Reviewer'), role('r2', 'Documenter')],
    '/api/conversations': [listed('c1', 'Fix the login'), listed('c2', 'Tidy the docs')],
    '/api/conversations/c1': snapshot('c1', [said]),
    '/api/conversations/c2': snapshot('c2'),
    '/api/projects/p/memory': projectMemory(),
    '/api/record': { rows: [] },
    '/api/roles/activity': { last: {}, running: {} },
    '/api/recipes': { recipes: [], broken: [], writer: null },
    '/api/roles/r2/jobs': { jobs: [], days30: { jobs: 0, failed: 0, tokens: 0, unreported: 0 } },
    '/api/projects/p/board': { limit: null, running: 0, conversations: [], conflicts: [] },
    '/api/board': { backlog_waiting: 0, limit: null, running: 0, conversations: [], conflicts: [] },
    '/api/hold': { held: false, since: null, running: 0, triggers: 0, backlogs: [], nights: [], stopped: [], stopping: 0 },
    '/api/tiers': { strongest: [], balanced: [], fast: [] },
    '/api/projects/p/others-instructions': { paths: [], more: 0, partial: false },
  }
  asked = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      asked.push(url)
      const path = url.split('?')[0]
      if (init?.method === 'POST' && path === '/api/conversations') return new Response(JSON.stringify(listed('c3', 'New conversation')), { status: 200 })
      if (path === '/api/conversations/c3') return new Response(JSON.stringify(snapshot('c3')), { status: 200 })
      if (path === '/api/projects/p/memory/search') return new Response(JSON.stringify({ memory: [], turns: [] }), { status: 200 })
      return new Response(JSON.stringify(answers[path] ?? []), { status: 200 })
    }),
  )
  resetStoreForTests()
})
// (Unmounted first: React Flow's late effects still reach for the stubbed ResizeObserver.)
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const palette = () => screen.queryByRole('dialog', { name: 'Go to' })
const options = () => within(palette()!).getAllByRole('option').map(option => option.textContent)

test('Ctrl+K opens it from inside the message box; it finds by name as it is typed; Esc closes it and the focus is back in the box', async () => {
  render(<App />)
  const box = await screen.findByLabelText('Message')
  await waitFor(() => expect(asked).toContain('/api/conversations/c1'))
  await userEvent.click(box)
  await userEvent.keyboard('{Control>}k{/Control}')
  expect(palette()).toBeInTheDocument()
  const find = within(palette()!).getByRole('combobox', { name: 'Go to' })
  expect(find).toHaveFocus()
  // (nothing of it went into the message box)
  expect(box).toHaveValue('')
  await userEvent.type(find, 'doc') // (not 'do': the To-do page has it too)
  expect(options()).toEqual(['Tidy the docsConversation', 'DocumenterRole', 'Search in messages: “doc”Search'])
  // the first is the one Enter takes, and the arrows move it, round the ends
  const selected = () => within(palette()!).getByRole('option', { selected: true })
  expect(selected()).toHaveTextContent('Tidy the docs')
  expect(find).toHaveAttribute('aria-activedescendant', selected().id)
  await userEvent.keyboard('{ArrowUp}')
  expect(selected()).toHaveTextContent('Search in messages')
  await userEvent.keyboard('{ArrowDown}{ArrowDown}')
  expect(selected()).toHaveTextContent('Documenter')
  await userEvent.keyboard('{Escape}')
  expect(palette()).not.toBeInTheDocument()
  expect(box).toHaveFocus()
})

test('Enter goes there: a page, a role on its page, a conversation by its name', async () => {
  render(<App />)
  await screen.findByLabelText('Message')
  const pick = async (words: string) => {
    await userEvent.keyboard('{Control>}k{/Control}')
    await userEvent.type(within(palette()!).getByRole('combobox'), `${words}{Enter}`)
    expect(palette()).not.toBeInTheDocument()
  }
  await pick('triggers')
  expect(await screen.findByRole('heading', { name: 'Triggers' })).toBeInTheDocument()
  // the Conversations page by the rail's word for it, too
  await pick('chats')
  expect(await screen.findByRole('heading', { name: 'Conversations' })).toBeInTheDocument()
  // a role: the Agents page, open on it rather than on the first
  await pick('documenter')
  await userEvent.click(await screen.findByRole('tab', { name: 'Instructions' }))
  await userEvent.click(screen.getByRole('button', { name: 'Edit' }))
  expect(screen.getByRole('textbox', { name: 'Instructions' })).toHaveValue("Documenter's instructions")
  // a section of the project's settings
  await pick('memory and web')
  expect(screen.getByRole('form', { name: 'Project settings' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Web search' })).toBeInTheDocument()
  // a conversation, by its name: it is opened on the canvas
  await pick('tidy')
  await waitFor(() => expect(asked).toContain('/api/conversations/c2'))
  expect(screen.queryByRole('form', { name: 'Project settings' })).not.toBeInTheDocument()
  expect(await screen.findByLabelText('Message')).toBeInTheDocument()
})

test('a section picked while the settings are open is shown, and what is not saved in another stays', async () => {
  render(<App />)
  await screen.findByLabelText('Message')
  await userEvent.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('button', { name: 'Settings' }))
  await userEvent.click(within(screen.getByRole('form', { name: 'Project settings' })).getByRole('button', { name: /^Limits and money/ }))
  await userEvent.type(screen.getByLabelText('At most this many agents at work in this project'), '3')
  await userEvent.keyboard('{Control>}k{/Control}')
  await userEvent.type(within(palette()!).getByRole('combobox'), 'notifications{Enter}')
  expect(screen.getByRole('heading', { name: 'Notifications' })).toBeInTheDocument()
  await userEvent.click(within(screen.getByRole('form', { name: 'Project settings' })).getByRole('button', { name: /^Limits and money/ }))
  expect(screen.getByLabelText('At most this many agents at work in this project')).toHaveValue('3')
})

test('a section of the settings picked over a page picked before leaves that page as it was: what is written in it stays; ⚙ opens the settings on their first section again', async () => {
  render(<App />)
  await screen.findByLabelText('Message')
  const pick = async (words: string) => {
    await userEvent.keyboard('{Control>}k{/Control}')
    await userEvent.type(within(palette()!).getByRole('combobox'), `${words}{Enter}`)
  }
  await pick('documenter')
  await userEvent.click(await screen.findByRole('tab', { name: 'Instructions' }))
  await userEvent.click(screen.getByRole('button', { name: 'Edit' }))
  const instructions = screen.getByRole('textbox', { name: 'Instructions' })
  await userEvent.type(instructions, ' Not saved yet.')
  await pick('notifications')
  expect(screen.getByRole('heading', { name: 'Notifications' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Close settings' }))
  expect(screen.getByRole('textbox', { name: 'Instructions' })).toHaveValue("Documenter's instructions Not saved yet.")
  await userEvent.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('button', { name: 'Settings' }))
  expect(screen.getByRole('heading', { name: 'Agents' })).toBeInTheDocument()
})

test('“Search in messages” opens the memory’s search with the words, and searches them', async () => {
  render(<App />)
  await screen.findByLabelText('Message')
  await userEvent.keyboard('{Control>}k{/Control}')
  await userEvent.type(within(palette()!).getByRole('combobox'), 'port 8123')
  await userEvent.click(within(palette()!).getByRole('option', { name: /Search in messages/ }))
  const search = await screen.findByLabelText('Search everything this project remembers')
  expect(search).toHaveValue('port 8123')
  expect(search).toHaveFocus()
  await waitFor(() => expect(asked).toContain('/api/projects/p/memory/search?q=port%208123'))
})

test('the tool servers are read when it opens, and found', async () => {
  answers['/api/mcp-servers'] = [{ id: 's1', name: 'Files server', tools: [], read_at: null }]
  render(<App />)
  await screen.findByLabelText('Message')
  await userEvent.keyboard('{Control>}k{/Control}')
  await userEvent.type(within(palette()!).getByRole('combobox'), 'files')
  expect(await within(palette()!).findByRole('option', { name: /Files server/ })).toBeInTheDocument()
})

test('the first steps are one path - a provider, a folder, a message: the first not done is the current one, and all three done they are gone without a flag', async () => {
  answers['/api/projects'] = []
  answers['/api/conversations'] = []
  // (The provider made at the first start, "Local", with no model server behind it: that is not done.)
  answers['/api/health'] = { ...health, provider_id: 'pv', model_reachable: false, error: 'model server unreachable: refused' }
  // (What the add-a-provider form asks as it opens: nothing known.)
  answers['/api/providers/suggest'] = { models: [], service: null, api: null, env: [], addresses: [] }
  render(<App />)
  const steps = await screen.findByRole('region', { name: 'First steps' })
  const items = () => within(screen.getByRole('region', { name: 'First steps' })).getAllByRole('listitem')
  const current = () => items().findIndex(item => item.getAttribute('aria-current') === 'step')
  // (Only the current one has a button: it goes where the step is done.)
  expect(items().map(item => item.textContent)).toEqual([
    "To do: A provider: the model your agents run on.Add a providerLocal isn't answering - add another provider, or start its model server.",
    'To do: A folder: the project your agents work in.',
    'To do: Your first message: what you want done.',
  ])
  expect(current()).toBe(0)
  await userEvent.click(within(steps).getByRole('button', { name: 'Add a provider' }))
  expect(await screen.findByRole('dialog', { name: 'Add a provider' })).toBeInTheDocument()
  // a provider that answers: the folder is the next
  answers['/api/health'] = { ...health, provider_id: 'pv' }
  await act(() => import('../state/store').then(({ useApp }) => useApp.getState().loadHealth()))
  await userEvent.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('button', { name: 'Canvas' }))
  expect(items()[0]).toHaveTextContent('Done: A provider is set up.')
  expect(current()).toBe(1)
  await userEvent.click(within(screen.getByRole('region', { name: 'First steps' })).getByRole('button', { name: 'Choose a folder' }))
  expect(screen.getByRole('dialog', { name: 'This chat’s folders' })).toBeInTheDocument()
  await userEvent.keyboard('{Escape}')
  // a folder: the message is the next, and its button takes the focus to the message box
  answers['/api/projects'] = [project]
  await act(() => import('../state/store').then(({ useApp }) => useApp.getState().loadProjects()))
  expect(items()[1]).toHaveTextContent('Done: A project folder is added.')
  expect(current()).toBe(2)
  await userEvent.click(within(screen.getByRole('region', { name: 'First steps' })).getByRole('button', { name: 'Write your first message' }))
  expect(screen.getByLabelText('Message')).toHaveFocus()
  // a message written in any chat: gone - in a new, empty chat too, with the model down since, and nothing kept to say so
  answers['/api/health'] = { ...health, provider_id: 'pv', model_reachable: false, error: 'model server unreachable: refused' }
  await act(() => import('../state/store').then(({ useApp }) => useApp.getState().loadHealth()))
  answers['/api/conversations'] = [{ ...listed('c1', 'Fix the login'), wrote: true }]
  await act(() => import('../state/store').then(({ useApp }) => useApp.getState().loadProjects()))
  await act(() => import('../state/store').then(({ useApp }) => useApp.getState().newConversation()))
  await waitFor(() => expect(asked).toContain('/api/conversations/c3'))
  expect(screen.queryByRole('region', { name: 'First steps' })).not.toBeInTheDocument()
  expect(localStorage.getItem('koloni-first-steps')).toBeNull()
})

test('a conversation with a turn has no first steps over it, even with the model down: the banner says that', async () => {
  answers['/api/health'] = { ...health, model_reachable: false, error: 'model server unreachable: refused' }
  // (its Reviewer would run on it: it is in use)
  answers['/api/providers'] = [{ id: 'pv', name: 'Local', kind: 'openai_compat', default_model: 'qwen', models: [] }]
  answers['/api/roles/models'] = [{ role: 'Reviewer', provider_name: 'Local', asks_how_hard: null }]
  render(<App />)
  await waitFor(() => expect(asked).toContain('/api/conversations/c1'))
  expect(await screen.findByLabelText('Message')).toBeInTheDocument()
  await screen.findByText(/Local isn't answering/)
  expect(screen.queryByRole('region', { name: 'First steps' })).not.toBeInTheDocument()
  expect(localStorage.getItem('koloni-first-steps')).toBeNull()
})

test('Hide puts them away for good; Help shows them again', async () => {
  answers['/api/conversations'] = []
  const { unmount } = render(<App />)
  const steps = await screen.findByRole('region', { name: 'First steps' })
  await userEvent.click(within(steps).getByRole('button', { name: 'Hide the first steps' }))
  expect(screen.queryByRole('region', { name: 'First steps' })).not.toBeInTheDocument()
  unmount()
  resetStoreForTests()
  render(<App />)
  await screen.findByLabelText('Message')
  expect(screen.queryByRole('region', { name: 'First steps' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Help' }))
  await userEvent.click(within(screen.getByRole('dialog', { name: 'Help' })).getByRole('button', { name: 'Show the first steps' }))
  expect(await screen.findByRole('region', { name: 'First steps' })).toBeInTheDocument()
})

test('with no conversation, the Conversations page offers to start one', async () => {
  answers['/api/conversations'] = []
  render(<App />)
  await userEvent.click(await screen.findByRole('button', { name: 'Chats' }))
  expect(screen.getByText(/No conversations yet/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'New chat' }))
  await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith('/api/conversations', expect.objectContaining({ method: 'POST', body: JSON.stringify({ project_id: null }) })))
})

test('Esc is the palette’s while it is open: a panel under it that listens for Esc on the document does not hear it, wherever the focus went', async () => {
  const under = vi.fn()
  const onEsc = (event: KeyboardEvent) => {
    if (event.key !== 'Escape') return
    event.stopPropagation()
    under()
  }
  document.addEventListener('keydown', onEsc, true)
  try {
    render(
      <>
        <button type="button">opener</button>
        <button type="button">elsewhere</button>
        <Palette places={[{ kind: 'Page', name: 'Usage', go: () => {} }]} onOpen={() => {}} onSearch={() => {}} />
      </>,
    )
    screen.getByRole('button', { name: 'opener' }).focus()
    await userEvent.keyboard('{Control>}k{/Control}')
    // (something under it took the focus, as a node's panel does)
    screen.getByRole('button', { name: 'elsewhere' }).focus()
    await userEvent.keyboard('{Escape}')
    expect(palette()).not.toBeInTheDocument()
    expect(under).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'opener' })).toHaveFocus()
    // closed, Esc is theirs again
    await userEvent.keyboard('{Escape}')
    expect(under).toHaveBeenCalledTimes(1)
  } finally {
    document.removeEventListener('keydown', onEsc, true)
  }
})

test('with Help open, Esc closes the palette over it and leaves Help open', async () => {
  render(<App />)
  await screen.findByLabelText('Message')
  await userEvent.click(screen.getByRole('button', { name: 'Help' }))
  await userEvent.keyboard('{Control>}k{/Control}')
  await userEvent.keyboard('{Escape}')
  expect(palette()).not.toBeInTheDocument()
  expect(screen.getByRole('dialog', { name: 'Help' })).toBeInTheDocument()
})

test('a name is found without its accents or case: “ilk” finds “İlk deneme”, “cagri” finds “Çağrı”', async () => {
  render(<Palette places={[{ kind: 'Conversation', name: 'İlk deneme', go: () => {} }, { kind: 'Role', name: 'Çağrı', go: () => {} }]} onOpen={() => {}} onSearch={() => {}} />)
  await userEvent.keyboard('{Control>}k{/Control}')
  await userEvent.type(within(palette()!).getByRole('combobox'), 'ilk')
  expect(options()[0]).toBe('İlk denemeConversation')
  await userEvent.clear(within(palette()!).getByRole('combobox'))
  await userEvent.type(within(palette()!).getByRole('combobox'), 'cagri')
  expect(options()[0]).toBe('ÇağrıRole')
})

test('gone to another page by Enter, the focus is on that page, not lost', async () => {
  render(<App />)
  const box = await screen.findByLabelText('Message')
  await userEvent.click(box)
  await userEvent.keyboard('{Control>}k{/Control}')
  await userEvent.type(within(palette()!).getByRole('combobox'), 'triggers{Enter}')
  await screen.findByRole('heading', { name: 'Triggers' })
  await waitFor(() => expect(document.querySelector('.main')).toHaveFocus())
})
