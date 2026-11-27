import { expect, test } from 'vitest'
import type { BacklogTask, Story } from '../api/types'
import { cardsOf, inFilter, treeOf, type TreeRow } from './tree'

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

const story = (over: Partial<Story>): Story => ({
  id: over.title ?? 's',
  goal_id: null,
  title: 's',
  position: 0,
  state: 'todo',
  notes: [],
  created_by: 'user',
  closed_at: null,
  ...over,
})

const label = (row: TreeRow) =>
  row.kind === 'story'
    ? `story:${row.story.title}`
    : row.kind === 'task'
      ? `task:${row.task.title}`
      : `section:${row.title}`

const stories = [
  story({ title: 'Şifre sıfırlama', goal_id: 'g', position: 1, state: 'running' }),
  story({ title: 'Login düzelt', goal_id: 'g', position: 0, state: 'done' }),
]
const tasks = [
  task({ title: 'Footer’daki yıl yanlış', kind: 'bug', position: 5 }),
  task({ title: 'E-posta gönderimi', story_id: 'Şifre sıfırlama', status: 'doing', position: 4 }),
  task({ title: 'Test ekle', story_id: 'Login düzelt', status: 'done', position: 2 }),
  task({ title: 'Mobilde buton kayık', story_id: 'Login düzelt', kind: 'bug', status: 'done', position: 3 }),
  task({ title: 'Hatayı bul', story_id: 'Login düzelt', priority: 'high', status: 'done', position: 9 }),
  task({ title: 'An agent’s idea', status: 'proposed', position: 6 }),
]

test('the stories in their order - those a goal holds too (0.1.10: no goal level) - then the tasks without a story', () => {
  expect(treeOf(tasks, stories, 'all').map(label)).toEqual([
    'story:Login düzelt',
    'task:Hatayı bul',
    'task:Test ekle',
    'task:Mobilde buton kayık',
    'story:Şifre sıfırlama',
    'task:E-posta gönderimi',
    'section:Without a story',
    'task:Footer’daki yıl yanlış',
  ])
  const depths = treeOf(tasks, stories, 'all').map(row => ('depth' in row ? row.depth : null))
  expect(depths).toEqual([null, 1, 1, 1, null, 1, null, 0])
  // A story of no goal stands among them by its place, its tasks one step in; a plain list has no heading.
  const alone = treeOf(
    [task({ title: 'a', story_id: 'Solo' }), task({ title: 'b' })],
    [story({ title: 'Solo' })],
    'all',
  )
  expect(alone.map(label)).toEqual(['story:Solo', 'task:a', 'section:Without a story', 'task:b'])
  expect(treeOf([task({ title: 'b' })], [], 'all').map(label)).toEqual(['task:b'])
})

test('the filters', () => {
  expect(inFilter(task({ status: 'blocked' }), 'todo')).toBe(true)
  expect(inFilter(task({ status: 'todo' }), 'todo')).toBe(true)
  expect(inFilter(task({ status: 'todo', place: 1 }), 'todo')).toBe(false)
  expect(inFilter(task({ status: 'todo', place: 1 }), 'running')).toBe(true)
  expect(inFilter(task({ status: 'review' }), 'running')).toBe(true)
  expect(inFilter(task({ status: 'doing' }), 'running')).toBe(true)
  expect(inFilter(task({ status: 'done' }), 'done')).toBe(true)
  expect(inFilter(task({ status: 'done' }), 'todo')).toBe(false)
  // Under Done: the done tasks and their stories; a story with none left shows by its own state.
  expect(treeOf(tasks, stories, 'done').map(label)).toEqual([
    'story:Login düzelt',
    'task:Hatayı bul',
    'task:Test ekle',
    'task:Mobilde buton kayık',
  ])
  expect(treeOf(tasks, stories, 'running').map(label)).toEqual(['story:Şifre sıfırlama', 'task:E-posta gönderimi'])
  // (nothing shown over the tasks of no story: no heading)
  expect(treeOf(tasks, stories, 'todo').map(label)).toEqual(['task:Footer’daki yıl yanlış'])
  // A story at done?, its task waiting for your word: under Running, not Done.
  const waits = [task({ title: 'w', story_id: 'Waits', status: 'review' })]
  const asked = [story({ title: 'Waits', state: 'done?' })]
  expect(treeOf(waits, asked, 'running').map(label)).toEqual(['story:Waits', 'task:w'])
  expect(treeOf(waits, asked, 'done')).toEqual([])
})

test('a story of the agent with only proposed tasks is not shown', () => {
  const theirs = story({ title: 'Agent’s', created_by: 'agent' })
  const proposed = task({ title: 'idea', story_id: 'Agent’s', status: 'proposed' })
  expect(treeOf([proposed], [theirs], 'all')).toEqual([])
  // Once one of its tasks is added, it is.
  expect(treeOf([{ ...proposed, status: 'todo' }], [theirs], 'all').map(label)).toEqual(['story:Agent’s', 'task:idea'])
})

test('the tree as cards (0.1.10): each story with its tasks - one with none shown too -, then one card of the tasks of no story', () => {
  const stories = [story({ title: 'Login' }), story({ title: 'Empty', position: 1 })]
  const tasks = [
    task({ title: 'form', story_id: 'Login' }),
    task({ title: 'reset', story_id: 'Login', position: 1 }),
    task({ title: 'loose' }),
    task({ title: 'bug', kind: 'bug', position: 1 }),
  ]
  const cards = cardsOf(treeOf(tasks, stories, 'all'))
  expect(cards.map(card => [card.key, card.tasks.map(one => one.title)])).toEqual([
    ['Login', ['form', 'reset']],
    ['Empty', []],
    ['none', ['loose', 'bug']],
  ])
  // A list of no story at all is one card.
  expect(cardsOf(treeOf([task({ title: 'only' })], [], 'all')).map(card => [card.story, card.tasks.length])).toEqual([
    [null, 1],
  ])
})
