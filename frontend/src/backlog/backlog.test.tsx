import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Away, AwayJob, BacklogAuto, BacklogTask, Board, Provider } from '../api/types'
import { waitingTotal } from '../board/waiting'
import { BacklogPage, PLAN_ASK, WaitRow } from './BacklogPage'

const task = (over: Partial<BacklogTask>): BacklogTask => ({
  id: over.title ?? 't',
  title: 't',
  detail: null,
  criteria: null,
  priority: 'normal',
  status: 'todo',
  position: 0,
  conversation_id: null,
  created_by: 'user',
  pending: null,
  assessment: null,
  not_in: false,
  after: [],
  queued: false,
  stuck: null,
  waiting: false,
  ...over,
})

const CHOICE = { permission_mode: 'ask', provider_id: null, model_id: null, lead_work: 'delegates', cannot_run: null } as const

const page = () => ({
  error: null,
  auto: null,
  providers: [] as Provider[],
  onAuto: vi.fn(async () => {}),
  onChoice: vi.fn(async () => {}),
  onAdd: vi.fn(async () => {}),
  onChange: vi.fn(async () => {}),
  onDelete: vi.fn(async (_id: string) => {}),
  onDecide: vi.fn(async (_id: string, _decision: 'approve' | 'reject') => {}),
  onRun: vi.fn(async () => {}),
  onOpen: vi.fn(),
})

/** A task's ⋯, opened: its menu. */
async function more(title: string) {
  await userEvent.click(screen.getByRole('button', { name: `${title}: more` }))
  return screen.getByRole('menu', { name: `${title}: more` })
}

test('moves stay within a priority, by the places the server renumbers', async () => {
  const props = page()
  const backlog = [
    task({ title: 'crash', priority: 'high', position: 2 }),
    task({ title: 'login', position: 0 }),
    task({ title: 'logout', position: 1 }),
  ]
  render(<BacklogPage {...props} backlog={backlog} />)
  let menu = await more('crash')
  expect(within(menu).getByRole('menuitem', { name: 'Move up' })).toBeDisabled()
  expect(within(menu).getByRole('menuitem', { name: 'Move down' })).toBeDisabled() // the next is another priority
  await userEvent.keyboard('{Escape}')
  menu = await more('login')
  expect(within(menu).getByRole('menuitem', { name: 'Move up' })).toBeDisabled()
  await userEvent.click(within(menu).getByRole('menuitem', { name: 'Move down' }))
  expect(props.onChange).toHaveBeenCalledWith('login', { position: 2 })
  expect(screen.queryByRole('menu')).toBeNull() // a pick closes it
  await userEvent.click(within(await more('logout')).getByRole('menuitem', { name: 'Move up' }))
  expect(props.onChange).toHaveBeenCalledWith('logout', { position: 0 })
  // Dragged by its grip onto a task of another priority: it takes that one's place and priority.
  const row = (title: string) => screen.getByRole('listitem', { name: title })
  fireEvent.dragStart(row('logout').querySelector('.backlog-grip')!, { dataTransfer: {} })
  fireEvent.drop(row('crash'))
  expect(props.onChange).toHaveBeenLastCalledWith('logout', { position: 2, priority: 'high' })
})

test('⋯ opens from the keyboard, its items are reached with Tab, and Esc gives the focus back', async () => {
  const props = page()
  render(<BacklogPage {...props} backlog={[task({ title: 'one' }), task({ title: 'two', position: 1 })]} />)
  const dots = screen.getByRole('button', { name: 'two: more' })
  expect(dots).toHaveAttribute('aria-haspopup', 'menu')
  dots.focus()
  await userEvent.keyboard('{Enter}')
  const menu = screen.getByRole('menu', { name: 'two: more' })
  expect(within(menu).getAllByRole('menuitem').map(item => item.textContent)).toEqual(['Edit', 'Waits for', 'Move up', 'Move down', 'Delete'])
  await userEvent.tab()
  expect(within(menu).getByRole('menuitem', { name: 'Edit' })).toHaveFocus()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('menu')).toBeNull()
  expect(dots).toHaveFocus()
  // Move up, from the keyboard alone.
  await userEvent.keyboard('{Enter}')
  await userEvent.tab()
  await userEvent.tab()
  await userEvent.tab()
  expect(screen.getByRole('menuitem', { name: 'Move up' })).toHaveFocus()
  await userEvent.keyboard('{Enter}')
  expect(props.onChange).toHaveBeenCalledWith('two', { position: 0 })
})

