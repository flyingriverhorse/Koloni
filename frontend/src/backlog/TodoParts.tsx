import { useEffect, useRef, useState } from 'react'
import type { BacklogTask, Story } from '../api/types'
import { AwayPanel } from '../chat/AwayPanel'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { usePanel } from '../shell/usePanel'
import { useApp } from '../state/store'
import { tickable, type Filter } from './tree'

/** To-do's parts (0.1.10, the tree gone for cards): its bar, a task's marks, a story's ⋯, its Rename and its Delete. */

/** What To-do changes of a story; each throws ApiError, and the list is read again after it. */
export interface TreeActions {
  onStory: (storyId: string, change: { title?: string; closed?: boolean }) => Promise<void>
  onDeleteStory: (storyId: string) => Promise<void>
}

export const STATE_WORD: Record<Story['state'], string> = {
  done: '✓ done',
  running: '● running',
  todo: '○ todo',
  stuck: '⚠ stuck',
  'done?': 'done?',
}

/** A row's ⋯ and its menu: each item closes it, then does its work. */
export function RowMenu({ id, name, items }: { id: string; name: string; items: [string, () => void][] }) {
  const { open, setOpen, close, button, panel } = usePanel()
  return (
    <>
      <button
        ref={button}
        id={id}
        type="button"
        className="icon-btn"
        aria-label={`${name}: more`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => (open ? close() : setOpen(true))}
      >
        ⋯
      </button>
      {open && (
        <div ref={panel} tabIndex={-1} className="allow-list-panel msg-menu" role="menu" aria-label={`${name}: more`}>
          {items.map(([label, run]) => (
            <button
              key={label}
              type="button"
              role="menuitem"
              onClick={() => {
                close()
                run()
              }}
            >
              {label}
            </button>
          ))}
        </div>
      )}
    </>
  )
}

/** A title changed in place: Enter keeps it, Esc leaves it as it was. */
export function Rename({
  id,
  title,
  onSave,
  onCancel,
}: {
  id: string
  title: string
  onSave: (title: string) => void
  onCancel: () => void
}) {
  const [value, setValue] = useState(title)
  const field = useRef<HTMLInputElement>(null)
  useEffect(() => field.current?.focus(), [])
  return (
    <form
      className="todo-rename"
      onSubmit={event => {
        event.preventDefault()
        if (value.trim()) onSave(value.trim())
      }}
      onKeyDown={event => event.key === 'Escape' && onCancel()}
    >
      <label className="visually-hidden" htmlFor={id}>{`Rename “${title}”`}</label>
      <input
        ref={field}
        id={id}
        className="input"
        required
        maxLength={200}
        value={value}
        onChange={e => setValue(e.target.value)}
      />
      <button type="submit" className="btn btn-small btn-primary">
        Save
      </button>
    </form>
  )
}

/** Delete asked twice, where it was first asked: what was under it stays. */
export function Deleting({
  title,
  busy,
  onDelete,
  onKeep,
}: {
  title: string
  busy: boolean
  onDelete: () => void
  onKeep: () => void
}) {
  // (Asked where its ⋯ was: the focus on Delete, as it opens - no `autoFocus`.)
  const asked = useRef<HTMLButtonElement>(null)
  useEffect(() => asked.current?.focus(), [])
  return (
    <>
      <button ref={asked} type="button" className="btn btn-small btn-danger" disabled={busy} onClick={onDelete}>
        {`Delete “${title}”`}
      </button>
      <button type="button" className="btn btn-small" onClick={onKeep}>
        Keep it
      </button>
    </>
  )
}

export type Doing = 'rename' | 'delete' | null

/** What a row's ⋯ opened (Rename, Delete) - and, once that is done or left, the focus back on its ⋯. */
export function useDoing(menuId: string) {
  const [doing, setDoing] = useState<Doing>(null)
  const [back, setBack] = useState(0)
  useEffect(() => {
    if (back) document.getElementById(menuId)?.focus()
  }, [back, menuId])
  const done = () => {
    setDoing(null)
    setBack(n => n + 1)
  }
  return { doing, setDoing, done }
}

/** Whether a story may be closed: each of its tasks (proposals left out) done - one at "done?" waits for your word first. */
export const closable = (story: Story, tasks: BacklogTask[]) => {
  const own = tasks.filter(task => task.story_id === story.id && task.status !== 'proposed')
  return story.state === 'done?' && own.length > 0 && own.every(task => task.status === 'done')
}

const FILTERS: [Filter, string][] = [
  ['all', 'All'],
  ['todo', 'Todo'],
  ['running', 'Running'],
  ['done', 'Done'],
]
/** Where a new task is typed. */
const focusAdd = () => document.getElementById('new-task-title')?.focus()

/**
 * ☾ Away from To-do: the Away panel of the chat open now, when it is a chat of this folder that has had a turn - from a
 * story's panel (`pick`), its tasks ticked first: "☾ Do tonight".
 */
export function AwayButton({
  projectId,
  pick,
  label = 'Away',
}: {
  projectId?: string
  pick?: string[]
  label?: string
}) {
  const conv = useApp(s => s.conv)
  const { open, setOpen, close, button, panel } = usePanel()
  const here = projectId && conv?.conversation.project_id === projectId ? conv : null
  const why = !here
    ? 'Open a chat of this folder first: ☾ Away starts from the chat you go away from'
    : here.runs.length === 0
      ? 'Write to the Orchestrator first: Away finishes this chat’s turn'
      : null
  return (
    <div className="allow-list away-chip-wrap">
      <button
        ref={button}
        type="button"
        className="btn btn-small"
        aria-haspopup="dialog"
        aria-expanded={open}
        disabled={!!why}
        title={why ?? `Go away: “${here?.conversation.title}” finishes its turn, then To-do is worked through`}
        onClick={() => (open ? close() : setOpen(true))}
      >
        <span aria-hidden="true">☾</span> {label}
      </button>
      {open && here && (
        <div ref={panel} tabIndex={-1} role="dialog" aria-label="Away" className="allow-list-panel away-panel">
          <AwayPanel conv={here} pick={pick} onClose={close} />
        </div>
      )}
    </div>
  )
}

/** To-do's bar (0.1.8): its filters, + Task and ☾ Away. */
export function TodoBar({
  filter,
  onFilter,
  projectId,
}: {
  filter: Filter
  onFilter: (filter: Filter) => void
  projectId?: string
}) {
  return (
    <div className="todo-bar" role="toolbar" aria-label="To-do">
      <div role="group" aria-label="Show tasks" className="todo-filters">
        {FILTERS.map(([value, label]) => (
          <button
            key={value}
            type="button"
            className="btn btn-small"
            aria-pressed={filter === value}
            onClick={() => onFilter(value)}
          >
            {label}
          </button>
        ))}
      </div>
      <Hint doc={GUIDE.todoStories}>
        A story holds the tasks and bugs that go on together. A story is done only when you close it.
      </Hint>
      <button type="button" className="btn btn-small" onClick={focusAdd}>
        + Task
      </button>
      <AwayButton projectId={projectId} />
    </div>
  )
}

/** A task row's tick and its type - a bug in rose. */
export function TaskMarks({
  task,
  ticked,
  onTick,
}: {
  task: BacklogTask
  ticked: boolean
  onTick: (on: boolean) => void
}) {
  return (
    <>
      <input
        type="checkbox"
        aria-label={`Tick ${task.title}`}
        checked={ticked}
        disabled={!tickable(task)}
        onChange={e => onTick(e.target.checked)}
      />
      <span className={`tag${task.kind === 'bug' ? ' tag-del' : ''}`}>{task.kind}</span>
    </>
  )
}
