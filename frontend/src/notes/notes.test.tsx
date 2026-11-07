import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { AgentWindow } from '../agents/AgentWindow'
import { ROLE_TOOLS } from '../agents/roleTools'
import { chatColours } from '../agents/teamRun'
import { ApiError } from '../api/client'
import { EVENT_TYPES } from '../api/sse'
import type { ChannelMessage } from '../api/types'
import { type Node, type NodeProps, ReactFlowProvider } from '@xyflow/react'
import { deriveGraph } from '../canvas/deriveGraph'
import type { SharedData } from '../canvas/sharedColumn'
import { SharedNode } from '../canvas/SharedNode'
import { foldGraph } from '../canvas/foldGraph'
import { ChannelPanel } from '../chat/ChannelPanel'
import { ChatPanel } from '../chat/ChatPanel'
import { MessageList } from '../chat/MessageList'
import { applyEvent, fromSnapshot } from '../state/applyEvent'
import { resetStoreForTests, useApp } from '../state/store'
import { NotesPanel } from './NotesPanel'
import { notebookRun, readLine, readersOf } from './notesText'
import { agent, assistantMessage, convState, handedNote, note, openAgentFold, run, userMessage } from '../test-fixtures'
import { when } from '../canvas/turns'

// The Lead opened a Coder and a Tester. The Tester wrote a note; the Coder and the Lead
// were handed it. Then the user wrote one, which only the Coder has been handed.
const first = note('n1', 'r', { agent_id: 'tester', content: 'hello.py is mine', read_by: ['coder', 'lead'] })
const second = note('n2', 'r', {
  agent_id: null,
  content: 'Leave the tests alone.',
  created_at: '2026-10-05T10:07:09Z',
  read_by: ['coder'],
})
const state = convState({
  runs: [run('r', 'running')],
  agents: [
    agent('r', 'running', { id: 'lead' }),
    agent('r', 'running', { id: 'coder', parent_agent_id: 'lead', role_name: 'Coder', depth: 1 }),
    agent('r', 'completed', { id: 'tester', parent_agent_id: 'lead', role_name: 'Tester', depth: 1 }),
  ],
  messages: [
    userMessage('r', 'fix it'),
    handedNote(first, 'coder'),
    handedNote(first, 'lead'),
    { ...assistantMessage('m1', 'r', 'Working on it.'), agent_id: 'lead' },
    { ...assistantMessage('k1', 'r', 'I leave hello.py alone.'), agent_id: 'coder' },
    handedNote(second, 'coder'),
  ],
  boardPosts: [first, second],
})

const handlers = {
  onRemoveQueued: () => {},
  onOpenChange: () => {},
  onDecide: async () => {},
  onDecideCommand: async () => {},
}

afterEach(() => resetStoreForTests())

test('the notebook is in the snapshot, and a new note arrives as an event', () => {
  const snapshot = { board_posts: [first], last_event_id: 4 } as Parameters<typeof fromSnapshot>[0]
  let s = fromSnapshot(snapshot)
  expect(s.boardPosts).toEqual([first])
  expect(EVENT_TYPES).toContain('board.posted')
  s = applyEvent(s, 5, 'board.posted', second)
  s = applyEvent(s, 5, 'board.posted', second)
  expect(s.boardPosts).toEqual([first, second])
})

test('a role can be given the two notebook tools', () => {
  const hints = Object.fromEntries(ROLE_TOOLS.map(tool => [tool.name, tool.hint]))
  expect(hints.post_note).toBe('leave notes on the shared notebook')
  expect(hints.read_notes).toBe('read the shared notebook')
  // in the order the server keeps them: the backlog's tiles (63b) and the trigger's before the notebook, the two memory tools after (slice 17)
  expect(ROLE_TOOLS.map(tool => tool.name).slice(-8)).toEqual(['read_backlog', 'add_task', 'change_task', 'propose_trigger', 'post_note', 'read_notes', 'remember', 'recall'])
})

// --- a note handed to an agent is not something one agent said to another ------------

