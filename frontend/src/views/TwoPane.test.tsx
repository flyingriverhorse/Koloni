import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { type TreeFile, TwoPane } from './TwoPane'

const files: TreeFile[] = [
  { id: '1', path: 'Artifacts/site/index.html', title: 'site/index.html · by Lead', meta: 'proposed', dot: true },
  { id: '2', path: 'Artifacts/notes.md', title: 'notes.md · by Lead', meta: 'shown' },
  { id: '3', path: 'Images/chart.png', title: 'chart.png · by Coder', meta: 'shown' },
]
/** The tree with its folders open till closed: which are open is the caller's (slice 42c). */
function Tree(more: Partial<Parameters<typeof TwoPane>[0]>) {
  const [open, setOpen] = useState<Record<string, boolean>>({})
  return (
    <TwoPane name="t" files={files} selected="1" onOpen={() => {}} isOpen={key => open[key] ?? true} onFolder={(key, now) => setOpen(was => ({ ...was, [key]: now }))} {...more}>
      <p>the content</p>
    </TwoPane>
  )
}
const pane = (more: Partial<Parameters<typeof TwoPane>[0]> = {}) => render(<Tree {...more} />)
const items = () => screen.getAllByRole('treeitem')
const item = (name: string | RegExp) => screen.getByRole('treeitem', { name })

beforeEach(() => localStorage.clear())
afterEach(() => vi.restoreAllMocks())

test('the files are a tree by their folders: each with its state, a dot when new, and who wrote it on hover', () => {
  pane()
  const tree = screen.getByRole('tree', { name: 'Files' })
  expect(within(tree).getAllByRole('treeitem').map(i => i.textContent)).toEqual(['Artifacts', 'site', 'index.htmlproposed', 'notes.mdshown', 'Images', 'chart.pngshown'])
  expect(item('Artifacts')).toHaveAttribute('aria-expanded', 'true')
  expect(item('Artifacts')).toHaveAttribute('aria-level', '1')
  expect(item(/^index\.html/)).toHaveAttribute('aria-level', '3')
  expect(item(/^index\.html/)).not.toHaveAttribute('aria-expanded')
  expect(item(/^index\.html/)).toHaveAccessibleName('index.html new proposed')
  expect(item(/^index\.html/)).toHaveAttribute('title', 'site/index.html · by Lead')
  expect(item(/^index\.html/)).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByText('the content')).toBeInTheDocument()
})

test('the keyboard: one stop in the tab order; up and down move, right and left open and close or go in and out, Enter opens', async () => {
  const onOpen = vi.fn()
  pane({ onOpen })
  // (one item takes the tab stop: the one open)
  expect(items().filter(i => i.tabIndex === 0)).toEqual([item(/^index\.html/)])
  item(/^index\.html/).focus()
  await userEvent.keyboard('{ArrowDown}')
  expect(item(/^notes\.md/)).toHaveFocus()
  await userEvent.keyboard('{Enter}')
  expect(onOpen).toHaveBeenLastCalledWith('2')
  await userEvent.keyboard('{ArrowUp}{ArrowUp}')
  expect(item('site')).toHaveFocus()
  await userEvent.keyboard('{ArrowLeft}')
  expect(item('site')).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByRole('treeitem', { name: /^index\.html/ })).not.toBeInTheDocument()
  await userEvent.keyboard('{ArrowLeft}')
  expect(item('Artifacts')).toHaveFocus()
  await userEvent.keyboard('{ArrowRight}')
  expect(item('site')).toHaveFocus()
  await userEvent.keyboard('{ArrowRight}')
  expect(item('site')).toHaveAttribute('aria-expanded', 'true')
  await userEvent.keyboard('{ArrowRight}')
  expect(item(/^index\.html/)).toHaveFocus()
  await userEvent.keyboard('{End}')
  expect(item(/^chart\.png/)).toHaveFocus()
  await userEvent.keyboard('{Home}')
  expect(item('Artifacts')).toHaveFocus()
  expect(items().filter(i => i.tabIndex === 0)).toEqual([item('Artifacts')])
  // a click opens a file, and a folder opens or closes
  await userEvent.click(item(/^chart\.png/))
  expect(onOpen).toHaveBeenLastCalledWith('3')
  await userEvent.click(item('Images'))
  expect(item('Images')).toHaveAttribute('aria-expanded', 'false')
})

