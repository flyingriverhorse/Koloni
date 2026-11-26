import { X } from '@phosphor-icons/react'
import { type KeyboardEvent, type ReactNode, useEffect, useId, useRef } from 'react'
import type { Away, BacklogTask, Story } from '../api/types'
import { useAsk } from '../memory/useAsk'
import { CELL, STANDS_WORD, type Stands, taskStands } from '../ready/cells'
import { Cell } from '../shell/Cell'
import { NotebookNotes } from './Notebook'
import { AwayButton, Deleting, Rename, RowMenu, STATE_WORD, type TreeActions, closable, useDoing } from './TodoTree'
import { type Card, tickable } from './tree'

/** The panel's element: what an open card controls. */
export const PANEL = 'todo-panel'
/** A card's button, by its key: where the focus goes back when its panel closes. */
export const cardId = (key: string) => `todo-card-${key}`
const titleOf = (card: Card) => card.story?.title ?? 'Without a story'

/** Each task of a card as it stands, and its word; `pushes`: the tasks whose push the night parked for you. */
const standsOf = (card: Card, pushes: Set<string>) =>
  card.tasks.map(task => ({ task, said: taskStands(task, pushes.has(task.id)) }))

/**
 * A story as a card (0.1.10): its name, how many of its tasks are done, a cell for each task - a row of honeycomb - and
 * its tasks, each with its cell and how it stands. The card is one button: it opens the story's panel.
 */
function StoryCard({
  card,
  open,
  onOpen,
  pushes,
}: {
  card: Card
  open: boolean
  onOpen: () => void
  pushes: Set<string>
}) {
  const done = card.tasks.filter(task => task.status === 'done').length
  const stands = standsOf(card, pushes)
  const title = titleOf(card)
  return (
    <li>
      <button
        id={cardId(card.key)}
        type="button"
        className="todo-card"
        aria-expanded={open}
        aria-controls={open ? PANEL : undefined}
        aria-label={`${title}: ${done} of ${card.tasks.length} done`}
        onClick={onOpen}
      >
        <span className="todo-card-line">
          <span className="todo-card-name">{title}</span>
          <span className="muted">
            {done} / {card.tasks.length}
          </span>
        </span>
        <span className="cell-comb">
          {stands.map(({ task, said: [state, word] }) => (
            <Cell key={task.id} {...CELL[state]} label={`${task.title}: ${word}`} big />
          ))}
        </span>
        <span className="todo-card-tasks">
          {stands.length === 0 && <span className="muted">No task yet</span>}
          {stands.map(({ task, said: [state, word] }) => (
            <span key={task.id} className="todo-card-task">
              <Cell {...CELL[state]} label={word} />
              <span className="todo-card-title">{task.title}</span>
              <span className={`todo-card-state todo-is-${state}`}>{word}</span>
            </span>
          ))}
        </span>
      </button>
    </li>
  )
}

/** To-do's stories as cards, and its tasks of no story as one more; one open at a time. */
export function StoryCards({
  cards,
  openKey,
  onOpen,
  pushes,
}: {
  cards: Card[]
  openKey: string | null
  onOpen: (key: string | null) => void
  pushes: Set<string>
}) {
  return (
    <ul className="todo-cards" aria-label="Stories">
      {cards.map(card => (
        <StoryCard
          key={card.key}
          card={card}
          open={openKey === card.key}
          onOpen={() => onOpen(openKey === card.key ? null : card.key)}
          pushes={pushes}
        />
      ))}
    </ul>
  )
}

/** What the cells mean, once, under the cards. */
export function CellLegend() {
  return (
    <p className="cell-legend" aria-label="What the cells say">
      {(Object.keys(STANDS_WORD) as Stands[]).map(state => (
        <span key={state}>
          <Cell {...CELL[state]} label={STANDS_WORD[state]} /> {STANDS_WORD[state]}
        </span>
      ))}
    </p>
  )
}

/** The chat a story runs in - its task at work's, else the newest of its tasks that has one. */
const chatOf = (tasks: BacklogTask[]) =>
  (tasks.find(task => task.status === 'doing' && task.conversation_id) ?? tasks.findLast(task => task.conversation_id))
    ?.conversation_id ?? null

/** A story's facts, from the record: its branch where a night's job of it had one, its chat, how it stands. */
function Facts({
  story,
  tasks,
  chats,
  away,
}: {
  story: Story
  tasks: BacklogTask[]
  chats: Record<string, string>
  away?: Away | null
}) {
  const ids = new Set(tasks.map(task => task.id))
  const branches = [
    ...new Set(
      (away?.jobs ?? []).flatMap(job => (ids.has(job.task_id ?? '') && job.branch?.name ? [job.branch.name] : [])),
    ),
  ]
  const chat = chatOf(tasks)
  const done = tasks.filter(task => task.status === 'done').length
  return (
    <dl className="todo-facts">
      {branches.length > 0 && (
        <>
          <dt>Branch</dt>
          <dd className="mono">{branches.join(', ')}</dd>
        </>
      )}
      {chat && chats[chat] && (
        <>
          <dt>Chat</dt>
          <dd>“{chats[chat]}”, in a topic of its own</dd>
        </>
      )}
      <dt>State</dt>
      <dd>
        {STATE_WORD[story.state]}, {done} of {tasks.length} tasks done
      </dd>
    </dl>
  )
}

