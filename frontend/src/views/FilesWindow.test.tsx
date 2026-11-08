import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import type { Board, Command, FileHistory, GitChange, Project, ProjectEntry, View } from '../api/types'
import { ChatPanel } from '../chat/ChatPanel'
import { applyEvent, type ConvState } from '../state/applyEvent'
import { resetStoreForTests, useApp } from '../state/store'
import { agent, command, convState, fileChange, run, toolCall } from '../test-fixtures'
import { FilesWindow } from './FilesWindow'
import { type Item, servedOf, useViews, viewsStamp } from './views'

const view = (id: string, path: string, over: Partial<View> = {}): View => ({
  id,
  path,
  kind: 'html',
  agent_id: 'r1',
  status: 'proposed',
  sha: `sha-${id}`,
  note: null,
  too_large: false,
  url: `/api/conversations/c1/views/${id}/${path.split('/').at(-1)}`,
  at: '2026-10-15T10:00:00Z',
  ...over,
})

const lead = agent('r1', 'running', { id: 'r1', name: 'Lead' })
const none = () => {}
const project = { id: 'p', root_path: 'C:/work/koloni' }
type Props = Parameters<typeof FilesWindow>[0]
const props = (more: Partial<Props> = {}): Props => ({
  project,
  changes: [],
  views: [],
  fresh: [],
  agents: [lead],
  open: true,
  at: { key: null, n: 0 },
  height: 0.45,
  expanded: false,
  onExpand: none,
  onClose: none,
  onSeen: none,
  onDecide: async () => {},
  ...more,
})
/** Opened on `key` (as a button or "View diff" asks), or on nothing. */
const panel = (more: Partial<Props> = {}, key: string | null = null) => render(<FilesWindow {...props({ at: { key, n: 1 }, ...more })} />)

const entry = (name: string, kind: ProjectEntry['kind'] = 'file'): ProjectEntry => ({ name, kind, size: kind === 'dir' ? null : 10 })
/** The project on disk, folder by folder ('' the root), and the files' text; the requests made, by address. */
let disk: Record<string, ProjectEntry[]> = {}
let texts: Record<string, Partial<{ text: string | null; binary: boolean; too_large: boolean }>> = {}
let asked: string[] = []
let viewsListed: View[] = []
/** What git says is changed (K-degisenler): null where the project has no git; and each file's diff against HEAD. */
let gitChanges: GitChange[] | null = null
let gitDiffs: Record<string, string> = {}
/** The last works on record of each file (K-devir-4); null where none. */
let history: Record<string, FileHistory[]> = {}
beforeEach(() => {
  localStorage.clear()
  resetStoreForTests()
  history = {}
  disk = { '': [entry('node_modules', 'dir'), entry('src', 'dir'), entry('README.md'), entry('hello.py')], src: [entry('a.py')] }
  texts = { 'hello.py': { text: "print('hi')\n" } }
  asked = []
  viewsListed = []
  gitChanges = null
  gitDiffs = {}
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      asked.push(`${init?.method ?? 'GET'} ${url}`)
      const where = new URL(url, 'http://app')
      const path = where.searchParams.get('path') ?? ''
      if (where.pathname.endsWith('/changes')) return new Response(JSON.stringify(gitChanges), { status: 200 })
      if (where.pathname.endsWith('/file-history')) return new Response(JSON.stringify(history[path] ?? null), { status: 200 })
      const body = where.pathname.endsWith('/files')
        ? (disk[path] ?? null)
        : where.pathname.endsWith('/file')
          ? { text: null, size: 10, binary: false, too_large: false, ...texts[path] }
          : where.pathname.endsWith('/changes/diff')
            ? { diff: gitDiffs[path] ?? '' }
            : where.pathname.endsWith('/views')
              ? viewsListed
              : where.pathname.endsWith('/copy')
                ? { agent_id: 'c', folder: null, files: [{ path: 'a.txt', kind: 'modify', diff: '@@ -1 +1 @@\n-a\n+b\n', additions: 1, deletions: 1 }] }
                : where.pathname.endsWith('/frame')
                ? { frameable: true }
                : {}
      return new Response(JSON.stringify(body), { status: body === null ? 404 : 200 })
    }),
  )
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const treeOf = () => screen.getByRole('tree', { name: 'Files' })
const treeItems = () => within(treeOf()).getAllByRole('treeitem').map(i => i.getAttribute('aria-label') ?? i.textContent)
const tabs = () => within(screen.getByRole('tablist', { name: 'Open files' })).getAllByRole('tab').map(t => t.textContent)
/** The × on a tab: drawn on it for the mouse, out of what a screen reader reads (Delete closes it from the keyboard). */
const closeOf = (name: string) => userEvent.click(screen.getAllByRole('tab').find(tab => tab.textContent === name)!.querySelector('.view-tab-close')!)

// --- the tree (slice 42c §2) ---------------------------------------------------------------------

test('the root is the project folder’s name, with no section above it; its folders are read as they open, one level, and node_modules stays closed', async () => {
  panel()
  await waitFor(() => expect(treeItems()).toEqual(['koloni', 'node_modules', 'src', 'hello.py', 'README.md']))
  expect(within(treeOf()).getByRole('treeitem', { name: 'koloni' })).toHaveAttribute('aria-level', '1')
  expect(within(treeOf()).getByRole('treeitem', { name: 'node_modules' })).toHaveAttribute('aria-expanded', 'false')
  expect(asked.filter(a => a.includes('/files'))).toEqual(['GET /api/projects/p/files?path='])
  await userEvent.click(within(treeOf()).getByRole('treeitem', { name: 'src' }))
  await waitFor(() => expect(treeItems()).toEqual(['koloni', 'node_modules', 'src', 'a.py', 'hello.py', 'README.md']))
  expect(asked).toContain('GET /api/projects/p/files?path=src')
  // (no Artifacts, Images or Previews heading: nothing is served)
  expect(screen.queryByRole('treeitem', { name: /^(Artifacts|Images|Previews)/ })).not.toBeInTheDocument()
})

test('asked for the shared folder, it opens the project and the folders down to it, and chooses it in view (B-163)', async () => {
  // (The user had closed the project's own folder before.)
  localStorage.setItem('koloni-files-folders-p', JSON.stringify({ '/koloni': false }))
  disk = { ...disk, '': [entry('.git', 'dir'), entry('.koloni', 'dir'), ...disk['']], '.koloni': [entry('shared', 'dir')], '.koloni/shared': [entry('notes.md')] }
  const scrolled = vi.fn()
  Element.prototype.scrollIntoView = scrolled // (jsdom has none)
  try {
    const { rerender } = panel({}, 'folder:.koloni/shared')
    await waitFor(() => expect(treeItems()).toContain('notes.md'))
    const shared = within(treeOf()).getByRole('treeitem', { name: 'shared' })
    expect(shared).toHaveAttribute('aria-expanded', 'true')
    expect(shared).toHaveAttribute('aria-selected', 'true')
    expect(shared).toHaveAttribute('tabindex', '0')
    await waitFor(() => expect(scrolled.mock.contexts).toContain(shared))
    // A file chosen, then the folder asked for again: one row is chosen, the file's.
    rerender(<FilesWindow {...props({ at: { key: 'hello.py', n: 2 } })} />)
    rerender(<FilesWindow {...props({ at: { key: 'folder:.koloni/shared', n: 3 } })} />)
    expect(within(treeOf()).getByRole('treeitem', { name: 'shared' })).not.toHaveAttribute('aria-selected')
    expect(within(treeOf()).getAllByRole('treeitem').filter(i => i.getAttribute('aria-selected') === 'true')).toHaveLength(1)
  } finally {
    delete (Element.prototype as Partial<Element>).scrollIntoView
  }
})

