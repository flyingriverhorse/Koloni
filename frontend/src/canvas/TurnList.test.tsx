import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { RECENT, TurnList } from './TurnList'
import { type TurnRow, when } from './turns'

const row = (runId: string, over: Partial<TurnRow> = {}): TurnRow => ({
  runId,
  unattended: false,
  text: `say ${runId}`,
  triggerName: null,
  agents: 0,
  files: 0,
  ended: 'done',
  waits: false,
  kept: false,
  at: '2026-10-05T10:00:00Z',
  ...over,
})
const nightly = (runId: string, over: Partial<TurnRow> = {}) => row(runId, { unattended: true, triggerName: 'Nightly look', ...over })

function list(rows: TurnRow[], current: string | null, over: Partial<Parameters<typeof TurnList>[0]> = {}) {
  return <TurnList rows={rows} current={current} onPick={() => {}} {...over} />
}
/** Drawn, and opened from its button in the top bar. */
function show(element: ReturnType<typeof list>) {
  const drawn = render(element)
  fireEvent.click(screen.getByRole('button', { name: /^Recent/ }))
  return drawn
}
const panel = () => screen.getByRole('complementary', { name: 'Recent' })
const rows = () => Array.from(panel().querySelectorAll<HTMLElement>('.turn-row'))

test('slice 107: Recent lists the last five messages, newest first - when, what was asked, its work, how it stands - and says where the older ones are', () => {
  const at = (n: number) => `2026-10-05T1${n}:00:00Z`
  const all = Array.from({ length: 7 }, (_, n) => row(`m${n + 1}`, { at: at(n) }))
  all[5] = row('m6', { at: at(5), text: 'add a test', agents: 2, files: 3, ended: 'failed' })
  show(list(all, 'm6'))
  expect(RECENT).toBe(5)
  expect(rows().map(b => b.textContent)).toEqual([
    `say m7${when(at(6))}done`,
    `add a test${when(at(5))}2 agents · 3 filesfailed`,
    `say m5${when(at(4))}done`,
    `say m4${when(at(3))}done`,
    `say m3${when(at(2))}done`,
  ])
  // how each ended is said by the one label a state has everywhere: its word, in its colour
  expect(rows()[1].querySelector<HTMLElement>('.status')!.style.color).toBe('var(--del)')
  // the one the canvas draws is marked, and only that one
  expect(rows().map(b => b.getAttribute('aria-current'))).toEqual([null, 'true', null, null, null])
  expect(within(panel()).getByText('Older ones: in the chat, from a message’s ⋯')).toBeInTheDocument()
})

test('with five or fewer there is nothing older to point to; a message a trigger sent goes by the trigger’s name', () => {
  show(list([row('a'), nightly('n', { ended: 'working' })], 'a'))
  expect(rows().map(b => b.textContent)).toEqual([`Nightly look${when('2026-10-05T10:00:00Z')}working`, `say a${when('2026-10-05T10:00:00Z')}done`])
  expect(screen.queryByText(/Older ones/)).toBeNull()
})

test('a message in which something waits, or whose changes were kept, says so on its row - and the button says something waits', () => {
  render(list([row('a', { waits: true, ended: 'working' }), row('b', { kept: true })], 'b'))
  const button = screen.getByRole('button', { name: /^Recent/ })
  expect(within(button).getByRole('img', { name: 'something waits for you' })).toBeInTheDocument()
  fireEvent.click(button)
  const [newer, older] = rows()
  expect(within(newer).getByText('changes kept')).not.toHaveClass('tag-warn')
  expect(newer).not.toHaveTextContent('waits for you')
  expect(older).toHaveTextContent('waits for you')
})

test('Recent opens from its button in the top bar; Esc closes it, and the focus goes back to it', async () => {
  render(list([row('a')], 'a'))
  const button = screen.getByRole('button', { name: 'Recent' })
  expect(button).toHaveAttribute('aria-expanded', 'false')
  // (it names what it opens only while that is there)
  expect(button).not.toHaveAttribute('aria-controls')
  await userEvent.click(button)
  expect(button).toHaveAttribute('aria-expanded', 'true')
  expect(button).toHaveAttribute('aria-controls', panel().id)
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('complementary', { name: 'Recent' })).not.toBeInTheDocument()
  expect(button).toHaveFocus()
})

test('a message picked is drawn, and the list closes over it, the focus back on its button', async () => {
  const onPick = vi.fn()
  render(list([row('a'), row('b')], 'b', { onPick }))
  const button = screen.getByRole('button', { name: 'Recent' })
  await userEvent.click(button)
  await userEvent.click(rows()[1])
  expect(onPick).toHaveBeenCalledWith('a')
  expect(screen.queryByRole('complementary', { name: 'Recent' })).not.toBeInTheDocument()
  expect(button).toHaveFocus()
})

test('a click elsewhere closes it', async () => {
  render(list([row('a')], 'a'))
  await userEvent.click(screen.getByRole('button', { name: 'Recent' }))
  expect(panel()).toBeInTheDocument()
  await userEvent.click(document.body)
  expect(screen.queryByRole('complementary', { name: 'Recent' })).not.toBeInTheDocument()
})

test('with no message the list says so', () => {
  show(list([], null))
  expect(screen.getByText('No message yet.')).toBeInTheDocument()
})

