import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import type { Away, AwayJob, BacklogTask } from '../api/types'
import { type Node, type NodeProps, ReactFlowProvider } from '@xyflow/react'
import { type AwayJobData, deriveGraph } from '../canvas/deriveGraph'
import { AwayJobNode } from '../canvas/nodes'
import { useApp } from '../state/store'
import { agent, convState, run, userMessage } from '../test-fixtures'
import { AwayFrom, AwayNight, AwayOffer, AwayReport, AwayStatus, AwaySummary } from './Away'

const job = (over: Partial<AwayJob>): AwayJob => ({
  title: 'job',
  line: null,
  team: null,
  recipe: null,
  task_id: null,
  conversation_id: null,
  state: 'planned',
  why: null,
  assessment: null,
  kept: [],
  files: [],
  taken: [],
  shared: [],
  kept_out: [],
  asks: [],
  checks: [],
  now: null,
  spent: null,
  ...over,
})

const card = (over: Partial<Away>): Away => ({
  id: 'a1',
  project_id: 'p1',
  conversation_id: 'c1',
  run_id: 'r',
  status: 'planned',
  jobs: [job({ title: 'Forgot my password page', line: 'the link, the email, the form', team: 'Web app', task_id: 't1' }), job({ title: 'README install' })],
  kept_out: ['src/payments'],
  until: '2026-10-27T04:00:00Z',
  money: 5,
  started_at: null,
  ended_at: null,
  why: null,
  seen_at: null,
  tried: [],
  slipped: [],
  job_minutes: 60,
  on_plan: null,
  spent: null,
  currency: 'USD',
  at_least: false,
  counts: { done: 0, waits: 0, failed: 0, not_started: 0 },
  proposed: [],
  decided: [],
  ...over,
})

const stub = () => {
  const awayDo = vi.fn(async () => {})
  const answerAsk = vi.fn(async () => {})
  const takeIn = vi.fn(async () => {})
  useApp.setState({ awayDo, answerAsk, takeIn })
  return { awayDo, answerAsk, takeIn }
}

afterEach(() => useApp.setState({ conv: null }))