test('a change that comes reads the open folders again, and keeps their rows - and the focus - till the answer comes', async () => {
  const { rerender } = panel()
  const row = await within(treeOf()).findByRole('treeitem', { name: 'hello.py' })
  row.focus()
  let answer = (_: Response) => {}
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(done => (answer = done))))
  rerender(<FilesWindow {...props({ at: { key: null, n: 1 }, changes: [fileChange('f1', 'r1', { path: 'new.txt', kind: 'create', status: 'proposed' })] })} />)
  await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/projects/p/files?path=', expect.anything()))
  expect(within(treeOf()).getByRole('treeitem', { name: 'hello.py' })).toHaveFocus()
  await act(async () => answer(new Response(JSON.stringify([entry('hello.py'), entry('new.txt')]), { status: 200 })))
  await waitFor(() => expect(within(treeOf()).queryByRole('treeitem', { name: 'README.md' })).not.toBeInTheDocument())
  expect(within(treeOf()).getByRole('treeitem', { name: 'hello.py' })).toHaveFocus()
})

test('three changes to one file are one row, and only the latest is shown; M / A / D, a dot while it waits, its folders dotted and open', async () => {
  const changes = [
    fileChange('f1', 'r1', { path: 'src/a.py', status: 'applied', diff: '@@ -1 +1 @@\n-one\n+two\n', created_at: '2026-10-05T10:00:01Z' }),
    fileChange('f2', 'r1', { path: 'src\\a.py', status: 'applied', diff: '@@ -1 +1 @@\n-two\n+three\n', created_at: '2026-10-05T10:00:02Z' }),
    fileChange('f3', 'r1', { path: 'src/a.py', status: 'proposed', diff: '@@ -1 +1 @@\n-three\n+four\n', created_at: '2026-10-05T10:00:03Z' }),
    fileChange('f4', 'r1', { path: 'new.txt', kind: 'create', status: 'applied', diff: '@@ -0,0 +1 @@\n+fresh\n' }),
    fileChange('f5', 'r1', { path: 'old.txt', kind: 'delete', status: 'proposed', diff: '@@ -1 +0,0 @@\n-gone\n' }),
  ]
  disk[''].push(entry('new.txt'))
  panel({ changes }, 'src/a.py')
  await waitFor(() => expect(treeItems()).toContain('a.py modified, Waits for you'))
  expect(treeItems()).toEqual(['koloni changed', 'node_modules', 'src changed', 'a.py modified, Waits for you', 'hello.py', 'new.txt added, Applied', 'old.txt deleted, Waits for you', 'README.md'])
  const row = within(treeOf()).getByRole('treeitem', { name: /^a\.py/ })
  expect(row).toHaveTextContent(/^a\.pyM$/)
  expect(row.querySelector('.tree-mark-warn')).toHaveTextContent('M')
  expect(row.querySelector('.tree-wait')).not.toBeNull()
  expect(within(treeOf()).getByRole('treeitem', { name: /^new\.txt/ }).querySelector('.tree-mark-ok')).toHaveTextContent('A')
  expect(within(treeOf()).getByRole('treeitem', { name: /^old\.txt/ }).querySelector('.tree-mark-del')).toHaveTextContent('D')
  // the latest change's diff only, with its decisions
  expect(screen.getByText('four')).toBeInTheDocument()
  expect(screen.queryByText('two')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument()
  expect(tabs()).toEqual(['a.py'])
  // what waits, above the tree: the next one is the deleted file
  expect(screen.getByText('2 files wait')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /^Next waiting/ }))
  expect(tabs()).toEqual(['a.py', 'old.txt'])
  expect(screen.getByText('gone')).toBeInTheDocument()
})

test('a change the server says is gone from disk says so; a file the listing leaves out (a secret’s name) does not (B-55)', async () => {
  const changes = [
    fileChange('f1', 'r1', { path: 'first.txt', kind: 'create', status: 'applied', gone: true }),
    fileChange('f2', 'r1', { path: 'src/greet.py', status: 'applied', gone: true }),
    fileChange('f3', 'r1', { path: 'hello.py', status: 'applied' }),
    fileChange('f4', 'r1', { path: '.env.example', kind: 'create', status: 'applied' }),
  ]
  panel({ changes })
  await waitFor(() => expect(treeItems()).toContain('first.txt added, Applied, not on disk now'))
  await waitFor(() => expect(treeItems()).toContain('greet.py modified, Applied, not on disk now'))
  expect(treeItems()).toEqual(expect.arrayContaining(['hello.py modified, Applied', '.env.example added, Applied']))
  expect(within(treeOf()).getByRole('treeitem', { name: /^first\.txt/ })).toHaveTextContent(/^first\.txtGone$/)
})

