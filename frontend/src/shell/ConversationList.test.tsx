import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import type { Board, ListedConversation, Project, Run } from '../api/types'
import { type ReadyItem, readyItems } from '../ready/ready'
import { boardTurn, command, conversation, convState, question, run } from '../test-fixtures'
import { ConversationList, dayOf } from './ConversationList'

type BoardConversation = Board['conversations'][number]
const onBoard = (id: string, over: Partial<BoardConversation> = {}): BoardConversation => ({
  conversation_id: id,
  title: id,
  agents: [],
  merges_pending: 0,
  turn: null,
  ...over,
})
const asking = {
  id: 'x',
  name: 'Lead',
  status: 'waiting_approval' as const,
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
  own_questions: 0,
}

const listed = (id: string, title: string, kept: boolean): ListedConversation => ({
  ...convState().conversation,
  id,
  title,
  kept,
  backlog_task: null,
  wrote: false,
})

test('a conversation with changes that were kept and are not decided yet says so, as its turn does', () => {
  render(
    <ConversationList
      conversations={[listed('a', 'Fix the greeting', true), listed('b', 'Write the docs', false)]}
      currentId="b"
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={async () => {}}
    />,
  )
  const kept = screen.getByRole('button', { name: /^Fix the greeting/ })
  expect(kept).toHaveTextContent('changes kept')
  expect(screen.getByText('changes kept')).toHaveClass('tag')
  expect(screen.getByRole('button', { name: /^Write the docs/ })).not.toHaveTextContent('changes kept')
})

test('each row says its name and when it was last worked on; a long name is cut, whole in its title; the list is sorted by date or by name', async () => {
  const long =
    'A conversation with a long name about the greeting module, what the reviewer said of it and what is left to do'
  const conversations = [
    { ...listed('a', 'write the docs', false), updated_at: '2026-10-16T10:00:00Z' },
    { ...listed('b', long, false), updated_at: '2026-10-16T12:00:00Z' },
    { ...listed('c', 'Fix the greeting', false), updated_at: '2026-10-15T09:00:00Z' },
  ]
  render(
    <ConversationList
      conversations={conversations}
      currentId={null}
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={async () => {}}
    />,
  )
  const names = () => screen.getAllByRole('listitem').map(item => item.querySelector('.conv-row-title')!.textContent)
  const title = screen.getByText(long)
  expect(title).toHaveAttribute('title', long)
  expect(title).toHaveClass('conv-row-title')
  expect(screen.getByRole('button', { name: /^write the docs/ })).toHaveTextContent(/Oct 16/)
  // Newest first, as the server lists them; or by name.
  expect(names()).toEqual([long, 'write the docs', 'Fix the greeting'])
  expect(screen.getByLabelText('Sort by')).toHaveValue('date')
  await userEvent.selectOptions(screen.getByLabelText('Sort by'), 'Name')
  expect(names()).toEqual([long, 'Fix the greeting', 'write the docs'])
  await userEvent.selectOptions(screen.getByLabelText('Sort by'), 'Last activity')
  expect(names()).toEqual([long, 'write the docs', 'Fix the greeting'])
})

test('each row says how it stands - waits for you, working, done - and those that wait for you come first', () => {
  const conversations = [
    { ...listed('a', 'Docs', false), updated_at: '2026-10-16T12:00:00Z' },
    { ...listed('b', 'Tests', false), updated_at: '2026-10-16T11:00:00Z' },
    { ...listed('c', 'Asks', false), updated_at: '2026-10-15T09:00:00Z' },
    { ...listed('d', 'Fresh', false), updated_at: '2026-10-14T09:00:00Z' },
  ]
  const board: Board = {
    backlog_waiting: 0,
    limit: null,
    running: 1,
    conflicts: [],
    conversations: [
      onBoard('a', { turn: boardTurn('r1', 'completed', '2026-10-16T12:30:00Z') }),
      onBoard('b', { agents: [{ ...asking, status: 'running' }], turn: boardTurn('r2', 'running', null) }),
      onBoard('c', { agents: [asking], merges_pending: 1, turn: boardTurn('r3', 'waiting_approval', null) }),
      onBoard('d'),
    ],
  }
  render(
    <ConversationList
      conversations={conversations}
      board={board}
      currentId={null}
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={async () => {}}
    />,
  )
  const rows = screen.getAllByRole('button', { name: /^(Docs|Tests|Asks|Fresh)/ })
  expect(rows.map(row => row.querySelector('.conv-row-title')!.textContent)).toEqual(['Asks', 'Docs', 'Tests', 'Fresh'])
  // (Its chat not read for Ready for you yet: the Board says it waits.)
  expect(rows[0]).toHaveTextContent('Waits for your word')
  expect(within(rows[0]).getByText('Waits for your word')).toHaveClass('conv-is-yours')
  expect(rows[1]).toHaveTextContent('Done')
  expect(rows[2]).toHaveTextContent('Orchestrator working')
  // never run: nothing made up
  expect(rows[3]).toHaveTextContent('No turn yet')
  expect(rows[3]).not.toHaveTextContent(/done|working|waits/i)
  // Each row's cell, beside its button: its label says how it stands - its colour never alone.
  const cells = rows.map(row => within(row.closest('li')!).getByRole('img'))
  expect(cells.map(cell => cell.getAttribute('aria-label'))).toEqual(['waits for your word', 'done', 'at work', 'idle'])
  expect(cells.map(cell => cell.className)).toEqual([
    'cell cell-honey cell-soft',
    'cell cell-ok cell-full',
    'cell cell-honey cell-full',
    'cell cell-plain cell-none',
  ])
  // the last activity is the turn's end where that is later than the conversation's last change
  expect(rows[1]).toHaveTextContent(
    new Date('2026-10-16T12:30:00Z').toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }),
  )
})

