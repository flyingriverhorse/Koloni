import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type {
  Away,
  AwayJob,
  BacklogDrafter,
  BacklogTask,
  Board,
  Goal,
  NewBacklogTask,
  Provider,
  Story,
  TodoTreeIn,
} from '../api/types'
import { waitingTotal } from '../board/waiting'
import { BacklogPage, HIVE_KEEPER_DOES, PLAN_ASK, WaitRow } from './BacklogPage'

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
  stuck: null,
  waiting: false,
  kind: 'task',
  created_at: '2026-10-05T10:00:00Z',
  ...over,
})

const page = () => ({
  error: null,
  providers: [] as Provider[],
  onAdd: vi.fn(async () => {}),
  onChange: vi.fn(async () => {}),
  onDelete: vi.fn(async (_id: string) => {}),
  onDecide: vi.fn(async (_id: string, _decision: 'approve' | 'reject') => {}),
  onDoInChat: vi.fn(async (_ids: string[], _cid: string | null) => {}),
  onOpen: vi.fn(),
})

/** The form a task is added in. */
const addForm = () => within(screen.getByRole('form', { name: 'Add a task' }))

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
  expect(
    within(menu)
      .getAllByRole('menuitem')
      .map(item => item.textContent),
  ).toEqual(['Edit', 'Waits for', 'Move up', 'Move down', 'Delete'])
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
    task({
      title: 'form',
      status: 'review',
      conversation_id: 'c1',
      pending: { priority: 'high', status: 'done' },
      assessment: 'Criteria 1 and 2 met.',
    }),
    task({ title: 'remember me', status: 'proposed', created_by: 'agent', criteria: 'stays signed in' }),
  ]
  render(<BacklogPage {...props} backlog={backlog} />)
  const waiting = screen.getByRole('region', { name: 'Waiting for you' })
  expect(within(waiting).getByRole('heading')).toHaveTextContent('Waiting for you 3')
  expect(
    within(waiting)
      .getAllByRole('group')
      .map(row => row.getAttribute('aria-label')),
  ).toEqual(['Proposed task: remember me', 'Done? form', 'Proposed change: form'])
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
  expect(within(screen.getByRole('group', { name: 'Proposed task: b' })).getByRole('alert')).toHaveTextContent(
    'the backlog is full',
  )
  expect(within(screen.getByRole('group', { name: 'Proposed task: a' })).queryByRole('alert')).toBeNull()
  expect(props.onChange).not.toHaveBeenCalled() // "done?" is not in it
})

test('a task whose work is not in the project yet is not asked "done?": its row in the list says so (B-78)', async () => {
  const props = page()
  render(
    <BacklogPage
      {...props}
      backlog={[task({ title: 'calc', status: 'review', not_in: true, conversation_id: 'c9' })]}
    />,
  )
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
  // The empty list says what a task is, and points at what is already on the page.
  expect(
    screen.getByText(
      'No task yet. A task is work for later: type its title in “Add a task” above, tick it, and Do in chat gives it to a chat.',
    ),
  ).toBeInTheDocument()
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
  expect(props.onAdd).toHaveBeenLastCalledWith({
    title: 'new one!',
    detail: null,
    criteria: null,
    priority: 'high',
    kind: 'task',
  })
  await userEvent.type(title, 'next{Enter}')
  expect(props.onAdd).toHaveBeenLastCalledWith({
    title: 'next',
    detail: null,
    criteria: null,
    priority: 'normal',
    kind: 'task',
  })
})

test("the rail's badge counts what waits on the backlog too", () => {
  const board: Board = { backlog_waiting: 2, limit: null, running: 0, conflicts: [], conversations: [] }
  expect(waitingTotal(board)).toBe(2)
})

