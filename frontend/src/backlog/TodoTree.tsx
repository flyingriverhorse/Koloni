import { useEffect, useState, type ReactNode } from 'react'
import type { BacklogTask, Goal, Story } from '../api/types'
import { AwayPanel } from '../chat/AwayPanel'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { useAsk } from '../memory/useAsk'
import { usePanel } from '../shell/usePanel'
import { useApp } from '../state/store'
import { NotebookButton } from './Notebook'
import { tickable, type Filter, type TreeRow } from './tree'

/** What the tree changes of a goal or a story; each throws ApiError, and the list is read again after it. */
export interface TreeActions {
  onGoal: (goalId: string, change: { title?: string }) => Promise<void>
  onDeleteGoal: (goalId: string) => Promise<void>
  onStory: (storyId: string, change: { title?: string; goal_id?: string | null; closed?: boolean }) => Promise<void>
  onDeleteStory: (storyId: string) => Promise<void>
  onNewGoal: (title: string) => Promise<Goal>
}

interface Props extends TreeActions {
  rows: TreeRow[]
  tasks: BacklogTask[]
  goals: Goal[]
  /** The ticked tasks, and ticking (or not) some at once. */
  selected: Set<string>
  onSelect: (taskIds: string[], on: boolean) => void
  /** The project's chats' titles, by id: where a running story is. */
  chats: Record<string, string>
  /** A task's row, as the list draws it. */
  taskRow: (task: BacklogTask, depth: 0 | 1 | 2) => ReactNode
}

const STATE_WORD: Record<Story['state'], string> = {
  done: '✓ done',
  running: '● running',
  todo: '○ todo',
  stuck: '⚠ stuck',
  'done?': 'done?',
}
const STATE_TONE: Record<Story['state'], string> = {
  done: ' tag-ok',
  running: ' tag-accent',
  todo: '',
  stuck: ' tag-del',
  'done?': ' tag-ok',
}