test('a To-do list task’s chat has its symbol and its task’s state, unless the chat’s own state says the same', () => {
  const task = (id: string, status: NonNullable<ListedConversation['backlog_task']>['status'], waiting = false) => ({
    id,
    status,
    waiting,
  })
  const conversations = [
    { ...listed('a', 'Pin notes', false), backlog_task: task('t1', 'doing') },
    { ...listed('b', 'Fix the module', false), backlog_task: task('t2', 'blocked') },
    { ...listed('c', 'Export to CSV', false), backlog_task: task('t3', 'review', true) },
    { ...listed('d', 'Plan sharing', false), backlog_task: task('t4', 'review') },
    listed('e', 'My own chat', false),
  ]
  const board: Board = {
    backlog_waiting: 0,
    limit: null,
    running: 1,
    conflicts: [],
    conversations: [
      onBoard('a', { agents: [{ ...asking, status: 'running' }], turn: boardTurn('r1', 'running', null) }),
    ],
  }
  render(
    <ConversationList
      conversations={conversations}
      board={board}
      currentId={null}
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={async () => {}}
    />,
  )
  const row = (name: string) => screen.getByRole('button', { name: new RegExp(`^(From the to-do list )?${name}`) })
  expect(within(row('Pin notes')).getByRole('img', { name: 'From the to-do list' })).toHaveAttribute(
    'title',
    'From the to-do list',
  )
  expect(within(row('My own chat')).queryByRole('img', { name: 'From the to-do list' })).toBeNull()
  // its turn already says "working": not twice
  expect(row('Pin notes').textContent!.match(/working/g)).toHaveLength(1)
  expect(within(row('Fix the module')).getByText('stuck')).toHaveClass('tag-warn')
  // (your word in honey, as its cell would be; stuck red-orange)
  expect(within(row('Export to CSV')).getByText('waits for you')).toHaveClass('tag-accent')
  expect(within(row('Plan sharing')).getByText('done?')).not.toHaveClass('tag-warn')
})

test('a search finds conversations by name; one is archived, stands under "Archived", and comes back', async () => {
  const onArchive = vi.fn().mockResolvedValue(undefined)
  const conversations = [
    listed('a', 'Fix the greeting', false),
    { ...listed('b', 'Watch the build', false), archived_at: '2026-10-17T08:00:00Z' },
  ]
  render(
    <ConversationList
      conversations={conversations}
      currentId={null}
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={onArchive}
    />,
  )
  const archived = screen.getByRole('region', { name: 'Archived' })
  expect(within(archived).getByRole('button', { name: /^Watch the build/ })).toBeInTheDocument()
  expect(screen.getAllByRole('listitem')).toHaveLength(2)

  await userEvent.click(screen.getByRole('button', { name: 'Archive Fix the greeting' }))
  expect(onArchive).toHaveBeenCalledWith('a', true)
  await userEvent.click(within(archived).getByRole('button', { name: 'Unarchive Watch the build' }))
  expect(onArchive).toHaveBeenCalledWith('b', false)

  await userEvent.type(screen.getByRole('searchbox', { name: 'Search conversations' }), 'GREET')
  expect(screen.getAllByRole('listitem')).toHaveLength(1)
  expect(screen.getByRole('button', { name: /^Fix the greeting/ })).toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'Archived' })).toBeNull()
  await userEvent.clear(screen.getByRole('searchbox', { name: 'Search conversations' }))
  await userEvent.type(screen.getByRole('searchbox', { name: 'Search conversations' }), 'nothing like it')
  expect(screen.getByText('No conversation has that in its name.')).toBeInTheDocument()
})