test('what waits for you is one row each - new tasks, then "done?", then changes - with its buttons on the row', async () => {
  const props = page()
  const backlog = [
    task({ title: 'form', status: 'review', conversation_id: 'c1', pending: { priority: 'high', status: 'done' }, assessment: 'Criteria 1 and 2 met.' }),
    task({ title: 'remember me', status: 'proposed', created_by: 'agent', criteria: 'stays signed in' }),
  ]
  render(<BacklogPage {...props} backlog={backlog} />)
  const waiting = screen.getByRole('region', { name: 'Waiting for you' })
  expect(within(waiting).getByRole('heading')).toHaveTextContent('Waiting for you 3')
  expect(within(waiting).getAllByRole('group').map(row => row.getAttribute('aria-label'))).toEqual(['Proposed task: remember me', 'Done? form', 'Proposed change: form'])
  // Each a single row: its kind, its title, one second line.
  const proposed = screen.getByRole('group', { name: 'Proposed task: remember me' })
  expect(proposed.querySelectorAll('.backlog-sub')).toHaveLength(1)
  expect(proposed).toHaveTextContent('new task')
  expect(proposed).toHaveTextContent('Proposed by an agent · Done when: stays signed in')
  await userEvent.click(within(proposed).getByRole('button', { name: 'Add' }))
  expect(props.onDecide).toHaveBeenCalledWith('remember me', 'approve')
  expect(screen.queryByRole('button', { name: /^Approve all/ })).toBeNull() // only one proposal
  const change = screen.getByRole('group', { name: 'Proposed change: form' })
  expect(change).toHaveTextContent('Priority normal → high')
  expect(change).toHaveTextContent('Status done? → done') // in the page's words
  await userEvent.click(within(change).getByRole('button', { name: 'Reject' }))
  expect(props.onDecide).toHaveBeenCalledWith('form', 'reject')
  // Its turn over, it waits too - one row for each thing the badge counts; done is the user's word.
  const done = screen.getByRole('group', { name: 'Done? form' })
  expect(done).toHaveTextContent('An agent’s view (an opinion): Criteria 1 and 2 met.')
  await userEvent.click(within(done).getByRole('button', { name: 'Open chat' }))
  expect(props.onOpen).toHaveBeenCalledWith('c1')
  await userEvent.click(within(done).getByRole('button', { name: 'Done' }))
  expect(props.onChange).toHaveBeenCalledWith('form', { status: 'done' })
  await userEvent.click(within(done).getByRole('button', { name: 'Not yet' }))
  expect(props.onChange).toHaveBeenCalledWith('form', { status: 'todo' })
  // The proposed one is not on the list until it is approved; the view, under the opened title, is not its status.
  const tasks = screen.getByRole('list', { name: 'Tasks' })
  expect(within(tasks).queryByText('remember me')).toBeNull()
  expect(within(tasks).queryByText(/an opinion, not a status/)).toBeNull()
  expect(within(tasks).getByText('A change to it waits for you above')).toBeInTheDocument()
  await userEvent.click(within(tasks).getByRole('button', { name: 'form' }))
  expect(within(tasks).getByText(/an opinion, not a status/)).toBeInTheDocument()
  expect(screen.getByRole('combobox', { name: 'Status of form' })).toHaveValue('review')
  expect(screen.getByRole('button', { name: 'Run the backlog' })).toBeDisabled() // no task is todo
  expect(screen.getByRole('button', { name: 'Run the backlog' })).toHaveAccessibleDescription('Off')
})

