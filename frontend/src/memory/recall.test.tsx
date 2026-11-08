import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, onTestFinished, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { Project, Provider } from '../api/types'
import { useApp } from '../state/store'
import { conversation, convState, memoryRecord, projectMemory, run } from '../test-fixtures'
import { MemoryPage } from './MemoryPage'
import { lastAutoText, leftHow, moment, whoWhen } from './memoryText'

const handlers = () => ({
  onApprove: vi.fn().mockResolvedValue(undefined),
  onReject: vi.fn().mockResolvedValue(undefined),
  onRestore: vi.fn().mockResolvedValue(undefined),
  onConfirm: vi.fn().mockResolvedValue(undefined),
  onCorrect: vi.fn().mockResolvedValue(undefined),
  onWrite: vi.fn().mockResolvedValue(undefined),
  onSaveRules: vi.fn().mockResolvedValue(undefined),
  onSavePreferences: vi.fn().mockResolvedValue(undefined),
  onAddPreference: vi.fn().mockResolvedValue(undefined),
  onReload: vi.fn().mockResolvedValue(undefined),
})

const auto = memoryRecord('a1', {
  origin: 'auto',
  agent_id: null,
  agent_name: null,
  noted_by: { provider_name: 'Fast', model_id: 'quick' },
  text: 'hello.py prints the greeting at start.',
  about: 'start',
})

const BOX = 'Search everything this project remembers'
const search = () => screen.getByRole('region', { name: 'Search' })
async function notes() {
  await userEvent.click(screen.getByRole('tab', { name: /^Notes/ }))
  return screen.getByRole('tabpanel', { name: /^Notes/ })
}

test('a note made by itself is signed as the summariser’s, with the model that made it', async () => {
  expect(whoWhen(auto)).toMatch(/^noted by KOLONİ’s summariser \(Fast · quick\) from what was said on a message · /)
  expect(whoWhen({ ...auto, noted_by: null })).toMatch(/summariser \(not on record\)/)
  expect(whoWhen(memoryRecord('n'))).toMatch(/^noted by Lead · /)
  expect(leftHow({ ...auto, status: 'superseded', decided_by: 'auto', decided_at: null })).toBe(
    'replaced by a newer note of KOLONİ’s summariser',
  )
  render(<MemoryPage memory={projectMemory({ journal: [auto] })} {...handlers()} />)
  expect(within(await notes()).getByRole('article')).toHaveTextContent('noted by KOLONİ’s summariser (Fast · quick)')
})

test('the journal says how noting by itself went after the last turn, of which turn, and why nothing was noted', async () => {
  expect(lastAutoText(null, 'x')).toBeNull()
  expect(lastAutoText({ run_id: 'r', noted: 2, skipped: 1, note: null }, 'T')).toBe('After the last work noted by itself (T): 2 noted, 1 skipped.')
  expect(lastAutoText({ run_id: 'r', noted: 1, skipped: 0, note: null }, 'T')).toBe('After the last work noted by itself (T): 1 noted.')
  const why = 'the request to the summariser failed: nothing was noted'
  const memory = projectMemory({ last_auto: { run_id: 'r2', noted: 0, skipped: 0, note: why } })
  const { unmount } = render(<MemoryPage memory={memory} {...handlers()} />)
  expect(await notes()).toHaveTextContent(`After the last work noted by itself (a message of a conversation not open here) nothing was noted: ${why}.`)
  unmount()
  // a turn of the open conversation is named by when it was and the conversation's title
  useApp.setState({ conv: convState({ runs: [run('r1', 'completed'), run('r2', 'completed', { created_at: '2026-10-13T10:00:00Z' })] }) })
  render(<MemoryPage memory={memory} {...handlers()} />)
  const said = (await notes()).textContent ?? ''
  expect(said).toContain(`(the work on the ${moment('2026-10-13T10:00:00Z')} message in “${conversation.title}”)`)
  useApp.setState({ conv: null })
})

