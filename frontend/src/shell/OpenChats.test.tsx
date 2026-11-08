import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import type { Board, FolderBrowse, ListedConversation, Project } from '../api/types'
import { boardTurn, convState } from '../test-fixtures'
import { OpenChats } from './OpenChats'
import { ADD_W, MORE_W, TAB_MIN } from './openTabs'

type BoardConversation = Board['conversations'][number]
const listed = (id: string, title: string, project_id: string | null = null): ListedConversation => ({ ...convState().conversation, id, title, project_id, kept: false, backlog_task: null, wrote: false })
const onBoard = (id: string, over: Partial<BoardConversation> = {}): BoardConversation => ({ conversation_id: id, title: id, agents: [], merges_pending: 0, turn: null, ...over })
const folder = (id: string, name: string) => ({ id, name, root_path: `C:\\work\\${name}`, created_at: '2026-10-01T00:00:00Z' }) as Project
const projects = [folder('p', 'greeter'), folder('q', 'docs')]
const conversations = [listed('a', 'Fix the greeting', 'p'), listed('b', 'Write the docs'), listed('c', 'Tidy the tests', 'q')]
const board = {
  conversations: [onBoard('a', { turn: boardTurn('r', 'completed', 't') }), onBoard('b', { merges_pending: 1 }), onBoard('c', { turn: boardTurn('s', 'running', null) })],
  backlog_waiting: 0,
} as unknown as Board

function tabs(over: Partial<Parameters<typeof OpenChats>[0]> = {}) {
  const on = {
    onOpen: vi.fn(),
    onClose: vi.fn(),
    onOpenFolder: vi.fn(async (path: string) => folder('new', path.split('\\').at(-1)!)),
    onBrowse: vi.fn(async (path: string | null): Promise<FolderBrowse> => ({ path: path ?? 'C:\\work', parts: [{ name: 'C:\\', path: 'C:' }, { name: 'work', path: 'C:\\work' }], shortcuts: [], entries: [], more: false })),
  }
  render(
    <div className="app">
      <OpenChats tabs={['p', 'none', 'q']} conversations={conversations} projects={projects} board={board} openTab="p" {...on} {...over} />
    </div>,
  )
  return on
}

afterEach(() => vi.unstubAllGlobals())

test('each tab is a project: its folder\'s name, or "No folder", and how its chats stand; one where a chat waits for you is orange', () => {
  tabs()
  const list = screen.getByRole('tablist', { name: 'Open projects' })
  const [p, none, q] = within(list).getAllByRole('tab')
  expect(p).toHaveAccessibleName('greeter')
  expect(p).toHaveTextContent(/^greeter$/)
  expect(p).toHaveAttribute('aria-selected', 'true')
  expect(none).toHaveAccessibleName('No folder, waits for you')
  expect(q).toHaveAccessibleName('docs, working')
  expect(none.parentElement).toHaveClass('open-chat-waits')
  expect(p.parentElement).not.toHaveClass('open-chat-waits')
  // the dot in its state's colour; the word is read out, not drawn
  expect(none.querySelector('.open-chat-dot')).toHaveStyle({ background: 'var(--warn)' })
  expect(p.querySelector('.open-chat-dot')).toHaveStyle({ background: 'var(--muted)' })
  expect(list).not.toHaveTextContent('waits for you')
})

test('a click goes to a tab\'s project; its × closes the tab, no chat', async () => {
  const on = tabs()
  await userEvent.click(screen.getByRole('tab', { name: /^No folder/ }))
  expect(on.onOpen).toHaveBeenCalledWith('none')
  // the open one is not read again
  await userEvent.click(screen.getByRole('tab', { name: 'greeter' }))
  expect(on.onOpen).toHaveBeenCalledTimes(1)
  await userEvent.click(screen.getByRole('button', { name: 'Close docs' }))
  expect(on.onClose).toHaveBeenCalledWith('q')
})

test('the tabs are one tab stop: the arrows, Home and End move along them, Enter opens one, Delete closes it; the open one\'s × comes next', async () => {
  const on = tabs()
  await userEvent.tab()
  const [p, none, q] = screen.getAllByRole('tab')
  expect(p).toHaveFocus()
  await userEvent.keyboard('{ArrowRight}')
  expect(none).toHaveFocus()
  // (the focus only: opening one reads a chat and draws its canvas)
  expect(on.onOpen).not.toHaveBeenCalled()
  await userEvent.keyboard('{End}')
  expect(q).toHaveFocus()
  await userEvent.keyboard('{ArrowRight}')
  expect(p).toHaveFocus()
  await userEvent.keyboard('{ArrowLeft}{Home}{ArrowRight}{Enter}')
  expect(on.onOpen).toHaveBeenCalledWith('none')
  await userEvent.keyboard('{Delete}')
  expect(on.onClose).toHaveBeenCalledWith('none')
  // (not the open one's: the focus goes to the open one)
  await waitFor(() => expect(p).toHaveFocus())
  await userEvent.tab()
  expect(screen.getByRole('button', { name: 'Close greeter' })).toHaveFocus()
})