test('each row restores to before its message: the card, named by the message’s time, looks ahead first; Esc closes the card alone', async () => {
  const asked = vi.fn(async (_url: string) => new Response(JSON.stringify({ turns: [], revert: ['a.txt'], skip: [], reject: [], copies: [], commands: [], stays: [], note: null }), { status: 200 }))
  vi.stubGlobal('fetch', asked)
  show(list([row('r1'), nightly('r2')], 'r2', { conversationId: 'c1' }))
  const [, older] = Array.from(panel().querySelectorAll<HTMLElement>('.recent-row'))
  expect(within(panel()).getAllByRole('button', { name: 'Restore to before this' })).toHaveLength(2)
  await userEvent.click(within(older).getByRole('button', { name: 'Restore to before this' }))
  const card = screen.getByRole('region', { name: `Restore to before your ${when('2026-10-05T10:00:00Z')} message` })
  expect(await within(card).findByRole('region', { name: 'Will be reverted' })).toHaveTextContent('a.txt')
  expect(String(asked.mock.calls[0][0])).toBe('/api/conversations/c1/restore?before=r1')
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('region', { name: /^Restore to before/ })).toBeNull()
  expect(panel()).toBeInTheDocument()
  // a trigger's message is not the user's
  await userEvent.click(within(panel()).getAllByRole('button', { name: 'Restore to before this' })[0])
  expect(screen.getByRole('region', { name: `Restore to before the ${when('2026-10-05T10:00:00Z')} message` })).toBeInTheDocument()
  vi.unstubAllGlobals()
})

test('the topic of the message drawn is renamed in place: Enter saves the new name, Esc leaves it as it was', async () => {
  const onRename = vi.fn().mockResolvedValue(undefined)
  show(list([row('a')], 'a', { topic: { id: 'ta', title: 'Fix the greeting' }, onRename }))
  expect(within(panel()).getByText('Topic: Fix the greeting')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Rename Fix the greeting' }))
  const name = screen.getByRole('textbox', { name: 'Topic name' })
  expect(name).toHaveValue('Fix the greeting')
  expect(name).toHaveFocus()
  await userEvent.clear(name)
  await userEvent.type(name, 'The greeting{Enter}')
  expect(onRename).toHaveBeenCalledWith('ta', 'The greeting')
  expect(screen.queryByRole('textbox', { name: 'Topic name' })).not.toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: 'Rename Fix the greeting' }))
  await userEvent.type(screen.getByRole('textbox', { name: 'Topic name' }), ' again{Escape}')
  expect(screen.queryByRole('textbox', { name: 'Topic name' })).not.toBeInTheDocument()
  // (that Esc was the box's: the list is still open)
  expect(panel()).toBeInTheDocument()
  // a name that is empty, or the one it has, is not sent
  await userEvent.click(screen.getByRole('button', { name: 'Rename Fix the greeting' }))
  await userEvent.type(screen.getByRole('textbox', { name: 'Topic name' }), '{Enter}')
  await userEvent.click(screen.getByRole('button', { name: 'Rename Fix the greeting' }))
  await userEvent.clear(screen.getByRole('textbox', { name: 'Topic name' }))
  await userEvent.type(screen.getByRole('textbox', { name: 'Topic name' }), '   {Enter}')
  expect(onRename).toHaveBeenCalledTimes(1)
})

test('a name the server refuses stays in the box, with the reason; with no topic of the user’s there is nothing to rename', async () => {
  const onRename = vi.fn().mockRejectedValue({ detail: 'title is empty' })
  const { unmount } = show(list([row('a')], 'a', { topic: { id: 'ta', title: 'Fix the greeting' }, onRename }))
  await userEvent.click(screen.getByRole('button', { name: 'Rename Fix the greeting' }))
  await userEvent.type(screen.getByRole('textbox', { name: 'Topic name' }), '!{Enter}')
  expect(await screen.findByRole('alert')).toHaveTextContent('title is empty')
  expect(screen.getByRole('textbox', { name: 'Topic name' })).toHaveValue('Fix the greeting!')
  unmount()
  show(list([nightly('n')], 'n', { topic: null, onRename }))
  expect(screen.queryByRole('button', { name: /^Rename/ })).not.toBeInTheDocument()
})

test('slice 107: a message that waits for you further back than the last five is listed under them - the dot never points at nothing', () => {
  const all = [row('old', { waits: true, text: 'approve this' }), ...Array.from({ length: 6 }, (_, n) => row(`m${n + 1}`))]
  render(list(all, 'm6'))
  const button = screen.getByRole('button', { name: /^Recent/ })
  expect(within(button).getByRole('img', { name: 'something waits for you' })).toBeInTheDocument()
  fireEvent.click(button)
  const older = within(panel()).getByRole('region', { name: 'Older, waits for you' })
  expect(within(older).getByRole('button', { name: /approve this/ })).toHaveTextContent('waits for you')
  // (none further back waits: no such part)
  cleanup()
  show(list(all.slice(1), 'm6'))
  expect(screen.queryByRole('region', { name: 'Older, waits for you' })).toBeNull()
})

test('slice 107: a message still queued or at work has no Restore to before it', () => {
  show(list([row('a'), row('b', { ended: 'working' }), row('c', { ended: 'queued' })], 'b', { conversationId: 'c1' }))
  const restores = Array.from(panel().querySelectorAll('.recent-row')).map(li => within(li as HTMLElement).queryByRole('button', { name: 'Restore to before this' }) !== null)
  expect(restores).toEqual([false, false, true])
})