test('a file opened from outside has its folders opened; a folder closed after stays closed', async () => {
  const { rerender } = pane({ selected: '3' })
  await userEvent.click(item('site'))
  expect(item('site')).toHaveAttribute('aria-expanded', 'false')
  rerender(<Tree selected="1" />)
  expect(item('site')).toHaveAttribute('aria-expanded', 'true')
  expect(item(/^index\.html/)).toHaveAttribute('aria-selected', 'true')
  await userEvent.click(item('site'))
  rerender(<Tree selected="1" files={[...files]} />)
  expect(item('site')).toHaveAttribute('aria-expanded', 'false')
})

test('a folder is one though nothing in it is read yet; below the top folders come first, by name; a changed file dots its folders, in words too', () => {
  const tree: TreeFile[] = [
    { id: '/koloni', path: 'koloni', folder: true, title: '', meta: '' },
    { id: 'b.py', path: 'koloni/b.py', title: 'b.py', meta: '' },
    { id: '/koloni/empty', path: 'koloni/empty', folder: true, title: '', meta: '' },
    { id: 'src/a.py', path: 'koloni/src/a.py', title: 'src/a.py', meta: 'modified, Waits for you', changed: true },
    { id: 'A.md', path: 'koloni/A.md', title: 'A.md', meta: '' },
  ]
  pane({ files: tree, selected: undefined, isOpen: key => key !== '/koloni/empty' })
  expect(items().map(i => i.textContent)).toEqual(['koloni', 'empty', 'src', 'a.pymodified, Waits for you', 'A.md', 'b.py'])
  expect(item('empty')).toHaveAttribute('aria-expanded', 'false')
  expect(item('koloni changed')).toHaveAttribute('aria-level', '1')
  expect(item('src changed').querySelector('.tree-changed')).not.toBeNull()
  expect(item('empty').querySelector('.tree-changed')).toBeNull()
  expect(item('a.py modified, Waits for you')).toHaveAttribute('aria-level', '3')
})

test('the files can be hidden and shown by a button, and made wider or narrower by their edge - and the width is kept', async () => {
  const { unmount } = pane()
  await userEvent.click(screen.getByRole('button', { name: 'Hide files' }))
  expect(screen.queryByRole('tree')).not.toBeInTheDocument()
  expect(screen.getByText('the content')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Show files' }))
  const edge = screen.getByRole('separator', { name: 'Resize files' })
  const was = Number(edge.getAttribute('aria-valuenow'))
  edge.focus()
  await userEvent.keyboard('{ArrowRight}')
  expect(Number(edge.getAttribute('aria-valuenow'))).toBe(was + 16)
  unmount()
  pane()
  expect(Number(screen.getByRole('separator', { name: 'Resize files' }).getAttribute('aria-valuenow'))).toBe(was + 16)
  // dragged to almost nothing, they are hidden
  const drag = screen.getByRole('separator', { name: 'Resize files' })
  fireEvent.pointerDown(drag, { pointerId: 1, button: 0, clientX: 200 })
  fireEvent.pointerMove(drag, { pointerId: 1, clientX: 20 })
  fireEvent.pointerUp(drag, { pointerId: 1, clientX: 20 })
  expect(screen.queryByRole('tree')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Show files' })).toBeInTheDocument()
})

test('in a narrow window the files are hidden at first, a button away', async () => {
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(400)
  pane()
  expect(screen.queryByRole('tree')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Show files' }))
  expect(screen.getByRole('tree', { name: 'Files' })).toBeInTheDocument()
})

test('the files are never wider than the window leaves them, whatever width was kept; a hidden pane hands the focus to the button that shows it, and back', async () => {
  localStorage.setItem('koloni-t-files-width', '900')
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(600)
  pane()
  const edge = screen.getByRole('separator', { name: 'Resize files' })
  expect(edge).toHaveAttribute('aria-valuenow', '440')
  expect(edge).toHaveAttribute('aria-valuemax', '440')
  expect(screen.getByRole('tree').parentElement).toHaveStyle({ width: '440px' })
  await userEvent.click(screen.getByRole('button', { name: 'Hide files' }))
  expect(screen.getByRole('button', { name: 'Show files' })).toHaveFocus()
  await userEvent.click(screen.getByRole('button', { name: 'Show files' }))
  expect(screen.getByRole('button', { name: 'Hide files' })).toHaveFocus()
})

test('what is shown beside a name can be a mark of its own; the words are still its name and on hover', () => {
  render(
    <TwoPane name="t" files={[{ id: '1', path: 'a.py', title: 'a.py · Applied', meta: '+1 −0 Applied', mark: <span className="tree-mark">●</span> }]} selected="1" onOpen={() => {}} isOpen={() => true} onFolder={() => {}}>
      <p />
    </TwoPane>,
  )
  expect(item('a.py +1 −0 Applied')).toHaveTextContent(/^a\.py●$/)
})