test('on Windows a file is one row whatever case its path is written in, named as it is on disk', async () => {
  vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue('Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
  panel({ changes: [fileChange('f1', 'r1', { path: 'Hello.PY', status: 'proposed' })] }, 'hello.py')
  expect(await within(treeOf()).findByRole('treeitem', { name: 'hello.py modified, Waits for you' })).toBeInTheDocument()
  expect(within(treeOf()).getAllByRole('treeitem', { name: /^hello\.py/i })).toHaveLength(1)
  expect(tabs()).toEqual(['hello.py'])
})

test('a decision goes to the latest change of the file shown', async () => {
  const onDecide = vi.fn(async () => {})
  panel({ changes: [fileChange('f1', 'r1', { status: 'applied' }), fileChange('f2', 'r1', { status: 'proposed', created_at: '2026-10-05T10:00:09Z' })], onDecide }, 'src/a.py')
  await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
  expect(onDecide).toHaveBeenCalledWith('f2', 'approve')
})

// --- the file on the right (slice 42c §3) -------------------------------------------------------------

test('a string over several lines of a file is coloured on each of them (K-42a)', async () => {
  texts['hello.py'] = { text: 'x = """one\ntwo\nthree"""\ny = 1\n' }
  panel({}, 'hello.py')
  await screen.findByText('4')
  const lines = Array.from(document.querySelectorAll('.diff-line .diff-text'), line => Boolean(line.querySelector('.hljs-string')))
  expect(lines).toEqual([true, true, true, false])
})

test('any other file is its code, read only: numbered and coloured; one not text, or too large, says so', async () => {
  texts['big.log'] = { too_large: true }
  texts['pic.bin'] = { binary: true }
  disk[''].push(entry('big.log'), entry('pic.bin'))
  panel({}, 'hello.py')
  expect(await screen.findByText('1')).toHaveClass('diff-no')
  expect(document.querySelector('.diff-text .hljs-built_in')).toHaveTextContent('print')
  expect(asked).toContain('GET /api/projects/p/file?path=hello.py')
  await userEvent.click(await within(treeOf()).findByRole('treeitem', { name: 'big.log' }))
  expect(await screen.findByText('Too large to show: over 256 KB.')).toBeInTheDocument()
  await userEvent.click(within(treeOf()).getByRole('treeitem', { name: 'pic.bin' }))
  expect(await screen.findByText('Not text: there is no code to show.')).toBeInTheDocument()
})

test('a page of the project: Preview, framed by slice 39’s rules from the project’s own address, its script run only once asked; Code is its text', async () => {
  disk[''].push(entry('page.html'))
  texts['page.html'] = { text: '<p>hi</p>\n' }
  panel({}, 'page.html')
  const frame = () => document.querySelector('iframe')!
  expect(frame().getAttribute('src')).toBe('/api/projects/p/raw/page.html')
  expect(frame().getAttribute('sandbox')).toBe('')
  expect(screen.getByRole('button', { name: 'Preview' })).toHaveAttribute('aria-pressed', 'true')
  await userEvent.click(screen.getByRole('button', { name: 'Run once' }))
  expect(frame().getAttribute('sandbox')).toBe('allow-scripts')
  await userEvent.click(screen.getByRole('button', { name: 'Code' }))
  expect(document.querySelector('iframe')).toBeNull()
  expect(await screen.findByText('1')).toHaveClass('diff-no')
  expect(document.querySelector('.hljs-tag')).not.toBeNull()
})

test('a page an agent wrote is previewed from its view (the text not on disk yet), its script on a click, and goes on running when written again; a changed one opens on its diff', async () => {
  const written = view('v2', 'site/page.html', { note: 'the new page' })
  const { rerender } = render(<FilesWindow {...props({ views: [written], at: { key: 'site/page.html', n: 1 } })} />)
  const frame = () => document.querySelector('iframe')!
  expect(frame()).toHaveAttribute('title', 'site/page.html')
  expect(frame().getAttribute('src')).toBe('/api/conversations/c1/views/v2/page.html?v=sha-v2-proposed')
  expect(screen.getByText(/the new page/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Run once' }))
  expect(frame().getAttribute('sandbox')).toBe('allow-scripts')
  rerender(<FilesWindow {...props({ views: [{ ...written, sha: 'sha-v2-again' }], at: { key: 'site/page.html', n: 1 } })} />)
  expect(frame().getAttribute('src')).toBe('/api/conversations/c1/views/v2/page.html?v=sha-v2-again-proposed')
  expect(frame().getAttribute('sandbox')).toBe('allow-scripts')
  // with a change to it, it opens on the diff; Preview a click away
  rerender(<FilesWindow {...props({ views: [written], changes: [fileChange('f1', 'r1', { path: 'site/page.html', status: 'proposed', diff: '@@ -0,0 +1 @@\n+<p>hi</p>\n' })], at: { key: 'site/page.html', n: 2 } })} />)
  expect(screen.getByRole('button', { name: 'Diff' })).toHaveAttribute('aria-pressed', 'true')
  expect(document.querySelector('iframe')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Preview' }))
  expect(document.querySelector('iframe')).not.toBeNull()
  expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument()
})

test('K-39-betik: a page’s script is asked about - Run once, Always run in this chat, Don’t run - and always runs, until Ask each time', async () => {
  const frame = () => document.querySelector('iframe')!
  const { unmount } = panel({ views: [view('v1', 'a.html')] }, 'a.html')
  const ask = screen.getByRole('group', { name: 'Run its script?' })
  expect(within(ask).getAllByRole('button').map(b => b.textContent)).toEqual(['Run once', 'Always run in this chat', 'Don’t run'])
  // Don't run: the page stays drawn, without its script, and the ask goes
  await userEvent.click(within(ask).getByRole('button', { name: 'Don’t run' }))
  expect(screen.queryByRole('group', { name: 'Run its script?' })).toBeNull()
  expect(frame().getAttribute('sandbox')).toBe('')
  // B-168: a slim line says so, and Run once is still there; ran once, Ask each time draws it again without it
  const said = () => screen.getByRole('group', { name: 'Its script' })
  expect(said()).toHaveTextContent('Script not run.')
  await userEvent.click(within(said()).getByRole('button', { name: 'Run once' }))
  expect(frame().getAttribute('sandbox')).toBe('allow-scripts')
  expect(said()).toHaveTextContent('Script ran once.')
  expect(within(said()).getAllByRole('button').map(b => b.textContent)).toEqual(['Ask each time'])
  await userEvent.click(within(said()).getByRole('button', { name: 'Ask each time' }))
  expect(frame().getAttribute('sandbox')).toBe('')
  expect(within(screen.getByRole('group', { name: 'Run its script?' })).getAllByRole('button')).toHaveLength(3)
  expect(asked.some(a => a.startsWith('PATCH'))).toBe(false) // (once is this page's, never the chat's)
  unmount()

  // Always run in this chat: kept on the conversation; its pages run, and the same place turns it off
  useApp.setState({ conv: convState() })
  const id = useApp.getState().conv!.conversation.id
  panel({ views: [view('v1', 'a.html')] }, 'a.html')
  await userEvent.click(screen.getByRole('button', { name: 'Always run in this chat' }))
  expect(asked).toContain(`PATCH /api/conversations/${id}`)
  expect(JSON.parse(String(vi.mocked(fetch).mock.calls.at(-1)![1]!.body))).toEqual({ page_scripts: true })
  act(() => useApp.setState(s => ({ conv: { ...s.conv!, conversation: { ...s.conv!.conversation, page_scripts: true } } })))
  expect(frame().getAttribute('sandbox')).toBe('allow-scripts')
  const on = screen.getByRole('group', { name: 'Its script' })
  expect(on).toHaveTextContent('Scripts run in this chat without asking.')
  await userEvent.click(within(on).getByRole('button', { name: 'Ask each time' }))
  expect(JSON.parse(String(vi.mocked(fetch).mock.calls.at(-1)![1]!.body))).toEqual({ page_scripts: false })
})

test('K-39-betik: Always runs only this chat’s own pages - a page of the project it never made is asked about still', async () => {
  useApp.setState({ conv: convState() })
  act(() => useApp.setState(s => ({ conv: { ...s.conv!, conversation: { ...s.conv!.conversation, page_scripts: true } } })))
  disk[''].push(entry('docs.html'))
  panel({}, 'docs.html')
  expect(document.querySelector('iframe')!.getAttribute('sandbox')).toBe('')
  expect(screen.getByRole('group', { name: 'Run its script?' })).toBeInTheDocument()
})

test('a drawing is framed too, never with its script; a picture is a picture, with nothing to switch to; one too large is not loaded', async () => {
  panel({ views: [view('v1', 'd.svg', { kind: 'svg' }), view('v2', 'chart.png', { kind: 'image', status: 'shown' }), view('v3', 'big.png', { kind: 'image', too_large: true })] }, 'd.svg')
  expect(document.querySelector('iframe[title="d.svg"]')?.getAttribute('sandbox')).toBe('')
  expect(screen.queryByRole('group', { name: 'Run its script?' })).not.toBeInTheDocument()
  await userEvent.click(within(treeOf()).getByRole('treeitem', { name: /^chart\.png/ }))
  expect(screen.getByRole('img', { name: 'chart.png' })).toHaveAttribute('src', '/api/conversations/c1/views/v2/chart.png?v=sha-v2-shown')
  expect(screen.queryByRole('button', { name: 'Code' })).not.toBeInTheDocument()
  await userEvent.click(within(treeOf()).getByRole('treeitem', { name: /^big\.png/ }))
  expect(screen.getByText(/Too large to show/)).toBeInTheDocument()
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
})

test('a page that goes elsewhere by itself - a second load at the same address - is taken off, and the user told', () => {
  panel({ views: [view('v1', 'p.html')] }, 'p.html')
  const frame = document.querySelector('iframe')!
  fireEvent.load(frame) // its own load
  expect(document.querySelector('iframe')).not.toBeNull()
  fireEvent.load(frame) // and once more, the address unchanged: it went somewhere
  expect(document.querySelector('iframe')).toBeNull()
  expect(screen.getByText('The page tried to go elsewhere; it was stopped.')).toBeInTheDocument()
})

test('a note is read as Markdown, not framed', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(url.includes('/views/') ? '# Plan\n\n- one' : '[]', { status: 200 })))
  panel({ views: [view('v1', 'notes.md', { kind: 'md' })] }, 'notes.md')
  expect(await screen.findByRole('heading', { name: 'Plan' })).toBeInTheDocument()
  expect(document.querySelector('iframe')).toBeNull()
})

// --- the window ---------------------------------------------------------------------------------------

test('Esc closes it; its button expands it over the canvas and shrinks it back', async () => {
  const onClose = vi.fn()
  const onExpand = vi.fn()
  const { rerender } = panel({ onClose, onExpand }, 'hello.py')
  screen.getByRole('tab', { name: 'hello.py' }).focus()
  await userEvent.keyboard('{Escape}')
  expect(onClose).toHaveBeenCalledOnce()
  await userEvent.click(screen.getByRole('button', { name: 'Expand workspace' }))
  expect(onExpand).toHaveBeenCalledOnce()
  rerender(<FilesWindow {...props({ expanded: true, at: { key: 'hello.py', n: 1 } })} />)
  expect(screen.getByRole('region', { name: 'Workspace' })).toHaveClass('view-panel-wide')
  expect(screen.getByRole('button', { name: 'Shrink workspace' })).toBeInTheDocument()
})

test('closed, it is an empty box on the page: nothing in it runs or is read', () => {
  const { container } = panel({ open: false, views: [view('v1', 'p.html')] }, 'p.html')
  expect(container.querySelector('.view-panel')).toHaveAttribute('hidden')
  expect(container.querySelector('iframe')).toBeNull()
  expect(asked).toEqual([])
})

test('the views are read again when a change is made or decided', () => {
  const made = convState({ fileChanges: [fileChange('f1', 'r1', { status: 'proposed' })] })
  const decided = convState({ fileChanges: [fileChange('f1', 'r1', { status: 'applied' })] })
  expect(viewsStamp(made)).not.toBe(viewsStamp(convState()))
  expect(viewsStamp(decided)).not.toBe(viewsStamp(made))
})

test('the views are read again when a file is put there with no call of its own: one a command made (R161)', () => {
  const before = convState()
  expect(viewsStamp(applyEvent(before, 7, 'view.shown', { id: 'v1', path: 'docs/note.docx', agent_id: 'a1', note: null }))).not.toBe(viewsStamp(before))
})

test('the list of the conversation left, come after the first list of the one opened, is dropped: what is shown there next is new', async () => {
  let late: ((views: View[]) => void) | null = null
  let listed: View[] = []
  const get = vi.spyOn(api, 'get').mockImplementation(path => (path === '/conversations/old/views' ? new Promise(done => (late = done)) : Promise.resolve(listed)) as never)
  const at = (id: string, over: Partial<ConvState> = {}) => convState({ conversation: { ...convState().conversation, id }, ...over })
  const { result, rerender } = renderHook(({ conv }) => useViews(conv, false), { initialProps: { conv: at('old') } })
  await waitFor(() => expect(late).not.toBeNull())
  rerender({ conv: at('new') })
  await waitFor(() => expect(get).toHaveBeenCalledWith('/conversations/new/views'))
  await act(async () => late!([view('v0', 'old.html')]))
  listed = [view('v1', 'chart.png', { status: 'shown' })]
  rerender({ conv: at('new', { toolCalls: [toolCall('t1', 'r1', 'show', 'succeeded')] }) })
  await waitFor(() => expect(result.current.fresh).toEqual(['v1']), { timeout: 3000 })
})

test('tabs: a file picked in the tree comes on a tab; a dot marks one new till it is opened; × or Delete closes a tab, the file stays in the tree', async () => {
  const onSeen = vi.fn()
  panel({ views: [view('v1', 'a.html'), view('v2', 'b.svg', { kind: 'svg' })], fresh: ['v2'], onSeen }, 'a.html')
  expect(onSeen).not.toHaveBeenCalled() // (a.html was not new)
  const b = within(treeOf()).getByRole('treeitem', { name: 'b.svg new Waits for you' })
  await userEvent.click(b)
  expect(tabs()).toEqual(['a.html', 'b.svg'])
  expect(screen.getByRole('tab', { name: 'b.svg' })).toHaveAttribute('aria-selected', 'true')
  expect(document.querySelector('iframe')).toHaveAttribute('title', 'b.svg')
  expect(onSeen).toHaveBeenLastCalledWith(['v2'])
  await closeOf('a.html')
  expect(tabs()).toEqual(['b.svg'])
  screen.getByRole('tab', { name: 'b.svg' }).focus()
  await userEvent.keyboard('{Delete}')
  expect(within(screen.getByRole('tablist', { name: 'Open files' })).queryByRole('tab')).not.toBeInTheDocument()
  expect(screen.getByText('Pick a file in the tree.')).toBeInTheDocument()
  expect(within(treeOf()).getByRole('treeitem', { name: /^b\.svg/ })).toBeInTheDocument()
  expect(within(screen.getByRole('tablist', { name: 'Open files' })).queryAllByRole('button')).toEqual([])
})

test('dragged by its header it goes where it is put and is there again; a double click puts it back; expanded, it is not moved', () => {
  // (what jsdom does not lay out: a stage 1000 by 800, the window 480 by 300 at its left 100, bottom 100)
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const [x, y, width, height] = this.matches('.view-panel') ? [100, 400, 480, 300] : [0, 0, 1000, 800]
    return { x, y, width, height, left: x, top: y, right: x + width, bottom: y + height, toJSON: () => ({}) } as DOMRect
  })
  const { unmount } = panel()
  const region = () => screen.getByRole('region', { name: 'Workspace' })
  const top = () => region().querySelector('.view-top')!
  fireEvent.pointerDown(top(), { pointerId: 1, button: 0, clientX: 300, clientY: 300 })
  fireEvent.pointerMove(top(), { pointerId: 1, clientX: 340, clientY: 280 })
  fireEvent.pointerUp(top(), { pointerId: 1, clientX: 340, clientY: 280 })
  expect(region()).toHaveClass('moved')
  expect(JSON.parse(localStorage.getItem('koloni-view-spot')!)).toEqual({ x: 140, y: 120 })
  unmount()
  const { rerender } = panel()
  expect(region().style.getPropertyValue('--x')).toBe('140px')
  fireEvent.doubleClick(top())
  expect(region()).not.toHaveClass('moved')
  expect(screen.getByRole('button', { name: 'Move workspace' })).toBeInTheDocument()
  rerender(<FilesWindow {...props({ expanded: true })} />)
  expect(screen.queryByRole('button', { name: 'Move workspace' })).not.toBeInTheDocument()
})