test('the page before its list is read and when it could not be; no run settings, no Run the backlog (0.1.8)', () => {
  const props = page()
  const { rerender } = render(<BacklogPage {...props} backlog={null} />)
  expect(screen.getByText('Reading the To-do list…')).toHaveClass('muted')
  expect(screen.queryByRole('region', { name: 'Your tasks' })).toBeNull()
  rerender(<BacklogPage {...props} backlog={null} error="the server is down" />)
  expect(screen.getByRole('alert')).toHaveTextContent('The To-do list could not be read: the server is down')
  expect(screen.queryByText('Reading the To-do list…')).toBeNull()
  rerender(<BacklogPage {...props} backlog={[task({ title: 'one' })]} />)
  for (const gone of ['Run settings', 'Runs by itself', 'Run the backlog', 'On, waiting'])
    expect(document.body).not.toHaveTextContent(gone)
})

test('a task that waits for one at "done?" says why (B-349)', () => {
  const backlog = [
    task({ title: 'one', status: 'review' }),
    task({ title: 'two', status: 'review', not_in: true }),
    task({ title: 'three', after: ['one', 'two'] }),
  ]
  render(<BacklogPage {...page()} backlog={backlog} />)
  const why = 'one (done? - press Done above to go on), two (waiting for you - Take in)'
  expect(within(screen.getByRole('listitem', { name: 'three' })).getByText(`waits for: ${why}`)).toBeInTheDocument()
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
    title: 'job',
    line: null,
    team: null,
    recipe: null,
    task_id: null,
    conversation_id: null,
    state: 'done',
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
  const night = (jobs: AwayJob[]): Away => ({
    id: 'a1',
    project_id: 'p1',
    conversation_id: 'c1',
    run_id: 'r',
    status: 'running',
    jobs,
    kept_out: [],
    until: null,
    money: null,
    started_at: '2026-10-26T21:42:00Z',
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
    counts: {},
    proposed: [],
    decided: [],
  })
  const jobs = [job({ title: 'one' }), job({ title: 'two', state: 'working' })]
  const { rerender } = render(<BacklogPage {...page()} backlog={[]} away={night(jobs)} />)
  const region = screen.getByRole('region', { name: "While you're away" })
  expect(within(region).getByText("☾ While you're away: 1 of 2 done").closest('details')).not.toHaveAttribute('open')
  const ask = { kind: 'commands' as const, id: 'k1', text: 'Coder asks to run "npm test"' }
  rerender(
    <BacklogPage
      {...page()}
      backlog={[]}
      away={night([...jobs, job({ title: 'three', state: 'waits', asks: [ask] })])}
    />,
  )
  expect(region.querySelector('details')).toBeNull()
  expect(within(region).getByRole('button', { name: 'Allow and go on' })).toBeVisible()
})

test('what is decided is never cut before its button: a waiting row wraps whole, only a task row folded cuts its line', () => {
  const style = document.createElement('style')
  style.textContent = readFileSync('src/theme/memory.css', 'utf8') // (run from frontend/)
  document.head.append(style)
  const long = 'x'.repeat(400)
  render(
    <BacklogPage
      {...page()}
      backlog={[
        task({ title: 'form', pending: { detail: long } }),
        task({ title: 'calc', status: 'blocked', stuck: long }),
      ]}
    />,
  )
  const change = screen.getByRole('group', { name: 'Proposed change: form' })
  expect(getComputedStyle(change.querySelector('.backlog-sub')!).whiteSpace).toBe('pre-wrap')
  expect(within(change).getByRole('button', { name: 'Change' })).toBeEnabled()
  expect(
    getComputedStyle(screen.getByRole('listitem', { name: 'calc' }).querySelector('.backlog-sub')!).whiteSpace,
  ).toBe('nowrap')
  style.remove()
})

test("a task's waiting rows stand by themselves too, each decision its own row (the Ready panel's)", async () => {
  const props = page()
  render(
    <WaitRow
      task={task({ title: 'form', status: 'review', pending: { priority: 'high' } })}
      onDecide={props.onDecide}
      onChange={props.onChange}
      onOpen={props.onOpen}
    />,
  )
  expect(screen.getAllByRole('group').map(row => row.getAttribute('aria-label'))).toEqual([
    'Done? form',
    'Proposed change: form',
  ])
  await userEvent.click(
    within(screen.getByRole('group', { name: 'Proposed change: form' })).getByRole('button', { name: 'Change' }),
  )
  expect(props.onDecide).toHaveBeenCalledWith('form', 'approve')
})

