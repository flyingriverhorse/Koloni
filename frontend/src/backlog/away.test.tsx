import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import type { Away, AwayJob, Project } from '../api/types'
import { type Node, type NodeProps, ReactFlowProvider } from '@xyflow/react'
import { type AwayJobData, deriveGraph } from '../canvas/deriveGraph'
import { AwayJobNode } from '../canvas/nodes'
import { useApp } from '../state/store'
import { agent, convState, run, userMessage } from '../test-fixtures'
import { AwayCard, AwayFrom, AwayNight, AwayReport, AwayStatus } from './Away'

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

test('the card lists the jobs and what is kept out; only Start starts it, and Change the list edits it first', async () => {
  const { awayDo } = stub()
  render(<AwayCard card={card({})} />)
  const it = screen.getByRole('region', { name: "While you're away" })
  expect(it).toHaveTextContent('Forgot my password page')
  expect(it).toHaveTextContent('the link, the email, the form')
  expect(it).toHaveTextContent('Kept out: src/payments')
  expect(awayDo).not.toHaveBeenCalled() // shown, nothing started
  await userEvent.click(screen.getByRole('button', { name: 'Change the list' }))
  await userEvent.click(screen.getByRole('button', { name: 'Take out README install' }))
  await userEvent.click(screen.getByRole('button', { name: '+ Add a job' }))
  await userEvent.type(screen.getByRole('textbox', { name: 'Job 2' }), 'Welcome email retries')
  await userEvent.click(screen.getByRole('button', { name: 'Save the list' }))
  expect(awayDo).toHaveBeenCalledWith('a1', 'change', {
    jobs: [
      { title: 'Forgot my password page', line: 'the link, the email, the form', team: 'Web app', recipe: null, task_id: 't1' },
      { title: 'Welcome email retries', line: null, team: null, recipe: null },
    ],
    kept_out: ['src/payments'],
  })
  await userEvent.click(screen.getByRole('button', { name: 'Start' }))
  expect(awayDo).toHaveBeenLastCalledWith('a1', 'start', undefined)
  await userEvent.click(screen.getByRole('button', { name: 'Not now' }))
  expect(awayDo).toHaveBeenLastCalledWith('a1', 'dismiss', undefined)
})

test('K-vekil-karar: the card suggests the Lead answers while you are away, one click, never on its own', async () => {
  // (The project's, every chat's since tek-ev.)
  const saveProjectSettings = vi.fn(async () => {})
  const folder = (when_away: 'waits' | 'lead') => [{ id: 'p1', when_away } as Project]
  useApp.setState({ saveProjectSettings, conv: convState({ conversation: { ...convState({}).conversation, id: 'c1', project_id: 'p1' } }), projects: folder('waits') })
  const { rerender } = render(<AwayCard card={card({})} />)
  expect(saveProjectSettings).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: 'Let the Orchestrator answer what it safely can' }))
  expect(saveProjectSettings).toHaveBeenCalledWith({ when_away: 'lead' })
  useApp.setState({ projects: folder('lead') })
  rerender(<AwayCard card={card({})} />)
  expect(screen.queryByRole('button', { name: 'Let the Orchestrator answer what it safely can' })).toBeNull()
  expect(screen.getByRole('region', { name: "While you're away" })).toHaveTextContent('The Orchestrator answers what it safely can for you')
})

test('once started or put away, the card is one line', () => {
  stub()
  const { rerender } = render(<AwayCard card={card({ status: 'dismissed' })} />)
  expect(screen.getByRole('note')).toHaveTextContent('Not now: this card was put away.')
  rerender(<AwayCard card={card({ status: 'ended', why: 'Stopped by you.' })} />)
  expect(screen.getByRole('note')).toHaveTextContent('Stopped by you. The report is on the canvas.')
  expect(screen.queryByRole('button', { name: 'Start' })).toBeNull()
})