test('those picked are archived together; only archived ones are deleted, after a yes that says how many, and what was not is said', async () => {
  const onArchive = vi.fn().mockResolvedValue(undefined)
  const onDelete = vi.fn().mockResolvedValue({
    deleted: ['b'],
    refused: [{ id: 'c', title: 'Nightly', why: 'a turn of it is at work or waits to start' }],
  })
  const away = (id: string, title: string) => ({ ...listed(id, title, false), archived_at: '2026-10-17T08:00:00Z' })
  const conversations = [
    listed('a', 'Docs', false),
    away('b', 'Old'),
    away('c', 'Nightly'),
    listed('d', 'Tests', false),
  ]
  render(
    <ConversationList
      conversations={conversations}
      currentId={null}
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={onArchive}
      onDelete={onDelete}
    />,
  )
  const button = (name: RegExp) => screen.getByRole('button', { name })
  expect(button(/^Archive selected/)).toBeDisabled()
  await userEvent.click(screen.getByRole('checkbox', { name: 'Select Docs' }))
  await userEvent.click(screen.getByRole('checkbox', { name: 'Select Tests' }))
  // (none of them is archived: none of them can be deleted)
  expect(button(/^Delete selected/)).toBeDisabled()
  await userEvent.click(button(/^Archive selected \(2\)/))
  expect(onArchive.mock.calls).toEqual([
    ['a', true],
    ['d', true],
  ])
  // All of those the list shows, then only the archived ones are deleted - not before a yes.
  await userEvent.click(screen.getByRole('checkbox', { name: 'Select all shown' }))
  // B-337: KOLONİ's own question, never the browser's.
  const browser = vi.spyOn(window, 'confirm')
  const asked = () =>
    screen.getByRole('alertdialog', {
      name: /^Delete 2 archived chats from KOLONİ\? This cannot be undone in KOLONİ\. Their messages/,
    })
  await userEvent.click(button(/^Delete selected \(2\)/))
  await userEvent.click(within(asked()).getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('alertdialog')).toBeNull()
  expect(onDelete).not.toHaveBeenCalled()
  await userEvent.click(button(/^Delete selected \(2\)/))
  await userEvent.click(within(asked()).getByRole('button', { name: 'Delete' }))
  expect(onDelete).toHaveBeenCalledWith(['b', 'c'])
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Nightly was not deleted: a turn of it is at work or waits to start',
  )
  expect(browser).not.toHaveBeenCalled()
  browser.mockRestore()
})

test('a row says its last turn’s agents, model and tokens, where the Board has it', () => {
  const board: Board = {
    backlog_waiting: 0,
    limit: null,
    running: 0,
    conflicts: [],
    conversations: [
      onBoard('a', {
        turn: boardTurn('r1', 'completed', '2026-10-16T12:30:00Z', {
          agents: 3,
          provider_name: 'Local',
          model_id: 'qwen3',
          tokens: 12500,
        }),
      }),
    ],
  }
  render(
    <ConversationList
      conversations={[listed('a', 'Docs', false), listed('b', 'Other folder', false)]}
      board={board}
      currentId={null}
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={async () => {}}
    />,
  )
  expect(screen.getByRole('button', { name: /^Docs/ })).toHaveTextContent('3 agents · Local · qwen3 · 12,500 tokens')
  expect(screen.getByRole('button', { name: /^Other folder/ })).not.toHaveTextContent('tokens')
})