// "Write it with the Hive keeper" (6 Nov): what is typed, written as tasks by a model asked once; nothing is added without the user.
const paid = {
  id: 'p2',
  name: 'Cloud',
  kind: 'openai_compat',
  base_url: 'https://api.example.com/v1',
  default_model: 'mini',
  models: [],
} as unknown as Provider
const drafter = (over: Partial<BacklogDrafter> = {}): BacklogDrafter => ({
  why: null,
  provider_id: 'p2',
  model_id: null,
  ...over,
})

const one = (title: string, over: Partial<NewBacklogTask> = {}): NewBacklogTask => ({
  title,
  detail: null,
  criteria: null,
  priority: 'normal',
  kind: 'task',
  ...over,
})
const DRAFT = {
  by: 'Cloud (mini)',
  goal: 'Sign-in holds',
  stories: [
    {
      title: 'Login on mobile',
      notes: ['The form is shared with the desktop page.'],
      tasks: [one('Fix login on mobile', { detail: 'Breaks under 400 px', criteria: 'Fits 360 px', kind: 'bug' })],
    },
    { title: 'Password reset', notes: [], tasks: [one('Password reset'), one('Remember me', { priority: 'low' })] },
  ],
  tasks: [one('Footer year')],
}
/** The bar's Write it with the Hive keeper, pressed: its note box. */
async function noteBox() {
  await userEvent.click(screen.getByRole('button', { name: 'Write it with the Hive keeper' }))
  return within(screen.getByRole('form', { name: 'Write it with the Hive keeper' }))
}
const added = { goal_id: 'g1', story_ids: ['s1'], task_ids: ['t1'] }

test('the note is written as a goal, stories and tasks: each changed, a story added by its Add, the rest by Add all', async () => {
  const props = page()
  const onDraft = vi.fn(async (_text: string) => DRAFT)
  const onAddTree = vi.fn(async (_tree: TodoTreeIn) => added)
  render(
    <BacklogPage
      {...props}
      backlog={[]}
      providers={[paid]}
      drafter={drafter()}
      onDraft={onDraft}
      onAddTree={onAddTree}
      onPlan={vi.fn(async () => {})}
    />,
  )
  const box = await noteBox()
  const write = box.getByRole('button', { name: 'Write it' })
  expect(write).toBeDisabled() // (nothing typed yet)
  await userEvent.type(box.getByLabelText('Your note'), 'login mobilde bozuk')
  // Who writes them and what it costs, in sight - never behind a ⓘ.
  expect(write).toHaveAccessibleDescription(
    `${HIVE_KEEPER_DOES} Cloud (mini) writes them: one request you pay for. Nothing is saved until you add it.`,
  )
  await userEvent.click(write)
  expect(onDraft).toHaveBeenCalledWith('login mobilde bozuk')
  const drafts = await screen.findByRole('region', { name: 'Drafted tasks' })
  expect(within(drafts).getByText(/Written by Cloud \(mini\)/)).toBeVisible()
  expect(within(drafts).getByLabelText('Goal')).toHaveValue('Sign-in holds')
  // The box closed (Esc, or its button again), the draft stays - it was a request - and so does the note.
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('form', { name: 'Write it with the Hive keeper' })).toBeNull()
  expect(screen.getByRole('region', { name: 'Drafted tasks' })).toBeVisible()
  expect((await noteBox()).getByLabelText('Your note')).toHaveValue('login mobilde bozuk')
  const login = within(drafts).getByRole('group', { name: 'Story 1' })
  expect(within(login).getByLabelText('Story')).toHaveValue('Login on mobile')
  expect(login).toHaveTextContent('The form is shared with the desktop page.')
  const first = within(login).getByRole('group', { name: 'Draft 1' })
  await userEvent.clear(within(first).getByLabelText('Title'))
  await userEvent.type(within(first).getByLabelText('Title'), 'Fix the login page')
  await userEvent.selectOptions(within(first).getByLabelText('Priority'), 'normal')
  await userEvent.click(within(login).getByRole('button', { name: 'Add' }))
  // Only this story, under the goal.
  expect(onAddTree).toHaveBeenLastCalledWith({
    goal: 'Sign-in holds',
    goal_id: null,
    stories: [
      {
        title: 'Login on mobile',
        notes: ['The form is shared with the desktop page.'],
        tasks: [one('Fix the login page', { detail: 'Breaks under 400 px', criteria: 'Fits 360 px', kind: 'bug' })],
      },
    ],
    tasks: [],
  })
  expect(within(drafts).queryByRole('group', { name: 'Story 2' })).toBeNull() // (the first went)
  await userEvent.click(within(drafts).getByRole('button', { name: 'Remove draft 2' })) // (Remember me)
  expect(
    within(drafts)
      .getAllByRole('group', { name: /^Draft/ })
      .map(group => within(group).getByLabelText<HTMLInputElement>('Title').value),
  ).toEqual(['Password reset', 'Footer year'])
  await userEvent.click(within(drafts).getByRole('button', { name: 'Add all' }))
  // The rest, under the goal the first Add made.
  expect(onAddTree).toHaveBeenLastCalledWith({
    goal: null,
    goal_id: 'g1',
    stories: [{ title: 'Password reset', notes: [], tasks: [one('Password reset')] }],
    tasks: [one('Footer year')],
  })
  expect(onAddTree).toHaveBeenCalledTimes(2)
  expect(props.onAdd).not.toHaveBeenCalled()
  expect(screen.queryByRole('region', { name: 'Drafted tasks' })).toBeNull()
})

