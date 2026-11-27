import { X } from '@phosphor-icons/react'
import { type KeyboardEvent, type ReactNode, type RefObject, useEffect, useId, useRef, useState } from 'react'
import type { Away, BacklogTask, Story } from '../api/types'
import { useAsk } from '../memory/useAsk'
import { CELL, STANDS_WORD, type Stands, taskStands } from '../ready/cells'
import { Cell } from '../shell/Cell'
import { NotebookNotes } from './Notebook'
import { AwayButton, Deleting, Rename, RowMenu, STATE_WORD, type TreeActions, closable, useDoing } from './TodoParts'
import { type Card, cardId, tickable } from './tree'

/** The panel's element: what an open card controls. */
const PANEL = 'todo-panel'
const titleOf = (card: Card) => card.story?.title ?? 'Without a story'

/** Each task of a card as it stands, and its word; `pushes`: the tasks whose push the night parked for you. */
const standsOf = (card: Card, pushes: Set<string>) =>
  card.tasks.map(task => ({ task, said: taskStands(task, pushes.has(task.id)) }))

/**
 * A story as a card (0.1.10): its name, how many of all its tasks are done (`all`: a filter shows some), a cell for each
 * task shown - a row of honeycomb - and those tasks, each with its cell and how it stands. The card is one button: it
 * opens the story's panel. Its name says the story and its count; its tasks, each with its word, describe it.
 */
function StoryCard({
  card,
  all,
  open,
  onOpen,
  pushes,
}: {
  card: Card
  all: BacklogTask[]
  open: boolean
  onOpen: () => void
  pushes: Set<string>
}) {
  const done = all.filter(task => task.status === 'done').length
  const stands = standsOf(card, pushes)
  const title = titleOf(card)
  const id = cardId(card.key)
  return (
    <li>
      <button
        id={id}
        type="button"
        className="todo-card"
        aria-expanded={open}
        aria-controls={open ? PANEL : undefined}
        aria-label={`${title}: ${done} of ${all.length} done`}
        aria-describedby={`${id}-tasks`}
        onClick={onOpen}
      >
        <span className="todo-card-line">
          <span className="todo-card-name">{title}</span>
          <span className="muted">
            {done} / {all.length}
          </span>
        </span>
        <span className="cell-comb">
          {stands.map(({ task, said: [state, word] }) => (
            <Cell key={task.id} {...CELL[state]} label={`${task.title}: ${word}`} big hidden />
          ))}
        </span>
        <span id={`${id}-tasks`} className="todo-card-tasks">
          {stands.length === 0 && <span className="muted">No task yet</span>}
          {stands.map(({ task, said: [state, word] }) => (
            <span key={task.id} className="todo-card-task">
              <Cell {...CELL[state]} label={word} hidden />
              <span className="todo-card-title">{task.title}</span>
              {/* (Said apart to a screen reader: "title: word;", as the eye sees them apart.) */}
              <span className="visually-hidden">:</span>{' '}
              <span className={`todo-card-state todo-is-${state}`}>{word}</span>
              <span className="visually-hidden">;</span>{' '}
            </span>
          ))}
        </span>
      </button>
    </li>
  )
}

/** To-do's stories as cards, and its tasks of no story as one more; one open at a time. `whole`: all of a card's tasks,
 *  whatever a filter shows - what it counts. */
export function StoryCards({
  cards,
  whole,
  openKey,
  onOpen,
  pushes,
}: {
  cards: Card[]
  whole: (card: Card) => BacklogTask[]
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
          all={whole(card)}
          open={openKey === card.key}
          onOpen={() => onOpen(openKey === card.key ? null : card.key)}
          pushes={pushes}
        />
      ))}
    </ul>
  )
}

/** What the cells mean, once, under the cards: each cell with its word - the word is what a screen reader says. */
export function CellLegend() {
  return (
    <p className="cell-legend">
      {(Object.keys(STANDS_WORD) as Stands[]).map(state => (
        <span key={state}>
          <Cell {...CELL[state]} label={STANDS_WORD[state]} hidden /> {STANDS_WORD[state]}
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
          <dt>Night branch</dt>
          <dd className="mono">{branches.join(', ')}</dd>
        </>
      )}
      {chat && chats[chat] && (
        <>
          <dt>Chat</dt>
          <dd>“{chats[chat]}”</dd>
        </>
      )}
      <dt>State</dt>
      <dd>
        {STATE_WORD[story.state]}, {done} of {tasks.length} tasks done
      </dd>
    </dl>
  )
}

/** A story's own buttons: Continue in chat, ☾ Do tonight, Close story (or Open it again), and ⋯ for Rename and Delete.
 *  `tasks`: all of its tasks, whatever a filter shows. */
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

/** The window where the halves stand one under the other: there the panel takes the window, a modal. */
const NARROW = '(max-width: 980px)'

/** Whether the window is narrow now - and again as it is resized. */
function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => window.matchMedia?.(NARROW).matches ?? false)
  useEffect(() => {
    const query = window.matchMedia?.(NARROW)
    const heard = () => setNarrow(query?.matches ?? false)
    query?.addEventListener?.('change', heard)
    return () => query?.removeEventListener?.('change', heard)
  }, [])
  return narrow
}