test('the chat leaves out the notes the lead was handed, and does not count them', () => {
  const { container, unmount } = render(<MessageList {...handlers} state={state} />)
  expect(screen.getByText('Working on it.')).toBeInTheDocument()
  expect(screen.queryByText('hello.py is mine')).not.toBeInTheDocument()
  expect(container.querySelector('.msg-from')).toBeNull()
  unmount()

  useApp.setState({ conv: state })
  render(<ChatPanel />)
  // what you asked and what the lead said
  expect(document.querySelector('.chat-count')).toHaveTextContent(/^2$/)
})

test('a note left for one agent is not taken as delivered because the notebook said the same', () => {
  // The Tester also left the Coder a note of its own, in the same words; that one waits.
  const left: ChannelMessage = {
    id: 'c1', run_id: 'r', from_agent_id: 'tester', to_agent_id: 'coder', kind: 'note',
    content: 'hello.py is mine', created_at: '2026-10-05T10:00:05Z',
  }
  const waiting = { ...handedNote(first, 'coder'), id: 'w1', board_post_id: null, delivered_at: null }
  render(<ChannelPanel state={{ ...state, channelMessages: [left], messages: [...state.messages, waiting] }} />)
  expect(screen.getByText('Tester → Coder · note · not delivered')).toBeInTheDocument()
})