test('with no model to ask the button says why; Plan it in a chat asks for the Hive keeper', async () => {
  const props = page()
  const onPlan = vi.fn(async (_message: string) => {})
  const why = 'There is no model to ask: add a provider on the Models page.'
  render(
    <BacklogPage
      {...props}
      backlog={[]}
      providers={[]}
      drafter={drafter({ why, provider_id: null })}
      onDraft={vi.fn()}
      onPlan={onPlan}
    />,
  )
  const box = await noteBox()
  await userEvent.type(box.getByLabelText('Your note'), 'şifre sıfırlama lazım')
  const write = box.getByRole('button', { name: 'Write it' })
  expect(write).toBeDisabled()
  expect(write).toHaveAccessibleDescription(`${HIVE_KEEPER_DOES} ${why}`)
  await userEvent.click(box.getByRole('button', { name: 'Plan it in a chat' }))
  expect(onPlan).toHaveBeenCalledWith(`${PLAN_ASK}şifre sıfırlama lazım`)
  expect(props.onAdd).not.toHaveBeenCalled()
  // Esc closes the note box; the bar's button opens it again.
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('form', { name: 'Write it with the Hive keeper' })).toBeNull()
})

test('while Add all runs, the drafts are held: none is changed and added twice', async () => {
  let done = () => {}
  const props = page()
  const onAddTree = vi.fn(
    () =>
      new Promise<typeof added>(resolve => (done = () => resolve({ goal_id: null, story_ids: [], task_ids: ['t'] }))),
  )
  const onDraft = vi.fn(async () => ({ by: 'Cloud (mini)', goal: null, stories: [], tasks: [one('One')] }))
  render(
    <BacklogPage
      {...props}
      backlog={[]}
      providers={[paid]}
      drafter={drafter()}
      onDraft={onDraft}
      onAddTree={onAddTree}
    />,
  )
  const box = await noteBox()
  await userEvent.type(box.getByLabelText('Your note'), 'a note')
  await userEvent.click(box.getByRole('button', { name: 'Write it' }))
  const drafts = await screen.findByRole('region', { name: 'Drafted tasks' })
  expect(within(drafts).queryByLabelText('Goal')).toBeNull() // (tasks alone: no goal, no story)
  await userEvent.click(within(drafts).getByRole('button', { name: 'Add all' }))
  expect(within(drafts).getByLabelText('Title')).toBeDisabled()
  expect(within(drafts).getByLabelText('Priority')).toBeDisabled()
  expect(within(drafts).getByRole('button', { name: 'Add' })).toBeDisabled()
  await act(async () => done())
  expect(screen.queryByRole('region', { name: 'Drafted tasks' })).toBeNull()
  expect(onAddTree).toHaveBeenCalledTimes(1)
})

