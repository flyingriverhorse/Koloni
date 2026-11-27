import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { BacklogDrafter, BacklogTask, Board, NewBacklogTask, Provider, Story, TodoTreeIn } from '../api/types'
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

/** A card of To-do (0.1.10), opened: its story's panel - the tasks of no story are one card too. */
async function open(name: string) {
  await userEvent.click(screen.getByRole('button', { name: new RegExp(`^${name}: \\d+ of \\d+ done$`) }))
  return screen.getByRole('complementary', { name })
}
const loose = () => open('Without a story')

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
  await loose()
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
  await loose()
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

test('what waits for your word is not on To-do (0.1.10: Ready for you has it, on the left): a task’s row points there', async () => {
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
  expect(screen.queryByRole('region', { name: 'Waiting for you' })).toBeNull()
  expect(screen.queryByRole('group', { name: /^Proposed/ })).toBeNull()
  // The proposed one is not on the list until it is approved; the view, under the opened title, is not its status.
  await loose()
  const tasks = screen.getByRole('list', { name: 'Tasks' })
  expect(within(tasks).queryByText('remember me')).toBeNull()
  expect(within(tasks).queryByText(/an opinion, not a status/)).toBeNull()
  expect(within(tasks).getByText('A change to it waits under Waiting for your word')).toBeInTheDocument()
  await userEvent.click(within(tasks).getByRole('button', { name: 'form' }))
  expect(within(tasks).getByText(/an opinion, not a status/)).toBeInTheDocument()
  expect(screen.getByRole('combobox', { name: 'Status of form' })).toHaveValue('review')
})

test('a task’s rows of what waits: one row each - new task, "done?", change - with its buttons on the row', async () => {
  const props = page()
  const form = task({
    title: 'form',
    status: 'review',
    conversation_id: 'c1',
    pending: { priority: 'high', status: 'done' },
    assessment: 'Criteria 1 and 2 met.',
  })
  const proposal = task({ title: 'remember me', status: 'proposed', created_by: 'agent', criteria: 'stays signed in' })
  render(
    <>
      {[proposal, form].map(one => (
        <WaitRow key={one.id} task={one} onDecide={props.onDecide} onChange={props.onChange} onOpen={props.onOpen} />
      ))}
    </>,
  )
  expect(screen.getAllByRole('group').map(row => row.getAttribute('aria-label'))).toEqual([
    'Proposed task: remember me',
    'Done? form',
    'Proposed change: form',
  ])
  // Each a single row: its kind, its title, one second line.
  const proposed = screen.getByRole('group', { name: 'Proposed task: remember me' })
  expect(proposed.querySelectorAll('.backlog-sub')).toHaveLength(1)
  expect(proposed).toHaveTextContent('new task')
  expect(proposed).toHaveTextContent('Proposed by an agent · Done when: stays signed in')
  await userEvent.click(within(proposed).getByRole('button', { name: 'Add to To-do' }))
  expect(props.onDecide).toHaveBeenCalledWith('remember me', 'approve')
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
})

test('a task whose work is not in the project yet is not asked "done?": its row in the list says so (B-78)', async () => {
  const props = page()
  render(
    <BacklogPage
      {...props}
      backlog={[task({ title: 'calc', status: 'review', not_in: true, conversation_id: 'c9' })]}
    />,
  )
  await loose()
  const row = within(screen.getByRole('listitem', { name: 'calc' }))
  expect(row.getByText('needs you · Take in')).toBeInTheDocument()
  expect(row.getByText(/Its work is not in the project yet: take it in or discard it in its chat/)).toBeInTheDocument()
  await userEvent.click(row.getByRole('button', { name: 'Open chat · calc' }))
  expect(props.onOpen).toHaveBeenCalledWith('c9')
})

