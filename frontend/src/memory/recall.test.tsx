import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, onTestFinished, test, vi } from 'vitest'
import { ApiError } from '../api/client'
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
  onSaveProjectNotes: vi.fn().mockResolvedValue(undefined),
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
  expect(lastAutoText({ run_id: 'r', noted: 2, skipped: 1, note: null }, 'T')).toBe(
    'After the last work noted by itself (T): 2 noted, 1 skipped.',
  )
  expect(lastAutoText({ run_id: 'r', noted: 1, skipped: 0, note: null }, 'T')).toBe(
    'After the last work noted by itself (T): 1 noted.',
  )
  const why = 'the request to the summariser failed: nothing was noted'
  const memory = projectMemory({ last_auto: { run_id: 'r2', noted: 0, skipped: 0, note: why } })
  const { unmount } = render(<MemoryPage memory={memory} {...handlers()} />)
  expect(await notes()).toHaveTextContent(
    `After the last work noted by itself (a message of a conversation not open here) nothing was noted: ${why}.`,
  )
  unmount()
  // a turn of the open conversation is named by when it was and the conversation's title
  useApp.setState({
    conv: convState({ runs: [run('r1', 'completed'), run('r2', 'completed', { created_at: '2026-10-13T10:00:00Z' })] }),
  })
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
  expect(within(search()).getByText('Nothing on record speaks to “newer”.').closest('[aria-live]')).toHaveAttribute(
    'aria-live',
    'polite',
  )
})

test('Enter searches deeper, as an agent’s recall does: the memory, and what earlier messages said, each in its own group', async () => {
  const onSearch = vi.fn().mockResolvedValue({
    memory: [auto],
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
      {
        who: 'Coder',
        conversation_id: 'c1',
        conversation_title: 'The greeting',
        run_id: 'r1',
        at: '2026-10-13T10:01:00Z',
        excerpt: 'It is in notes.md.',
        kind: 'turn',
        trigger: false,
      },
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
      {
        who: 'You',
        conversation_id: null,
        conversation_title: '',
        run_id: 'task:t1',
        at: null,
        excerpt: 'Fix the ledger — it closed at midnight',
        kind: 'task',
        trigger: false,
      },
      {
        who: 'Lead',
        conversation_id: 'c2',
        conversation_title: 'spin',
        run_id: 'r2',
        at: '2026-10-13T10:01:00Z',
        excerpt: 'The nightly build is green.',
        kind: 'turn',
        trigger: true,
      },
    ],
  })
  render(<MemoryPage memory={projectMemory()} {...handlers()} onSearch={onSearch} />)
  await userEvent.type(screen.getByLabelText(BOX), 'ledger{Enter}')
  const said = within(await within(search()).findByRole('list', { name: 'In earlier messages' })).getAllByRole(
    'listitem',
  )
  expect(said[0]).toHaveTextContent('a To-do task closed by you · a day not on record')
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
  render(
    <MemoryPage memory={projectMemory()} {...handlers()} onSearch={onSearch} searchFor={{ words: 'greeting', n: 1 }} />,
  )
  expect(scrolled).toHaveBeenCalledExactlyOnceWith({ block: 'start' })
  expect(scrolled.mock.contexts[0]).toBe(screen.getByRole('search'))
  expect(screen.getByLabelText(BOX)).toHaveFocus()
  expect(screen.getByLabelText(BOX)).toHaveValue('greeting')
  expect(onSearch).toHaveBeenCalledWith('greeting')
  expect(await screen.findByText('Nothing on record speaks to “greeting”.')).toBeInTheDocument()
})

// --- 22c: another project's memory ---------------------------------------------------------

test('what a linked project holds is its own group, tagged with the project and not checked here', async () => {
  const onSearch = vi.fn().mockResolvedValue({
    memory: [
      memoryRecord('w', { text: 'retry payment on 502' }),
      memoryRecord('m', {
        text: 'Payments are retried thrice',
        from_project: 'Other one',
        source_state: 'elsewhere',
        source: { path: 'notes.md', start: 3, end: 4 },
        project_id: 'b',
      }),
    ],
    turns: [
      {
        who: 'You',
        conversation_id: 'c2',
        conversation_title: 'Retries',
        run_id: 'r9',
        at: '2026-10-13T10:00:00Z',
        excerpt: 'payments were retried thrice',
        project: 'Other one',
      },
    ],
  })
  render(<MemoryPage memory={projectMemory()} {...handlers()} onSearch={onSearch} />)
  await userEvent.type(screen.getByLabelText(BOX), 'retry payment{Enter}')
  const own = within(
    await within(search()).findByRole('list', { name: 'What an agent would find in the memory' }),
  ).getAllByRole('listitem')
  expect(own).toHaveLength(1)
  expect(own[0]).toHaveTextContent('retry payment on 502')
  const linked = within(within(search()).getByRole('list', { name: 'In linked projects' })).getAllByRole('listitem')
  expect(linked[0]).toHaveTextContent('from project Other one')
  expect(linked[0]).toHaveTextContent('its files are not in this project: it could not be checked here')
  expect(linked[0]).toHaveTextContent('not checked here: the file is in another project')
  expect(linked[1]).toHaveTextContent('“payments were retried thrice”')
  expect(linked[1]).toHaveTextContent('from project Other one')
  // said in another project: not under this one's earlier messages
  expect(within(search()).queryByRole('list', { name: 'In earlier messages' })).toBeNull()
  // (0.1.10: the search by meaning is cut - no way to choose it, no tag)
  expect(screen.queryByRole('button', { name: /by words|by meaning/ })).toBeNull()
  expect(search()).not.toHaveTextContent('by meaning')
})

test('the status line is empty until words are typed, then says what the page has and that Enter searches deeper; what only another project said is its own group', async () => {
  const onSearch = vi.fn().mockResolvedValue({
    memory: [],
    turns: [
      {
        who: 'You',
        conversation_id: 'c2',
        conversation_title: 'Retries',
        run_id: 'r9',
        at: '2026-10-13T10:00:00Z',
        excerpt: 'payments were retried thrice',
        project: 'Other one',
      },
    ],
  })
  render(<MemoryPage memory={projectMemory()} {...handlers()} onSearch={onSearch} />)
  expect(within(search()).getByRole('status')).toBeEmptyDOMElement()
  await userEvent.type(screen.getByLabelText(BOX), 'thrice{Enter}')
  expect(within(search()).getByRole('status')).toHaveTextContent(
    /^Nothing on this page has “thrice”\. Enter searches deeper\.$/,
  )
  const linked = within(await within(search()).findByRole('list', { name: 'In linked projects' })).getAllByRole(
    'listitem',
  )
  expect(linked).toHaveLength(1)
  expect(linked[0]).toHaveTextContent('“payments were retried thrice”')
  expect(within(search()).getByRole('heading', { name: 'Searched deeper for “thrice”' })).toBeInTheDocument()
  expect(within(search()).getByText('Nothing on record speaks to “thrice”.')).toBeInTheDocument()
  expect(within(search()).getByText('Nothing said in earlier messages speaks to “thrice”.')).toBeInTheDocument()
})