test('with no tabs there is no row; the last one closed, its chat still open, leaves "+"', async () => {
  const { container } = render(<OpenChats tabs={[]} conversations={conversations} projects={[]} board={null} openTab={null} onOpen={() => {}} onClose={() => {}} onOpenFolder={vi.fn()} onBrowse={vi.fn()} />)
  expect(container).toBeEmptyDOMElement()
  const on = tabs({ tabs: [] })
  expect(screen.queryByRole('tab')).toBeNull()
  // Its folder browser, cancelled, gives the focus back to "+".
  await userEvent.click(screen.getByRole('button', { name: 'Go to another folder' }))
  await userEvent.click(within(screen.getByRole('dialog', { name: 'Go to another folder' })).getByRole('button', { name: 'Open a folder…' }))
  const browser = await screen.findByRole('dialog', { name: 'Open a folder' })
  expect(on.onBrowse).toHaveBeenCalled()
  await userEvent.click(within(browser).getByRole('button', { name: 'Cancel' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Go to another folder' })).toHaveFocus())
})

test('"+" offers the recent folders, "No folder" and "Open a folder…"; one picked, or one opened from the browser, is gone to', async () => {
  const on = tabs()
  await userEvent.click(screen.getByRole('button', { name: 'Go to another folder' }))
  const panel = screen.getByRole('dialog', { name: 'Go to another folder' })
  // (the open tab's folder is not offered)
  expect(within(panel).getAllByRole('button').map(b => b.textContent)).toEqual([expect.stringMatching(/^docsC:\\work\\docs · /), 'Open a folder…', 'No folder · a plain chat'])
  await userEvent.click(within(panel).getByRole('button', { name: /^docs/ }))
  expect(on.onOpen).toHaveBeenLastCalledWith('q')
  expect(screen.queryByRole('dialog')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Go to another folder' }))
  await userEvent.click(within(screen.getByRole('dialog', { name: 'Go to another folder' })).getByRole('button', { name: /^No folder/ }))
  expect(on.onOpen).toHaveBeenLastCalledWith('none')

  await userEvent.click(screen.getByRole('button', { name: 'Go to another folder' }))
  await userEvent.click(within(screen.getByRole('dialog', { name: 'Go to another folder' })).getByRole('button', { name: 'Open a folder…' }))
  const browser = await screen.findByRole('dialog', { name: 'Open a folder' })
  // beside the open tab's folder
  expect(on.onBrowse).toHaveBeenCalledWith('C:\\work')
  await userEvent.click(within(browser).getByRole('button', { name: 'Open "work"' }))
  expect(on.onOpenFolder).toHaveBeenCalledWith('C:\\work')
  expect(on.onOpen).toHaveBeenLastCalledWith('new')
  expect(screen.queryByRole('dialog')).toBeNull()
})

test('the tabs with no room are in a "+N" list, orange when one of them waits; the open tab stays in the row, and "+" beside them', async () => {
  let resized: (width: number) => void = () => {}
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(on: (entries: { contentRect: { width: number } }[]) => void) {
        resized = width => on([{ contentRect: { width } }])
      }
      observe() {}
      disconnect() {}
    },
  )
  const on = tabs({ openTab: 'q' })
  act(() => resized(TAB_MIN + MORE_W + ADD_W))
  expect(screen.getAllByRole('tab').map(tab => tab.textContent)).toEqual(['docs'])
  const more = screen.getByRole('button', { name: '2 more open projects' })
  expect(more).toHaveTextContent('+2')
  expect(more).toHaveClass('open-chat-waits')
  expect(screen.getByRole('button', { name: 'Go to another folder' })).toBeInTheDocument()
  await userEvent.click(more)
  const list = screen.getByRole('dialog', { name: 'More open projects' })
  await userEvent.click(within(list).getByRole('button', { name: /^No folder/ }))
  expect(on.onOpen).toHaveBeenCalledWith('none')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})