/** A story's own buttons: Continue in chat, ☾ Do tonight, Close story (or Open it again), and ⋯ for Rename and Delete. */
function StoryActs({
  story,
  tasks,
  listed,
  projectId,
  actions,
  onOpenChat,
}: {
  story: Story
  tasks: BacklogTask[]
  listed: BacklogTask[]
  projectId?: string
  actions: TreeActions
  onOpenChat: (conversationId: string) => void
}) {
  const { busy, error, ask } = useAsk()
  const menu = `story-${story.id}-more`
  const { doing, setDoing, done: back } = useDoing(menu)
  const chat = chatOf(tasks)
  const tonight = tasks.filter(task => task.status === 'todo' && !task.place).map(task => task.id)
  const close = (closed: boolean) => void ask(() => actions.onStory(story.id, { closed }))
  return (
    <div className="todo-panel-acts">
      {doing === 'rename' && (
        <Rename
          id={`story-${story.id}-name`}
          title={story.title}
          onSave={title => void ask(() => actions.onStory(story.id, { title })).then(ok => ok && back())}
          onCancel={back}
        />
      )}
      {chat && (
        <button type="button" className="btn btn-small btn-primary" onClick={() => onOpenChat(chat)}>
          Continue in chat
        </button>
      )}
      {tonight.length > 0 && <AwayButton projectId={projectId} pick={tonight} label="Do tonight" />}
      {closable(story, listed) && (
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => close(true)}>
          Close story
        </button>
      )}
      {story.state === 'done' && (
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => close(false)}>
          Open it again
        </button>
      )}
      {doing === 'delete' ? (
        <Deleting
          title={story.title}
          busy={busy}
          onDelete={() => void ask(() => actions.onDeleteStory(story.id))}
          onKeep={back}
        />
      ) : (
        <RowMenu
          id={menu}
          name={story.title}
          items={[
            ['Rename', () => setDoing('rename')],
            ['Delete', () => setDoing('delete')],
          ]}
        />
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}

/** Its open tasks ticked at once, for Do in chat - all of them, or none. */
function TickAll({
  card,
  selected,
  onSelect,
}: {
  card: Card
  selected: Set<string>
  onSelect: (taskIds: string[], on: boolean) => void
}) {
  const open = card.tasks.filter(tickable).map(task => task.id)
  if (!open.length) return null
  return (
    <label className="todo-tick-all">
      <input
        type="checkbox"
        aria-label={card.story ? `Tick the story ${card.story.title}` : 'Tick the tasks of no story'}
        checked={open.every(one => selected.has(one))}
        onChange={e => onSelect(open, e.target.checked)}
      />{' '}
      Tick its open tasks
    </label>
  )
}

interface PanelProps {
  card: Card
  /** The task it was opened at: its row takes the focus, in view. */
  at?: string
  /** Every task on To-do (proposals left out): whether the story may be closed. */
  listed: BacklogTask[]
  chats: Record<string, string>
  away?: Away | null
  projectId?: string
  actions: TreeActions
  selected: Set<string>
  onSelect: (taskIds: string[], on: boolean) => void
  onOpenChat: (conversationId: string) => void
  onClose: () => void
  /** Its tasks' rows, as To-do draws them, and the dock under them. */
  children: ReactNode
}

/**
 * A story opened (0.1.10), over To-do: its branch, chat and state; its notebook, each note with when and who wrote it;
 * Continue in chat, ☾ Do tonight, Close story; its tasks, each with all it can do. It takes the focus; its Close and
 * Esc - not one inside a form, which is the form's - close it.
 */
export function StoryPanel({
  card,
  at,
  listed,
  chats,
  away,
  projectId,
  actions,
  selected,
  onSelect,
  onOpenChat,
  onClose,
  children,
}: PanelProps) {
  const id = useId()
  const box = useRef<HTMLElement>(null)
  useEffect(() => {
    const row = at ? document.getElementById(`task-${at}-title`)?.closest('button') : null
    ;(row ?? box.current)?.focus()
    row?.scrollIntoView?.({ block: 'center' })
  }, [card.key, at])
  const title = titleOf(card)
  const onKey = (event: KeyboardEvent) => {
    if (event.key === 'Escape' && !(event.target as Element).closest('form')) onClose()
  }
  return (
    <aside ref={box} id={PANEL} tabIndex={-1} className="todo-panel" aria-labelledby={`${id}-title`} onKeyDown={onKey}>
      <div className="todo-panel-head">
        <div>
          <span className="muted">{card.story ? 'Story' : 'Tasks of no story'}</span>
          <h3 id={`${id}-title`}>{title}</h3>
        </div>
        <button type="button" className="icon-btn" aria-label={`Close ${title}`} onClick={onClose}>
          <X size={16} />
        </button>
      </div>
      {card.story && <Facts story={card.story} tasks={card.tasks} chats={chats} away={away} />}
      {card.story && card.story.notes.length > 0 && (
        <section className="todo-book" aria-label="The job's notebook">
          <h4>The job’s notebook</h4>
          <NotebookNotes notes={card.story.notes} of="story" />
        </section>
      )}
      {card.story && (
        <StoryActs
          story={card.story}
          tasks={card.tasks}
          listed={listed}
          projectId={projectId}
          actions={actions}
          onOpenChat={onOpenChat}
        />
      )}
      <TickAll card={card} selected={selected} onSelect={onSelect} />
      {children}
    </aside>
  )
}