/** A row's ⋯ and its menu: each item closes it, then does its work. */
function RowMenu({ id, name, items }: { id: string; name: string; items: [string, () => void][] }) {
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
function Rename({
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
        id={id}
        className="input"
        autoFocus
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
function Deleting({
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
  return (
    <>
      <button type="button" className="btn btn-small btn-danger" autoFocus disabled={busy} onClick={onDelete}>
        {`Delete “${title}”`}
      </button>
      <button type="button" className="btn btn-small" onClick={onKeep}>
        Keep it
      </button>
    </>
  )
}

type Doing = 'rename' | 'goal' | 'delete' | null
type Item = [string, () => void]

/** What a row's ⋯ opened (Rename, Goal, Delete) - and, once that is done or left, the focus back on its ⋯. */
function useDoing(menuId: string) {
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
const closable = (story: Story, tasks: BacklogTask[]) => {
  const own = tasks.filter(task => task.story_id === story.id && task.status !== 'proposed')
  return story.state === 'done?' && own.length > 0 && own.every(task => task.status === 'done')
}

/** A story's ⋯: Rename, Goal, Delete - and, once all its tasks are done, Close the story (done is only ever yours), or Open it again. */
const storyItems = (
  story: Story,
  canClose: boolean,
  set: (doing: Doing) => void,
  close: (closed: boolean) => void,
): Item[] => [
  ['Rename', () => set('rename')],
  ['Goal', () => set('goal')],
  ...(canClose ? [['Close the story', () => close(true)] as Item] : []),
  ...(story.state === 'done' ? [['Open it again', () => close(false)] as Item] : []),
  ['Delete', () => set('delete')],
]

/** A goal: its title, how many of its stories are done, and a bar of it. */
function GoalRow({ row, actions }: { row: Extract<TreeRow, { kind: 'goal' }>; actions: TreeActions }) {
  const { busy, error, ask } = useAsk()
  const { goal, done, all } = row
  const id = `goal-${goal.id}`
  const { doing, setDoing, done: back } = useDoing(`${id}-more`)
  return (
    <li className="todo-goal" aria-labelledby={`${id}-title`}>
      <div className="backlog-row">
        <span className="kicker">Goal</span>
        {doing === 'rename' ? (
          <Rename
            id={`${id}-name`}
            title={goal.title}
            onSave={title => void ask(() => actions.onGoal(goal.id, { title })).then(ok => ok && back())}
            onCancel={back}
          />
        ) : (
          <strong id={`${id}-title`} className="backlog-row-text">
            {goal.title}
          </strong>
        )}
        <span className="muted">{`${done} / ${all} stories`}</span>
        <span
          className="todo-progress"
          role="progressbar"
          aria-label={`${goal.title}: stories done`}
          aria-valuemin={0}
          aria-valuemax={all}
          aria-valuenow={done}
        >
          <span style={{ width: `${all ? (100 * done) / all : 0}%` }} />
        </span>
        {doing === 'delete' ? (
          <Deleting
            title={goal.title}
            busy={busy}
            onDelete={() => void ask(() => actions.onDeleteGoal(goal.id))}
            onKeep={back}
          />
        ) : (
          <RowMenu
            id={`${id}-more`}
            name={goal.title}
            items={[
              ['Rename', () => setDoing('rename')],
              ['Delete', () => setDoing('delete')],
            ]}
          />
        )}
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </li>
  )
}

/** A story's goal chosen: none, one of the project's, or a new one named here. */
function GoalChoice({
  id,
  story,
  goals,
  actions,
  onDone,
}: {
  id: string
  story: Story
  goals: Goal[]
  actions: TreeActions
  onDone: () => void
}) {
  const { busy, error, ask } = useAsk()
  const [naming, setNaming] = useState(false)
  const set = (goalId: string | null) =>
    void ask(() => actions.onStory(story.id, { goal_id: goalId })).then(ok => ok && onDone())
  return (
    <div className="todo-rename">
      {naming ? (
        <Rename
          id={`${id}-new-goal`}
          title=""
          onSave={title =>
            void ask(async () => {
              const goal = await actions.onNewGoal(title)
              await actions.onStory(story.id, { goal_id: goal.id })
            }).then(ok => ok && onDone())
          }
          onCancel={onDone}
        />
      ) : (
        <>
          <label className="visually-hidden" htmlFor={`${id}-goal`}>{`Goal of ${story.title}`}</label>
          <select
            id={`${id}-goal`}
            className="input"
            autoFocus
            disabled={busy}
            value={story.goal_id ?? ''}
            onChange={e => (e.target.value === NEW ? setNaming(true) : set(e.target.value || null))}
            onKeyDown={e => e.key === 'Escape' && onDone()}
          >
            <option value="">No goal</option>
            {goals.map(goal => (
              <option key={goal.id} value={goal.id}>
                {goal.title}
              </option>
            ))}
            <option value={NEW}>New goal…</option>
          </select>
        </>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}

const NEW = '__new__'

interface StoryProps {
  row: Extract<TreeRow, { kind: 'story' }>
  tasks: BacklogTask[]
  goals: Goal[]
  selected: Set<string>
  onSelect: Props['onSelect']
  chats: Props['chats']
  actions: TreeActions
}

/** A story: a tick for its open tasks, its state, its notebook, the chat it runs in, and ⋯ (Rename, Goal, Delete). */
function StoryRow({ row, tasks, goals, selected, onSelect, chats, actions }: StoryProps) {
  const { busy, error, ask } = useAsk()
  const { story } = row
  const id = `story-${story.id}`
  const { doing, setDoing, done: back } = useDoing(`${id}-more`)
  const open = tasks.filter(task => task.story_id === story.id && tickable(task)).map(task => task.id)
  const ticked = open.length > 0 && open.every(one => selected.has(one))
  const at = tasks.find(task => task.story_id === story.id && task.status === 'doing' && task.conversation_id)
  const chat = story.state === 'running' && at?.conversation_id ? chats[at.conversation_id] : undefined
  return (
    <li className={`todo-story todo-depth-${row.depth}`} aria-labelledby={`${id}-title`}>
      <div className="backlog-row">
        <input
          type="checkbox"
          aria-label={`Tick the story ${story.title}`}
          checked={ticked}
          disabled={!open.length}
          onChange={e => onSelect(open, e.target.checked)}
        />
        <span className="kicker">Story</span>
        {doing === 'rename' ? (
          <Rename
            id={`${id}-name`}
            title={story.title}
            onSave={title => void ask(() => actions.onStory(story.id, { title })).then(ok => ok && back())}
            onCancel={back}
          />
        ) : (
          <strong id={`${id}-title`} className="backlog-row-text">
            {story.title}
          </strong>
        )}
        {chat && <span className="muted">{`in “${chat}”`}</span>}
        <NotebookButton story={story} />
        <span className={`tag${STATE_TONE[story.state]}`}>{STATE_WORD[story.state]}</span>
        {doing === 'delete' ? (
          <Deleting
            title={story.title}
            busy={busy}
            onDelete={() => void ask(() => actions.onDeleteStory(story.id))}
            onKeep={back}
          />
        ) : (
          <RowMenu
            id={`${id}-more`}
            name={story.title}
            items={storyItems(
              story,
              closable(story, tasks),
              setDoing,
              closed => void ask(() => actions.onStory(story.id, { closed })),
            )}
          />
        )}
      </div>
      {doing === 'goal' && <GoalChoice id={id} story={story} goals={goals} actions={actions} onDone={back} />}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </li>
  )
}

/** The To-do list as a tree (0.1.8): goals, their stories, tasks and bugs, and the tasks of no story under their heading. */
export function TodoTree({ rows, tasks, goals, selected, onSelect, chats, taskRow, ...actions }: Props) {
  return (
    <ol className="backlog-rows todo-tree" aria-label="Tasks">
      {rows.map(row =>
        row.kind === 'goal' ? (
          <GoalRow key={`g-${row.goal.id}`} row={row} actions={actions} />
        ) : row.kind === 'story' ? (
          <StoryRow
            key={`s-${row.story.id}`}
            row={row}
            tasks={tasks}
            goals={goals}
            selected={selected}
            onSelect={onSelect}
            chats={chats}
            actions={actions}
          />
        ) : row.kind === 'section' ? (
          <li key="section" className="todo-section kicker">
            {row.title}
          </li>
        ) : (
          taskRow(row.task, row.depth)
        ),
      )}
    </ol>
  )
}

const FILTERS: [Filter, string][] = [
  ['all', 'All'],
  ['todo', 'Todo'],
  ['running', 'Running'],
  ['done', 'Done'],
]
/** Where a new task is typed. */
const focusAdd = () => document.getElementById('new-task-title')?.focus()

/** ☾ Away from To-do: the Away panel of the chat open now, when it is a chat of this folder that has had a turn. */
function AwayButton({ projectId }: { projectId?: string }) {
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
        <span aria-hidden="true">☾</span> Away
      </button>
      {open && here && (
        <div ref={panel} tabIndex={-1} role="dialog" aria-label="Away" className="allow-list-panel away-panel">
          <AwayPanel conv={here} onClose={close} />
        </div>
      )}
    </div>
  )
}

/** The To-do page's bar (0.1.8): its filters, + Task, Write it with the Hive keeper (its note box), and ☾ Away. */
export function TodoBar({
  filter,
  onFilter,
  projectId,
  onHive,
  noting,
}: {
  filter: Filter
  onFilter: (filter: Filter) => void
  projectId?: string
  /** Opens or closes the Hive keeper's note box; none where a note can be neither written nor planned here. */
  onHive?: () => void
  noting: boolean
}) {
  return (
    <div className="todo-bar" role="toolbar" aria-label="To-do">
      <div role="group" aria-label="Show" className="todo-filters">
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
        A goal holds stories; a story holds the tasks and bugs that go on together. A story is done only when you close
        it.
      </Hint>
      <button type="button" className="btn btn-small" onClick={focusAdd}>
        + Task
      </button>
      {onHive && (
        <button id="todo-hive" type="button" className="btn btn-small" aria-expanded={noting} onClick={onHive}>
          Write it with the Hive keeper
        </button>
      )}
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