/**
 * While the panel is open, what it lies over cannot be reached: the rest of To-do (its cards to its dock) is inert -
 * and, `modal` (a narrow window, the panel the window's), everything else on the page too. What comes into To-do after
 * it opened - a draft's tree, the tasks the Orchestrator turned down - is made inert as it comes; not what opens over
 * the page meanwhile (Ctrl+K, the folder browser, Ready for you's panel), which must be reached. As it closes only what
 * it made inert is put back.
 */
function useInertAround(box: RefObject<HTMLElement | null>, modal: boolean) {
  useEffect(() => {
    const panel = box.current
    if (!panel) return
    // Each parent whose children but one are shut, and that one: the panel, then (modal) each of its ancestors.
    const around: [Element | null, Element][] = [[panel.parentElement, panel]]
    for (let at = panel.parentElement; modal && at && at !== document.body; at = at.parentElement)
      around.push([at.parentElement, at])
    const made = new Set<Element>()
    const shut = (levels: typeof around) => {
      for (const [parent, keep] of levels)
        for (const one of Array.from(parent?.children ?? []))
          if (one !== keep && !one.hasAttribute('inert')) {
            one.setAttribute('inert', '')
            made.add(one)
          }
    }
    shut(around)
    const watch = new MutationObserver(() => shut(around.slice(0, 1)))
    if (panel.parentElement) watch.observe(panel.parentElement, { childList: true })
    return () => {
      watch.disconnect()
      made.forEach(one => one.removeAttribute('inert'))
    }
  }, [box, modal])
}

/** The panel's elements a Tab goes to, in order. */
const tabbable = (box: HTMLElement) =>
  Array.from(
    box.querySelectorAll<HTMLElement>('a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])'),
  ).filter(one => !one.matches(':disabled') && !one.closest('[inert], [hidden]'))

/** A modal's Tab goes round within it: from its last element to its first, and back with Shift+Tab. */
function keepTab(event: KeyboardEvent, box: HTMLElement) {
  const all = tabbable(box)
  const [first, last] = [all[0], all.at(-1)]
  const at = document.activeElement
  if (!first || !last) return
  if (event.shiftKey && (at === first || at === box)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && at === last) {
    event.preventDefault()
    first.focus()
  }
}

interface PanelProps {
  card: Card
  /** All of its tasks, whatever a filter shows: its facts and buttons are of the whole story. */
  all: BacklogTask[]
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
  /** Something open over it must be reached - the settings: the page around it is not shut, modal or not. */
  covered?: boolean
  /** Its tasks' rows, as To-do draws them, and the dock under them. */
  children: ReactNode
}

/**
 * A story opened (0.1.10), over To-do: its branch, chat and state; its notebook, each note with when and who wrote it;
 * Continue in chat, ☾ Do tonight, Close story; its tasks, each with all it can do. It takes the focus; its Close and
 * Esc - not one inside a form, which is the form's - close it. What it lies over is inert while it is open; on a narrow
 * window it is a modal dialog over the page, its Tab going round within it.
 */
export function StoryPanel({
  card,
  all,
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
  covered = false,
  children,
}: PanelProps) {
  const id = useId()
  const box = useRef<HTMLElement>(null)
  const modal = useNarrow()
  useInertAround(box, modal && !covered)
  useEffect(() => {
    const row = at ? document.getElementById(`task-${at}-title`)?.closest('button') : null
    ;(row ?? box.current)?.focus()
    row?.scrollIntoView?.({ block: 'center' })
  }, [card.key, at])
  const title = titleOf(card)
  const onKey = (event: KeyboardEvent) => {
    if (event.key === 'Escape' && !(event.target as Element).closest('form')) onClose()
    if (event.key === 'Tab' && modal && box.current) keepTab(event, box.current)
  }
  return (
    <aside
      ref={box}
      id={PANEL}
      tabIndex={-1}
      className="todo-panel"
      role={modal ? 'dialog' : undefined}
      aria-modal={modal || undefined}
      aria-labelledby={`${id}-title`}
      onKeyDown={onKey}
    >
      <div className="todo-panel-head">
        <div>
          <span className="muted">{card.story ? 'Story' : 'Tasks of no story'}</span>
          <h3 id={`${id}-title`}>{title}</h3>
        </div>
        <button type="button" className="icon-btn" aria-label={`Close ${title}`} onClick={onClose}>
          <X size={16} />
        </button>
      </div>
      {card.story && <Facts story={card.story} tasks={all} chats={chats} away={away} />}
      {card.story && card.story.notes.length > 0 && (
        <section className="todo-book" aria-label="The job's notebook">
          <h4>The job’s notebook</h4>
          <NotebookNotes notes={card.story.notes} of="story" />
        </section>
      )}
      {card.story && (
        <StoryActs
          story={card.story}
          tasks={all}
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