test('a newer search is never overwritten by an older one’s answer, and the answer is announced', async () => {
  let first: (value: unknown) => void = () => {}
  const onSearch = vi
    .fn()
    .mockImplementationOnce(() => new Promise(resolve => (first = resolve)))
    .mockResolvedValueOnce({ memory: [], turns: [] })
  render(<MemoryPage memory={projectMemory()} {...handlers()} onSearch={onSearch} />)
  const box = screen.getByLabelText(BOX)
  await userEvent.type(box, 'older')
  fireEvent.submit(box.closest('form') as HTMLFormElement)
  await userEvent.clear(box)
  await userEvent.type(box, 'newer')
  fireEvent.submit(box.closest('form') as HTMLFormElement)
  expect(await within(search()).findByText('Nothing on record speaks to “newer”.')).toBeInTheDocument()
  first({ memory: [auto], turns: [] })
  await new Promise(resolve => setTimeout(resolve, 20))
  expect(within(search()).queryByText('hello.py prints the greeting at start.')).toBeNull()
  expect(within(search()).getByText('Nothing on record speaks to “newer”.').closest('[aria-live]')).toHaveAttribute('aria-live', 'polite')
})

test('Enter searches deeper, as an agent’s recall does: the memory, and what earlier messages said, each in its own group', async () => {
  const onSearch = vi.fn().mockResolvedValue({
    memory: [{ ...auto, by_meaning: true }],
    turns: [
      {
        who: 'You',
        conversation_id: 'c1',
        conversation_title: 'The greeting',
        run_id: 'r1',
        at: '2026-10-13T10:00:00Z',
        excerpt: 'How is the greeting spelled?',
        kind: 'turn',
        trigger: false,
      },
      { who: 'Coder', conversation_id: 'c1', conversation_title: 'The greeting', run_id: 'r1', at: '2026-10-13T10:01:00Z', excerpt: 'It is in notes.md.', kind: 'turn', trigger: false },
    ],
  })
  render(<MemoryPage memory={projectMemory()} {...handlers()} onSearch={onSearch} />)
  // what it looks in, behind its "?"
  expect(search()).toHaveTextContent('never what a tool returned')
  expect(within(search()).getByRole('button', { name: 'Search deeper' })).toBeDisabled()
  expect(screen.getByRole('search')).toBeInTheDocument()
  await userEvent.type(screen.getByLabelText(BOX), '  greeting  {Enter}')
  expect(onSearch).toHaveBeenCalledWith('greeting')
  const memory = await within(search()).findByRole('list', { name: 'What an agent would find in the memory' })
  // found by meaning: the words on the page would not have found it
  expect(memory).toHaveTextContent('by meaning')
  expect(memory).toHaveTextContent('hello.py prints the greeting at start.')
  const said = within(within(search()).getByRole('list', { name: 'In earlier messages' })).getAllByRole('listitem')
  expect(said[0]).toHaveTextContent('“How is the greeting spelled?”')
  expect(said[0]).toHaveTextContent('You · The greeting ·')
  expect(said[1]).toHaveTextContent('Coder · The greeting ·')
  // nothing from a linked project: no such group
  expect(within(search()).queryByRole('list', { name: 'In linked projects' })).toBeNull()
})

test('without a deeper search, the box still sifts the page, and Enter does nothing', async () => {
  render(<MemoryPage memory={projectMemory({ journal: [auto] })} {...handlers()} />)
  expect(screen.queryByRole('button', { name: 'Search deeper' })).toBeNull()
  await userEvent.type(screen.getByLabelText(BOX), 'greeting{Enter}')
  expect(within(search()).getByRole('status')).toHaveTextContent('1 on this page has “greeting”.')
  expect(within(search()).getByRole('status')).not.toHaveTextContent('Enter searches deeper')
})

