import { useEffect } from 'react'
import type { BacklogTask } from '../api/types'
import { useAsk } from '../memory/useAsk'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { chatQueue } from './todo'

/** Above the message box: the chat's To-do queue - the task at work, those waiting (each can go back), and that your message goes first. */
export function TodoQueue({
  running,
  waiting,
  onRemove,
}: {
  running: BacklogTask | null
  waiting: BacklogTask[]
  onRemove: (taskId: string) => Promise<void>
}) {
  const { busy, error, ask } = useAsk()
  if (!running && !waiting.length) return null
  return (
    <section className="todo-queue" aria-label="To-do queue">
      <div className="kicker">{waiting.length} wait</div>
      <ol className="todo-queue-list">
        {running && (
          <li>
            {running.title} <span className="muted">· running</span>
          </li>
        )}
        {waiting.map(task => (
          <li key={task.id}>
            {task.title}{' '}
            <button
              type="button"
              className="btn btn-link"
              aria-label={`Remove “${task.title}” from the queue`}
              disabled={busy}
              onClick={() => void ask(() => onRemove(task.id))}
            >
              Remove
            </button>
          </li>
        ))}
      </ol>
      <p className="muted todo-queue-note">+ your message goes first when you send one</p>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </section>
  )
}

/** The queue as the chat has it: its project's To-do read once (a task's turn and its cards need it too). */
export function ChatTodoQueue({ conv, open }: { conv: ConvState | null; open: boolean }) {
  const backlog = useApp(s => s.backlog)
  const projectId = conv?.conversation.project_id ?? null
  const here = useApp(s => s.projectId) === projectId && projectId !== null
  // (Read where a task has had a turn here; Do in chat reads it as it opens the chat.)
  const tasks = !!conv?.runs.some(run => run.task_id)
  useEffect(() => {
    if (here && tasks && backlog === null) void useApp.getState().loadBacklog()
  }, [here, tasks, backlog])
  if (!open || !here || !backlog || !conv) return null
  const { running, waiting } = chatQueue(backlog, conv.conversation.id)
  return <TodoQueue running={running} waiting={waiting} onRemove={useApp.getState().unqueueTask} />
}