test('the top bar says which job of how many and until when, with Stop all - only while the night runs', async () => {
  const { awayDo } = stub()
  const night = card({ status: 'running', jobs: [job({ state: 'done' }), job({ state: 'working' }), job({ state: 'next' })] })
  const { rerender } = render(<AwayStatus away={night} onOpen={() => {}} />)
  expect(screen.getByRole('button', { name: /^☾ Away · job 2 of 3 · until \d\d:\d\d$/ })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Stop all' }))
  expect(awayDo).toHaveBeenCalledWith('a1', 'stop')
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
  const proposed = { id: 'p1', title: 'Rate-limit the reset form', detail: null, criteria: null, priority: 'normal' as const, status: 'proposed' as const, position: 3, conversation_id: null, created_by: 'agent' as const, pending: null, assessment: null, not_in: false, after: [], queued: false, waiting: false }
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

test('the card says how long a job may work, that a plan counts no money, and a stop many hours away', () => {
  stub()
  const until = new Date(Date.now() + 20 * 3_600_000).toISOString()
  render(<AwayCard card={card({ until, on_plan: 'Claude' })} />)
  const it = screen.getByRole('region', { name: "While you're away" })
  expect(it).toHaveTextContent('A job works at most 60 minutes')
  expect(it).toHaveTextContent('No money is counted on Claude, a plan')
  expect(it).toHaveTextContent('(that is in about 20 hours, tomorrow)')
  expect(it).not.toHaveTextContent('no time limit')
})

test('a card with no stop time says the time limit is off (the user, 6 Nov)', () => {
  stub()
  render(<AwayCard card={card({ until: null, on_plan: 'Claude' })} />)
  const it = screen.getByRole('region', { name: "While you're away" })
  expect(screen.getByLabelText('Stop at')).toHaveValue('')
  expect(it).toHaveTextContent('(empty: no time limit) or after')
  expect(it).toHaveTextContent('there only the time holds, once you set one.')
  expect(it).not.toHaveTextContent('in about')
  expect(it).not.toHaveTextContent('no spend limit')
})

test('a card with no money says there is no spend limit, never a dollar default (the user, 6 Nov)', () => {
  stub()
  render(<AwayCard card={card({ money: null })} />)
  const it = screen.getByRole('region', { name: "While you're away" })
  expect(screen.getByLabelText('Stop after spending')).toHaveValue(null)
  expect(it).toHaveTextContent('USD (empty: no spend limit), whichever comes first')
  expect(it).not.toHaveTextContent(/\$\d|5\.00|null/)
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

test('the card says a stop under an hour away in minutes', () => {
  stub()
  render(<AwayCard card={card({ until: new Date(Date.now() + 40 * 60_000 + 20_000).toISOString() })} />)
  expect(screen.getByRole('region', { name: "While you're away" })).toHaveTextContent('(that is in about 40 minutes)')
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

test('B-146: Ready for you lists a card that waits for its Start and a night job that waits for your word - the job answered in its chat', async () => {
  const { answerAsk } = stub()
  const openConversation = vi.fn(async () => {})
  useApp.setState({ openConversation })
  const { WaitingList } = await import('../chat/MessageList')
  const { waitingSummary, waitingOf } = await import('../chat/waiting')
  const ask = { kind: 'commands' as const, id: 'k1', text: 'Coder asks to run "npm test"' }
  const night = card({ id: 'a0', status: 'ended', jobs: [job({ title: 'two', task_id: 't2', conversation_id: 'c3', state: 'waits', why: ask.text, asks: [ask] }), job({ title: 'one', task_id: 't1', state: 'done' })] })
  const state = convState({ runs: [run('r', 'completed')], away: [night, card({})] })
  expect(waitingSummary(waitingOf(state))).toBe('1 away card to start · 1 away job waiting')
  const on = { onRemoveQueued: vi.fn(), onOpenChange: vi.fn(), onDecide: vi.fn(), onDecideCommand: vi.fn(), onDecideWeb: vi.fn() }
  render(<WaitingList state={state} on={on as never} onDecidePlan={vi.fn()} known={{ roles: [], providers: [] }} />)
  expect(screen.queryByText('Nothing waits for you.')).toBeNull()
  expect(screen.getByRole('region', { name: "While you're away" })).toBeInTheDocument()
  // Ready for you (tek-ev decision 1): what the night's job asks, whole - answered in its chat, where the card is.
  expect(screen.getByText(ask.text)).toHaveClass('mono')
  expect(screen.queryByRole('button', { name: 'Allow and go on' })).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Open its chat to answer' }))
  expect(openConversation).toHaveBeenCalledWith('c3')
  expect(answerAsk).not.toHaveBeenCalled()
})