test('what the server refuses of an archive is said', async () => {
  const onArchive = vi.fn().mockRejectedValue(new Error('origin not allowed'))
  render(
    <ConversationList
      conversations={[listed('a', 'Docs', false)]}
      currentId={null}
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={onArchive}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: 'Archive Docs' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Docs could not be archived: origin not allowed')
})

test('an archived conversation that waits for you stands on top, said to be archived, as the badge counts it', () => {
  const conversations = [
    listed('a', 'Docs', false),
    { ...listed('b', 'Nightly', false), archived_at: '2026-10-17T08:00:00Z' },
    { ...listed('c', 'Old', false), archived_at: '2026-10-17T08:00:00Z' },
  ]
  const board: Board = {
    backlog_waiting: 0,
    limit: null,
    running: 0,
    conflicts: [],
    conversations: [onBoard('a'), onBoard('b', { agents: [asking] }), onBoard('c')],
  }
  render(
    <ConversationList
      conversations={conversations}
      board={board}
      currentId={null}
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={async () => {}}
    />,
  )
  const top = screen.getAllByRole('list')[0]
  const first = within(top).getAllByRole('button', { name: /^(Docs|Nightly)/ })[0]
  expect(first).toHaveTextContent(/^Nightly.*Waits for your word.*archived/)
  expect(within(top).getByRole('button', { name: 'Unarchive Nightly' })).toBeInTheDocument()
  const archived = screen.getByRole('region', { name: 'Archived' })
  expect(within(archived).queryByText('Nightly')).toBeNull()
  expect(within(archived).getByRole('button', { name: /^Old/ })).toBeInTheDocument()
})

test('a day is today from local midnight, this week for the six days before it, and older before that', () => {
  const now = new Date(2026, 9, 21, 10, 0)
  expect(dayOf(new Date(2026, 9, 21, 0, 0).getTime(), now)).toBe('Today')
  expect(dayOf(new Date(2026, 9, 20, 23, 59).getTime(), now)).toBe('Last 7 days')
  expect(dayOf(new Date(2026, 9, 15, 0, 0).getTime(), now)).toBe('Last 7 days')
  expect(dayOf(new Date(2026, 9, 14, 23, 59).getTime(), now)).toBe('Older')
})

test('by last activity the rows fall under Today, Last 7 days and Older, one that waits for you first in its group (no group of its own: tek-ev §1); by name it is one list', async () => {
  const ago = (days: number) => new Date(Date.now() - days * 86_400_000).toISOString()
  const conversations = [
    { ...listed('a', 'Now', false), updated_at: new Date().toISOString() },
    { ...listed('b', 'Lately', false), updated_at: ago(3) },
    { ...listed('c', 'Long ago', false), updated_at: ago(30) },
    { ...listed('d', 'Asks', false), updated_at: ago(30) },
  ]
  const board: Board = {
    backlog_waiting: 0,
    limit: null,
    running: 0,
    conflicts: [],
    conversations: [onBoard('a'), onBoard('b'), onBoard('c'), onBoard('d', { agents: [asking] })],
  }
  render(
    <ConversationList
      conversations={conversations}
      board={board}
      currentId={null}
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={async () => {}}
    />,
  )
  const under = (group: string) =>
    within(screen.getByRole('region', { name: group }))
      .getAllByRole('listitem')
      .map(item => item.querySelector('.conv-row-title')!.textContent)
  expect(screen.getAllByRole('heading', { level: 3 }).map(h => h.textContent)).not.toContain('waits for you')
  expect(screen.getAllByRole('heading', { level: 4 }).map(h => h.textContent)).toEqual([
    'Today',
    'Last 7 days',
    'Older',
  ])
  expect(under('Today')).toEqual(['Now'])
  expect(under('Last 7 days')).toEqual(['Lately'])
  expect(under('Older')).toEqual(['Asks', 'Long ago'])
  await userEvent.selectOptions(screen.getByLabelText('Sort by'), 'Name')
  expect(screen.queryByRole('heading', { level: 4 })).toBeNull()
  expect(screen.getAllByRole('listitem')).toHaveLength(4)
})

const folder = (id: string, name: string) => ({ id, name, root_path: `C:\\work\\${name}` }) as Project
const inFolder = (id: string, project_id: string | null, updated_at: string): ListedConversation => ({
  ...listed(id, id, false),
  project_id,
  updated_at,
})

test('the chats are grouped by folder: the open chat’s first and open, the others closed - the one used last first, those with no folder last; each opens and closes', async () => {
  const conversations = [
    inFolder('plain talk', null, '2026-10-24T12:00:00Z'),
    inFolder('enemy AI', 'g', '2026-10-24T11:00:00Z'),
    inFolder('login tests', 'a', '2026-10-24T10:00:00Z'),
    inFolder('mermaid', 'a', '2026-10-22T10:00:00Z'),
  ]
  const shown = (currentId: string | null) =>
    render(
      <ConversationList
        conversations={conversations}
        projects={[folder('a', 'Skyulf-Agent'), folder('g', 'oyun-projesi')]}
        currentId={currentId}
        onOpen={() => {}}
        onNew={() => {}}
        onArchive={async () => {}}
      />,
    )
  let { unmount } = shown('mermaid')
  const groups = () => screen.getAllByRole('heading', { level: 3 }).map(h => h.textContent)
  // Each folder says how many chats it holds; Now is the last heading.
  expect(groups()).toEqual(['Skyulf-Agent 2 chats', 'oyun-projesi 1 chat', 'No folder 1 chat', 'Now every folder'])
  const titles = (name: string) =>
    within(screen.getByRole('region', { name }))
      .queryAllByRole('listitem')
      .map(item => item.querySelector('.conv-row-title')!.textContent)
  expect(titles('Skyulf-Agent')).toEqual(['login tests', 'mermaid'])
  expect(titles('oyun-projesi')).toEqual([])
  expect(titles('No folder')).toEqual([])
  expect(screen.getByRole('button', { name: 'No folder' })).toHaveAttribute('aria-expanded', 'false')
  const header = screen.getByRole('button', { name: 'Skyulf-Agent' })
  expect(header).toHaveAttribute('aria-expanded', 'true')
  await userEvent.click(header)
  expect(header).toHaveAttribute('aria-expanded', 'false')
  expect(titles('Skyulf-Agent')).toEqual([])
  await userEvent.click(screen.getByRole('button', { name: 'No folder' }))
  expect(titles('No folder')).toEqual(['plain talk'])
  // In a plain chat its group is the first and open.
  unmount()
  ;({ unmount } = shown('plain talk'))
  expect(groups()).toEqual(['No folder 1 chat', 'oyun-projesi 1 chat', 'Skyulf-Agent 2 chats', 'Now every folder'])
  expect(titles('No folder')).toEqual(['plain talk'])
  expect(titles('Skyulf-Agent')).toEqual([])
  // With no chat open, all of them are open.
  unmount()
  shown(null)
  expect(groups()).toEqual(['oyun-projesi 1 chat', 'Skyulf-Agent 2 chats', 'No folder 1 chat', 'Now every folder'])
  expect(titles('oyun-projesi')).toEqual(['enemy AI'])
})

test('B-395: Select all shown picks only the rows on screen, not those under a closed folder', async () => {
  const conversations = [
    inFolder('login tests', 'a', '2026-10-24T10:00:00Z'),
    inFolder('mermaid', 'a', '2026-10-22T10:00:00Z'),
    inFolder('enemy AI', 'g', '2026-10-24T11:00:00Z'),
    inFolder('plain talk', null, '2026-10-24T12:00:00Z'),
  ]
  const onArchive = vi.fn().mockResolvedValue(undefined)
  render(
    <ConversationList
      conversations={conversations}
      projects={[folder('a', 'Skyulf-Agent'), folder('g', 'oyun-projesi')]}
      currentId="mermaid"
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={onArchive}
    />,
  )
  await userEvent.click(screen.getByRole('checkbox', { name: 'Select all shown' }))
  expect(screen.getByRole('button', { name: 'Archive selected (2)' })).toBeEnabled()
  await userEvent.click(screen.getByRole('button', { name: 'Archive selected (2)' }))
  expect(onArchive.mock.calls).toEqual([
    ['login tests', true],
    ['mermaid', true],
  ])
})

test('"New chat" asks for one', async () => {
  const onNew = vi.fn()
  render(
    <ConversationList
      conversations={[inFolder('one', 'a', '2026-10-24T10:00:00Z')]}
      projects={[folder('a', 'Skyulf-Agent')]}
      currentId={null}
      onOpen={() => {}}
      onNew={onNew}
      onArchive={async () => {}}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: 'New chat' }))
  expect(onNew).toHaveBeenCalledTimes(1)
})