test('Approve all adds the proposed tasks one after another; one refused stays on its row with why', async () => {
  const props = page()
  const order: string[] = []
  props.onDecide.mockImplementation(async (id: string) => {
    order.push(id)
    if (id === 'b') throw new Error('the backlog is full')
  })
  const backlog = ['a', 'b', 'c'].map(title => task({ title, status: 'proposed', created_by: 'agent' }))
  render(<BacklogPage {...props} backlog={[...backlog, task({ title: 'x', status: 'review' })]} />)
  await userEvent.click(screen.getByRole('button', { name: 'Approve all 3 proposals' }))
  expect(order).toEqual(['a', 'b', 'c'])
  expect(props.onDecide).toHaveBeenLastCalledWith('c', 'approve')
  expect(within(screen.getByRole('group', { name: 'Proposed task: b' })).getByRole('alert')).toHaveTextContent('the backlog is full')
  expect(within(screen.getByRole('group', { name: 'Proposed task: a' })).queryByRole('alert')).toBeNull()
  expect(props.onChange).not.toHaveBeenCalled() // "done?" is not in it
})

test('a task whose work is not in the project yet is not asked "done?": its row in the list says so (B-78)', async () => {
  const props = page()
  render(<BacklogPage {...props} backlog={[task({ title: 'calc', status: 'review', not_in: true, conversation_id: 'c9' })]} />)
  expect(screen.queryByRole('region', { name: 'Waiting for you' })).toBeNull()
  const row = within(screen.getByRole('listitem', { name: 'calc' }))
  expect(row.getByText('needs you · Take in')).toBeInTheDocument()
  expect(row.getByText(/Its work is not in the project yet: take it in or discard it in its chat/)).toBeInTheDocument()
  await userEvent.click(row.getByRole('button', { name: 'Open chat · calc' }))
  expect(props.onOpen).toHaveBeenCalledWith('c9')
})

test('a task is deleted from its ⋯ only once the user says so again', async () => {
  const props = page()
  render(<BacklogPage {...props} backlog={[task({ title: 'old' })]} />)
  await userEvent.click(within(await more('old')).getByRole('menuitem', { name: 'Delete' }))
  expect(props.onDelete).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: 'Delete “old”' })).toHaveFocus()
  await userEvent.click(screen.getByRole('button', { name: 'Keep it' }))
  expect(screen.getByRole('button', { name: 'old: more' })).toHaveFocus()
  await userEvent.click(within(await more('old')).getByRole('menuitem', { name: 'Delete' }))
  await userEvent.click(screen.getByRole('button', { name: 'Delete “old”' }))
  expect(props.onDelete).toHaveBeenCalledWith('old')
})

test('adding starts from one line: the rest opens once a title is typed, Esc closes it, Enter adds', async () => {
  const props = page()
  render(<BacklogPage {...props} backlog={[]} />)
  const form = within(screen.getByRole('form', { name: 'Add a task' }))
  const title = form.getByLabelText('Title')
  expect(title).toHaveAttribute('placeholder', 'Add a task — title, then Enter')
  expect(form.queryByLabelText('Priority')).toBeNull()
  await userEvent.type(title, 'new one')
  expect(form.getByLabelText('Detail')).toBeInTheDocument()
  expect(form.getByLabelText('Done when (optional)')).toBeInTheDocument()
  await userEvent.selectOptions(form.getByLabelText('Priority'), 'high')
  await userEvent.keyboard('{Escape}')
  expect(form.queryByLabelText('Priority')).toBeNull()
  await userEvent.type(title, '!')
  expect(form.getByLabelText('Priority')).toHaveValue('high') // opened again as it was
  await userEvent.click(form.getByRole('button', { name: 'Add task' }))
  expect(props.onAdd).toHaveBeenLastCalledWith({ title: 'new one!', detail: null, criteria: null, priority: 'high' })
  await userEvent.type(title, 'next{Enter}')
  expect(props.onAdd).toHaveBeenLastCalledWith({ title: 'next', detail: null, criteria: null, priority: 'normal' })
})

test("the rail's badge counts what waits on the backlog too", () => {
  const board: Board = { backlog_waiting: 2, limit: null, running: 0, conflicts: [], conversations: [] }
  expect(waitingTotal(board)).toBe(2)
})

