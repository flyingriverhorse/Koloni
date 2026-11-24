import type { BacklogTask, Story } from '../api/types'
import { useApp } from '../state/store'

const RANK: Record<BacklogTask['priority'], number> = { high: 0, normal: 1, low: 2 }

/** A story's tasks as To-do orders them (priority, then place), its proposals left out. */
export function storyTasks(story: string, backlog: BacklogTask[]): BacklogTask[] {
  return backlog
    .filter(one => one.story_id === story && one.status !== 'proposed')
    .sort((a, b) => RANK[a.priority] - RANK[b.priority] || a.position - b.position)
}

/** What a task's message in the chat is headed with: "From To-do · task i / n" in its story, else its kind. */
export function todoLabel(task: BacklogTask, backlog: BacklogTask[]): string {
  const mine = task.story_id ? storyTasks(task.story_id, backlog) : []
  const at = mine.findIndex(one => one.id === task.id)
  return at < 0 ? `From To-do · ${task.kind}` : `From To-do · task ${at + 1} / ${mine.length}`
}

/** The line over a story's topic in the chat. */
export const storyDivider = (story: Pick<Story, 'title'>) => `Topic · Story · ${story.title} · 📓 notes`

/** The chat's To-do queue: the task at work in it, and those waiting, in their order. */
export function chatQueue(
  backlog: BacklogTask[],
  cid: string,
): { running: BacklogTask | null; waiting: BacklogTask[] } {
  const here = backlog.filter(one => one.conversation_id === cid)
  return {
    running: here.find(one => one.status === 'doing') ?? null,
    waiting: here.filter(one => one.place != null).sort((a, b) => (a.place ?? 0) - (b.place ?? 0)),
  }
}

/** Whether a story's every task is done - and it is not closed yet: "Story done?" is asked. */
export const storyDone = (story: Story, backlog: BacklogTask[]) => {
  const mine = storyTasks(story.id, backlog)
  return !story.closed_at && mine.length > 0 && mine.every(one => one.status === 'done')
}

const NO_TASKS: BacklogTask[] = []
const NO_STORIES: Story[] = []

/** The open project's To-do as the chat draws it: its tasks and stories, none until read. */
export function useTodo() {
  return { backlog: useApp(s => s.backlog) ?? NO_TASKS, stories: useApp(s => s.stories) ?? NO_STORIES }
}