test('a closed backlog task and a trigger’s turn are said as what they are, with no empty part (B-329)', async () => {
  const onSearch = vi.fn().mockResolvedValue({
    memory: [],
    turns: [
      { who: 'You', conversation_id: null, conversation_title: '', run_id: 'task:t1', at: null, excerpt: 'Fix the ledger — it closed at midnight', kind: 'task', trigger: false },
      { who: 'Lead', conversation_id: 'c2', conversation_title: 'spin', run_id: 'r2', at: '2026-10-13T10:01:00Z', excerpt: 'The nightly build is green.', kind: 'turn', trigger: true },
    ],
  })
  render(<MemoryPage memory={projectMemory()} {...handlers()} onSearch={onSearch} />)
  await userEvent.type(screen.getByLabelText(BOX), 'ledger{Enter}')
  const said = within(await within(search()).findByRole('list', { name: 'In earlier messages' })).getAllByRole('listitem')
  expect(said[0]).toHaveTextContent('a backlog task closed by you · a day not on record')
  expect(said[0]).not.toHaveTextContent('· ·')
  expect(said[1]).toHaveTextContent(`Lead · spin · ${moment('2026-10-13T10:01:00Z')} · in a trigger’s turn`)
  // the box emptied, what was found deeper goes with it
  await userEvent.clear(screen.getByLabelText(BOX))
  expect(within(search()).queryByRole('list', { name: 'In earlier messages' })).toBeNull()
})

test('a search that finds nothing says so for each part, and one that fails says why', async () => {
  const onSearch = vi
    .fn()
    .mockResolvedValueOnce({ memory: [], turns: [] })
    .mockRejectedValueOnce(new ApiError(500, 'the database is locked'))
  render(<MemoryPage memory={projectMemory()} {...handlers()} onSearch={onSearch} />)
  await userEvent.type(screen.getByLabelText(BOX), 'zebra{Enter}')
  expect(await within(search()).findByText('Nothing on record speaks to “zebra”.')).toBeInTheDocument()
  expect(within(search()).getByText('Nothing said in earlier messages speaks to “zebra”.')).toBeInTheDocument()
  await userEvent.click(within(search()).getByRole('button', { name: 'Search deeper' }))
  expect(await within(search()).findByRole('alert')).toHaveTextContent('the database is locked')
})

test('come from Ctrl+K, the search box is scrolled into sight, has the focus and searches the words deeper; opened on its own, nothing is scrolled', async () => {
  const scrolled = vi.fn()
  // (jsdom lays nothing out and has no scrollIntoView: this one only says it was asked for.)
  Element.prototype.scrollIntoView = scrolled
  onTestFinished(() => {
    delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView
  })
  const onSearch = vi.fn().mockResolvedValue({ memory: [], turns: [] })
  const { unmount } = render(<MemoryPage memory={projectMemory()} {...handlers()} onSearch={onSearch} />)
  expect(scrolled).not.toHaveBeenCalled()
  unmount()
  render(<MemoryPage memory={projectMemory()} {...handlers()} onSearch={onSearch} searchFor={{ words: 'greeting', n: 1 }} />)
  expect(scrolled).toHaveBeenCalledExactlyOnceWith({ block: 'start' })
  expect(scrolled.mock.contexts[0]).toBe(screen.getByRole('search'))
  expect(screen.getByLabelText(BOX)).toHaveFocus()
  expect(screen.getByLabelText(BOX)).toHaveValue('greeting')
  expect(onSearch).toHaveBeenCalledWith('greeting')
  expect(await screen.findByText('Nothing on record speaks to “greeting”.')).toBeInTheDocument()
})

// --- 22c: another project's memory, and the search by meaning ---------------------------------

test('what a linked project holds is its own group, tagged with the project and not checked here; what was found by meaning says so; and why the search by meaning is off', async () => {
  const onSearch = vi.fn().mockResolvedValue({
    memory: [
      memoryRecord('w', { text: 'retry payment on 502' }),
      memoryRecord('m', { text: 'Payments are retried thrice', by_meaning: true, from_project: 'Other one', source_state: 'elsewhere', source: { path: 'notes.md', start: 3, end: 4 }, project_id: 'b' }),
    ],
    turns: [
      { who: 'You', conversation_id: 'c2', conversation_title: 'Retries', run_id: 'r9', at: '2026-10-13T10:00:00Z', excerpt: 'payments were retried thrice', project: 'Other one', by_meaning: true },
    ],
    meaning_off: 'search by meaning is off: model server unreachable: connection refused',
  })
  render(<MemoryPage memory={projectMemory()} {...handlers()} onSearch={onSearch} />)
  await userEvent.type(screen.getByLabelText(BOX), 'retry payment{Enter}')
  const own = within(await within(search()).findByRole('list', { name: 'What an agent would find in the memory' })).getAllByRole('listitem')
  expect(own).toHaveLength(1)
  expect(own[0]).toHaveTextContent('retry payment on 502')
  expect(own[0]).not.toHaveTextContent('by meaning')
  const linked = within(within(search()).getByRole('list', { name: 'In linked projects' })).getAllByRole('listitem')
  expect(linked[0]).toHaveTextContent('from project Other one')
  expect(linked[0]).toHaveTextContent('its files are not in this project: it could not be checked here')
  expect(linked[0]).toHaveTextContent('by meaning')
  expect(linked[0]).toHaveTextContent('not checked here: the file is in another project')
  expect(linked[1]).toHaveTextContent('“payments were retried thrice”')
  expect(linked[1]).toHaveTextContent('from project Other one')
  expect(linked[1]).toHaveTextContent('by meaning')
  // said in another project: not under this one's earlier messages
  expect(within(search()).queryByRole('list', { name: 'In earlier messages' })).toBeNull()
  expect(search()).toHaveTextContent('search by meaning is off: model server unreachable: connection refused')
})