test('Run the backlog and its switch: how the run stands, and where each task stands in it', async () => {
  const props = page()
  const backlog = [
    task({ title: 'one', status: 'doing', conversation_id: 'c1' }),
    task({ title: 'two', status: 'todo', queued: true, after: ['one'] }),
    task({ title: 'three', status: 'todo', queued: true }),
    task({ title: 'four', status: 'blocked', stuck: 'the check "pytest" did not pass' }),
    task({ title: 'five', status: 'review', not_in: true }),
    task({ title: 'six', status: 'doing', waiting: true }),
  ]
  const { rerender } = render(<BacklogPage {...props} backlog={backlog} auto={{ ...CHOICE, on: false, halt: null }} />)
  const button = screen.getByRole('button', { name: 'Run the backlog' })
  expect(button).toHaveAccessibleDescription('Running 2 of 4')
  expect(screen.getByRole('region', { name: 'Your tasks' })).toHaveTextContent('Your tasks · 6')
  const row = (title: string) => within(screen.getByRole('listitem', { name: title }))
  expect(row('one').getByText('running')).toHaveClass('tag')
  expect(row('two').getByText('waits for: one')).toHaveClass('backlog-sub')
  expect(row('two').getByText('queued')).toHaveClass('tag')
  expect(row('three').getByText('queued')).toHaveClass('tag')
  expect(row('four').getByText('stuck: the check "pytest" did not pass')).toBeInTheDocument()
  expect(row('four').getByText('stuck')).toHaveClass('tag')
  expect(row('five').getByText('needs you · Take in')).toBeInTheDocument()
  expect(row('six').getByText('waiting for you')).toBeInTheDocument() // its turn asks you mid-way
  await userEvent.click(button)
  expect(props.onRun).toHaveBeenCalled()
  const toggle = screen.getByRole('switch', { name: 'Runs by itself' })
  expect(toggle).toHaveAccessibleDescription(/^Off: tasks start only from Run the backlog\. A task not finished gets one fix round/)
  await userEvent.click(toggle)
  expect(props.onAuto).toHaveBeenCalledWith(true)
  // a limit reached: paused, and why
  rerender(<BacklogPage {...props} backlog={backlog} auto={{ ...CHOICE, on: true, halt: 'Paused: the project is over this month’s budget.' }} />)
  expect(toggle).toBeChecked()
  expect(button).toHaveAccessibleDescription('Paused: the project is over this month’s budget.')
})

test('a task that waits for one at "done?" says why, and so does the run (B-349)', () => {
  const backlog = [
    task({ title: 'one', status: 'review' }),
    task({ title: 'two', status: 'review', not_in: true }),
    task({ title: 'three', queued: true, after: ['one', 'two'] }),
  ]
  render(<BacklogPage {...page()} backlog={backlog} auto={{ ...CHOICE, on: false, halt: null }} />)
  const why = 'one (done? - press Done above to go on), two (waiting for you - Take in)'
  expect(within(screen.getByRole('listitem', { name: 'three' })).getByText(`waits for: ${why}`)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Run the backlog' })).toHaveAccessibleDescription(`Nothing running: waits for ${why}`)
})

test('a provider no backlog task can run on is said beside Run the backlog, and nothing starts the run until it is changed', () => {
  const why = "Default (agy) works with its own tools, so backlog tasks can't run on it - choose a provider."
  const backlog = [task({ title: 'one' })]
  const { rerender } = render(<BacklogPage {...page()} backlog={backlog} auto={{ ...CHOICE, on: false, halt: null, cannot_run: why }} />)
  expect(screen.getByText(why)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Run the backlog' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Run the backlog' })).toHaveAccessibleDescription(`Off · ${why}`)
  expect(screen.getByRole('button', { name: 'Run the backlog' })).toHaveAttribute('title', why)
  expect(screen.getByRole('switch', { name: 'Runs by itself' })).toBeDisabled()
  // on already, it can still be turned off
  rerender(<BacklogPage {...page()} backlog={backlog} auto={{ ...CHOICE, on: true, halt: null, cannot_run: why }} />)
  expect(screen.getByRole('switch', { name: 'Runs by itself' })).toBeEnabled()
})

