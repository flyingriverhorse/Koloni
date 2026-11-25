import type { BacklogTask, Story } from '../api/types'
import { inOrder } from '../backlog/tree'

/** What the strip over a chat says of the story at work in it (0.1.8). */
export interface Strip {
  story: Story
  /** The place of its task at work among the story's tasks, from 1, and how many they are. */
  at: number
  of: number
  /** The story's next task waiting in this chat's queue, if one waits. */
  next: BacklogTask | null
}

/**
 * The story a chat works through, for the strip over it: that of the To-do task at work in the chat - or, while none
 * is, of the first waiting in its queue - with that task's place among its story's tasks (in the To-do list's order,
 * proposals left out) and the story's next task waiting there. null while no task of a story is at work or waits in it.
 */
export function stripOf(backlog: BacklogTask[], stories: Story[], cid: string): Strip | null {
  const here = backlog.filter(task => task.conversation_id === cid && task.story_id)
  const waiting = here.filter(task => task.place != null && task.status !== 'doing')
  waiting.sort((a, b) => (a.place ?? 0) - (b.place ?? 0))
  const current = here.find(task => task.status === 'doing') ?? waiting[0]
  const story = current && stories.find(one => one.id === current.story_id && one.state !== 'done')
  if (!current || !story) return null
  const tasks = inOrder(backlog.filter(task => task.story_id === story.id && task.status !== 'proposed'))
  const next = waiting.find(task => task.story_id === story.id && task !== current) ?? null
  return { story, at: tasks.indexOf(current) + 1, of: tasks.length, next }
}
