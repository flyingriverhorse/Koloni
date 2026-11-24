import { useState } from 'react'
import type { BacklogTask, Run, Story } from '../api/types'
import { useAsk } from '../memory/useAsk'
import { useApp } from '../state/store'
import { storyDone } from './todo'
import { addToStory, fixTask } from './todoActions'

/** A card's buttons, and what went wrong with the last press. */
function Buttons({ items, error }: { items: [string, () => void, boolean?][]; error: string | null }) {
  return (
    <>
      <div className="todo-card-actions">
        {items.map(([label, run, disabled]) => (
          <button key={label} type="button" className="btn btn-small" disabled={disabled} onClick={run}>
            {label}
          </button>
        ))}
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </>
  )
}

/** Under a To-do task's last turn while it waits at "done?": the Scout's view, and the user's word. */
export function DoneCard({
  task,
  onChange,
}: {
  task: BacklogTask
  onChange: (taskId: string, change: { status: 'done' | 'todo' }) => Promise<void>
}) {
  const { busy, error, ask } = useAsk()
  return (
    <div className="cmd-approval todo-card" role="group" aria-label={`Done? — “${task.title}”`}>
      <div className="kicker cmd-approval-kicker">Done? — “{task.title}”</div>
      {task.assessment && <p className="card-said">{task.assessment}</p>}
      <Buttons
        error={error}
        items={[
          ['Yes, done', () => void ask(() => onChange(task.id, { status: 'done' })), busy],
          ['Not yet', () => void ask(() => onChange(task.id, { status: 'todo' })), busy],
        ]}
      />
    </div>
  )
}

const LEFT = (id: string) => `koloni.todo.left.${id}`

function wasLeft(id: string) {
  try {
    return localStorage.getItem(LEFT(id)) === '1'
  } catch {
    return false
  }
}

/** Under a To-do task's last turn while it is stuck: why, Fix it (one more round), To-do, or Leave it (one line). */
export function StuckCard({
  task,
  onFix,
  onOpenTodo,
}: {
  task: BacklogTask
  onFix: (taskId: string) => Promise<void>
  onOpenTodo: (taskId: string) => void
}) {
  const { busy, error, ask } = useAsk()
  const [left, setLeft] = useState(() => wasLeft(task.id))
  const title = `Stuck — “${task.title}”`
  if (left)
    return (
      <div className="muted todo-card-left" role="group" aria-label={title}>
        {title}{' '}
        <button type="button" className="btn btn-link" onClick={() => setLeft(false)}>
          Show
        </button>
      </div>
    )
  return (
    <div className="cmd-approval todo-card" role="group" aria-label={title}>
      <div className="kicker cmd-approval-kicker">{title}</div>
      {task.stuck && <p className="card-said">{task.stuck}</p>}
      <Buttons
        error={error}
        items={[
          ['Fix it', () => void ask(() => onFix(task.id)), busy],
          ['Open it in To-do', () => onOpenTodo(task.id)],
          [
            'Leave it',
            () => {
              try {
                localStorage.setItem(LEFT(task.id), '1')
              } catch {
                // (this browser keeps nothing: it is folded until the chat is drawn again)
              }
              setLeft(true)
            },
          ],
        ]}
      />
    </div>
  )
}

/** Under a story's last turn in the chat once every task of it is done: close it, or add a task (queued here). */
export function StoryDoneCard({
  story,
  onClose,
  onAdd,
}: {
  story: Story
  onClose: (storyId: string) => Promise<void>
  onAdd: (storyId: string, title: string) => Promise<void>
}) {
  const { busy, error, ask } = useAsk()
  const [adding, setAdding] = useState<string | null>(null)
  const title = `Story done? — “${story.title}”`
  return (
    <div className="cmd-approval todo-card" role="group" aria-label={title}>
      <div className="kicker cmd-approval-kicker">{title}</div>
      {adding !== null && (
        <form
          className="todo-card-add"
          onSubmit={e => {
            e.preventDefault()
            const name = adding.trim()
            if (name) void ask(() => onAdd(story.id, name)).then(done => done && setAdding(null))
          }}
        >
          <input
            autoFocus
            className="input"
            aria-label="The new task's title"
            maxLength={200}
            value={adding}
            disabled={busy}
            onChange={e => setAdding(e.target.value)}
          />
          <button type="submit" className="btn btn-small btn-primary" disabled={busy || !adding.trim()}>
            Add and queue it here
          </button>
        </form>
      )}
      <Buttons
        error={error}
        items={[
          ['Close the story', () => void ask(() => onClose(story.id)), busy],
          ['Add a task', () => setAdding(adding === null ? '' : null), busy],
        ]}
      />
    </div>
  )
}

/** What a To-do card in the chat asks the app for: the To-do page, at that task's row. */
export const OPEN_TODO = 'koloni:open-todo'

/**
 * Under a turn of a To-do task in the chat (0.1.8): its Done? or Stuck card, under the task's last turn here - and
 * Story done? under its story's last task turn here, once every task of it is done. Drawn from the task's state alone.
 */
export function TodoTurnCards({ cid, runs, runId }: { cid: string; runs: Run[]; runId: string }) {
  const backlog = useApp(s => s.backlog) ?? []
  const stories = useApp(s => s.stories) ?? []
  const app = useApp.getState()
  const taskOf = (run: Run) => backlog.find(one => one.id === run.task_id)
  const task = backlog.find(one => one.id === runs.find(run => run.id === runId)?.task_id)
  if (!task) return null
  const last = (match: (run: Run) => boolean) => runs.findLast(match)?.id === runId
  const story = stories.find(one => one.id === task.story_id)
  const lastOfStory = story && last(run => taskOf(run)?.story_id === story.id)
  return (
    <>
      {last(run => run.task_id === task.id) && task.status === 'review' && (
        <DoneCard task={task} onChange={app.changeTask} />
      )}
      {last(run => run.task_id === task.id) && task.status === 'blocked' && task.stuck && (
        <StuckCard
          task={task}
          onFix={fixTask}
          onOpenTodo={id => window.dispatchEvent(new CustomEvent(OPEN_TODO, { detail: id }))}
        />
      )}
      {lastOfStory && storyDone(story, backlog) && (
        <StoryDoneCard
          story={story}
          onClose={id => app.changeStory(id, { closed: true })}
          onAdd={(id, title) => addToStory(id, title, cid)}
        />
      )}
    </>
  )
}