test('the top bar says which To-do task of how many and until when, with I’m back and Stop all - only while away', async () => {
  const { awayDo } = stub()
  const comeBack = vi.fn(async () => {})
  useApp.setState({ comeBack })
  const night = card({ status: 'running', jobs: [job({ state: 'done' }), job({ state: 'working' }), job({ state: 'next' })] })
  const { rerender } = render(<AwayStatus away={night} onOpen={() => {}} />)
  expect(screen.getByRole('button', { name: /^☾ Away · To-do 2 of 3 · until \d\d:\d\d$/ })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Stop all' }))
  expect(awayDo).toHaveBeenCalledWith('a1', 'stop')
  await userEvent.click(screen.getByRole('button', { name: 'I’m back' }))
  expect(comeBack).toHaveBeenCalledWith('a1')
  rerender(<AwayStatus away={{ ...night, status: 'ended' }} onOpen={() => {}} />)
  expect(screen.queryByRole('button', { name: 'Stop all' })).toBeNull()
})

test('each job as it stands: what waits is answered here, what is done is taken in by you, what failed is tried again once the night is over', async () => {
  const { awayDo, answerAsk, takeIn } = stub()
  const ask = { kind: 'commands' as const, id: 'k1', text: 'Coder asks to run "npm test"' }
  const night = card({
    status: 'ended',
    jobs: [
      job({ title: 'one', task_id: 't1', conversation_id: 'c2', state: 'done', kept: ['m1'], files: ['a.py', 'src/payments/x.py'], kept_out: ['src/payments/x.py'], checks: ['Reviewer: no findings'] }),
      job({ title: 'two', task_id: 't2', conversation_id: 'c3', state: 'waits', why: ask.text, asks: [ask] }),
      job({ title: 'three', task_id: 't3', conversation_id: 'c4', state: 'failed', why: 'model server unreachable' }),
    ],
  })
  const onOpen = vi.fn()
  render(<AwayNight away={night} onOpen={onOpen} />)
  const row = (name: RegExp) => screen.getByRole('listitem', { name })
  expect(row(/^one: Done/)).toHaveTextContent('2 files in its copy, waits for you')
  expect(row(/^one: Done/)).toHaveTextContent('Its copy changed src/payments/x.py, where you said not to')
  expect(row(/^one: Done/)).toHaveTextContent('Reviewer: no findings')
  await userEvent.click(within(row(/^one: Done/)).getByRole('button', { name: 'Take in' }))
  expect(takeIn).toHaveBeenCalledWith(['m1'])
  await userEvent.click(within(row(/^two: Waits for you/)).getByRole('button', { name: 'Allow and go on' }))
  expect(answerAsk).toHaveBeenCalledWith(ask, true)
  await userEvent.click(within(row(/^two/)).getByRole('button', { name: 'Open its chat' }))
  expect(onOpen).toHaveBeenCalledWith('c3')
  expect(row(/^three: Could not be done/)).toHaveTextContent('model server unreachable')
  await userEvent.click(within(row(/^three/)).getByRole('button', { name: 'Try again' }))
  expect(awayDo).toHaveBeenCalledWith('a1', 'jobs/t3/again')
})

test('a job row while the night runs: what it spent, what it does now, its view, a file shared, See the changes, Not started, Refuse, no Try again yet', async () => {
  const { answerAsk } = stub()
  const ask = { kind: 'commands' as const, id: 'k1', text: 'Coder asks to run "npm test"' }
  const night = card({
    status: 'running',
    jobs: [
      job({ title: 'one', task_id: 't1', conversation_id: 'c2', state: 'done', kept: ['m1'], files: ['a.py'], spent: 0.5, assessment: 'Looks right', shared: ['a.py'] }),
      job({ title: 'two', task_id: 't2', state: 'working', now: 'Running the tests', why: 'still at it' }),
      job({ title: 'three', task_id: 't3', state: 'next', why: 'never said' }),
      job({ title: 'four', task_id: 't4', state: 'failed', why: 'model server unreachable' }),
      job({ title: 'five', task_id: 't5', state: 'waits', why: 'Waits in its chat', asks: [ask] }),
    ],
  })
  const onOpen = vi.fn()
  render(<AwayNight away={night} onOpen={onOpen} />)
  const row = (name: RegExp) => screen.getByRole('listitem', { name })
  const one = row(/^one: Done$/)
  expect(one.querySelector('.away-line')).toHaveTextContent('1 file in its copy, waits for you · 0.50 USD')
  expect(one.querySelector('q.away-view')).toHaveTextContent('Looks right')
  expect(one).toHaveTextContent('Another job changed a.py too: the two are joined line by line when you take both in.')
  await userEvent.click(within(one).getByRole('button', { name: 'See the changes' }))
  expect(onOpen).toHaveBeenCalledWith('c2')
  expect(row(/^two: Working$/).querySelector('.away-now')).toHaveTextContent('Running the tests')
  expect(row(/^two: Working$/).querySelector('.away-line')).toHaveTextContent('still at it')
  expect(row(/^three: Next$/).querySelector('.away-line')).toHaveTextContent('Not started')
  expect(row(/^three: Next$/)).not.toHaveTextContent('never said')
  expect(within(row(/^four/)).queryByRole('button', { name: 'Try again' })).toBeNull()
  expect(within(row(/^four/)).queryByRole('button', { name: 'Open its chat' })).toBeNull()
  expect(row(/^five: Waits for you$/).querySelector('.away-line')).toHaveTextContent('Waits in its chat')
  await userEvent.click(within(row(/^five/)).getByRole('button', { name: 'Refuse' }))
  expect(answerAsk).toHaveBeenCalledWith(ask, false)
})

test("on the canvas the night is the card's turn's: its jobs hang off the Lead, and done and waiting ones lead to the report", () => {
  const night = card({
    status: 'ended',
    started_at: '2026-10-26T21:42:00Z',
    jobs: [job({ title: 'one', task_id: 't1', state: 'done' }), job({ title: 'two', task_id: 't2', state: 'waits' }), job({ title: 'three', task_id: 't3', state: 'next' })],
  })
  const g = deriveGraph(convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed')], messages: [userMessage('r', 'sleep')], away: [night] }))
  expect(g.nodes.filter(n => n.kind === 'awayjob').map(n => n.id)).toEqual(['awayjob:a1:t1', 'awayjob:a1:t2', 'awayjob:a1:t3'])
  expect(g.nodes.some(n => n.id === 'away:a1' && n.kind === 'away')).toBe(true)
  const into = g.edges.filter(e => e.target === 'away:a1').map(e => [e.source, !!e.waits])
  expect(into).toEqual([
    ['awayjob:a1:t1', false],
    ['awayjob:a1:t2', true],
  ])
  // a card not started draws nothing
  const planned = deriveGraph(convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed')], messages: [userMessage('r', 'sleep')], away: [card({})] }))
  expect(planned.nodes.some(n => n.kind === 'away' || n.kind === 'awayjob')).toBe(false)
})

test('the report follows Take in, and a job that changed nothing says so, with no Take in (B-122, B-123)', () => {
  const night = card({
    status: 'ended',
    started_at: '2026-10-26T21:42:00Z',
    ended_at: '2026-10-27T01:05:00Z',
    counts: { done: 3, waits: 0, failed: 0, not_started: 0 },
    jobs: [
      job({ title: 'one', task_id: 't1', state: 'done', taken: ['calc.py'] }),
      job({ title: 'two', task_id: 't2', state: 'done', kept: ['m2'], files: ['notes.md'] }),
      job({ title: 'three', task_id: 't3', state: 'done' }),
    ],
  })
  render(<AwayReport away={night} onOpen={() => {}} />)
  expect(screen.getByText(/done, 1 for you to take in/)).toHaveTextContent('3 done, 1 for you to take in')
  expect(screen.getByText(/what you took in is in your project/)).toBeInTheDocument()
  expect(screen.getByRole('listitem', { name: 'one: Done' })).toHaveTextContent('taken in: calc.py')
  const three = screen.getByRole('listitem', { name: 'three: Done, nothing changed' })
  expect(three).toHaveTextContent('nothing changed')
  expect(within(three).queryByRole('button', { name: 'Take in' })).toBeNull()
})

test("a job cut by the night's stop is stopped, not one that could not be done, and is tried again (B-148)", async () => {
  const { awayDo } = stub()
  const night = card({
    status: 'ended',
    why: 'Stopped by you.',
    counts: { done: 0, waits: 0, failed: 0, stopped: 1, not_started: 1 },
    jobs: [job({ title: 'one', task_id: 't1', conversation_id: 'c2', state: 'stopped', why: 'Stopped by you.' }), job({ title: 'two', state: 'next' })],
  })
  render(<AwayReport away={night} onOpen={() => {}} />)
  expect(screen.getByRole('heading', { name: 'Stopped' })).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Could not be done' })).toBeNull()
  expect(document.querySelector('.away-stopped')).toHaveTextContent('1 stopped')
  const one = screen.getByRole('listitem', { name: 'one: Stopped' })
  expect(one).toHaveTextContent('Stopped by you.')
  await userEvent.click(within(one).getByRole('button', { name: 'Try again' }))
  expect(awayDo).toHaveBeenCalledWith('a1', 'jobs/t1/again')
  const node = { id: 'j', data: { job: night.jobs[0] }, selected: false } as unknown as NodeProps<Node<AwayJobData & Record<string, unknown>>>
  render(
    <ReactFlowProvider>
      <AwayJobNode {...node} />
    </ReactFlowProvider>,
  )
  expect(screen.getByText('STOPPED')).toBeInTheDocument()
})

test("a night job's chat leads back to its night's report; another chat has no such link (B-150)", async () => {
  const openTurn = vi.fn(async () => {})
  const select = vi.fn()
  const night = card({ id: 'a7', conversation_id: 'c1', run_id: 'r1', status: 'ended', started_at: '2026-10-26T21:42:00Z', jobs: [job({ title: 'one', conversation_id: 'c2', state: 'done' })] })
  const was = useApp.getState()
  useApp.setState({ away: night, openTurn, select })
  const { unmount } = render(<AwayFrom chat="c9" />)
  expect(screen.queryByRole('button', { name: /back to their report/ })).toBeNull()
  unmount()
  render(<AwayFrom chat="c2" />)
  const back = screen.getByRole('button', { name: /back to their report/ })
  const at = new Date('2026-10-26T21:42:00Z').toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
  expect(back).toHaveTextContent(`From the jobs started at ${at} while you were away — back to their report`)
  await userEvent.click(back)
  expect(openTurn).toHaveBeenCalledWith('c1', 'r1')
  expect(select).toHaveBeenCalledWith('away:a7')
  useApp.setState({ away: null, openTurn: was.openTurn, select: was.select })
})

test("a job's canvas node says what it left as the report does, not '0 files' (batch-20)", () => {
  const node = (one: AwayJob) => ({ id: 'j', data: { job: one }, selected: false }) as unknown as NodeProps<Node<AwayJobData & Record<string, unknown>>>
  render(
    <ReactFlowProvider>
      <AwayJobNode {...node(job({ title: 'one', state: 'done' }))} />
      <AwayJobNode {...node(job({ title: 'two', state: 'done', taken: ['calc.py'] }))} />
      <AwayJobNode {...node(job({ title: 'three', state: 'done', kept: ['m1'], files: ['a.py', 'b.py'] }))} />
    </ReactFlowProvider>,
  )
  const said = Array.from(document.querySelectorAll('.node-said'), one => one.textContent)
  expect(said).toEqual(['nothing changed', 'taken in: calc.py', '2 files in its copy, waits for you'])
})

test('the report: Take in all takes in every done job, and what was proposed while you were away is kept or dismissed by you', async () => {
  const { takeIn } = stub()
  const decideTask = vi.fn(async () => {})
  useApp.setState({ decideTask })
  const proposed = { id: 'p1', title: 'Rate-limit the reset form', detail: null, criteria: null, priority: 'normal' as const, status: 'proposed' as const, position: 3, conversation_id: null, created_by: 'agent' as const, pending: null, assessment: null, not_in: false, after: [], queued: false, waiting: false, created_at: '2026-10-26T22:00:00Z' }
  const night = card({
    status: 'ended',
    started_at: '2026-10-26T21:42:00Z',
    ended_at: '2026-10-27T01:05:00Z',
    counts: { done: 2, waits: 0, failed: 0, not_started: 0 },
    jobs: [job({ title: 'one', task_id: 't1', state: 'done', kept: ['m1'] }), job({ title: 'two', task_id: 't2', state: 'done', kept: ['m2', 'm3'] })],
    proposed: [proposed],
  })
  render(<AwayReport away={night} onOpen={() => {}} />)
  await userEvent.click(screen.getByRole('button', { name: 'Take in all (2)' }))
  expect(takeIn).toHaveBeenCalledWith(['m1', 'm2', 'm3'])
  expect(screen.getByText('Nothing tried to change src/payments.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Add to To-do' }))
  expect(decideTask).toHaveBeenCalledWith('p1', 'approve')
  await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
  expect(decideTask).toHaveBeenLastCalledWith('p1', 'reject')
})

test("a Take in that is refused (a line clashes) opens the job's chat, where its kept copy's card decides it", async () => {
  stub()
  useApp.setState({ takeIn: vi.fn(async () => Promise.reject(new Error('say whose side is taken of: a.py'))) })
  const onOpen = vi.fn()
  render(<AwayNight away={card({ status: 'ended', jobs: [job({ title: 'one', task_id: 't1', conversation_id: 'c2', state: 'done', kept: ['m1'], files: ['a.py'] })] })} onOpen={onOpen} />)
  await userEvent.click(screen.getByRole('button', { name: 'Take in' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('say whose side is taken of: a.py')
  expect(onOpen).toHaveBeenCalledWith('c2')
})

test('a job that waits says its command once, and one that needs the project itself may be taken in as it is', async () => {
  const { takeIn } = stub()
  const ask = { kind: 'commands' as const, id: 'k1', text: 'Coder asks to run "npm test"' }
  const night = card({
    status: 'ended',
    jobs: [
      job({ title: 'two', task_id: 't2', conversation_id: 'c3', state: 'waits', why: ask.text, asks: [ask] }),
      job({ title: 'build', task_id: 't3', conversation_id: 'c4', state: 'waits', why: 'Needs the project itself: build/ is not in the copy', kept: ['m2'] }),
    ],
  })
  render(<AwayNight away={night} onOpen={vi.fn()} />)
  expect(within(screen.getByRole('listitem', { name: /^two/ })).getAllByText(ask.text)).toHaveLength(1)
  await userEvent.click(within(screen.getByRole('listitem', { name: /^build/ })).getByRole('button', { name: 'Take in' }))
  expect(takeIn).toHaveBeenCalledWith(['m2'])
})

test("the report says apart what a job's copy changed in a place kept out, and a night with nothing for you folds to one line", () => {
  stub()
  const night = card({
    status: 'ended',
    seen_at: '2026-10-27T07:10:00Z',
    tried: [{ task_id: 't1', what: 'Coder: run rm secret' }],
    slipped: [{ task_id: 't1', what: 'one: changed src/payments/x.py in its copy' }],
    jobs: [job({ title: 'one', task_id: 't1', state: 'done' })],
  })
  const { unmount } = render(<AwayReport away={night} onOpen={() => {}} />)
  expect(screen.getByText('Coder: run rm secret - refused')).toBeInTheDocument()
  expect(screen.getByText('one: changed src/payments/x.py in its copy')).toBeInTheDocument()
  unmount()
  render(<AwayNight away={night} onOpen={() => {}} />)
  expect(screen.getByText('☾ While you were away: 1 of 1 done').closest('details')).not.toHaveAttribute('open')
})

test('a night job that waits keeps the night open, even with no question on its row', () => {
  stub()
  const night = card({ status: 'running', jobs: [job({ title: 'one', state: 'done' }), job({ title: 'two', task_id: 't2', conversation_id: 'c3', state: 'waits', why: 'Waits for you in its chat' })] })
  render(<AwayNight away={night} onOpen={vi.fn()} />)
  const region = screen.getByRole('region', { name: "While you're away" })
  expect(region.querySelector('details')).toBeNull()
  expect(within(screen.getByRole('listitem', { name: 'two: Waits for you' })).getByRole('button', { name: 'Open its chat' })).toBeVisible()
})

test('B-146: Ready for you lists a job of Away that waits for your word - not the Orchestrator’s offer; the job answered in its chat', async () => {
  const { answerAsk } = stub()
  const openConversation = vi.fn(async () => {})
  useApp.setState({ openConversation })
  const { WaitingList } = await import('../chat/MessageList')
  const { waitingSummary, waitingOf } = await import('../chat/waiting')
  const ask = { kind: 'commands' as const, id: 'k1', text: 'Coder asks to run "npm test"' }
  const night = card({ id: 'a0', status: 'ended', jobs: [job({ title: 'two', task_id: 't2', conversation_id: 'c3', state: 'waits', why: ask.text, asks: [ask] }), job({ title: 'one', task_id: 't1', state: 'done' })] })
  const state = convState({ runs: [run('r', 'completed')], away: [night, card({})] })
  expect(waitingSummary(waitingOf(state))).toBe('1 away job waiting')
  const on = { onRemoveQueued: vi.fn(), onOpenChange: vi.fn(), onDecide: vi.fn(), onDecideCommand: vi.fn(), onDecideWeb: vi.fn() }
  render(<WaitingList state={state} on={on as never} onDecidePlan={vi.fn()} known={{ roles: [], providers: [] }} />)
  expect(screen.queryByText('Nothing waits for you.')).toBeNull()
  // (the offer is the Go away line under its turn, no card that waits)
  expect(screen.queryByRole('group', { name: 'Go away now?' })).toBeNull()
  // Ready for you (tek-ev decision 1): what the night's job asks, whole - answered in its chat, where the card is.
  expect(screen.getByText(ask.text)).toHaveClass('mono')
  expect(screen.queryByRole('button', { name: 'Allow and go on' })).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Open its chat to answer' }))
  expect(openConversation).toHaveBeenCalledWith('c3')
  expect(answerAsk).not.toHaveBeenCalled()
})

test('the report’s sums: counts that are not there are 0, one waits and two wait, stopped only when there are', () => {
  stub()
  const night = card({ status: 'ended', kept_out: [], counts: { waits: 1 } })
  const { container, rerender } = render(<AwayReport away={night} onOpen={() => {}} />)
  const sums = () => Array.from(container.querySelectorAll('.away-sums > span'), one => `${one.className}: ${one.textContent}`)
  expect(sums()).toEqual(['away-done: 0 done', 'away-waits: 1 waits for your word', 'away-failed: 0 could not be done'])
  // nothing is kept out: the report has no section for it
  expect(screen.queryByRole('heading', { name: 'Kept out, as you asked' })).toBeNull()
  rerender(<AwayReport away={card({ status: 'ended', counts: { done: 2, waits: 2, failed: 1, stopped: 3 } })} onOpen={() => {}} />)
  expect(sums()).toEqual(['away-done: 2 done', 'away-waits: 2 wait for your word', 'away-failed: 1 could not be done', 'away-stopped: 3 stopped'])
  // kept out and nothing tried it: the section says so, in the report's last place
  expect(container.querySelector('.away-report > .away-sec:last-child')).toHaveTextContent('Kept out, as you askedNothing tried to change src/payments.')
})

test('the report’s kept-out list: what was refused first, then what slipped into a copy', () => {
  stub()
  const night = card({ status: 'ended', tried: [{ task_id: 't1', what: 'Coder: run rm secret' }], slipped: [{ task_id: 't1', what: 'one: changed x.py' }] })
  const { container, rerender } = render(<AwayReport away={night} onOpen={() => {}} />)
  const lines = () => Array.from(container.querySelectorAll('.away-sec ul > li'), one => `${one.className}: ${one.textContent}`)
  expect(lines()).toEqual(['mono: Coder: run rm secret - refused', 'mono away-shared: one: changed x.py'])
  expect(screen.queryByText(/Nothing tried to change/)).toBeNull()
  rerender(<AwayReport away={{ ...night, tried: [] }} onOpen={() => {}} />)
  expect(lines()).toEqual(['mono away-shared: one: changed x.py'])
})

const task = (id: string, over: Partial<BacklogTask> = {}): BacklogTask => ({
  id, title: `Task ${id}`, detail: null, criteria: null, priority: 'normal', status: 'proposed', position: 0, conversation_id: null, created_by: 'agent',
  pending: null, assessment: null, not_in: false, after: [], queued: false, stuck: null, waiting: false, created_at: '2026-11-16T10:00:00Z',
  proposed_in: 'c', ...over,
})

test('the Go away line names and sends only the tasks its Orchestrator added - a sub-agent’s or an earlier turn’s stays in the panel', async () => {
  // (The review: one click approved and ran every task any agent proposed in the chat.)
  const goAway = vi.fn(async () => {})
  const mine = ['t1', 't2', 't3', 't4'].map(id => task(id))
  useApp.setState({ goAway, backlog: [...mine, task('sneaky'), task('earlier'), task('old', { status: 'todo', proposed_in: null })] })
  const offer = card({ id: 'o1', conversation_id: 'c', jobs: mine.map(t => job({ title: t.title, task_id: t.id })), kept_out: ['secret106'], until: '2026-11-22T05:00:00Z', money: 2 })
  render(<AwayOffer conv={convState()} offer={offer} />)
  const line = screen.getByRole('group', { name: 'Go away now?' })
  expect(line).toHaveTextContent(/Go away now\? Task t1, Task t2, Task t3 and 1 more · Until \d\d:\d\d · at most 2\.00 USD · kept out secret106/)
  await userEvent.click(within(line).getByRole('button', { name: 'Go away' }))
  expect(goAway).toHaveBeenCalledWith('c', { task_ids: ['t1', 't2', 't3', 't4'], order: [], until: expect.stringMatching(/^\d\d:\d\d$/), money: 2, kept_out: ['secret106'] })
  await userEvent.click(within(line).getByRole('button', { name: 'Change' }))
  expect(screen.getByRole('heading', { name: 'You’re away' })).toBeInTheDocument()
  expect(screen.getByRole('checkbox', { name: 'Task t1' })).toBeChecked()
  expect(screen.getByRole('checkbox', { name: 'Task sneaky' })).not.toBeChecked()
  expect(screen.getByRole('checkbox', { name: 'Task earlier' })).not.toBeChecked()
  useApp.setState({ backlog: null })
})

test('the summary: its span, done of n, what was decided, what waits with Allow and go on, what it spent; Ready and the canvas', async () => {
  const { answerAsk } = stub()
  const showReady = vi.fn()
  const openTurn = vi.fn(async () => {})
  const select = vi.fn()
  const ask = { kind: 'commands' as const, id: 'k1', text: 'Lead asks to run "rm -rf ../old"' }
  const away = card({
    id: 'a9', conversation_id: 'c', status: 'ended', started_at: '2026-11-21T21:10:00Z', ended_at: '2026-11-22T05:42:00Z', decided: ['Opened a Tester', 'ran "rm -rf build" (your words)'],
    jobs: [job({ title: 'Add a bye line', task_id: 't1', state: 'done', kept: ['m1'] }), job({ title: 'Say hello twice', task_id: 't2', state: 'waits', why: ask.text, asks: [ask] })],
  })
  useApp.setState({ away, showReady, openTurn, select })
  const line = 'While you were away (23:10 – 07:42): 1 of 2 To-do done · 2 decided for you · 1 waits · 0.84 USD'
  render(<AwaySummary line={line} conv={convState()} />)
  const summary = screen.getByRole('region', { name: 'While you were away' })
  expect(within(summary).getByRole('heading')).toHaveTextContent('While you were away (23:10 – 07:42)')
  expect(summary).toHaveTextContent('1 of 2 To-do done · 2 decided for you · 1 waits · 0.84 USD')
  expect(summary).toHaveTextContent('done Add a bye line - wait in Ready to take in')
  expect(summary).toHaveTextContent('decided Opened a Tester · ran "rm -rf build" (your words)')
  await userEvent.click(within(summary).getByRole('button', { name: 'Allow and go on' }))
  expect(answerAsk).toHaveBeenCalledWith(ask, true)
  await userEvent.click(within(summary).getByRole('button', { name: 'Review and take in' }))
  expect(showReady).toHaveBeenCalledWith(true)
  await userEvent.click(within(summary).getByRole('button', { name: 'On the canvas' }))
  expect(openTurn).toHaveBeenCalledWith('c', 'r')
  expect(select).toHaveBeenCalledWith('away:a9')
  useApp.setState({ away: null })
})

test('an older summary, or one of another chat, is its one line', () => {
  useApp.setState({ away: card({ conversation_id: 'other', status: 'ended' }) })
  render(<AwaySummary line="While you were away (01:00 – 02:00): 0 of 1 To-do done" conv={convState()} />)
  expect(screen.getByRole('note')).toHaveTextContent('While you were away (01:00 – 02:00): 0 of 1 To-do done')
  useApp.setState({ away: null })
})