test('the status filter shows those whose last turn failed or was stopped, or those done - those that wait for you are Ready for you’s (tek-ev §1)', async () => {
  const conversations = ['Asks', 'Broke', 'Halted', 'Cut', 'Shipped', 'Fresh'].map(title => listed(title, title, false))
  const turn = (status: Run['status']) => boardTurn(`r-${status}`, status, null)
  const board: Board = {
    backlog_waiting: 0,
    limit: null,
    running: 0,
    conflicts: [],
    conversations: [
      onBoard('Asks', { agents: [asking] }),
      onBoard('Broke', { turn: turn('failed') }),
      onBoard('Halted', { turn: turn('cancelled') }),
      onBoard('Cut', { turn: turn('interrupted') }),
      onBoard('Shipped', { turn: turn('completed') }),
      onBoard('Fresh'),
    ],
  }
  render(
    <ConversationList
      conversations={conversations}
      board={board}
      currentId={null}
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={async () => {}}
    />,
  )
  const names = () =>
    screen
      .getAllByRole('listitem')
      .map(item => item.querySelector('.conv-row-title')!.textContent)
      .sort()
  expect(names()).toHaveLength(6)
  expect(
    within(screen.getByLabelText('Show'))
      .getAllByRole('option')
      .map(o => o.textContent),
  ).toEqual(['All states', 'Failed or stopped', 'Done'])
  await userEvent.selectOptions(screen.getByLabelText('Show'), 'Failed or stopped')
  expect(names()).toEqual(['Broke', 'Cut', 'Halted'])
  await userEvent.selectOptions(screen.getByLabelText('Show'), 'Done')
  expect(names()).toEqual(['Shipped'])
  // the search and the filter together: nothing left, and it says which filter
  await userEvent.type(screen.getByRole('searchbox', { name: 'Search conversations' }), 'Broke')
  expect(screen.getByText('None of them is “Done”.')).toBeInTheDocument()
})

test('before the Board is read a filter shows none, and says how each one stands is not read yet', async () => {
  render(
    <ConversationList
      conversations={[listed('a', 'Docs', false)]}
      currentId={null}
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={async () => {}}
    />,
  )
  expect(screen.getByLabelText('Show')).toHaveDisplayValue('All states')
  await userEvent.selectOptions(screen.getByLabelText('Show'), 'Done')
  expect(screen.queryByRole('listitem')).toBeNull()
  expect(screen.getByText('How each conversation stands is not read yet.')).toBeInTheDocument()
})