test('the raw steps of an agent show the notes it was handed as notes, as its story does', async () => {
  render(<AgentWindow state={state} agentId="coder" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  const steps = await openAgentFold('Every step as recorded')
  expect(within(steps).getByText('I leave hello.py alone.')).toBeInTheDocument()
  // never as its own words: whose note it is, over it
  expect(within(steps).getByText('note from the notebook, written by Tester')).toBeInTheDocument()
  expect(within(steps).getByText('note from the notebook, written by you')).toBeInTheDocument()
})

test('an agent’s window shows each note it was handed, and who wrote it', () => {
  render(<AgentWindow state={state} agentId="coder" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(screen.getByRole('heading', { name: 'Got a note from the notebook, by Tester' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Got a note from the notebook, by you' })).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: /^Got a message from/ })).not.toBeInTheDocument()
  const text = document.body.textContent ?? ''
  const order = ['hello.py is mine', 'I leave hello.py alone.', 'Leave the tests alone.']
  expect(order.map(piece => text.indexOf(piece)).every((at, i, all) => at >= 0 && (i === 0 || at > all[i - 1]))).toBe(true)
})

// --- the Notes tab ------------------------------------------------------------------

const clock = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })

test('the Notes tab lists the turn’s notes in order: who wrote each, when, and who has read it', () => {
  render(<NotesPanel state={state} onWrite={async () => {}} />)
  const text = document.body.textContent ?? ''
  const order = [
    'Tester', clock(first.created_at), 'hello.py is mine', 'handed to 2 of 2',
    'You', clock(second.created_at), 'Leave the tests alone.', 'handed to 1 of 3 · not yet to Lead, Tester',
  ]
  expect(order.map(piece => text.indexOf(piece)).every((at, i, all) => at >= 0 && (i === 0 || at >= all[i - 1]))).toBe(true)
})

test('who has read a note is what the records say: it grows as the note is handed over, and only then', () => {
  expect(readersOf(state, second)).toMatchObject({ read: [{ id: 'coder' }], unread: [{ id: 'lead' }, { id: 'tester' }] })
  // the lead takes its next step and is handed the note
  const next = applyEvent(state, 1, 'message.created', handedNote(second, 'lead'))
  expect(readersOf(next, second)).toMatchObject({ read: [{ id: 'lead' }, { id: 'coder' }], unread: [{ id: 'tester' }] })
  // the same record arriving again as completed counts once
  const again = applyEvent(next, 2, 'message.completed', handedNote(second, 'lead'))
  expect(readersOf(again, second).read).toHaveLength(2)
  // a note is not handed back to the one who wrote it, nor to an agent you declined to open
  const declined = agent('r', 'rejected', { id: 'no', parent_agent_id: 'lead', role_name: 'Reviewer', depth: 1 })
  const withDeclined = { ...state, agents: [...state.agents, declined] }
  expect(readersOf(withDeclined, first)).toMatchObject({ read: [{ id: 'lead' }, { id: 'coder' }], unread: [] })
  // one waiting for your approval is not at work: it is not counted until you approve it
  const proposed = agent('r', 'proposed', { id: 'asked', parent_agent_id: 'lead', role_name: 'Reviewer', depth: 1 })
  const withProposed = { ...state, agents: [...state.agents, proposed] }
  expect(readersOf(withProposed, second).unread.map(a => a.id)).toEqual(['lead', 'tester'])
  expect(readLine(withProposed, second)).toBe('handed to 1 of 3 · not yet to Lead, Tester')
  const approved = applyEvent(withProposed, 3, 'agent.updated', { ...proposed, status: 'running' })
  expect(readLine(approved, second)).toBe('handed to 1 of 4 · not yet to Lead, Tester, Reviewer')
  // nobody else in the turn: said, not counted
  const alone = { ...state, agents: [state.agents[0]], boardPosts: [note('n3', 'r', { agent_id: 'lead' })] }
  render(<NotesPanel state={alone} onWrite={async () => {}} />)
  expect(screen.getByText('no other agent at this work')).toBeInTheDocument()
})

test('you write a note on the turn at work, and a refusal is shown', async () => {
  const onWrite = vi.fn(async () => {})
  render(<NotesPanel state={state} onWrite={onWrite} />)
  const box = screen.getByLabelText('A note for every agent working on this request')
  expect(screen.getByRole('button', { name: 'Post note' })).toBeDisabled()  // nothing written yet
  await userEvent.type(box, '  Keep the greeting short.  ')
  await userEvent.click(screen.getByRole('button', { name: 'Post note' }))
  expect(onWrite).toHaveBeenCalledWith('r', 'Keep the greeting short.')
  expect(box).toHaveValue('')

  onWrite.mockRejectedValueOnce(new ApiError(409, 'this turn is over: its notebook is closed'))
  await userEvent.type(box, 'Too late?')
  await userEvent.click(screen.getByRole('button', { name: 'Post note' }))
  expect(screen.getByRole('alert')).toHaveTextContent('this turn is over: its notebook is closed')
  expect(box).toHaveValue('Too late?')
})

test('the notebook of a turn that is over can be read but not written on, and says why', () => {
  const over = { ...state, runs: [run('r', 'completed')] }
  const { unmount } = render(<NotesPanel state={over} onWrite={async () => {}} />)
  expect(screen.getByText('hello.py is mine')).toBeInTheDocument()
  expect(screen.getByLabelText('A note for every agent working on this request')).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Post note' })).toBeDisabled()
  expect(screen.getByText('This work is over: its notebook is closed.')).toBeInTheDocument()
  unmount()

  // A turn that waits in the queue has no notebook yet: the one before it is still shown.
  const queued = { ...over, runs: [...over.runs, run('q', 'queued')] }
  expect(notebookRun(queued)?.id).toBe('r')
  // A turn that waits for your decision is still at work.
  expect(notebookRun({ ...queued, runs: [run('r', 'completed'), run('w', 'waiting_approval')] })?.id).toBe('w')
})

test('earlier turns can be picked at the top of the Notes tab: read, not written on', async () => {
  const onWrite = vi.fn(async () => {})
  const turns = {
    ...state,
    runs: [run('r', 'completed'), run('s', 'running'), run('q', 'queued')],
    agents: [...state.agents, agent('s', 'running')],
    messages: [...state.messages, userMessage('s', 'and now the docs, which are long and need a careful look'), userMessage('q', 'later')],
    boardPosts: [first, second, note('n9', 's', { agent_id: null, content: 'Second turn.' })],
  }
  render(<NotesPanel state={turns} onWrite={onWrite} />)
  // as before: the turn at work
  const picker = screen.getByLabelText('Whose notes')
  expect(picker).toHaveValue('s')
  expect(screen.getByText('Second turn.')).toBeInTheDocument()
  expect(screen.queryByText('hello.py is mine')).not.toBeInTheDocument()
  // only turns that have started have a notebook; each says what was asked and how many notes it has
  expect(Array.from(picker.querySelectorAll('option')).map(o => o.textContent)).toEqual([
    `${when('2026-10-05T10:00:00Z')} · fix it · 2 notes`,
    `${when('2026-10-05T10:00:00Z')} · and now the docs, which are long and nee… · 1 note`,
  ])
  await userEvent.selectOptions(picker, 'r')
  expect(screen.getByText('hello.py is mine')).toBeInTheDocument()
  expect(screen.queryByText('Second turn.')).not.toBeInTheDocument()
  expect(screen.getByLabelText('A note for every agent working on this request')).toBeDisabled()
  expect(screen.getByText('This work is over: its notebook is closed.')).toBeInTheDocument()
  // back on the turn at work, a note goes to that turn
  await userEvent.selectOptions(picker, 's')
  await userEvent.type(screen.getByLabelText('A note for every agent working on this request'), 'Mind the docs.')
  await userEvent.click(screen.getByRole('button', { name: 'Post note' }))
  expect(onWrite).toHaveBeenCalledWith('s', 'Mind the docs.')
})

test('the Notes tab follows a new turn unless an earlier one was picked, and one turn needs no picker', async () => {
  const one = { ...state, runs: [run('r', 'completed')] }
  const { rerender } = render(<NotesPanel state={one} onWrite={async () => {}} />)
  expect(screen.queryByLabelText('Whose notes')).not.toBeInTheDocument()
  const two = { ...one, runs: [run('r', 'completed'), run('s', 'running')], boardPosts: [first, note('n9', 's', { content: 'Second turn.' })] }
  rerender(<NotesPanel state={two} onWrite={async () => {}} />)
  expect(screen.getByLabelText('Whose notes')).toHaveValue('s')
  await userEvent.selectOptions(screen.getByLabelText('Whose notes'), 'r')
  const three = { ...two, runs: [run('r', 'completed'), run('s', 'completed'), run('t', 'running')] }
  rerender(<NotesPanel state={three} onWrite={async () => {}} />)
  expect(screen.getByLabelText('Whose notes')).toHaveValue('r') // what you picked stays
  expect(screen.getByText('hello.py is mine')).toBeInTheDocument()
})

test('before any turn has started there is nothing to write on', () => {
  for (const none of [null, convState(), convState({ runs: [run('q', 'queued')] })]) {
    const { unmount } = render(<NotesPanel state={none} onWrite={async () => {}} />)
    expect(screen.getByText('Notes that agents and you leave for everyone working on a message show here.')).toBeInTheDocument()
    expect(screen.getByLabelText('A note for every agent working on this request')).toBeDisabled()
    expect(screen.getByText('Nothing is at work. A note can be written while something is.')).toBeInTheDocument()
    unmount()
  }
})

test('the chat panel has the notebook as a tab, and what you write goes to the turn at work', async () => {
  const fetched = vi.fn(async () => new Response(JSON.stringify(second), { status: 201 }))
  vi.stubGlobal('fetch', fetched)
  useApp.setState({ conv: state })
  render(<ChatPanel />)
  // (Awaited: on a slow CI runner the count in the tab's name comes a moment after the first paint.)
  const tab = await screen.findByRole('tab', { name: /^Notes\s*2$/ }, { timeout: 5000 })
  expect(screen.queryByText('hello.py is mine')).not.toBeInTheDocument()
  await userEvent.click(tab)
  expect(screen.getByText('hello.py is mine')).toBeInTheDocument()
  await userEvent.type(screen.getByLabelText('A note for every agent working on this request'), 'Mind the docs.')
  await userEvent.click(screen.getByRole('button', { name: 'Post note' }))
  expect(fetched).toHaveBeenCalledWith('/api/runs/r/notes', expect.objectContaining({
    method: 'POST', body: JSON.stringify({ content: 'Mind the docs.' }),
  }))
  vi.unstubAllGlobals()
}, 15_000) // (the whole ChatPanel, typed into: past vitest's 5 s on a slow CI runner, which the 5 s wait above alone could fill)

// --- the canvas ---------------------------------------------------------------------

test('K-shared-bagli: on the canvas each agent’s notes are on its card - the newest two, then how many more; yours beside the Lead', () => {
  const more = ['check.py is mine too', 'and lint.py', 'and the docs'].map((content, at) => note(`n${at + 3}`, 'r', { agent_id: 'tester', content }))
  const { nodes, edges } = deriveGraph({ ...state, boardPosts: [first, second, ...more] })
  const block = (id: string) => nodes.find(n => n.id === id)?.data as SharedData | undefined
  // (No team: a card for each agent that used something, joined to its box by a dotted line; the Lead's and yours beside the Lead, with none.)
  expect(nodes.filter(n => n.kind === 'shared').map(n => n.id)).toEqual(['shared:r:top', 'shared:r:agent:tester'])
  expect(block('shared:r:top')?.rows.map(row => row.text)).toEqual(['You: “Leave the tests alone.”'])
  expect(block('shared:r:agent:tester')?.rows.map(row => [row.kind, row.text])).toEqual([
    ['notebook', 'Tester: “and lint.py”'],
    ['notebook', 'Tester: “and the docs”'],
    ['more', '+2 more notes'],
  ])
  // (On hover: who wrote it, when, and all of it; its turn too where its topic numbers it.)
  expect(block('shared:r:agent:tester')?.rows[0].title).toMatch(/^Tester · [^·]+ · to the notebook\nand lint.py$/)
  expect(edges.filter(e => e.shared)).toEqual([
    { id: 'shared:shared:r:top', source: 'agent:lead', target: 'shared:r:top', active: false, shared: { colour: 'var(--accent)', dotted: false } },
    { id: 'shared:shared:r:agent:tester', source: 'agent:tester', target: 'shared:r:agent:tester', active: false, shared: { colour: 'var(--accent)', dotted: true } },
  ])
  // Folded, the writer's box is still there for its line.
  expect(foldGraph({ nodes, edges }, { 'agent:tester': false }).edges.some(e => e.shared)).toBe(true)
})

test('a turn that used nothing has no card - KOLONİ’s own note is on the Notes tab only - and each turn has its own', () => {
  expect(deriveGraph({ ...state, boardPosts: [] }).nodes.some(n => n.kind === 'shared')).toBe(false)
  const ended = note('n8', 'r', { agent_id: null, koloni: true, content: 'Waits for you: the plan.' })
  expect(deriveGraph({ ...state, boardPosts: [ended] }).nodes.some(n => n.kind === 'shared')).toBe(false)
  const two = {
    ...state,
    runs: [run('r', 'completed'), run('s', 'running')],
    agents: [...state.agents, agent('s', 'running')],
    messages: [...state.messages, userMessage('s', 'and now?')],
    boardPosts: [first, note('n9', 's', { agent_id: null, content: 'Second turn.' })],
  }
  expect(deriveGraph(two).nodes.filter(n => n.kind === 'shared').map(n => n.runId)).toEqual(['r', 's'])
})

test('a note’s row opens the Notes tab at that note, on its own turn’s notebook', async () => {
  const later = { ...state, runs: [run('r', 'completed'), run('s', 'running')], messages: [...state.messages, userMessage('s', 'next')], boardPosts: [first, second, note('n9', 's', { content: 'Later.' })] }
  const data = deriveGraph(later).nodes.find(n => n.id === 'shared:r:agent:tester')!.data as SharedData
  render(
    <ReactFlowProvider>
      <SharedNode {...({ id: 'shared:r:agent:tester', data, selected: false } as unknown as NodeProps<Node<SharedData & Record<string, unknown>>>)} />
    </ReactFlowProvider>,
  )
  const row = screen.getByRole('button', { name: 'Tester: “hello.py is mine” - open it on the Notes tab' })
  expect(row).toHaveAttribute('title', expect.stringContaining('hello.py is mine'))
  await userEvent.click(row)
  expect([useApp.getState().chatTab, useApp.getState().chatAt]).toEqual(['Notes', 'note-n1'])
  // The Notes tab shows that note's turn - not the one at work - with the note there.
  const { container } = render(<NotesPanel state={later} onWrite={async () => {}} />)
  expect(container.querySelector('#note-n1')).toHaveTextContent('hello.py is mine')
  expect(screen.queryByText('Later.')).not.toBeInTheDocument()
})

// --- a notebook per team, and KOLONİ's note (K-not-oda) ----------------------------------

test('a turn with teams has a notebook per team, each in its colour; a note for every team says so; KOLONİ’s note stands apart', () => {
  const rows = [
    { team_id: 'web', recipe_id: null, no_recipe: false, picked_by: 'user' as const, why: null, state: null },
    { team_id: 'docs', recipe_id: null, no_recipe: false, picked_by: 'user' as const, why: null, state: null },
  ]
  const teamed = convState({
    conversation: { ...state.conversation, teams_mode: 'manual', teams: rows },
    runs: [{ ...run('r', 'completed'), ended_at: '2026-10-05T10:09:00Z' }],
    agents: state.agents,
    boardPosts: [
      note('n1', 'r', { agent_id: 'coder', content: 'web/app.js is mine', team_id: 'web', team: 'Web app' }),
      note('n2', 'r', { agent_id: 'tester', content: 'the API is /v2', team_id: 'web', team: 'Web app', everyone: true }),
      note('n3', 'r', { agent_id: 'lead', content: 'Docs: wait for the API' }),
      note('n4', 'r', { agent_id: 'coder', content: 'b.md says /v2', team_id: 'docs', team: 'Docs' }),
      note('n5', 'r', { agent_id: null, koloni: true, content: 'This turn is done. Done: Coder.', created_at: '2026-10-05T10:09:01Z' }),
    ],
  })
  render(<NotesPanel state={teamed} onWrite={async () => {}} />)
  const groups = screen.getAllByRole('region')
  expect(groups.map(g => g.getAttribute('aria-label'))).toEqual(['For every team', 'Web app notes', 'Docs notes'])
  // the whole turn's first, then each team's, in the order the notes were written
  expect(groups[1]).toHaveTextContent('web/app.js is mine')
  expect(groups[1]).toHaveTextContent('the API is /v2')
  expect(groups[2]).toHaveTextContent('b.md says /v2')
  const colours = chatColours(teamed)
  const dot = (group: HTMLElement) => (group.querySelector('.team-dot') as HTMLElement).style.background
  expect([dot(groups[1]), dot(groups[2])]).toEqual([colours.get('web'), colours.get('docs')].map(c => toCss(c!)))
  expect(dot(groups[1])).not.toBe(dot(groups[2]))
  // a team lead's note for every team is marked
  expect(within(groups[1]).getByText('for every team')).toBeInTheDocument()
  expect(within(groups[2]).queryByText('for every team')).not.toBeInTheDocument()
  // KOLONİ's note: who wrote it, told apart, and for the next turn
  const koloni = within(groups[0]).getByText('This turn is done. Done: Coder.').closest('.channel-message')!
  expect(koloni).toHaveClass('note-koloni')
  expect(koloni).toHaveTextContent('KOLONİ')
  expect(koloni).toHaveTextContent('written as this work ended, for the next turn')
  expect(within(groups[0]).getByText('Docs: wait for the API').closest('.channel-message')).not.toHaveClass('note-koloni')
})

test('a team’s own note is for its agents and the Lead: another team’s agent is not waited for', () => {
  const web = { team_id: 'web', recipe_id: null, no_recipe: false, picked_by: 'user' as const, why: null }
  const ran = { run_id: 'r', team: 'Web app', recipe: '', status: 'running' as const, steps: [], passes: [], agents: ['coder', 'tester'] }
  const writer = agent('r', 'running', { id: 'docs-writer', parent_agent_id: 'lead', role_name: 'Docs writer', depth: 1 })
  const teamed = {
    ...state,
    conversation: { ...state.conversation, teams_mode: 'manual' as const, teams: [{ ...web, state: ran }] },
    agents: [...state.agents, writer],
  }
  const own = note('n7', 'r', { agent_id: 'tester', team_id: 'web', team: 'Web app' })
  expect(readLine(teamed, own)).toBe('handed to 0 of 2 · not yet to Lead, Coder')
  // a team with no recipe: who is in it is the canvas's guess by roles, so only those handed it are named
  const byRoles = { ...teamed, conversation: { ...teamed.conversation, teams: [{ ...web, state: null }] } }
  expect(readLine(byRoles, own)).toBe('for Web app only · handed to nobody yet')
  const handed = { ...byRoles, messages: [...byRoles.messages, handedNote(own, 'coder')] }
  expect(readLine(handed, own)).toBe('handed to 1 of 1')
  // for every team: every agent of the turn
  expect(readLine(teamed, { ...own, everyone: true })).toBe('handed to 0 of 3 · not yet to Lead, Coder, Docs writer')
})

function toCss(colour: string): string {
  const probe = document.createElement('span')
  probe.style.background = colour
  return probe.style.background
}