// --- the Workspace button (42c §1, 42d) -----------------------------------------------------------------

const board = (waiting: number): Board => ({
  backlog_waiting: 0,
  limit: null,
  running: 0,
  conflicts: [],
  conversations: [{ conversation_id: 'c', title: 'One', agents: [], merges_pending: waiting, turn: null }],
})
function opened(more: Parameters<typeof convState>[0] = {}) {
  const conv = convState({ runs: [run('r1', 'running')], agents: [lead], ...more })
  useApp.setState({ conv, projectId: 'p', projects: [{ ...project, name: 'koloni' } as Project] })
  return conv
}

test('one Workspace button: open, a small file at the chat’s foot, at the end of the model’s line - not in its header nor the top bar - that glows while something waits; closed, beside the small box: its number is what waits for you as the Board counts it', async () => {
  opened()
  render(<ChatPanel />)
  const chat = screen.getByRole('region', { name: 'Chat' })
  // (the Board not read yet: no number, nothing to glow for)
  const foot = within(chat).getByRole('button', { name: 'Workspace' })
  expect(foot).toHaveAttribute('title', expect.stringMatching(/^Workspace/))
  expect(foot.closest('.composer-line')).not.toBeNull()
  expect(chat.querySelector('.chat-top')).not.toContainElement(foot)
  expect(foot).not.toHaveClass('glow')
  act(() => useApp.setState({ everywhere: board(2) }))
  expect(within(chat).getByRole('button', { name: 'Workspace 2 waiting' })).toHaveClass('glow')
  expect(screen.getAllByRole('button', { name: /^Workspace/ })).toHaveLength(1)
  // opened, it stops
  await userEvent.click(foot)
  expect(foot).not.toHaveClass('glow')
  await userEvent.click(foot)
  expect(screen.queryByRole('button', { name: /^(Artifacts|Images|Preview|Files)/ })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Hide chat' }))
  expect(screen.getAllByRole('button', { name: 'Workspace 2 waiting' })).toHaveLength(1)
  expect(chat).not.toContainElement(document.querySelector('.chat-dock'))
})

test('the button opens the window and closes it; Esc closes it back on the button; something new is a dot on it till opened', async () => {
  const conv = opened()
  render(<ChatPanel />)
  await waitFor(() => expect(asked).toContain('GET /api/conversations/c/views'), { timeout: 3000 })
  const button = screen.getByRole('button', { name: /^Workspace/ })
  await userEvent.click(button)
  const window = screen.getByRole('region', { name: 'Workspace' })
  expect(window).toBeVisible()
  expect(button).toHaveAttribute('aria-expanded', 'true')
  within(window).getByRole('button', { name: 'Close workspace' }).focus()
  await userEvent.keyboard('{Escape}')
  expect(window).not.toBeVisible()
  await waitFor(() => expect(button).toHaveFocus())
  expect(conv).toBeTruthy()
})

/** An agent shows a file: the views listed again with it on top. */
function shows(conv: ReturnType<typeof opened>, path: string, n: number) {
  viewsListed = [view(`v${n}`, path, { status: 'shown' }), ...viewsListed]
  const show = toolCall(`t${n}`, 'r1', 'show', 'succeeded')
  act(() => useApp.setState({ conv: { ...conv, toolCalls: [...(useApp.getState().conv?.toolCalls ?? []), show] } }))
}

test('what comes new opens Workspace at it by itself, the focus left in the message box; opened by itself and untouched it goes to the next, in use it only marks it new', async () => {
  const conv = opened()
  render(<ChatPanel />)
  await waitFor(() => expect(asked).toContain('GET /api/conversations/c/views'), { timeout: 3000 })
  const box = screen.getByLabelText('Message')
  box.focus()
  shows(conv, 'one.html', 1)
  await waitFor(() => expect(screen.getByRole('region', { name: 'Workspace' })).toBeVisible(), { timeout: 3000 })
  expect(screen.getByRole('tab', { name: 'one.html' })).toHaveAttribute('aria-selected', 'true')
  expect(box).toHaveFocus()
  // untouched: the next one is shown
  shows(conv, 'two.html', 2)
  await waitFor(() => expect(screen.getByRole('tab', { name: 'two.html' })).toHaveAttribute('aria-selected', 'true'), { timeout: 3000 })
  // in use: the next is only marked new there
  fireEvent.pointerDown(screen.getByRole('tab', { name: 'two.html' }))
  shows(conv, 'three.html', 3)
  expect(await within(treeOf()).findByRole('treeitem', { name: 'three.html new Shown' }, { timeout: 3000 })).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: 'two.html' })).toHaveAttribute('aria-selected', 'true')
  // closed unseen, it is new on the button
  await userEvent.click(screen.getByRole('button', { name: 'Close workspace' }))
  expect(screen.getByRole('button', { name: 'Workspace new' })).toBeInTheDocument()
})