test('a chat that waits for you stays under its folder, its row saying so - no group above the folders (tek-ev §1)', async () => {
  const conversations = [
    inFolder('enemy AI', 'g', '2026-10-24T11:00:00Z'),
    inFolder('pathing', 'g', '2026-10-24T10:00:00Z'),
    inFolder('login tests', 'a', '2026-10-24T09:00:00Z'),
  ]
  const board: Board = {
    backlog_waiting: 0,
    limit: null,
    running: 0,
    conflicts: [],
    conversations: [onBoard('enemy AI', { agents: [asking] })],
  }
  render(
    <ConversationList
      conversations={conversations}
      projects={[folder('a', 'Skyulf-Agent'), folder('g', 'oyun-projesi')]}
      board={board}
      currentId="login tests"
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={async () => {}}
    />,
  )
  const titles = (name: string) =>
    within(screen.getByRole('region', { name }))
      .queryAllByRole('listitem')
      .map(item => item.querySelector('.conv-row-title')!.textContent)
  expect(screen.getAllByRole('heading', { level: 3 }).map(h => h.textContent)).toEqual([
    'Skyulf-Agent 1 chat',
    'oyun-projesi 2 chats',
    'Now every folder',
  ])
  expect(screen.getByRole('button', { name: 'oyun-projesi' })).toHaveAttribute('aria-expanded', 'false')
  await userEvent.click(screen.getByRole('button', { name: 'oyun-projesi' }))
  expect(titles('oyun-projesi')).toEqual(['enemy AI', 'pathing'])
  expect(within(screen.getByRole('region', { name: 'oyun-projesi' })).getAllByRole('listitem')[0]).toHaveTextContent(
    'Waits for your word',
  )
})

describe('reading the list again', () => {
  let state: DocumentVisibilityState = 'visible'
  beforeEach(() => {
    state = 'visible'
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state })
  })
  afterEach(() => {
    vi.useRealTimers()
    Reflect.deleteProperty(document, 'visibilityState')
  })
  const turn = (to: DocumentVisibilityState) => {
    state = to
    document.dispatchEvent(new Event('visibilitychange'))
  }
  const page = (onRefresh: () => Promise<void>, onArchive = async () => {}) =>
    render(
      <ConversationList
        conversations={[listed('a', 'Docs', false)]}
        currentId={null}
        onOpen={() => {}}
        onNew={() => {}}
        onArchive={onArchive}
        onRefresh={onRefresh}
      />,
    )
  const failed = 'The conversations could not be read again: offline'

  test('the refresh button reads it, busy and not pressed again till the answer comes; a failed read is said till one works', async () => {
    let answer = () => {}
    const onRefresh = vi.fn(() => new Promise<void>(done => (answer = done)))
    page(onRefresh)
    const button = screen.getByRole('button', { name: 'Refresh conversations' })
    expect(button).toHaveAttribute('aria-busy', 'false')
    await userEvent.click(button)
    await userEvent.click(button)
    expect(onRefresh).toHaveBeenCalledTimes(1)
    expect(button).toHaveAttribute('aria-busy', 'true')
    expect(button).toBeDisabled()
    await act(async () => answer())
    expect(button).toHaveAttribute('aria-busy', 'false')
    onRefresh.mockRejectedValueOnce(new Error('offline'))
    await userEvent.click(button)
    expect(await screen.findByRole('alert')).toHaveTextContent(failed)
    onRefresh.mockResolvedValueOnce()
    await userEvent.click(button)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  test('a read clears only its own failure: an archive’s stays; a read by itself that works clears it too', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] }) // (userEvent's own timeouts stay real)
    const onRefresh = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(undefined)
    page(onRefresh, vi.fn().mockRejectedValue(new Error('origin not allowed')))
    await userEvent.click(screen.getByRole('button', { name: 'Archive Docs' }))
    await userEvent.click(screen.getByRole('button', { name: 'Refresh conversations' }))
    expect((await screen.findAllByRole('alert')).map(alert => alert.textContent)).toEqual([
      'Docs could not be archived: origin not allowed',
      failed,
    ])
    vi.advanceTimersByTime(30_000)
    await act(async () => {})
    expect(onRefresh).toHaveBeenCalledTimes(2)
    expect(screen.getAllByRole('alert').map(alert => alert.textContent)).toEqual([
      'Docs could not be archived: origin not allowed',
    ])
  })

  test('the page coming back into view reads it once, not again within a few seconds', () => {
    vi.useFakeTimers()
    const onRefresh = vi.fn(async () => {})
    page(onRefresh)
    expect(onRefresh).not.toHaveBeenCalled() // (the page read it as it opened)
    vi.advanceTimersByTime(10_000)
    turn('hidden')
    turn('visible')
    window.dispatchEvent(new Event('focus'))
    expect(onRefresh).toHaveBeenCalledTimes(1)
  })

  test('no timer runs while the page is hidden; shown, it reads every 30 s; gone, it stops', () => {
    vi.useFakeTimers()
    state = 'hidden'
    const onRefresh = vi.fn(async () => {})
    const { unmount } = page(onRefresh)
    vi.advanceTimersByTime(120_000)
    expect(onRefresh).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
    turn('visible')
    expect(onRefresh).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(30_000)
    expect(onRefresh).toHaveBeenCalledTimes(2)
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})

