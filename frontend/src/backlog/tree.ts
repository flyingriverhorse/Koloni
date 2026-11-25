import { useState } from 'react'
import type { BacklogTask, Goal, Story } from '../api/types'

/** The To-do page's filters (0.1.8): every task, those to do, those at work, those done. */
export type Filter = 'all' | 'todo' | 'running' | 'done'

/** Whether a task is under a filter: to do (or stuck), at work (queued in a chat, running, "done?"), or done. */
export function inFilter(task: BacklogTask, filter: Filter): boolean {
  if (filter === 'todo') return (task.status === 'todo' && !task.place) || task.status === 'blocked'
  if (filter === 'running') return !!task.place || task.status === 'doing' || task.status === 'review'
  if (filter === 'done') return task.status === 'done'
  return true
}

/** One row of the To-do tree: a goal with its stories done of all, a story, a task or bug, or the heading of the tasks of no story. */
export type TreeRow =
  | { kind: 'goal'; goal: Goal; done: number; all: number }
  | { kind: 'story'; story: Story; depth: 0 | 1 }
  | { kind: 'task'; task: BacklogTask; depth: 0 | 1 | 2 }
  | { kind: 'section'; title: 'Without a story' }

const RANK: Record<BacklogTask['priority'], number> = { high: 0, normal: 1, low: 2 }
/** Tasks in the To-do list's order: by priority, then by their place. */
export const inOrder = (tasks: BacklogTask[]) =>
  [...tasks].sort((a, b) => RANK[a.priority] - RANK[b.priority] || a.position - b.position)
const byPosition = <T extends { position: number }>(rows: T[]) => [...rows].sort((a, b) => a.position - b.position)

/** Whether a story with none of its tasks left under a filter is shown for its own state. */
const storyIn = (state: Story['state'], filter: Filter) =>
  filter === 'all' ||
  (filter === 'todo' && (state === 'todo' || state === 'stuck')) ||
  // (done? waits for your word: it is still running, not done)
  (filter === 'running' && (state === 'running' || state === 'done?')) ||
  (filter === 'done' && state === 'done')

/**
 * The To-do list as a tree: the goals in their order, each with its stories and their tasks (priority, then place);
 * the stories of no goal after them; last "Without a story" and the tasks of no story. Proposals are not in it (they
 * wait for your word above), nor a story an agent opened that holds only proposals; under a filter, a story with no
 * task left is shown only where its own state is under it, a goal only with a story shown.
 */
export function treeOf(tasks: BacklogTask[], stories: Story[], goals: Goal[], filter: Filter): TreeRow[] {
  const listed = tasks.filter(task => task.status !== 'proposed')
  const shown = stories.filter(story => story.created_by !== 'agent' || listed.some(t => t.story_id === story.id))
  const ids = new Set(shown.map(story => story.id))
  // (A task of a story not shown - gone since the list was read - stands with those of no story.)
  const of = (story: string | null) =>
    inOrder(listed.filter(task => (task.story_id && ids.has(task.story_id) ? task.story_id : null) === story))
  const storyRows = (story: Story, depth: 0 | 1): TreeRow[] => {
    const own = of(story.id).filter(task => inFilter(task, filter))
    if (!own.length && !storyIn(story.state, filter)) return []
    return [
      { kind: 'story', story, depth },
      ...own.map(task => ({ kind: 'task' as const, task, depth: (depth + 1) as 1 | 2 })),
    ]
  }
  const rows: TreeRow[] = []
  for (const goal of byPosition(goals)) {
    const under = byPosition(shown.filter(story => story.goal_id === goal.id)).flatMap(story => storyRows(story, 1))
    if (under.length || filter === 'all')
      rows.push({ kind: 'goal', goal, done: goal.stories_done, all: goal.stories_all }, ...under)
  }
  const known = new Set(goals.map(goal => goal.id))
  rows.push(
    ...byPosition(shown.filter(story => !story.goal_id || !known.has(story.goal_id))).flatMap(story =>
      storyRows(story, 0),
    ),
  )
  const loose = of(null).filter(task => inFilter(task, filter))
  // (A list with nothing shown over them is a plain list: no heading.)
  if (loose.length && rows.length) rows.push({ kind: 'section', title: 'Without a story' })
  return [...rows, ...loose.map(task => ({ kind: 'task' as const, task, depth: 0 as const }))]
}

/** A task that can be ticked to go into a chat: to do or stuck, not waiting in a chat's queue already. */
export const tickable = (task: BacklogTask) => (task.status === 'todo' || task.status === 'blocked') && !task.place

/**
 * The tree as the page shows it: its filter, its rows, the ticked tasks (ticked or not some at once), each task's
 * neighbours a move goes past (of its story and its priority), and a new story made for a task's form.
 */
export function useTreeView(
  listed: BacklogTask[],
  stories: Story[] | null | undefined,
  goals: Goal[] | null | undefined,
  onNewStory: (title: string) => Promise<Story>,
) {
  const [filter, setFilter] = useState<Filter>('all')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const own = { stories: stories ?? [], goals: goals ?? [] }
  const rows = treeOf(listed, own.stories, own.goals, filter)
  const select = (ids: string[], on: boolean) =>
    setSelected(now => new Set(on ? [...now, ...ids] : [...now].filter(one => !ids.includes(one))))
  const shown = rows.flatMap(row => (row.kind === 'task' ? [row.task] : []))
  const beside = (task: BacklogTask, by: -1 | 1) => {
    const mine = shown.filter(one => one.story_id === task.story_id)
    const next = mine[mine.indexOf(task) + by]
    return next && next.priority === task.priority ? next : undefined
  }
  return {
    ...own,
    filter,
    setFilter,
    rows,
    selected,
    select,
    beside,
    // (Nothing at all yet - no task, story or goal: the page says how to start.)
    empty: filter === 'all' && rows.length === 0,
    choice: { stories: own.stories, onNewStory: async (title: string) => (await onNewStory(title)).id },
  }
}