test('a task is deleted from its ⋯ only once the user says so again', async () => {
  const props = page()
  render(<BacklogPage {...props} backlog={[task({ title: 'old' })]} />)
  await loose()
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
      'No task yet. A task is work for later: type its title in “Add a task” above, or write a rough note below and the Hive keeper splits it into stories and tasks.',
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

test('a task that waits for one at "done?" says why (B-349)', async () => {
  const backlog = [
    task({ title: 'one', status: 'review' }),
    task({ title: 'two', status: 'review', not_in: true }),
    task({ title: 'three', after: ['one', 'two'] }),
  ]
  render(<BacklogPage {...page()} backlog={backlog} />)
  await loose()
  const why = 'one (done? - its Done under Waiting for your word), two (waiting for you - Take in)'
  expect(within(screen.getByRole('listitem', { name: 'three' })).getByText(`waits for: ${why}`)).toBeInTheDocument()
})

test('what a task waits for is chosen from its ⋯', async () => {
  const props = page()
  render(<BacklogPage {...props} backlog={[task({ title: 'one' }), task({ title: 'two', position: 1 })]} />)
  await loose()
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

test('what is decided is never cut before its button: a waiting row wraps whole, only a task row folded cuts its line', async () => {
  const style = document.createElement('style')
  style.textContent = readFileSync('src/theme/memory.css', 'utf8') // (run from frontend/)
  document.head.append(style)
  const long = 'x'.repeat(400)
  const props = page()
  const form = task({ title: 'form', pending: { detail: long } })
  render(
    <>
      <WaitRow task={form} onDecide={props.onDecide} onChange={props.onChange} onOpen={props.onOpen} />
      <BacklogPage {...props} backlog={[form, task({ title: 'calc', status: 'blocked', stuck: long })]} />
    </>,
  )
  await loose()
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
/** The rough note's box, under the cards: always in sight (0.1.10). */
async function noteBox() {
  return within(screen.getByRole('form', { name: 'Your rough note' }))
}
const added = { goal_id: 'g1', story_ids: ['s1'], task_ids: ['t1'] }

test('the note is written as stories and tasks (a goal it names is not shown: 0.1.10): each changed, a story added by its Add, the rest by Add all', async () => {
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
  const write = box.getByRole('button', { name: 'Split into tasks' })
  expect(write).toBeDisabled() // (nothing typed yet)
  await userEvent.type(box.getByLabelText('Your rough note'), 'login mobilde bozuk')
  // Who writes them and what it costs, in sight - never behind a ⓘ.
  expect(write).toHaveAccessibleDescription(
    `${HIVE_KEEPER_DOES} Cloud (mini) writes them: one request you pay for. Nothing is saved until you add it.`,
  )
  await userEvent.click(write)
  expect(onDraft).toHaveBeenCalledWith('login mobilde bozuk')
  const drafts = await screen.findByRole('region', { name: 'Drafted tasks' })
  expect(within(drafts).getByText(/Written by Cloud \(mini\)/)).toBeVisible()
  expect(within(drafts).queryByLabelText('Goal')).toBeNull()
  // The draft stays - it was a request - and so does the note.
  expect((await noteBox()).getByLabelText('Your rough note')).toHaveValue('login mobilde bozuk')
  const login = within(drafts).getByRole('group', { name: 'Story 1' })
  expect(within(login).getByLabelText('Story')).toHaveValue('Login on mobile')
  expect(login).toHaveTextContent('The form is shared with the desktop page.')
  const first = within(login).getByRole('group', { name: 'Draft 1' })
  await userEvent.clear(within(first).getByLabelText('Title'))
  await userEvent.type(within(first).getByLabelText('Title'), 'Fix the login page')
  await userEvent.selectOptions(within(first).getByLabelText('Priority'), 'normal')
  await userEvent.click(within(login).getByRole('button', { name: 'Add' }))
  // Only this story.
  expect(onAddTree).toHaveBeenLastCalledWith({
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
  // The rest.
  expect(onAddTree).toHaveBeenLastCalledWith({
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
  await userEvent.type(box.getByLabelText('Your rough note'), 'şifre sıfırlama lazım')
  const write = box.getByRole('button', { name: 'Split into tasks' })
  expect(write).toBeDisabled()
  expect(write).toHaveAccessibleDescription(`${HIVE_KEEPER_DOES} ${why}`)
  await userEvent.click(box.getByRole('button', { name: 'Plan it in a chat' }))
  expect(onPlan).toHaveBeenCalledWith(`${PLAN_ASK}şifre sıfırlama lazım`)
  expect(props.onAdd).not.toHaveBeenCalled()
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
  await userEvent.type(box.getByLabelText('Your rough note'), 'a note')
  await userEvent.click(box.getByRole('button', { name: 'Split into tasks' }))
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
  render(
    <>
      {backlog.map(one => (
        <WaitRow key={one.id} task={one} onDecide={props.onDecide} onChange={props.onChange} onOpen={props.onOpen} />
      ))}
    </>,
  )
  expect(screen.getAllByRole('group').map(row => row.getAttribute('aria-label'))).toEqual([
    'Proposed task: parser tests',
    'Proposed task: push it',
  ])
  expect(screen.getByRole('group', { name: 'Proposed task: push it' })).toHaveTextContent(
    'Its words look like they try to give the agent orders (rules: ignore previous)',
  )
  const row = screen.getByRole('group', { name: 'Proposed task: parser tests' })
  expect(row).toHaveTextContent('Proposed by the Scout, from: “the parser tests are left undone” · cover the parser')
  expect(
    within(row)
      .getAllByRole('button')
      .map(button => button.textContent),
  ).toEqual(['Add to To-do', 'Edit', 'Not wanted'])
  await userEvent.click(within(row).getByRole('button', { name: 'Not wanted' }))
  expect(props.onDecide).toHaveBeenLastCalledWith('parser tests', 'reject')
  await userEvent.click(within(row).getByRole('button', { name: 'Edit' }))
  const title = within(row).getByLabelText('Title')
  await userEvent.clear(title)
  await userEvent.type(title, 'Parser tests for dates')
  await userEvent.clear(within(row).getByLabelText('Detail'))
  await userEvent.click(within(row).getByRole('button', { name: 'Add to To-do' }))
  expect(props.onChange).toHaveBeenCalledWith('parser tests', { title: 'Parser tests for dates', detail: null })
  expect(props.onDecide).toHaveBeenLastCalledWith('parser tests', 'approve')
})

test('a task the Orchestrator added waits for your OK under Decided for you, not here; one it rejected stays findable, folded', async () => {
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
  // (Its OK and its Change → Reject are Decided for you's: ready/decisions.test.tsx.)
  expect(screen.queryByRole('group', { name: 'Added for you: parser tests' })).toBeNull()
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
  await userEvent.type(box.getByLabelText('Your rough note'), 'x')
  const write = () => box.getByRole('button', { name: 'Split into tasks' })
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
  expect(box.queryByRole('button', { name: 'Split into tasks' })).toBeNull()
  expect(document.getElementById('draft-who')).toBeNull()
  expect(box.getByRole('button', { name: 'Plan it in a chat' })).toBeEnabled()
  // with neither, no rough note
  rerender(<BacklogPage {...props} backlog={[]} providers={[paid]} drafter={drafter()} />)
  expect(screen.queryByRole('form', { name: 'Your rough note' })).toBeNull()
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
  await userEvent.type(box.getByLabelText('Your rough note'), 'x')
  await userEvent.click(box.getByRole('button', { name: 'Split into tasks' }))
  expect(await screen.findByRole('button', { name: 'Splitting…' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Splitting…' })).toHaveAttribute('aria-describedby', 'draft-who')
  expect(screen.getByRole('button', { name: 'Plan it in a chat' })).toBeDisabled()
  // (A task is still added the usual way meanwhile.)
  await userEvent.type(addForm().getByLabelText('Title'), 'other')
  expect(addForm().getByRole('button', { name: 'Add task' })).toBeEnabled()
})

// 0.1.8: To-do as a tree - stories, their tasks and bugs, the tasks of no story; the filters; a task's story and type.
// (0.1.10: no goal level - two stories a goal holds, made before, stand at the top.)
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
const TREE_TASKS = [
  task({ id: 't1', title: 'E-posta gönderimi', story_id: 's1', status: 'doing', conversation_id: 'c1' }),
  task({ id: 't2', title: 'Mobilde buton kayık', story_id: 's2', kind: 'bug', status: 'done', position: 1 }),
  task({ id: 't3', title: 'Footer’daki yıl yanlış', position: 2 }),
]

test('the cards: stories at the top (a goal’s too), a cell for each task and how it stands, the tasks of no story last; the filters', async () => {
  const props = page()
  render(<BacklogPage {...props} backlog={TREE_TASKS} stories={STORIES} chats={{ c1: 'Auth work' }} />)
  const cards = screen.getByRole('list', { name: 'Stories' })
  expect(within(cards).queryByText('Goal')).toBeNull()
  expect(
    within(cards)
      .getAllByRole('button')
      .map(card => card.getAttribute('aria-label')),
  ).toEqual(['Şifre sıfırlama: 0 of 1 done', 'Login düzelt: 1 of 1 done', 'Without a story: 0 of 1 done'])
  const running = within(cards).getByRole('button', { name: 'Şifre sıfırlama: 0 of 1 done' })
  expect(running).toHaveAttribute('aria-expanded', 'false')
  expect(running).toHaveTextContent('E-posta gönderimi: at work')
  // A cell for each task, named - its colour never says it alone.
  expect(running.querySelector('.cell-comb .cell')).toHaveAttribute('title', 'E-posta gönderimi: at work')
  expect(within(cards).getByRole('button', { name: /^Login düzelt/ })).toHaveTextContent('Mobilde buton kayık: done')
  // Done: only the done task, under its story.
  await userEvent.click(screen.getByRole('button', { name: 'Done', pressed: false }))
  expect(
    within(cards)
      .getAllByRole('button')
      .map(card => card.getAttribute('aria-label')),
  ).toEqual(['Login düzelt: 1 of 1 done'])
})

test('a story opened: its facts, its notebook with when and who, its tasks with all they do; Esc or Close shuts it, the focus back on its card', async () => {
  const props = page()
  render(<BacklogPage {...props} backlog={TREE_TASKS} stories={STORIES} chats={{ c1: 'Auth work' }} />)
  const card = screen.getByRole('button', { name: 'Şifre sıfırlama: 0 of 1 done' })
  const panel = await open('Şifre sıfırlama')
  expect(card).toHaveAttribute('aria-expanded', 'true')
  expect(panel).toHaveFocus()
  expect(panel).toHaveTextContent('State● running, 0 of 1 tasks done')
  expect(panel).toHaveTextContent('Chat“Auth work”')
  // Its notebook, in the panel: each note with its kind, its words, who wrote it and when.
  const book = within(panel).getByRole('region', { name: "The job's notebook" })
  expect(within(book).getAllByRole('listitem')[0]).toHaveTextContent(/^Decision a · Orchestrator · /)
  // Its chat: Continue in chat.
  await userEvent.click(within(panel).getByRole('button', { name: 'Continue in chat' }))
  expect(props.onOpen).toHaveBeenCalledWith('c1')
  // Its task, as To-do's row: its tick, its chat, ⋯.
  expect(within(panel).getByRole('listitem', { name: 'E-posta gönderimi' })).toBeVisible()
  expect(within(panel).getByRole('button', { name: 'Open chat · E-posta gönderimi' })).toBeVisible()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('complementary')).toBeNull()
  expect(card).toHaveFocus()
  await open('Without a story')
  await userEvent.click(screen.getByRole('button', { name: 'Close Without a story' }))
  expect(screen.queryByRole('complementary')).toBeNull()
  expect(screen.getByRole('button', { name: 'Without a story: 0 of 1 done' })).toHaveFocus()
})

test('asked to open at a task (Open it in To-do), its card opens at its row; asked with none, the heading takes the focus', async () => {
  const props = page()
  const { rerender } = render(
    <BacklogPage {...props} backlog={TREE_TASKS} stories={STORIES} asked={{ task: 't3', n: 1 }} />,
  )
  const panel = await screen.findByRole('complementary', { name: 'Without a story' })
  expect(within(panel).getByRole('button', { name: 'Footer’daki yıl yanlış' })).toHaveFocus()
  rerender(<BacklogPage {...props} backlog={TREE_TASKS} stories={STORIES} asked={{ n: 2 }} />)
  expect(screen.getByRole('heading', { name: /^To-do/ })).toHaveFocus()
})

test('a story’s tick ticks its open tasks; its ⋯ has no Goal (0.1.10)', async () => {
  const props = page()
  const tree = {
    onStory: vi.fn(async () => {}),
    onDeleteStory: vi.fn(async () => {}),
    onNewStory: vi.fn(async (title: string) => ({ ...STORIES[0], id: 's9', title })),
  }
  const backlog = [
    task({ title: 'one', story_id: 's1' }),
    task({ title: 'two', story_id: 's1', status: 'done', position: 1 }),
  ]
  render(<BacklogPage {...props} backlog={backlog} stories={STORIES} tree={tree} />)
  await open('Şifre sıfırlama')
  await userEvent.click(screen.getByRole('checkbox', { name: 'Tick the story Şifre sıfırlama' }))
  expect(screen.getByRole('checkbox', { name: 'Tick one' })).toBeChecked()
  expect(screen.getByRole('checkbox', { name: 'Tick two' })).toBeDisabled() // (done: nothing to do in a chat)
  await userEvent.click(screen.getByRole('button', { name: 'Şifre sıfırlama: more' }))
  expect(
    within(screen.getByRole('menu'))
      .getAllByRole('menuitem')
      .map(item => item.textContent),
  ).toEqual(['Rename', 'Delete'])
})

test('a story whose tasks are all done is closed by your word, and opened again', async () => {
  const props = page()
  const onStory = vi.fn(async () => {})
  const tree = { onStory, onDeleteStory: vi.fn(), onNewStory: vi.fn() }
  const asked = { ...STORIES[0], state: 'done?' as const }
  const backlog = [task({ id: 'd1', title: 'done one', story_id: 's1', status: 'done' })]
  const { rerender } = render(<BacklogPage {...props} backlog={backlog} stories={[asked]} tree={tree} />)
  const panel = await open('Şifre sıfırlama')
  expect(panel).toHaveTextContent('Statedone?')
  await userEvent.click(within(panel).getByRole('button', { name: 'Close story' }))
  expect(onStory).toHaveBeenLastCalledWith('s1', { closed: true })
  rerender(<BacklogPage {...props} backlog={backlog} stories={[{ ...asked, state: 'done' }]} tree={tree} />)
  expect(within(panel).queryByRole('button', { name: 'Close story' })).toBeNull()
  await userEvent.click(within(panel).getByRole('button', { name: 'Open it again' }))
  expect(onStory).toHaveBeenLastCalledWith('s1', { closed: false })
})

test('Edit gives a task its story and its type; a new story is made by its title', async () => {
  const props = page()
  const onNewStory = vi.fn(async (title: string) => ({ ...STORIES[0], id: 's9', title }))
  const tree = { onStory: vi.fn(), onDeleteStory: vi.fn(), onNewStory }
  render(<BacklogPage {...props} backlog={[task({ title: 'lone' })]} stories={STORIES} tree={tree} />)
  await loose()
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
  const tree = { onStory: vi.fn(async () => {}), onDeleteStory: vi.fn(), onNewStory: vi.fn() }
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
  render(
    <>
      <WaitRow task={proposal} onDecide={props.onDecide} onChange={props.onChange} onOpen={props.onOpen} />
      <BacklogPage {...props} backlog={backlog} stories={[waiting]} tree={tree} onDraft={vi.fn()} />
    </>,
  )
  // (A goal a row still names, of a story made before 0.1.10, is not said: the goal level is hidden.)
  expect(screen.getByRole('group', { name: 'Proposed task: Mobile button' })).toHaveTextContent(
    /Proposed by an agent · In story “Login” \(new\) · bugAdd to To-do/,
  )
  // done? with a task still at done?: no Close story yet.
  await open('Şifre sıfırlama')
  expect(screen.queryByRole('button', { name: 'Close story' })).toBeNull()
  const dots = screen.getByRole('button', { name: 'Şifre sıfırlama: more' })
  await userEvent.click(dots)
  // Rename left with Esc, and Delete's Keep it: the focus is back on ⋯.
  await userEvent.click(screen.getByRole('menuitem', { name: 'Rename' }))
  expect(screen.getByLabelText('Rename “Şifre sıfırlama”')).toHaveFocus()
  await userEvent.keyboard('{Escape}')
  expect(dots).toHaveFocus()
  await userEvent.click(dots)
  await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
  await userEvent.click(screen.getByRole('button', { name: 'Keep it' }))
  expect(screen.getByRole('button', { name: 'Şifre sıfırlama: more' })).toHaveFocus()
})

test('under a filter a card shows the tasks it lets through, and counts all of its story', async () => {
  const story = { ...STORIES[0], state: 'running' as const }
  const backlog = [
    task({ id: 'a', title: 'first', story_id: 's1', status: 'done' }),
    task({ id: 'b', title: 'second', story_id: 's1', position: 1 }),
  ]
  render(<BacklogPage {...page()} backlog={backlog} stories={[story]} />)
  await userEvent.click(screen.getByRole('button', { name: 'Todo', pressed: false }))
  const card = screen.getByRole('button', { name: 'Şifre sıfırlama: 1 of 2 done' })
  expect(card).toHaveTextContent('1 / 2')
  expect(card).toHaveTextContent('second')
  expect(card).not.toHaveTextContent('first')
})

test('a story gone from under its open panel - deleted, closed under a filter - closes it, the heading takes the focus; back, it stays closed', async () => {
  const props = page()
  const story = { ...STORIES[0], state: 'todo' as const }
  const backlog = [task({ id: 'a', title: 'a', story_id: 's1' }), task({ id: 'c', title: 'c' })]
  const { rerender } = render(<BacklogPage {...props} backlog={backlog} stories={[story]} />)
  expect(await open('Şifre sıfırlama')).toHaveFocus()
  // Deleted: the list read again without it, its task of no story now.
  const without = [task({ id: 'a', title: 'a' }), task({ id: 'c', title: 'c' })]
  rerender(<BacklogPage {...props} backlog={without} stories={[]} />)
  expect(screen.queryByRole('complementary')).toBeNull()
  expect(screen.getByRole('heading', { name: /^To-do/ })).toHaveFocus()
  // The same story back: its panel does not spring open, nor take the focus.
  rerender(<BacklogPage {...props} backlog={backlog} stories={[story]} />)
  expect(screen.queryByRole('complementary')).toBeNull()
  expect(screen.getByRole('heading', { name: /^To-do/ })).toHaveFocus()
})

test('under a filter, the card of no story counts only its own tasks, and a panel is of its whole story', async () => {
  const props = page()
  const story = { ...STORIES[0], state: 'running' as const }
  const backlog = [
    task({ id: 'a', title: 'a', story_id: 's1', status: 'done', conversation_id: 'c1' }),
    task({ id: 'b', title: 'b', story_id: 's1' }),
    task({ id: 'c', title: 'c', status: 'done' }),
  ]
  render(<BacklogPage {...props} backlog={backlog} stories={[story]} chats={{ c1: 'Auth work' }} />)
  await userEvent.click(screen.getByRole('button', { name: 'Done', pressed: false }))
  expect(screen.getByRole('button', { name: 'Without a story: 1 of 1 done' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Todo', pressed: false }))
  const panel = await open('Şifre sıfırlama')
  // (Its done task is filtered out of the card; its facts and its chat are still the story's.)
  expect(panel).toHaveTextContent('1 of 2 tasks done')
  expect(within(panel).getByRole('button', { name: 'Continue in chat' })).toBeVisible()
})

test('a card is named by its story and count, and described by its tasks, each with its word; the legend is said once', async () => {
  render(<BacklogPage {...page()} backlog={TREE_TASKS} stories={STORIES} />)
  const card = screen.getByRole('button', { name: 'Şifre sıfırlama: 0 of 1 done' })
  expect(card).toHaveAccessibleDescription('E-posta gönderimi: at work;')
  expect(card.querySelector('.cell')).toHaveAttribute('aria-hidden', 'true')
  const legend = document.querySelector('.cell-legend')!
  expect(legend).not.toHaveAttribute('aria-label')
  expect(legend.querySelectorAll('[role="img"]')).toHaveLength(0)
  expect(legend).toHaveTextContent('done')
})

test('while a story is open what it lies over is inert; on a narrow window it is a modal, the page behind it inert, its Tab going round in it', async () => {
  const { rerender, container } = render(
    <>
      <div className="ready-left">
        <button type="button">left</button>
      </div>
      <BacklogPage {...page()} backlog={TREE_TASKS} stories={STORIES} />
    </>,
  )
  const cards = screen.getByRole('list', { name: 'Stories' })
  const panel = await open('Şifre sıfırlama')
  expect(cards.closest('[inert]')).not.toBeNull()
  expect(container.querySelector('.ready-left')).not.toHaveAttribute('inert')
  await userEvent.keyboard('{Escape}')
  expect(cards.closest('[inert]')).toBeNull()
  expect(panel).not.toBeInTheDocument()
  // A narrow window: the panel is the window's - a dialog over everything, Shift+Tab never leaves it.
  const was = window.matchMedia
  window.matchMedia = ((query: string) => ({
    matches: query === '(max-width: 980px)',
    addEventListener: () => {},
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia
  try {
    rerender(
      <>
        <div className="ready-left">
          <button type="button">left</button>
        </div>
        <BacklogPage {...page()} backlog={TREE_TASKS} stories={STORIES} key="narrow" />
      </>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Şifre sıfırlama: 0 of 1 done' }))
    const dialog = screen.getByRole('dialog', { name: 'Şifre sıfırlama' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(container.querySelector('.ready-left')).toHaveAttribute('inert')
    const close = within(dialog).getByRole('button', { name: 'Close Şifre sıfırlama' })
    close.focus()
    await userEvent.tab({ shift: true })
    expect(dialog).toContainElement(document.activeElement as HTMLElement)
    await userEvent.tab()
    expect(close).toHaveFocus()
    await userEvent.click(close)
    expect(container.querySelector('.ready-left')).not.toHaveAttribute('inert')
  } finally {
    window.matchMedia = was
  }
})

/** A narrow window while `run` runs: a story's panel is a modal dialog. */
async function narrowWindow(run: () => Promise<void>) {
  const was = window.matchMedia
  window.matchMedia = ((query: string) => ({
    matches: query === '(max-width: 980px)',
    addEventListener: () => {},
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia
  try {
    await run()
  } finally {
    window.matchMedia = was
  }
}

test('what comes in beside an open story after it opened is inert too; as it closes only what it made inert is put back', async () => {
  const { rerender } = render(<BacklogPage {...page()} backlog={TREE_TASKS} stories={STORIES} />)
  const panel = await open('Şifre sıfırlama')
  // Another's inert, there before: left as it is.
  const theirs = document.createElement('p')
  theirs.setAttribute('inert', '')
  panel.parentElement!.append(theirs)
  // What comes in later - here a failed read's alert - is shut as it comes.
  rerender(<BacklogPage {...page()} backlog={TREE_TASKS} stories={STORIES} error="down" />)
  const alert = screen.getByText(/^The To-do list could not be read/)
  await vi.waitFor(() => expect(alert).toHaveAttribute('inert'))
  await userEvent.keyboard('{Escape}')
  expect(panel).not.toBeInTheDocument()
  expect(alert).not.toHaveAttribute('inert')
  expect(theirs).toHaveAttribute('inert')
  theirs.remove()
})

test('the settings opened over a narrow window’s story: the page around it is not shut while they are over it', async () => {
  const shown = (covered: boolean) => (
    <>
      <div className="ready-left">
        <button type="button">left</button>
      </div>
      <BacklogPage {...page()} backlog={TREE_TASKS} stories={STORIES} covered={covered} />
    </>
  )
  await narrowWindow(async () => {
    const { rerender, container } = render(shown(false))
    await userEvent.click(screen.getByRole('button', { name: 'Şifre sıfırlama: 0 of 1 done' }))
    expect(screen.getByRole('dialog', { name: 'Şifre sıfırlama' })).toBeInTheDocument()
    const left = container.querySelector('.ready-left')!
    expect(left).toHaveAttribute('inert')
    rerender(shown(true))
    expect(left).not.toHaveAttribute('inert')
    // (To-do under it is still shut.)
    expect(screen.getByRole('list', { name: 'Stories' }).closest('[inert]')).not.toBeNull()
    rerender(shown(false))
    expect(left).toHaveAttribute('inert')
  })
})

test('a narrow window’s story: what opens over the page after it - Ctrl+K, a portal in the body - is not shut; what was there is', async () => {
  // (As App lays it out: the page in .main, Ctrl+K beside .main in .app.)
  const shown = (palette: boolean) => (
    <div className="app">
      <nav aria-label="Rail">
        <button type="button">Chats</button>
      </nav>
      <div className="main">
        <BacklogPage {...page()} backlog={TREE_TASKS} stories={STORIES} />
      </div>
      {palette && (
        <div role="dialog" aria-label="Go to">
          <input aria-label="Go to" />
        </div>
      )}
    </div>
  )
  await narrowWindow(async () => {
    const { rerender } = render(shown(false))
    await userEvent.click(screen.getByRole('button', { name: 'Şifre sıfırlama: 0 of 1 done' }))
    expect(screen.getByRole('dialog', { name: 'Şifre sıfırlama' })).toBeInTheDocument()
    expect(document.querySelector('nav[aria-label="Rail"]')).toHaveAttribute('inert')
    rerender(shown(true))
    const portal = document.createElement('div')
    document.body.append(portal)
    await new Promise(done => setTimeout(done, 0))
    const box = screen.getByRole('textbox', { name: 'Go to' })
    expect(box.closest('[inert]')).toBeNull()
    expect(portal).not.toHaveAttribute('inert')
    await userEvent.type(box, 'chats')
    expect(box).toHaveValue('chats')
    portal.remove()
  })
})

test('a narrow window’s story: its Tab goes round what can be seen, not what is hidden in it', async () => {
  await narrowWindow(async () => {
    render(<BacklogPage {...page()} backlog={TREE_TASKS} stories={STORIES} />)
    await userEvent.click(screen.getByRole('button', { name: 'Şifre sıfırlama: 0 of 1 done' }))
    const dialog = screen.getByRole('dialog', { name: 'Şifre sıfırlama' })
    const ghost = document.createElement('div')
    ghost.hidden = true
    ghost.innerHTML = '<button type="button">ghost</button>'
    dialog.append(ghost)
    const close = within(dialog).getByRole('button', { name: 'Close Şifre sıfırlama' })
    close.focus()
    await userEvent.tab({ shift: true })
    const last = document.activeElement as HTMLElement
    expect(dialog).toContainElement(last)
    expect(last.closest('[hidden]')).toBeNull()
    await userEvent.tab()
    expect(close).toHaveFocus()
    ghost.remove()
  })
})

test('Esc in a task’s Edit closes the form, not the story', async () => {
  render(<BacklogPage {...page()} backlog={[task({ title: 'lone' })]} />)
  await loose()
  await userEvent.click(within(await more('lone')).getByRole('menuitem', { name: 'Edit' }))
  expect(screen.getByRole('form', { name: 'Edit lone' })).toBeInTheDocument()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('form', { name: 'Edit lone' })).toBeNull()
  expect(screen.getByRole('complementary', { name: 'Without a story' })).toBeInTheDocument()
})