test('the open chat is the current one, and each row’s button says Archive or Unarchive', () => {
  const conversations = [
    listed('a', 'Fix the greeting', false),
    { ...listed('b', 'Watch the build', false), archived_at: '2026-10-17T08:00:00Z' },
  ]
  render(
    <ConversationList
      conversations={conversations}
      currentId="a"
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={vi.fn()}
    />,
  )
  expect(screen.getByRole('button', { name: /^Fix the greeting/ })).toHaveAttribute('aria-current', 'true')
  expect(screen.getByRole('button', { name: /^Watch the build/ })).not.toHaveAttribute('aria-current')
  expect(screen.getByRole('button', { name: 'Unarchive Watch the build' })).toHaveTextContent(/^Unarchive$/)
  expect(screen.getByRole('button', { name: 'Archive Fix the greeting' })).toHaveTextContent(/^Archive$/)
})

/** Chat "x", whose agent asks to run a command and asks a question: two rows of Ready for you, as the pill counts them. */
const asks = () =>
  readyItems({
    conv: null,
    chats: {
      x: convState({
        conversation: { ...conversation, id: 'x', title: 'Fix the login' },
        runs: [run('rx', 'waiting_approval', { conversation_id: 'x' })],
        commands: [command('cmd', 'rx', { status: 'proposed', created_at: '2026-10-05T09:00:00Z' })],
        questions: [question('q', 'rx', { created_at: '2026-10-05T09:05:00Z' })],
      }),
    },
    projectId: null,
    backlog: null,
    memory: null,
    away: null,
  })

test('a chat’s row says what waits for your word in it - Ready for you’s own rows of it - and stands first; Now counts them as the pill does and goes to Ready', async () => {
  const items = asks()
  // (Both today: one group, the one that waits first in it.)
  const at = new Date().toISOString()
  expect(items).toHaveLength(2)
  const onReady = vi.fn()
  const board: Board = {
    backlog_waiting: 0,
    limit: null,
    running: 0,
    conflicts: [],
    // (The Board says nothing waits in "x": Ready for you's rows of it are what is said.)
    conversations: [
      onBoard('x', { turn: boardTurn('r1', 'completed', '2026-10-05T09:10:00Z') }),
      onBoard('y', { turn: boardTurn('r2', 'completed', at) }),
    ],
  }
  render(
    <ConversationList
      conversations={[
        { ...listed('y', 'Docs', false), updated_at: at },
        { ...listed('x', 'Fix the login', false), updated_at: at },
      ]}
      board={board}
      waiting={items}
      onReady={onReady}
      currentId={null}
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={async () => {}}
    />,
  )
  const rows = screen.getAllByRole('button', { name: /^(Docs|Fix the login)/ })
  expect(rows.map(row => row.querySelector('.conv-row-title')!.textContent)).toEqual(['Fix the login', 'Docs'])
  expect(rows[0]).toHaveTextContent('2 wait for your word · Command, Question')
  expect(within(rows[0].closest('li')!).getByRole('img', { name: 'waits for your word' })).toBeInTheDocument()
  expect(rows[1]).toHaveTextContent('Done')
  const now = screen.getByRole('complementary', { name: 'Now every folder' })
  expect(now).toHaveTextContent(
    'Nothing at work; 2 things wait for your word. Today 1 done. What waits is on Ready for you.',
  )
  expect(
    within(now)
      .getAllByRole('img')
      .slice(0, 3)
      .map(cell => cell.getAttribute('aria-label')),
  ).toEqual([
    'Command in “Fix the login”: waits for your word',
    'Question in “Fix the login”: waits for your word',
    '“Docs”: done today',
  ])
  // What the cells mean, in words.
  expect(within(now).getByLabelText('What the cells say')).toHaveTextContent(
    'done at work waits for your word stuck idle',
  )
  await userEvent.click(within(now).getByRole('button', { name: 'Go to Ready' }))
  expect(onReady).toHaveBeenCalledOnce()
})

test('Now before the Board is read: what waits is counted, how the chats stand is not said', () => {
  render(
    <ConversationList
      conversations={[listed('a', 'Docs', false)]}
      currentId={null}
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={async () => {}}
    />,
  )
  const now = screen.getByRole('complementary', { name: 'Now every folder' })
  expect(now).toHaveTextContent('How the chats stand is not read yet; nothing waits for your word.')
  expect(within(now).queryByRole('button', { name: 'Go to Ready' })).toBeNull()
  // Its row has no cell to say what is not known.
  expect(within(screen.getByRole('button', { name: /^Docs/ }).closest('li')!).queryByRole('img')).toBeNull()
})