test('closed, the focus goes back to the button that opened it - the chat’s or the small box’s; that one gone or hidden, to the one shown', async () => {
  opened()
  render(<ChatPanel />)
  const foot = screen.getByRole('button', { name: /^Workspace/ })
  await userEvent.click(foot)
  await userEvent.click(screen.getByRole('button', { name: 'Close workspace' }))
  await waitFor(() => expect(foot).toHaveFocus())
  // opened from the chat's foot, then the chat closed: that one is hidden, the small box's button takes it
  await userEvent.click(foot)
  await userEvent.click(screen.getByRole('button', { name: 'Hide chat' }))
  const beside = within(document.querySelector<HTMLElement>('.chat-dock')!).getByRole('button', { name: /^Workspace/ })
  await userEvent.click(screen.getByRole('button', { name: 'Close workspace' }))
  await waitFor(() => expect(beside).toHaveFocus())
  await userEvent.click(beside)
  await userEvent.click(screen.getByRole('button', { name: 'Close workspace' }))
  await waitFor(() => expect(beside).toHaveFocus())
  // opened beside the small box, then the chat opened: that button is gone
  await userEvent.click(beside)
  await userEvent.click(screen.getByRole('button', { name: /^Chat/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Close workspace' }))
  await waitFor(() => expect(foot).toHaveFocus())
})

test('"View diff" and a change that waits open Workspace at that file', async () => {
  opened({ fileChanges: [fileChange('f1', 'r1', { path: 'src\\a.py', status: 'applied', diff: '@@ -1 +1 @@\n-x\n+y\n' })] })
  render(<ChatPanel />)
  act(() => useApp.getState().openChange('f1'))
  expect(screen.getByRole('region', { name: 'Workspace' })).toBeVisible()
  expect(screen.getByRole('tab', { name: 'a.py' })).toHaveAttribute('aria-selected', 'true')
  expect(await within(treeOf()).findByRole('treeitem', { name: 'a.py modified, Applied' })).toHaveAttribute('aria-selected', 'true')
  // closed and asked again, it opens on it again
  await userEvent.click(screen.getByRole('button', { name: 'Close workspace' }))
  act(() => useApp.getState().openChange('f1'))
  expect(screen.getByRole('region', { name: 'Workspace' })).toBeVisible()
})

// --- slice 42b: Previews - what an agent's command serves, live --------------------------------------

const server = (id: string, over: Partial<Command> = {}) =>
  command(id, 'r1', { command: 'npm run dev', keep_running: true, status: 'running', exit_code: null, ended_at: null, preview_url: 'http://localhost:5173/', ...over })
const served = (...commands: Command[]): Item[] => servedOf(convState({ commands }))

test('a server’s page is framed from its own address and origin, with its scripts and forms - never moving the app nor opening windows; Reload, Open in browser and Stop', async () => {
  panel({ views: served(server('k1')) }, 'preview:k1')
  const frame = () => document.querySelector('iframe')!
  expect(frame()).toHaveAttribute('title', 'Preview of http://localhost:5173/')
  expect(frame()).toHaveAttribute('src', 'http://localhost:5173/')
  expect(frame().getAttribute('sandbox')).toBe('allow-scripts allow-same-origin allow-forms')
  expect(screen.getByRole('tab', { name: 'localhost:5173' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByRole('status')).toHaveTextContent('running')
  const link = screen.getByRole('link', { name: 'Open in browser' })
  expect(link).toHaveAttribute('href', 'http://localhost:5173/')
  expect(link).toHaveAttribute('target', '_blank')
  expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  await waitFor(() => expect(asked).toContain('GET /api/commands/k1/frame'))
  const before = frame()
  await userEvent.click(screen.getByRole('button', { name: 'Reload' }))
  expect(frame()).not.toBe(before)
  await userEvent.click(screen.getByRole('button', { name: 'Stop' }))
  expect(asked).toContain('POST /api/commands/k1/stop')
  // Previews, above the project's tree
  expect(treeItems().slice(0, 3)).toEqual(['Previews', 'localhost:5173 running', 'koloni'])
})

test('a server that does not allow being framed is not framed: it is offered in the browser', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(url.endsWith('/frame') ? { frameable: false } : []), { status: 200 })))
  panel({ views: served(server('k1')) }, 'preview:k1')
  expect(await screen.findByText('This server does not allow being shown here.')).toBeInTheDocument()
  expect(document.querySelector('iframe')).toBeNull()
  // (offered beside the words, as in the header)
  expect(screen.getAllByRole('link', { name: 'Open in browser' }).map(a => a.getAttribute('href'))).toEqual(['http://localhost:5173/', 'http://localhost:5173/'])
})

test('a server starting, stopped, or left when KOLONİ closed says so, and frames nothing', () => {
  const { unmount } = panel({ views: served(server('k1', { preview_url: null })) }, 'preview:k1')
  expect(screen.getByRole('status')).toHaveTextContent('starting…')
  expect(screen.getByText('Waiting for the address it serves on…')).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: 'npm run dev' })).toBeInTheDocument()
  unmount()
  panel({ views: served(server('k2', { status: 'killed' }), server('k3', { status: 'interrupted', preview_url: 'http://127.0.0.1:3000' })) }, 'preview:k3')
  expect(screen.getByRole('status')).toHaveTextContent('stopped when KOLONİ closed')
  expect(screen.getByText('It is not running any more.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Reload' })).not.toBeInTheDocument()
  expect(document.querySelector('iframe')).toBeNull()
  expect(treeItems().slice(0, 3)).toEqual(['Previews', '127.0.0.1:3000 stopped when KOLONİ closed', 'localhost:5173 stopped'])
})