test('by words / by meaning ▾ is the project’s setting, in a small window: a provider with a server address, what it costs in sight, and only what changed is sent', async () => {
  useApp.setState({
    projectId: 'p',
    projects: [{ id: 'p', name: 'demo', embedding_provider_id: null, embedding_model: 'text-embedding-3-small' }] as Project[],
    providers: [
      { id: 'srv', name: 'llama', kind: 'openai_compat', base_url: 'http://127.0.0.1:8080/v1' },
      { id: 'cc', name: 'Claude Code', kind: 'claude_cli', base_url: null },
    ] as Provider[],
  })
  onTestFinished(() => useApp.setState({ projectId: null, projects: [], providers: [] }))
  const onMeaning = vi.fn().mockResolvedValue(undefined)
  render(<MemoryPage memory={projectMemory()} {...handlers()} onSearch={vi.fn()} onMeaning={onMeaning} />)
  const open = screen.getByRole('button', { name: 'by words ▾' })
  expect(open).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByRole('dialog')).toBeNull()
  await userEvent.click(open)
  const picker = within(screen.getByRole('dialog', { name: 'How the memory is searched' })).getByRole('form', { name: 'Search by meaning' })
  // what it spends, in sight beside the choice: not behind a "?"
  expect(within(picker).getByText(/^One embeddings request to that provider for each search \(it also reads up to 50 notes, facts or earlier messages/)).toBeVisible()
  const choice = within(picker).getByLabelText('Search by meaning with')
  expect(within(choice).getAllByRole('option').map(o => o.textContent)).toEqual(['off: by words alone', 'llama'])
  expect(within(picker).getByLabelText('Embedding model')).toBeDisabled()
  expect(within(picker).getByRole('button', { name: 'Save' })).toBeDisabled()
  // off, the page says nothing of a cost
  expect(screen.queryByText(/^By meaning: /)).toBeNull()
  await userEvent.selectOptions(choice, 'srv')
  // closed and opened again, the choice not yet saved is still there
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(open).toHaveFocus()
  await userEvent.click(open)
  expect(within(picker).getByLabelText('Search by meaning with')).toHaveValue('srv')
  await userEvent.click(within(picker).getByRole('button', { name: 'Save' }))
  expect(onMeaning).toHaveBeenLastCalledWith({ embedding_provider_id: 'srv' })
  await userEvent.clear(within(picker).getByLabelText('Embedding model'))
  await userEvent.type(within(picker).getByLabelText('Embedding model'), 'nomic-embed')
  await userEvent.click(within(picker).getByRole('button', { name: 'Save' }))
  expect(onMeaning).toHaveBeenLastCalledWith({ embedding_provider_id: 'srv', embedding_model: 'nomic-embed' })
  // saved on the project, the button says so, and what each search spends is in sight under the box, the window closed
  useApp.setState({ projects: [{ id: 'p', name: 'demo', embedding_provider_id: 'srv', embedding_model: 'nomic-embed' }] as Project[] })
  const button = await screen.findByRole('button', { name: 'by meaning ▾' })
  await userEvent.click(button)
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(within(screen.getByRole('region', { name: 'Search' })).getByText(/^By meaning: One embeddings request to that provider for each search \(/)).toBeVisible()
})
