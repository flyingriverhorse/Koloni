import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { BacklogTask, Story } from '../api/types'
import { chatQueue, storyDivider, storyDone, todoLabel } from './todo'
import { DoneCard, StoryDoneCard, StuckCard } from './TodoCards'
import { TodoQueue } from './TodoQueue'

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
  created_at: '2026-11-24T10:00:00Z',
  ...over,
})

const story = (over: Partial<Story> = {}): Story => ({
  id: 's',
  goal_id: null,
  title: 'İki adımlı giriş',
  position: 0,
  state: 'running',
  notes: [],
  created_by: 'user',
  closed_at: null,
  ...over,
})

const t1 = task({ title: 'Kod üret', story_id: 's', position: 0 })
const t2 = task({ title: 'Ayarlarda aç / kapat', story_id: 's', position: 1 })
const lone = task({ title: 'Footer', kind: 'bug', position: 2 })
const proposal = task({ title: 'an agent’s', story_id: 's', status: 'proposed', position: 3 })
const backlog = [t1, t2, lone, proposal]

test('a task is labelled by its place in its story, a lone one by its kind', () => {
  expect(todoLabel(t2, backlog)).toBe('From To-do · task 2 / 2')
  expect(todoLabel(t1, backlog)).toBe('From To-do · task 1 / 2')
  expect(todoLabel(lone, backlog)).toBe('From To-do · bug')
  expect(storyDivider(story())).toBe('Topic · Story · İki adımlı giriş · 📓 notes')
})

test('the chat’s queue: the one at work and those waiting, in their order', () => {
  const here = [
    task({ title: 'a', conversation_id: 'c', status: 'doing' }),
    task({ title: 'b', conversation_id: 'c', place: 3 }),
    task({ title: 'c', conversation_id: 'c', place: 2 }),
    task({ title: 'd', conversation_id: 'other', place: 1 }),
  ]
  const queue = chatQueue(here, 'c')
  expect(queue.running?.title).toBe('a')
  expect(queue.waiting.map(one => one.title)).toEqual(['c', 'b'])
})

test('Story done? only once every task of it is done', () => {
  expect(
    storyDone(story(), [
      { ...t1, status: 'done' },
      { ...t2, status: 'review' },
    ]),
  ).toBe(false)
  expect(storyDone(story(), [{ ...t1, status: 'done' }, { ...t2, status: 'done' }, proposal])).toBe(true)
  expect(storyDone(story({ closed_at: '2026-11-24T11:00:00Z' }), [{ ...t1, status: 'done' }])).toBe(false)
})

test('Done? says the Scout’s view and takes the user’s word', async () => {
  const onChange = vi.fn(async () => {})
  render(<DoneCard task={{ ...t1, status: 'review', assessment: 'The test passes.' }} onChange={onChange} />)
  expect(screen.getByText('Done? — “Kod üret”')).toBeInTheDocument()
  expect(screen.getByText('The test passes.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Yes, done' }))
  expect(onChange).toHaveBeenLastCalledWith('Kod üret', { status: 'done' })
  await userEvent.click(screen.getByRole('button', { name: 'Not yet' }))
  expect(onChange).toHaveBeenLastCalledWith('Kod üret', { status: 'todo' })
})

test('Stuck says why; Fix it, To-do, and Leave it folds it to one line', async () => {
  const onFix = vi.fn(async () => {})
  const onOpenTodo = vi.fn()
  render(
    <StuckCard
      task={{ ...t1, status: 'blocked', stuck: 'the check "pytest" did not pass' }}
      onFix={onFix}
      onOpenTodo={onOpenTodo}
    />,
  )
  expect(screen.getByText('the check "pytest" did not pass')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Fix it' }))
  expect(onFix).toHaveBeenCalledWith('Kod üret')
  await userEvent.click(screen.getByRole('button', { name: 'Open it in To-do' }))
  expect(onOpenTodo).toHaveBeenCalledWith('Kod üret')
  await userEvent.click(screen.getByRole('button', { name: 'Leave it' }))
  expect(screen.queryByRole('button', { name: 'Fix it' })).toBeNull()
  expect(screen.getByRole('group', { name: 'Stuck — “Kod üret”' })).toHaveTextContent('Stuck — “Kod üret”')
})

test('Story done? closes the story, or adds a task to it', async () => {
  const onClose = vi.fn(async () => {})
  const onAdd = vi.fn(async () => {})
  render(<StoryDoneCard story={story()} onClose={onClose} onAdd={onAdd} />)
  await userEvent.click(screen.getByRole('button', { name: 'Close the story' }))
  expect(onClose).toHaveBeenCalledWith('s')
  await userEvent.click(screen.getByRole('button', { name: 'Add a task' }))
  await userEvent.type(screen.getByRole('textbox', { name: "The new task's title" }), 'Mobil{Enter}')
  expect(onAdd).toHaveBeenCalledWith('s', 'Mobil')
})

test('the queue above the box: how many wait, the one at work, Remove, and your message first', async () => {
  const onRemove = vi.fn(async () => {})
  const waiting = [task({ title: 'b' }), task({ title: 'c' })]
  render(<TodoQueue running={task({ title: 'a' })} waiting={waiting} onRemove={onRemove} />)
  const queue = screen.getByRole('region', { name: 'To-do queue' })
  expect(queue).toHaveTextContent('2 wait')
  expect(queue).toHaveTextContent('a · running')
  expect(queue).toHaveTextContent('+ your message goes first when you send one')
  await userEvent.click(screen.getByRole('button', { name: 'Remove “c” from the queue' }))
  expect(onRemove).toHaveBeenCalledWith('c')
})

test('no queue: nothing above the box', () => {
  const { container } = render(<TodoQueue running={null} waiting={[]} onRemove={async () => {}} />)
  expect(container).toBeEmptyDOMElement()
})