test('no Preview button: a server opens Workspace by itself once its address is known, under Previews', async () => {
  const conv = opened()
  render(<ChatPanel />)
  expect(screen.queryByRole('button', { name: /^Preview/ })).not.toBeInTheDocument()
  // (what is there when the list is first read is not new)
  await waitFor(() => expect(asked).toContain('GET /api/conversations/c/views'), { timeout: 3000 })
  // starting, with no address yet: nothing to show - it is new on the button
  act(() => useApp.setState({ conv: { ...conv, commands: [server('k1', { preview_url: null })] } }))
  expect(await screen.findByRole('button', { name: 'Workspace new' })).toBeInTheDocument()
  expect(document.getElementById('files-window')).not.toBeVisible()
  act(() => useApp.setState({ conv: { ...conv, commands: [server('k1')] } }))
  await waitFor(() => expect(screen.getByRole('region', { name: 'Workspace' })).toBeVisible())
  expect(tabs()).toEqual(['localhost:5173'])
  expect(within(treeOf()).getByRole('treeitem', { name: /^localhost:5173/ })).toHaveAttribute('aria-selected', 'true')
  expect(treeItems()[0]).toBe('Previews')
})

test('a server on the app’s own port is never framed - it would be the app’s own origin; the status reads first', () => {
  panel({ views: served(server('k1', { preview_url: `http://localhost:${location.port}/` })) }, 'preview:k1')
  expect(document.querySelector('iframe')).toBeNull()
  expect(screen.getByText('It serves on KOLONİ’s own port: it is not shown here.')).toBeInTheDocument()
  expect(screen.getAllByRole('link', { name: 'Open in browser' })).toHaveLength(2)
  // (the status first: the address and who started it are what is cut short in a narrow header)
  expect(document.querySelector('.view-where p')!.firstElementChild).toHaveAttribute('role', 'status')
})

test('B-165: opened with nothing new or waiting - after a reload - it opens what the chat last showed; two tabs of one name say the folder', async () => {
  const shown = (id: string, path: string) => toolCall(id, 'r1', 'show', 'succeeded', JSON.stringify({ path }), { result: `shown: ${path} is in the view beside the chat` })
  useApp.setState({ conv: convState({ toolCalls: [shown('t1', 'notes.md'), shown('t2', 'game/index.html')] }) })
  const views = [view('v1', 'index.html', { status: 'applied' }), view('v2', 'game/index.html', { status: 'shown' }), view('v3', 'notes.md', { kind: 'md', status: 'shown' })]
  const { unmount } = panel({ views })
  expect(tabs()).toEqual(['index.html'])
  expect(screen.getByRole('tab', { name: 'index.html' })).toHaveAttribute('title', expect.stringMatching(/^game\/index\.html/))
  // The root's index.html beside it: the one in game/ says so.
  await userEvent.click(within(treeOf()).getAllByRole('treeitem', { name: /^index\.html/ }).find(item => item.getAttribute('title') === 'index.html')!)
  expect(tabs()).toEqual(['game/index.html', 'index.html'])
  unmount()
  // The file shown is not there any more: nothing is opened for it.
  panel({ views: [view('v2', 'game/index.html', { status: 'shown', sha: null })] })
  expect(screen.getByText('Pick a file in the tree.')).toBeInTheDocument()
})

test('B-187: the page the chat last showed opens on its preview, though changed - on its diff while that change waits', () => {
  const shown = toolCall('t1', 'r1', 'show', 'succeeded', JSON.stringify({ path: 'game/index.html' }), { result: 'shown: game/index.html is in the view beside the chat' })
  useApp.setState({ conv: convState({ toolCalls: [shown] }) })
  const at = (status: 'applied' | 'proposed') =>
    panel({ views: [view('v2', 'game/index.html', { status })], changes: [fileChange('f1', 'r1', { path: 'game/index.html', status })] })
  const { unmount } = at('applied')
  expect(screen.getByRole('button', { name: 'Preview' })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByRole('button', { name: 'Diff' })).toHaveAttribute('aria-pressed', 'false')
  unmount()
  at('proposed')
  expect(screen.getByRole('button', { name: 'Diff' })).toHaveAttribute('aria-pressed', 'true')
})