test('a chat Ready for you has read waits only for what it lists: the Board, read before your answer, is not believed', () => {
  const board: Board = {
    backlog_waiting: 0,
    limit: null,
    running: 0,
    conflicts: [],
    conversations: [
      onBoard('a', { merges_pending: 1, turn: boardTurn('r1', 'completed', '2026-10-16T12:30:00Z') }),
      onBoard('b', { merges_pending: 1, turn: boardTurn('r2', 'completed', '2026-10-16T12:30:00Z') }),
    ],
  }
  render(
    <ConversationList
      conversations={[listed('a', 'Answered', false), listed('b', 'Not read yet', false)]}
      board={board}
      readChats={['a']}
      currentId={null}
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={async () => {}}
    />,
  )
  const cell = (name: string) =>
    within(screen.getByRole('button', { name: new RegExp(`^${name}`) }).closest('li')!).getByRole('img')
  expect(cell('Answered')).toHaveAccessibleName('done')
  expect(cell('Not read yet')).toHaveAccessibleName('waits for your word')
})

test('Now: a chat that waits for your word while another of its agents works is at work too; done and stuck today go by when its turn ended, not a rename', () => {
  const now = new Date().toISOString()
  const board: Board = {
    backlog_waiting: 0,
    limit: null,
    running: 1,
    conflicts: [],
    conversations: [
      onBoard('a', { agents: [asking, { ...asking, id: 'c', name: 'Coder', status: 'running' }] }),
      // Renamed today, its turn over long ago: not today's.
      onBoard('b', { turn: boardTurn('r2', 'completed', '2026-10-16T12:30:00Z') }),
      onBoard('c', { turn: boardTurn('r3', 'failed', now) }),
    ],
  }
  render(
    <ConversationList
      conversations={[
        listed('a', 'Asks and works', false),
        { ...listed('b', 'Renamed', false), updated_at: now },
        listed('c', 'Broke', false),
      ]}
      board={board}
      currentId={null}
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={async () => {}}
    />,
  )
  const nowPart = screen.getByRole('complementary', { name: 'Now every folder' })
  expect(nowPart).toHaveTextContent('1 chat at work; nothing waits for your word. Today 1 stuck.')
  expect(
    within(nowPart)
      .getAllByRole('img')
      .map(cell => cell.getAttribute('aria-label')),
  ).toEqual(['“Asks and works”: at work', '“Broke”: stuck today'])
})

test('Show goes by what a row says: a chat Ready for you read, its card answered, is Done though the Board still says it waits', async () => {
  const board: Board = {
    backlog_waiting: 0,
    limit: null,
    running: 0,
    conflicts: [],
    conversations: [onBoard('a', { merges_pending: 1, turn: boardTurn('r1', 'completed', '2026-10-16T12:30:00Z') })],
  }
  render(
    <ConversationList
      conversations={[listed('a', 'Answered', false)]}
      board={board}
      readChats={['a']}
      currentId={null}
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={async () => {}}
    />,
  )
  await userEvent.selectOptions(screen.getByLabelText('Show'), 'Done')
  expect(screen.getByRole('button', { name: /^Answered/ })).toHaveTextContent('Done')
})

test('a To-do task’s chat with no turn yet keeps its "to do": the idle line says less', () => {
  render(
    <ConversationList
      conversations={[
        { ...listed('a', 'Pin notes', false), backlog_task: { id: 't', status: 'todo', waiting: false } },
      ]}
      board={{ backlog_waiting: 0, limit: null, running: 0, conflicts: [], conversations: [onBoard('a')] }}
      currentId={null}
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={async () => {}}
    />,
  )
  const row = screen.getByRole('button', { name: /^(From the to-do list )?Pin notes/ })
  expect(row).toHaveTextContent('No turn yet')
  expect(within(row).getByText('to do')).toHaveClass('tag')
})

test('Now’s legend is one named group, its cells said once by their words; a comb of more than 30 says how many more', () => {
  const items = Array.from(
    { length: 32 },
    (_, at) =>
      ({
        what: 'task',
        key: `todo:t${at}:done?`,
        source: 'todo',
        at: '',
        task: { id: `t${at}`, conversation_id: null },
        kind: 'done?',
      }) as unknown as ReadyItem,
  )
  render(
    <ConversationList
      conversations={[listed('a', 'Docs', false)]}
      waiting={items}
      currentId={null}
      onOpen={() => {}}
      onNew={() => {}}
      onArchive={async () => {}}
    />,
  )
  const nowPart = screen.getByRole('complementary', { name: 'Now every folder' })
  const legend = within(nowPart).getByRole('group', { name: 'What the cells say' })
  expect(within(legend).queryAllByRole('img')).toHaveLength(0)
  expect(legend).toHaveTextContent('done at work waits for your word stuck idle')
  expect(within(nowPart).getAllByRole('img')).toHaveLength(30)
  expect(nowPart).toHaveTextContent('+2 more')
  expect(within(nowPart).getAllByRole('img')[0]).toHaveAccessibleName('Done?: waits for your word')
})