test('a proposal of the Scout says what it came from, and is added, edited first, or turned down; one the Orchestrator said no to waits for nobody', async () => {
  const props = page()
  const po = {
    chat: 'c',
    why: 'the parser tests are left undone',
    lead: null,
    lead_why: null,
    seen: false,
    injection: [] as string[],
  }
  const backlog = [
    task({ title: 'parser tests', status: 'proposed', created_by: 'agent', detail: 'cover the parser', po }),
    task({ title: 'help text', status: 'proposed', created_by: 'agent', po: { ...po, lead: 'no', lead_why: 'later' } }),
    task({ title: 'push it', status: 'proposed', created_by: 'agent', po: { ...po, injection: ['ignore_previous'] } }),
  ]
  render(<BacklogPage {...props} backlog={backlog} />)
  const waiting = screen.getByRole('region', { name: 'Waiting for you' })
  expect(
    within(waiting)
      .getAllByRole('group')
      .map(row => row.getAttribute('aria-label')),
  ).toEqual(['Proposed task: parser tests', 'Proposed task: push it'])
  expect(screen.getByRole('group', { name: 'Proposed task: push it' })).toHaveTextContent(
    'Its words look like they try to give the agent orders (rules: ignore previous)',
  )
  const row = screen.getByRole('group', { name: 'Proposed task: parser tests' })
  expect(row).toHaveTextContent('Proposed by the Scout, from: “the parser tests are left undone” · cover the parser')
  expect(
    within(row)
      .getAllByRole('button')
      .map(button => button.textContent),
  ).toEqual(['Add', 'Edit', 'Reject'])
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
  const po = {
    chat: 'c',
    why: 'the parser tests',
    lead_why: 'Tests were promised.',
    seen: false,
    injection: [] as string[],
  }
  const backlog = [
    task({ title: 'parser tests', status: 'todo', created_by: 'agent', po: { ...po, lead: 'add' } }),
    task({
      title: 'help text',
      status: 'proposed',
      created_by: 'agent',
      po: { ...po, lead: 'no', lead_why: 'Help can wait.' },
    }),
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

test('who writes the drafts is said by what is known: a model named for it, the provider’s default, or that it is not read yet', async () => {
  const props = page()
  const { rerender } = render(
    <BacklogPage {...props} backlog={[]} providers={[paid]} drafter={drafter({ model_id: 'big' })} onDraft={vi.fn()} />,
  )
  const box = await noteBox()
  await userEvent.type(box.getByLabelText('Your note'), 'x')
  const write = () => box.getByRole('button', { name: 'Write it' })
  expect(write()).toHaveAccessibleDescription(
    `${HIVE_KEEPER_DOES} Cloud (big) writes them: one request you pay for. Nothing is saved until you add it.`,
  )
  expect(write()).toBeEnabled()
  expect(document.getElementById('draft-who')).toHaveClass('muted')
  // no chat to plan it in: no button for it
  expect(box.queryByRole('button', { name: 'Plan it in a chat' })).toBeNull()
  rerender(
    <BacklogPage
      {...props}
      backlog={[]}
      providers={[{ ...paid, default_model: null }]}
      drafter={drafter()}
      onDraft={vi.fn()}
    />,
  )
  expect(write()).toHaveAccessibleDescription(
    `${HIVE_KEEPER_DOES} Cloud (its default model) writes them: one request you pay for. Nothing is saved until you add it.`,
  )
  rerender(<BacklogPage {...props} backlog={[]} providers={[]} drafter={drafter()} onDraft={vi.fn()} />)
  expect(write()).toHaveAccessibleDescription(`${HIVE_KEEPER_DOES} Who writes them is not read yet.`)
  expect(write()).toBeDisabled()
  // with no way to draft, neither the button nor its line - Plan it in a chat alone
  rerender(
    <BacklogPage {...props} backlog={[]} providers={[paid]} drafter={drafter()} onPlan={vi.fn(async () => {})} />,
  )
  expect(box.queryByRole('button', { name: 'Write it' })).toBeNull()
  expect(document.getElementById('draft-who')).toBeNull()
  expect(box.getByRole('button', { name: 'Plan it in a chat' })).toBeEnabled()
  // with neither, no Hive keeper on the bar
  rerender(<BacklogPage {...props} backlog={[]} providers={[paid]} drafter={drafter()} />)
  expect(screen.queryByRole('button', { name: 'Write it with the Hive keeper' })).toBeNull()
})

test('while the drafts are written the button says so, and neither it nor Plan it in a chat can be pressed', async () => {
  const props = page()
  const onDraft = vi.fn(() => new Promise<never>(() => {}))
  render(
    <BacklogPage
      {...props}
      backlog={[]}
      providers={[paid]}
      drafter={drafter()}
      onDraft={onDraft}
      onPlan={vi.fn(async () => {})}
    />,
  )
  const box = await noteBox()
  await userEvent.type(box.getByLabelText('Your note'), 'x')
  await userEvent.click(box.getByRole('button', { name: 'Write it' }))
  expect(await screen.findByRole('button', { name: 'Writing…' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Writing…' })).toHaveAttribute('aria-describedby', 'draft-who')
  expect(screen.getByRole('button', { name: 'Plan it in a chat' })).toBeDisabled()
  // (A task is still added the usual way meanwhile.)
  await userEvent.type(addForm().getByLabelText('Title'), 'other')
  expect(addForm().getByRole('button', { name: 'Add task' })).toBeEnabled()
})

// 0.1.8: To-do as a tree - goals, their stories, tasks and bugs, the tasks of no story; the filters; a task's story and type.
const note = (text: string) => ({ kind: 'decision', text, by: 'Orchestrator', at: '2026-11-24T10:00:00Z' })
const STORIES: Story[] = [
  {
    id: 's1',
    goal_id: 'g1',
    title: 'Şifre sıfırlama',
    position: 0,
    state: 'running',
    notes: ['a', 'b', 'c', 'd'].map(note),
    created_by: 'user',
    closed_at: null,
  },
  {
    id: 's2',
    goal_id: 'g1',
    title: 'Login düzelt',
    position: 1,
    state: 'done',
    notes: [],
    created_by: 'user',
    closed_at: '2026-11-24T09:00:00Z',
  },
]
const GOALS: Goal[] = [
  {
    id: 'g1',
    title: 'Kullanıcı girişi sağlam olsun',
    position: 0,
    created_by: 'user',
    stories_done: 1,
    stories_all: 2,
  },
]
const TREE_TASKS = [
  task({ id: 't1', title: 'E-posta gönderimi', story_id: 's1', status: 'doing', conversation_id: 'c1' }),
  task({ id: 't2', title: 'Mobilde buton kayık', story_id: 's2', kind: 'bug', status: 'done', position: 1 }),
  task({ id: 't3', title: 'Footer’daki yıl yanlış', position: 2 }),
]

test('the tree: a goal with its stories done, a story’s notes, state and chat, a bug, the tasks of no story; the filters', async () => {
  const props = page()
  render(<BacklogPage {...props} backlog={TREE_TASKS} stories={STORIES} goals={GOALS} chats={{ c1: 'Auth work' }} />)
  const tree = screen.getByRole('list', { name: 'Tasks' })
  const goal = within(tree).getByRole('listitem', { name: 'Kullanıcı girişi sağlam olsun' })
  expect(goal).toHaveTextContent('Goal')
  expect(goal).toHaveTextContent('1 / 2 stories')
  expect(within(goal).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '1')
  const running = within(tree).getByRole('listitem', { name: 'Şifre sıfırlama' })
  expect(within(running).getByRole('button', { name: '4 notes' })).toBeVisible()
  expect(running).toHaveTextContent('● running')
  expect(running).toHaveTextContent('in “Auth work”')
  expect(within(tree).getByRole('listitem', { name: 'Login düzelt' })).toHaveTextContent('✓ done')
  expect(within(within(tree).getByRole('listitem', { name: 'Mobilde buton kayık' })).getByText('bug')).toHaveClass(
    'tag-del',
  )
  expect(within(tree).getByText('Without a story')).toBeVisible()
  // The notebook, opened: what is in it, as written.
  await userEvent.click(within(running).getByRole('button', { name: '4 notes' }))
  expect(screen.getByRole('dialog', { name: 'Notebook of Şifre sıfırlama' })).toHaveTextContent('Decision a')
  await userEvent.keyboard('{Escape}')
  // Done: only the done task, under its story and goal.
  await userEvent.click(screen.getByRole('button', { name: 'Done', pressed: false }))
  expect(
    within(tree)
      .getAllByRole('listitem')
      .map(row => row.getAttribute('aria-labelledby') && row.querySelector('strong')?.textContent),
  ).toEqual(['Kullanıcı girişi sağlam olsun', 'Login düzelt', 'Mobilde buton kayık'])
})

test('a story’s tick ticks its open tasks; ⋯ Goal moves it to another goal or a new one', async () => {
  const props = page()
  const tree = {
    onGoal: vi.fn(async () => {}),
    onDeleteGoal: vi.fn(async () => {}),
    onStory: vi.fn(async () => {}),
    onDeleteStory: vi.fn(async () => {}),
    onNewGoal: vi.fn(async (title: string) => ({ ...GOALS[0], id: 'g2', title })),
    onNewStory: vi.fn(async (title: string) => ({ ...STORIES[0], id: 's9', title })),
  }
  const backlog = [
    task({ title: 'one', story_id: 's1' }),
    task({ title: 'two', story_id: 's1', status: 'done', position: 1 }),
  ]
  render(<BacklogPage {...props} backlog={backlog} stories={STORIES} goals={GOALS} tree={tree} />)
  await userEvent.click(screen.getByRole('checkbox', { name: 'Tick the story Şifre sıfırlama' }))
  expect(screen.getByRole('checkbox', { name: 'Tick one' })).toBeChecked()
  expect(screen.getByRole('checkbox', { name: 'Tick two' })).toBeDisabled() // (done: nothing to do in a chat)
  await userEvent.click(screen.getByRole('button', { name: 'Şifre sıfırlama: more' }))
  expect(
    within(screen.getByRole('menu'))
      .getAllByRole('menuitem')
      .map(item => item.textContent),
  ).toEqual(['Rename', 'Goal', 'Delete'])
  await userEvent.click(screen.getByRole('menuitem', { name: 'Goal' }))
  await userEvent.selectOptions(screen.getByLabelText('Goal of Şifre sıfırlama'), 'New goal…')
  await userEvent.type(screen.getByLabelText('Rename “”'), 'Sign-in{Enter}')
  expect(tree.onNewGoal).toHaveBeenCalledWith('Sign-in')
  expect(tree.onStory).toHaveBeenCalledWith('s1', { goal_id: 'g2' })
})

test('a story whose tasks are all done is closed by your word, and opened again', async () => {
  const props = page()
  const onStory = vi.fn(async () => {})
  const tree = {
    onGoal: vi.fn(),
    onDeleteGoal: vi.fn(),
    onStory,
    onDeleteStory: vi.fn(),
    onNewGoal: vi.fn(),
    onNewStory: vi.fn(),
  }
  const asked = { ...STORIES[0], state: 'done?' as const }
  const backlog = [task({ id: 'd1', title: 'done one', story_id: 's1', status: 'done' })]
  const { rerender } = render(<BacklogPage {...props} backlog={backlog} stories={[asked]} goals={GOALS} tree={tree} />)
  expect(screen.getByRole('listitem', { name: 'Şifre sıfırlama' })).toHaveTextContent('done?')
  await userEvent.click(screen.getByRole('button', { name: 'Şifre sıfırlama: more' }))
  await userEvent.click(screen.getByRole('menuitem', { name: 'Close the story' }))
  expect(onStory).toHaveBeenLastCalledWith('s1', { closed: true })
  rerender(
    <BacklogPage {...props} backlog={backlog} stories={[{ ...asked, state: 'done' }]} goals={GOALS} tree={tree} />,
  )
  await userEvent.click(screen.getByRole('button', { name: 'Şifre sıfırlama: more' }))
  await userEvent.click(screen.getByRole('menuitem', { name: 'Open it again' }))
  expect(onStory).toHaveBeenLastCalledWith('s1', { closed: false })
})

test('Edit gives a task its story and its type; a new story is made by its title', async () => {
  const props = page()
  const onNewStory = vi.fn(async (title: string) => ({ ...STORIES[0], id: 's9', title }))
  const tree = {
    onGoal: vi.fn(),
    onDeleteGoal: vi.fn(),
    onStory: vi.fn(),
    onDeleteStory: vi.fn(),
    onNewGoal: vi.fn(),
    onNewStory,
  }
  render(<BacklogPage {...props} backlog={[task({ title: 'lone' })]} stories={STORIES} goals={GOALS} tree={tree} />)
  await userEvent.click(within(await more('lone')).getByRole('menuitem', { name: 'Edit' }))
  const form = screen.getByRole('form', { name: 'Edit lone' })
  await userEvent.selectOptions(within(form).getByLabelText('Story'), 'Login düzelt')
  await userEvent.selectOptions(within(form).getByLabelText('Type'), 'bug')
  await userEvent.click(within(form).getByRole('button', { name: 'Save' }))
  expect(props.onChange).toHaveBeenLastCalledWith('lone', expect.objectContaining({ story_id: 's2', kind: 'bug' }))
  await userEvent.click(within(await more('lone')).getByRole('menuitem', { name: 'Edit' }))
  const again = screen.getByRole('form', { name: 'Edit lone' })
  await userEvent.selectOptions(within(again).getByLabelText('Story'), 'New story…')
  await userEvent.type(within(again).getByLabelText('New story’s title'), 'Footer{Enter}')
  expect(onNewStory).toHaveBeenCalledWith('Footer')
  await userEvent.click(within(again).getByRole('button', { name: 'Save' }))
  expect(props.onChange).toHaveBeenLastCalledWith('lone', expect.objectContaining({ story_id: 's9' }))
})

test('review M1 / M2 / LOW: a proposal says where adding it puts it; a story waiting at done? is closed only once each task is done; the focus comes back', async () => {
  const props = page()
  const tree = {
    onGoal: vi.fn(async () => {}),
    onDeleteGoal: vi.fn(),
    onStory: vi.fn(async () => {}),
    onDeleteStory: vi.fn(),
    onNewGoal: vi.fn(),
    onNewStory: vi.fn(),
  }
  const proposal = task({
    id: 'p1',
    title: 'Mobile button',
    status: 'proposed',
    created_by: 'agent',
    kind: 'bug',
    story_id: 'sx',
    story_title: 'Login',
    story_by: 'agent',
    goal_title: 'Auth',
    goal_by: 'user',
  })
  const waiting = { ...STORIES[0], state: 'done?' as const }
  const backlog = [proposal, task({ id: 'r1', title: 'waits', story_id: 's1', status: 'review' })]
  render(<BacklogPage {...props} backlog={backlog} stories={[waiting]} goals={GOALS} tree={tree} onDraft={vi.fn()} />)
  expect(screen.getByRole('group', { name: 'Proposed task: Mobile button' })).toHaveTextContent(
    'Proposed by an agent · In story “Login” (new) · goal “Auth” · bug',
  )
  // done? with a task still at done?: no Close the story yet.
  const dots = screen.getByRole('button', { name: 'Şifre sıfırlama: more' })
  await userEvent.click(dots)
  expect(screen.queryByRole('menuitem', { name: 'Close the story' })).toBeNull()
  // Rename left with Esc, and Delete's Keep it: the focus is back on ⋯.
  await userEvent.click(screen.getByRole('menuitem', { name: 'Rename' }))
  await userEvent.keyboard('{Escape}')
  expect(dots).toHaveFocus()
  await userEvent.click(dots)
  await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
  await userEvent.click(screen.getByRole('button', { name: 'Keep it' }))
  expect(screen.getByRole('button', { name: 'Şifre sıfırlama: more' })).toHaveFocus()
  // The Hive keeper's box closed with Esc: the focus is back on its button.
  const hive = screen.getByRole('button', { name: 'Write it with the Hive keeper' })
  await userEvent.click(hive)
  await userEvent.keyboard('{Escape}')
  expect(hive).toHaveFocus()
})