test('K-belge-ciktilari: an output asked for from the canvas opens on its preview, though changed; a pdf is the browser’s own viewer, in no sandbox, only once asked', async () => {
  const changes = [fileChange('f1', 'r1', { path: 'deck.html', status: 'applied' })]
  const { unmount } = panel({ views: [view('v1', 'deck.html', { status: 'applied' })], changes }, 'preview-of:deck.html')
  expect(screen.getByRole('button', { name: 'Preview' })).toHaveAttribute('aria-pressed', 'true')
  unmount()
  panel({ views: [view('v2', 'out/report.pdf', { kind: 'pdf', status: 'shown' })] }, 'preview-of:out/report.pdf')
  // (Not by itself: a flaw in the viewer would run as KOLONİ.)
  expect(document.querySelector('iframe')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Open the PDF preview' }))
  const frame = document.querySelector('iframe')!
  expect(frame.getAttribute('src')).toBe('/api/conversations/c1/views/v2/report.pdf?v=sha-v2-shown')
  expect(frame.hasAttribute('sandbox')).toBe(false)
  expect(screen.queryByRole('button', { name: 'Run once' })).toBeNull()
  // A link in it the frame followed - a second load - takes it off.
  fireEvent.load(frame)
  expect(document.querySelector('iframe')).not.toBeNull()
  fireEvent.load(frame)
  expect(document.querySelector('iframe')).toBeNull()
  expect(screen.getByText('The PDF tried to go elsewhere; it was stopped.')).toBeInTheDocument()
})

test('K-belge-ciktilari: a Word document, a workbook or a deck is drawn in the document viewer’s frame of no origin', () => {
  for (const [name, kind] of [['plan.docx', 'docx'], ['sums.xlsx', 'xlsx'], ['deck.pptx', 'pptx']] as const) {
    const { unmount } = panel({ views: [view(name, name, { kind, status: 'shown' })] }, `preview-of:${name}`)
    const frame = screen.getByTitle(`Document ${name}`)
    expect(frame).toHaveAttribute('sandbox', 'allow-scripts')
    expect(frame).toHaveAttribute('src', '/office/viewer.html')
    unmount()
  }
})

// --- the Changes tab (K-degisenler)---------------------------------------------------------------

const listTabs = () => within(screen.getByRole('tablist', { name: 'Show' })).getAllByRole('tab')

/** The Changes tree's rows as a screen reader names them; an agent's line with its time as `T`. */
const changeItems = () => within(screen.getByRole('tree', { name: 'Changes' })).getAllByRole('treeitem').map(i => (i.getAttribute('aria-label') ?? '').replace(/^[^·]*\d:\d\d[^·]* · /, 'T · '))

test('K-degisenler, sample A: Changes groups what changed by what you have to do - this chat’s under its agent, git’s other files on their own - in words, no letters; a click opens the diff against HEAD; the count is in the label', async () => {
  gitChanges = [
    { path: 'src/a.py', status: 'M' },
    { path: 'new.txt', status: '?' },
    { path: 'gone.txt', status: 'D' },
  ]
  gitDiffs = { 'new.txt': '@@ -0,0 +1 @@\n+fresh\n' }
  texts['new.txt'] = { text: 'fresh\n' }
  panel({ changes: [fileChange('f1', 'r1', { path: 'src/a.py', status: 'applied' })] })
  // (no count till git answered)
  await waitFor(() => expect(listTabs().map(t => t.textContent)).toEqual(['Files', 'Changes · 3']))
  expect(screen.getByRole('tree', { name: 'Files' })).toBeInTheDocument()
  await userEvent.click(listTabs()[1])
  expect(screen.getByRole('status')).toHaveTextContent("This chat's work, and what git sees changed in koloni since the last commit.")
  expect(changeItems()).toEqual(['In the project · 1', 'T · Lead', 'a.py in src changed', 'Not by an agent · 2', 'gone.txt deleted', 'new.txt new, not in git'])
  const tree = screen.getByRole('tree', { name: 'Changes' })
  expect(within(tree).getByRole('treeitem', { name: 'In the project · 1' })).toHaveAttribute('aria-level', '1')
  const row = within(tree).getByRole('treeitem', { name: /^a\.py/ })
  expect(row).toHaveAttribute('aria-level', '3')
  expect(row.querySelector('.tree-where')).toHaveTextContent('src')
  expect(row.querySelector('.tree-meta')).toHaveTextContent('changed')
  expect(tree.textContent).not.toMatch(/\b[MADR?]\b/)
  expect(JSON.parse(localStorage.getItem('koloni-files-list') ?? '')).toBe('changes')
  await userEvent.click(within(tree).getByRole('treeitem', { name: /^new\.txt/ }))
  expect(tabs()).toEqual(['new.txt'])
  expect(await screen.findByText('fresh')).toBeInTheDocument()
  expect(asked).toContain('GET /api/projects/p/changes/diff?path=new.txt')
  expect(document.querySelector('.diff-add')).not.toBeNull()
  // Back to the files from the keyboard; the tab is remembered. From Files the same file is its code, as VS Code's
  // Explorer opens it - the diff is Changes' own.
  listTabs()[1].focus()
  await userEvent.keyboard('{ArrowLeft}')
  expect(listTabs()[0]).toHaveAttribute('aria-selected', 'true')
  expect(listTabs()[0]).toHaveFocus()
  expect(screen.getByRole('tree', { name: 'Files' })).toBeInTheDocument()
  expect(JSON.parse(localStorage.getItem('koloni-files-list') ?? '')).toBe('files')
  expect(await screen.findByText('fresh')).toBeInTheDocument()
  expect(asked).toContain('GET /api/projects/p/file?path=new.txt')
  expect(document.querySelector('.diff-add')).toBeNull()
})

test('K-degisenler, sample A: with no git, Changes is this chat’s own record and says so plainly; Closed starts shut; nothing changed says so', async () => {
  localStorage.setItem('koloni-files-list', JSON.stringify('changes'))
  // (an agent's write into the scratch, .koloni/tmp/, is in no list of what changed: K-koloni-klasor)
  const scratch = fileChange('f3', 'r1', { path: '.koloni/tmp/a.txt' })
  const { rerender } = panel({ changes: [fileChange('f1', 'r1', { path: 'src/a.py', status: 'proposed' }), fileChange('f2', 'r1', { path: 'old.txt', status: 'rejected', diff: '+b' }), scratch] })
  // (what is closed is not counted)
  await waitFor(() => expect(listTabs()[1]).toHaveTextContent('Changes · 1'))
  expect(screen.getByRole('status')).toHaveTextContent("No git here, or it did not answer in time: this is what this chat's agents changed.")
  expect(changeItems()).toEqual(['Waits for you · 1', 'T · Lead', 'a.py in src changed', 'Closed · 1'])
  const closed = within(screen.getByRole('tree', { name: 'Changes' })).getByRole('treeitem', { name: 'Closed · 1' })
  expect(closed).toHaveAttribute('aria-expanded', 'false')
  await userEvent.click(closed)
  expect(changeItems()).toEqual(['Waits for you · 1', 'T · Lead', 'a.py in src changed', 'Closed · 1', 'T · Lead', 'old.txt changed, you said no'])
  expect(JSON.parse(localStorage.getItem('koloni-changes-open') ?? '')).toEqual({ '/Closed': true })
  // (what waits for you opens on its diff, with its decision there)
  await userEvent.click(within(screen.getByRole('tree', { name: 'Changes' })).getByRole('treeitem', { name: /^a\.py/ }))
  expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument()
  rerender(<FilesWindow {...props({ changes: [] })} />)
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Nothing changed.'))
  expect(listTabs()[1]).toHaveTextContent('Changes · 0')
})

test('K-degisenler, sample A: "Show folders as a tree" puts the files in their folders, open at first, a shut one remembered in this browser; unticked, each file has its folder after it; the count stays', async () => {
  localStorage.setItem('koloni-files-list', JSON.stringify('changes'))
  gitChanges = [
    { path: 'src/a.py', status: 'M' },
    { path: 'new.txt', status: '?' },
    { path: 'src/sub/b.py', status: 'A' },
  ]
  panel()
  await waitFor(() => expect(listTabs()[1]).toHaveTextContent('Changes · 3'))
  const asTree = screen.getByRole('checkbox', { name: 'Show folders as a tree' })
  expect(asTree).not.toBeChecked()
  expect(changeItems()).toEqual(['Not by an agent · 3', 'a.py in src changed', 'b.py in src/sub new', 'new.txt new, not in git'])
  const rows = () => within(screen.getByRole('tree', { name: 'Changes' })).getAllByRole('treeitem')
  await userEvent.click(asTree)
  expect(changeItems()).toEqual(['Not by an agent · 3', 'src', 'sub', 'b.py new', 'a.py changed', 'new.txt new, not in git'])
  expect(rows()[1]).toHaveAttribute('aria-expanded', 'true')
  expect(rows()[3]).toHaveAttribute('aria-level', '4')
  expect(listTabs()[1]).toHaveTextContent('Changes · 3')
  expect(JSON.parse(localStorage.getItem('koloni-changes-shape') ?? '')).toBe('tree')
  await userEvent.click(within(screen.getByRole('tree', { name: 'Changes' })).getByRole('treeitem', { name: 'sub' }))
  expect(changeItems()).toEqual(['Not by an agent · 3', 'src', 'sub', 'a.py changed', 'new.txt new, not in git'])
  expect(JSON.parse(localStorage.getItem('koloni-changes-open') ?? '')).toEqual({ '/Not by an agent/src/sub': false })
  await userEvent.click(asTree)
  expect(changeItems()).toEqual(['Not by an agent · 3', 'a.py in src changed', 'b.py in src/sub new', 'new.txt new, not in git'])
})


test('K-devir-4: over an opened file, the last agents on it - each a link to the agent, or to its chat when another; nothing where KOLONİ has nothing on record', async () => {
  useApp.setState({ conv: convState() })
  const one = (over: Partial<FileHistory>): FileHistory => ({ at: '2026-10-29T09:12:00Z', agent_id: 'a1', agent_role: 'Coder', agent_name: '', conversation_id: 'c', conversation_title: 'Fix greeting', kind: 'modify', status: 'taken in', ...over })
  history = { 'hello.py': [one({}), one({ agent_id: 'a2', agent_role: 'Reviewer', agent_name: 'Reviewer 2', conversation_id: 'c2', conversation_title: 'Other', status: 'discarded' })] }
  panel()
  await userEvent.click(await within(treeOf()).findByRole('treeitem', { name: 'hello.py' }))
  const line = await screen.findByText(/^Last on this file:/)
  expect(line).toHaveTextContent(/^Last on this file: Coder \d\d:\d\d[^(]*\(modified, taken in\) · Reviewer 2 \d\d:\d\d[^(]*in chat Other \(modified, discarded\)$/)
  expect(within(line).getAllByRole('button').map(b => b.textContent)).toEqual([expect.stringMatching(/^Coder /), expect.stringMatching(/^Reviewer 2 /)])
  await userEvent.click(within(line).getByRole('button', { name: /^Coder/ }))
  expect(useApp.getState().selectedNodeId).toBe('agent:a1')
  expect(asked.filter(a => a.includes('/file-history'))).toEqual(['GET /api/projects/p/file-history?path=hello.py'])
  await userEvent.click(within(treeOf()).getByRole('treeitem', { name: 'README.md' }))
  await waitFor(() => expect(asked).toContain('GET /api/projects/p/file-history?path=README.md'))
  expect(screen.queryByText(/^Last on this file:/)).not.toBeInTheDocument()
})

test('K-dallar: on a branch it reads that branch from git, read only - its tree, its code (no preview), its changes - and nothing of the chat', async () => {
  disk[''].push(entry('page.html'))
  gitChanges = [{ path: 'hello.py', status: 'M' }]
  gitDiffs['hello.py'] = "@@ -1 +1 @@\n-print('hi')\n+print('bye')\n"
  const written = view('v1', 'page.html')
  panel({ branch: 'refs/heads/feature', views: [written], changes: [fileChange('f1', 'r1', { path: 'README.md', status: 'proposed' })] }, 'page.html')
  expect(await screen.findByText('feature')).toBeInTheDocument()
  expect(screen.getByRole('status', { name: '' })).toHaveTextContent('feature · read only')
  await waitFor(() => expect(asked).toContain('GET /api/projects/p/files?path=&ref=refs%2Fheads%2Ffeature'))
  expect(asked).toContain('GET /api/projects/p/changes?ref=refs%2Fheads%2Ffeature')
  // (the page opens on its code from the branch: no preview, no Preview | Code, no line of who last worked on it)
  await waitFor(() => expect(asked).toContain('GET /api/projects/p/file?path=page.html&ref=refs%2Fheads%2Ffeature'))
  expect(screen.queryByRole('button', { name: 'Preview' })).toBeNull()
  expect(asked.some(one => one.includes('/file-history') || one.includes('/raw/'))).toBe(false)
  // (the chat's change waits for nobody here)
  expect(screen.queryByText('1 file waits')).toBeNull()
  await userEvent.click(screen.getByRole('tab', { name: /Changes/ }))
  await userEvent.click(await within(screen.getByRole('tree', { name: 'Changes' })).findByRole('treeitem', { name: /hello\.py/ }))
  await waitFor(() => expect(asked).toContain('GET /api/projects/p/changes/diff?path=hello.py&ref=refs%2Fheads%2Ffeature'))
  await userEvent.click(screen.getByRole('button', { name: 'Back to the project' }))
  expect(useApp.getState().filesRef).toBeNull()
})

test('K-dallar: the project switched to another branch, the Workspace reads its folders again - not what it read on the one before', async () => {
  opened()
  render(<ChatPanel />)
  act(() => useApp.getState().openFiles())
  await waitFor(() => expect(asked.filter(one => one === 'GET /api/projects/p/files?path=')).toHaveLength(1))
  act(() => useApp.setState({ gitBranch: 'feature' }))
  await waitFor(() => expect(asked.filter(one => one === 'GET /api/projects/p/files?path=')).toHaveLength(2))
})

test('B-342: a change done with that changes nothing is no diff to open on: the page opens as it is', () => {
  const written = view('v2', 'site/page.html')
  render(<FilesWindow {...props({ views: [written], changes: [fileChange('f1', 'r1', { path: 'site/page.html', status: 'rejected', diff: '', additions: 0, deletions: 0 })], at: { key: 'site/page.html', n: 1 } })} />)
  expect(screen.queryByText('No textual difference.')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Diff' })).toBeNull()
  expect(document.querySelector('iframe')).not.toBeNull()
})

test('B-338: a file added outside KOLONİ is in the tree once the user comes back to the page - read again at most every 2 s', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true, toFake: ['Date'] })
  panel()
  await within(treeOf()).findByRole('treeitem', { name: 'hello.py' })
  disk[''] = [...disk[''], entry('outside.txt')]
  act(() => window.dispatchEvent(new Event('focus')))
  expect(within(treeOf()).queryByRole('treeitem', { name: 'outside.txt' })).toBeNull() // (just opened: not yet)
  vi.setSystemTime(Date.now() + 3000)
  act(() => window.dispatchEvent(new Event('focus')))
  expect(await within(treeOf()).findByRole('treeitem', { name: 'outside.txt' })).toBeInTheDocument()
  vi.useRealTimers()
})

test('K-degisenler, sample A: the lines of a group go by when your message came - across days, whatever the clock writes', async () => {
  localStorage.setItem('koloni-files-list', JSON.stringify('changes'))
  const asked = (run: string, at: string) => ({ id: run, conversation_id: 'c', run_id: run, agent_id: null, role: 'user', content: run, created_at: at, status: 'complete' }) as never
  // (as text, "01:05 PM" or "13:05" of the next day sorts before "11:00 PM" or "23:00" of the day before)
  useApp.setState({ conv: convState({ messages: [asked('late', '2026-11-07T11:05:00Z'), asked('early', '2026-11-06T21:00:00Z')] }) })
  panel({ changes: [fileChange('l', 'late', { agent_id: 'r1', path: 'l.py', status: 'proposed' }), fileChange('e', 'early', { agent_id: 'r1', path: 'e.py', status: 'proposed' })] })
  await waitFor(() => expect(changeItems()).toEqual(['Waits for you · 2', 'T · Lead · “early”', 'e.py changed', 'T · Lead · “late”', 'l.py changed']))
})

test('K-degisenler, sample A: with git, the count is what git lists - as the top bar counts it', async () => {
  gitChanges = [{ path: 'a.py', status: 'M' }, { path: 'b.py', status: 'M' }]
  panel({ changes: [fileChange('p', 'r1', { path: 'c.py', status: 'proposed' })] })
  await waitFor(() => expect(listTabs()[1]).toHaveTextContent('Changes · 2'))
})

test('K-degisenler, sample A: a copy that waits, or was kept, opens on what it holds, with the way to its card', async () => {
  localStorage.setItem('koloni-files-list', JSON.stringify('changes'))
  const merge = (status: string, kept_in: string | null) => ({ id: `g-${status}`, run_id: 'r1', agent_id: 'c', status, files: [], kept_in, created_at: 't', decided_at: null }) as never
  const coder = agent('r1', 'completed', { id: 'c', name: 'Coder', copy: { state: 'own' } })
  for (const [held, button] of [[merge('pending', null), 'Take in…'], [merge('kept', 'C:/kept'), 'Look']] as const) {
    useApp.setState({ conv: convState({ merges: [held] }), selectedNodeId: null })
    const { unmount } = panel({ agents: [lead, coder] })
    await userEvent.click(await within(screen.getByRole('tree', { name: 'Changes' })).findByRole('treeitem', { name: /^Coder's copy/ }))
    expect(await screen.findByRole('region', { name: 'a.txt' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: button }))
    expect(useApp.getState().selectedNodeId).toBe('agent:c')
    unmount()
  }
})
