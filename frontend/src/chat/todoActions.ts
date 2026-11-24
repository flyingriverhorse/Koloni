import { api } from '../api/client'
import type { BacklogDone, BacklogTask } from '../api/types'
import { useApp } from '../state/store'

/** 0.1.8, To-do in a chat: what the To-do page and the chat's cards and queue ask the server for. Each throws ApiError. */
const projectPath = () => '/projects/' + useApp.getState().projectId

/** Do in chat: the ticked tasks wait in this chat's queue (null: a new chat's), which opens. Its id. */
export async function doInChat(taskIds: string[], conversationId: string | null): Promise<string> {
  const body = { task_ids: taskIds, conversation_id: conversationId }
  const done = await api.post<BacklogDone>(projectPath() + '/backlog/do-in-chat', body)
  await Promise.all([useApp.getState().loadBacklog(), useApp.getState().loadConversations()])
  await useApp.getState().openConversation(done.conversation_id)
  return done.conversation_id
}

/** The chat's queue's Remove: the task back on To-do. */
export async function unqueueTask(taskId: string) {
  await api.delete('/backlog/' + taskId + '/queue')
  await useApp.getState().loadBacklog()
}

/** Fix it, on a stuck task's card: one more fix round in its chat. */
export async function fixTask(taskId: string) {
  await api.post('/backlog/' + taskId + '/fix')
  await useApp.getState().loadBacklog()
}

/** Story done?'s Add a task: a task of the story, queued in this chat. */
export async function addToStory(storyId: string, title: string, conversationId: string) {
  const task = await api.post<BacklogTask>(projectPath() + '/backlog', { title, story_id: storyId })
  await api.post(projectPath() + '/backlog/do-in-chat', { task_ids: [task.id], conversation_id: conversationId })
  await useApp.getState().loadBacklog()
}