test('the level and the model of the chats the backlog opens are chosen under Run settings (B-350)', async () => {
  const props = page()
  const providers = [{ id: 'p1', name: 'Local', kind: 'openai_compat', default_model: 'qwen', models: [] }] as unknown as Provider[]
  const { rerender } = render(<BacklogPage {...props} providers={providers} backlog={[]} auto={{ ...CHOICE, on: false, halt: null }} />)
  expect(screen.queryByLabelText('Its chats’ level')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Run settings' }))
  expect(screen.getByRole('button', { name: 'Run settings' })).toHaveAttribute('aria-expanded', 'true')
  await userEvent.selectOptions(screen.getByLabelText('Its chats’ level'), 'full_auto')
  expect(props.onChoice).toHaveBeenCalledWith({ permission_mode: 'full_auto', provider_id: null, model_id: null, lead_work: 'delegates' })
  expect(screen.queryByText('Full auto', { selector: '.tag' })).toBeNull()
  rerender(<BacklogPage {...props} providers={providers} backlog={[]} auto={{ ...CHOICE, on: false, halt: null, permission_mode: 'full_auto' }} />)
  // Its warning is outside the panel: a tag beside Run settings, the sentence behind its ⓘ.
  expect(screen.getByText('Full auto', { selector: '.tag' })).toBeInTheDocument()
  expect(screen.getByLabelText('Its chats’ level')).toHaveAccessibleDescription(/^Full auto: its chats change files and run commands without asking\. .* it never answers for you\.$/)
  await userEvent.selectOptions(screen.getByLabelText('Provider'), 'p1')
  expect(props.onChoice).toHaveBeenLastCalledWith({ permission_mode: 'full_auto', provider_id: 'p1', model_id: null, lead_work: 'delegates' })
  rerender(<BacklogPage {...props} providers={providers} backlog={[]} auto={{ ...CHOICE, on: false, halt: null, permission_mode: 'full_auto', provider_id: 'p1' }} />)
  await userEvent.type(screen.getByLabelText('Model name'), 'small')
  await userEvent.tab()
  expect(props.onChoice).toHaveBeenLastCalledWith({ permission_mode: 'full_auto', provider_id: 'p1', model_id: 'small', lead_work: 'delegates' })
  // K-r144: and who changes the files there, as a chat's own choice
  await userEvent.selectOptions(screen.getByLabelText('Who changes the files'), 'itself')
  expect(props.onChoice).toHaveBeenLastCalledWith({ permission_mode: 'full_auto', provider_id: 'p1', model_id: null, lead_work: 'itself' })
})

test('what a task waits for is chosen from its ⋯', async () => {
  const props = page()
  render(<BacklogPage {...props} backlog={[task({ title: 'one' }), task({ title: 'two', position: 1 })]} />)
  await userEvent.click(within(await more('two')).getByRole('menuitem', { name: 'Waits for' }))
  expect(screen.getByLabelText(/^Waits for/)).toHaveFocus()
  await userEvent.selectOptions(screen.getByLabelText(/^Waits for/), 'one')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(props.onChange).toHaveBeenCalledWith('two', expect.objectContaining({ title: 'two', after: ['one'] }))
  // Edit opens the same form, on its title.
  await userEvent.click(within(await more('one')).getByRole('menuitem', { name: 'Edit' }))
  expect(within(screen.getByRole('form', { name: 'Edit one' })).getByLabelText('Title')).toHaveFocus()
})

test('a title typed while the last add is still going through is kept', async () => {
  const props = page()
  let through = () => {}
  props.onAdd.mockImplementationOnce(() => new Promise<void>(resolve => (through = resolve)))
  render(<BacklogPage {...props} backlog={[]} />)
  const title = within(screen.getByRole('form', { name: 'Add a task' })).getByLabelText('Title')
  await userEvent.type(title, 'one')
  await userEvent.click(screen.getByRole('button', { name: 'Add task' }))
  await userEvent.clear(title)
  await userEvent.type(title, 'two')
  expect(props.onAdd).toHaveBeenCalledWith(expect.objectContaining({ title: 'one' }))
  await act(async () => through())
  expect(title).toHaveValue('two')
})

test('the night is one line when nothing of it waits for you; a job that does keeps it open, its buttons in sight', () => {
  const job = (over: Partial<AwayJob>): AwayJob => ({
    title: 'job', line: null, team: null, recipe: null, task_id: null, conversation_id: null, state: 'done', why: null, assessment: null,
    kept: [], files: [], taken: [], shared: [], kept_out: [], asks: [], checks: [], now: null, spent: null, ...over,
  })
  const night = (jobs: AwayJob[]): Away => ({
    id: 'a1', project_id: 'p1', conversation_id: 'c1', run_id: 'r', status: 'running', jobs, kept_out: [], until: null, money: null,
    started_at: '2026-10-26T21:42:00Z', ended_at: null, why: null, seen_at: null, tried: [], slipped: [], job_minutes: 60, on_plan: null,
    spent: null, currency: 'USD', at_least: false, counts: {}, proposed: [],
  })
  const jobs = [job({ title: 'one' }), job({ title: 'two', state: 'working' })]
  const { rerender } = render(<BacklogPage {...page()} backlog={[]} away={night(jobs)} />)
  const region = screen.getByRole('region', { name: "While you're away" })
  expect(within(region).getByText("☾ While you're away: 1 of 2 done").closest('details')).not.toHaveAttribute('open')
  const ask = { kind: 'commands' as const, id: 'k1', text: 'Coder asks to run "npm test"' }
  rerender(<BacklogPage {...page()} backlog={[]} away={night([...jobs, job({ title: 'three', state: 'waits', asks: [ask] })])} />)
  expect(region.querySelector('details')).toBeNull()
  expect(within(region).getByRole('button', { name: 'Allow and go on' })).toBeVisible()
})

test('what is decided is never cut before its button: a waiting row wraps whole, only a task row folded cuts its line', () => {
  const style = document.createElement('style')
  style.textContent = readFileSync('src/theme/memory.css', 'utf8') // (run from frontend/)
  document.head.append(style)
  const long = 'x'.repeat(400)
  render(<BacklogPage {...page()} backlog={[task({ title: 'form', pending: { detail: long } }), task({ title: 'calc', status: 'blocked', stuck: long })]} />)
  const change = screen.getByRole('group', { name: 'Proposed change: form' })
  expect(getComputedStyle(change.querySelector('.backlog-sub')!).whiteSpace).toBe('pre-wrap')
  expect(within(change).getByRole('button', { name: 'Change' })).toBeEnabled()
  expect(getComputedStyle(screen.getByRole('listitem', { name: 'calc' }).querySelector('.backlog-sub')!).whiteSpace).toBe('nowrap')
  style.remove()
})

test("a task's waiting rows stand by themselves too, each decision its own row (the Ready panel's)", async () => {
  const props = page()
  render(<WaitRow task={task({ title: 'form', status: 'review', pending: { priority: 'high' } })} onDecide={props.onDecide} onChange={props.onChange} onOpen={props.onOpen} />)
  expect(screen.getAllByRole('group').map(row => row.getAttribute('aria-label'))).toEqual(['Done? form', 'Proposed change: form'])
  await userEvent.click(within(screen.getByRole('group', { name: 'Proposed change: form' })).getByRole('button', { name: 'Change' }))
  expect(props.onDecide).toHaveBeenCalledWith('form', 'approve')
})

// "Write it with the Product owner" (6 Nov): what is typed, written as tasks by a model asked once; nothing is added without the user.
const paid = { id: 'p2', name: 'Cloud', kind: 'openai_compat', base_url: 'https://api.example.com/v1', default_model: 'mini', models: [] } as unknown as Provider
const drafter = (over: Partial<NonNullable<BacklogAuto['drafter']>> = {}) => ({ ...CHOICE, on: false, halt: null, drafter: { why: null, provider_id: 'p2', model_id: null, ...over } })

test('the note is written as tasks once there is text: each changed, added by your word, or all at once', async () => {
  const props = page()
  const onDraft = vi.fn(async (_text: string) => ({
    by: 'Cloud (mini)',
    tasks: [
      { title: 'Fix login on mobile', detail: 'Breaks under 400 px', criteria: 'Fits 360 px', priority: 'high' as const },
      { title: 'Password reset', detail: null, criteria: null, priority: 'normal' as const },
      { title: 'Remember me', detail: null, criteria: null, priority: 'low' as const },
    ],
  }))
  render(<BacklogPage {...props} backlog={[]} providers={[paid]} auto={drafter()} onDraft={onDraft} onPlan={vi.fn(async () => {})} />)
  expect(screen.queryByRole('button', { name: 'Write it with the Product owner' })).toBeNull()
  await userEvent.type(screen.getByLabelText('Title'), 'login mobilde bozuk')
  const write = screen.getByRole('button', { name: 'Write it with the Product owner' })
  // Who writes them and what it costs, in sight - never behind a ⓘ.
  expect(write).toHaveAccessibleDescription('Cloud (mini) writes them: one request you pay for. Nothing is saved until you add it.')
  await userEvent.click(write)
  expect(onDraft).toHaveBeenCalledWith('login mobilde bozuk')
  const drafts = await screen.findByRole('region', { name: 'Drafted tasks' })
  expect(within(drafts).getByText(/Written by Cloud \(mini\)/)).toBeVisible()
  expect(props.onAdd).not.toHaveBeenCalled()
  const first = within(drafts).getByRole('group', { name: 'Draft 1' })
  await userEvent.clear(within(first).getByLabelText('Title'))
  await userEvent.type(within(first).getByLabelText('Title'), 'Fix the login page')
  await userEvent.selectOptions(within(first).getByLabelText('Priority'), 'normal')
  await userEvent.click(within(first).getByRole('button', { name: 'Add' }))
  expect(props.onAdd).toHaveBeenCalledWith({ title: 'Fix the login page', detail: 'Breaks under 400 px', criteria: 'Fits 360 px', priority: 'normal' })
  await userEvent.click(within(drafts).getByRole('button', { name: 'Remove draft 2' })) // (Remember me, now the second)
  expect(within(drafts).getAllByRole('group', { name: /^Draft/ }).map(one => within(one).getByLabelText<HTMLInputElement>('Title').value)).toEqual(['Password reset'])
  await userEvent.click(within(drafts).getByRole('button', { name: 'Add all' }))
  expect(props.onAdd).toHaveBeenLastCalledWith({ title: 'Password reset', detail: null, criteria: null, priority: 'normal' })
  expect(props.onAdd).toHaveBeenCalledTimes(2)
  expect(screen.queryByRole('region', { name: 'Drafted tasks' })).toBeNull()
})

test('with no model to ask the button says why; Plan it in a chat asks for the Product owner', async () => {
  const props = page()
  const onPlan = vi.fn(async (_message: string) => {})
  const why = 'There is no model to ask: add a provider on the Models page.'
  render(<BacklogPage {...props} backlog={[]} providers={[]} auto={drafter({ why, provider_id: null })} onDraft={vi.fn()} onPlan={onPlan} />)
  await userEvent.type(screen.getByLabelText('Title'), 'şifre sıfırlama lazım')
  const write = screen.getByRole('button', { name: 'Write it with the Product owner' })
  expect(write).toBeDisabled()
  expect(write).toHaveAccessibleDescription(why)
  await userEvent.click(screen.getByRole('button', { name: 'Plan it in a chat' }))
  expect(onPlan).toHaveBeenCalledWith(`${PLAN_ASK}şifre sıfırlama lazım`)
  expect(props.onAdd).not.toHaveBeenCalled()
})

test('while Add all runs, the drafts are held: none is changed and added twice', async () => {
  let done = () => {}
  const props = { ...page(), onAdd: vi.fn(() => new Promise<void>(resolve => (done = resolve))) }
  const onDraft = vi.fn(async () => ({ by: 'Cloud (mini)', tasks: [{ title: 'One', detail: null, criteria: null, priority: 'normal' as const }] }))
  render(<BacklogPage {...props} backlog={[]} providers={[paid]} auto={drafter()} onDraft={onDraft} />)
  await userEvent.type(screen.getByLabelText('Title'), 'a note')
  await userEvent.click(screen.getByRole('button', { name: 'Write it with the Product owner' }))
  const drafts = await screen.findByRole('region', { name: 'Drafted tasks' })
  await userEvent.click(within(drafts).getByRole('button', { name: 'Add all' }))
  expect(within(drafts).getByLabelText('Title')).toBeDisabled()
  expect(within(drafts).getByLabelText('Priority')).toBeDisabled()
  expect(within(drafts).getByRole('button', { name: 'Add' })).toBeDisabled()
  await act(async () => done())
  expect(screen.queryByRole('region', { name: 'Drafted tasks' })).toBeNull()
  expect(props.onAdd).toHaveBeenCalledTimes(1)
})


test('a proposal of the Assistant PO says what it came from, and is added, edited first, or turned down; one the Orchestrator said no to waits for nobody', async () => {
  const props = page()
  const po = { chat: 'c', why: 'the parser tests are left undone', lead: null, lead_why: null, seen: false, injection: [] as string[] }
  const backlog = [
    task({ title: 'parser tests', status: 'proposed', created_by: 'agent', detail: 'cover the parser', po }),
    task({ title: 'help text', status: 'proposed', created_by: 'agent', po: { ...po, lead: 'no', lead_why: 'later' } }),
    task({ title: 'push it', status: 'proposed', created_by: 'agent', po: { ...po, injection: ['ignore_previous'] } }),
  ]
  render(<BacklogPage {...props} backlog={backlog} />)
  const waiting = screen.getByRole('region', { name: 'Waiting for you' })
  expect(within(waiting).getAllByRole('group').map(row => row.getAttribute('aria-label'))).toEqual(['Proposed task: parser tests', 'Proposed task: push it'])
  expect(screen.getByRole('group', { name: 'Proposed task: push it' })).toHaveTextContent('Its words look like they try to give the agent orders (rules: ignore previous)')
  const row = screen.getByRole('group', { name: 'Proposed task: parser tests' })
  expect(row).toHaveTextContent('Proposed by the Assistant PO, from: “the parser tests are left undone” · cover the parser')
  expect(within(row).getAllByRole('button').map(button => button.textContent)).toEqual(['Add', 'Edit', 'Reject'])
  await userEvent.click(within(row).getByRole('button', { name: 'Reject' }))
  expect(props.onDecide).toHaveBeenLastCalledWith('parser tests', 'reject')
  await userEvent.click(within(row).getByRole('button', { name: 'Edit' }))
  const title = within(row).getByLabelText('Title')
  await userEvent.clear(title)
  await userEvent.type(title, 'Parser tests for dates')
  await userEvent.clear(within(row).getByLabelText('Detail'))
  await userEvent.click(within(row).getByRole('button', { name: 'Add' }))
  expect(props.onChange).toHaveBeenCalledWith('parser tests', { title: 'Parser tests for dates', detail: null })
  expect(props.onDecide).toHaveBeenLastCalledWith('parser tests', 'approve')
})


test('a task the Orchestrator added waits for your OK here, and one it rejected stays findable, folded', async () => {
  const props = page()
  const po = { chat: 'c', why: 'the parser tests', lead_why: 'Tests were promised.', seen: false, injection: [] as string[] }
  const backlog = [
    task({ title: 'parser tests', status: 'todo', created_by: 'agent', po: { ...po, lead: 'add' } }),
    task({ title: 'help text', status: 'proposed', created_by: 'agent', po: { ...po, lead: 'no', lead_why: 'Help can wait.' } }),
  ]
  render(<BacklogPage {...props} backlog={backlog} />)
  const added = screen.getByRole('group', { name: 'Added for you: parser tests' })
  expect(added).toHaveTextContent('Added by the Orchestrator at Full auto, not seen by you · “Tests were promised.”')
  await userEvent.click(within(added).getByRole('button', { name: 'OK' }))
  expect(props.onDecide).toHaveBeenLastCalledWith('parser tests', 'approve')
  await userEvent.click(within(added).getByRole('button', { name: 'Reject' }))
  expect(props.onDecide).toHaveBeenLastCalledWith('parser tests', 'reject')
  const folded = screen.getByText('Rejected by the Orchestrator (1)')
  await userEvent.click(folded)
  const rejected = screen.getByRole('group', { name: 'Rejected: help text' })
  expect(rejected).toHaveTextContent('“Help can wait.”')
  await userEvent.click(within(rejected).getByRole('button', { name: 'Add' }))
  expect(props.onDecide).toHaveBeenLastCalledWith('help text', 'approve')
})
