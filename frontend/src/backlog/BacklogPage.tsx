import { DotsSixVertical } from '@phosphor-icons/react'
import { Fragment, useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { type SpawnDecision } from '../agents/SpawnApproval'
import type {
  Away,
  BacklogDrafter,
  BacklogDraft,
  BacklogTask,
  BacklogTaskChange,
  NewBacklogTask,
  Provider,
  Story,
  TodoTreeAdded,
  TodoTreeIn,
} from '../api/types'
import { count } from '../board/columns'
import { useAsk } from '../memory/useAsk'
import { paidOf, type Paid } from '../models/cards'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { usePanel } from '../shell/usePanel'
import { TodoDock } from './Dock'
import { DraftTree } from './DraftTree'
import { NotebookButton } from './Notebook'
import { StoryPicker } from './StoryPicker'
import { CellLegend, StoryCards, StoryPanel } from './StoryCards'
import { TaskMarks, TodoBar, type TreeActions } from './TodoParts'
import { type Card, cardId, cardsOf, useTreeView, wholeOf } from './tree'

type Priority = BacklogTask['priority']
type Status = BacklogTask['status']

const PRIORITIES: Priority[] = ['high', 'normal', 'low']
// What the user may set; "proposed" is only ever an agent's.
const STATUSES: Exclude<Status, 'proposed'>[] = ['todo', 'doing', 'review', 'done', 'blocked']
const STATUS_WORD: Record<Status, string> = {
  proposed: 'proposed',
  todo: 'todo',
  doing: 'doing',
  review: 'done?',
  done: 'done',
  blocked: 'blocked',
}
const FIELD_WORD: Record<string, string> = {
  title: 'Title',
  detail: 'Detail',
  criteria: 'Done when',
  priority: 'Priority',
  status: 'Status',
  kind: 'Type',
}

/** Where adding a proposal puts it (review M2): its story, "(new)" where an agent's proposal opened it, and a bug said. */
const placeOf = (task: BacklogTask) =>
  [
    task.story_title && `In story “${task.story_title}”${task.story_by === 'agent' ? ' (new)' : ''}`,
    task.kind === 'bug' && 'bug',
  ]
    .filter(Boolean)
    .join(' · ')

interface Props {
  backlog: BacklogTask[] | null
  error: string | null
  /** Who "Write it with the Hive keeper" asks, or why nobody can; null until read. */
  drafter?: BacklogDrafter | null
  providers: Provider[]
  /** The project's night while you're away (slice 106): the one that runs, else its last. */
  away?: Away | null
  /** Each throws ApiError; the backlog is read again after it. */
  onAdd: (task: NewBacklogTask) => Promise<void>
  /** What is typed, written as stories and tasks by a model asked once; nothing is saved. Throws ApiError. */
  onDraft?: (text: string) => Promise<BacklogDraft>
  /** A draft's stories and tasks (or a part of them) added at once. Throws ApiError. */
  onAddTree?: (tree: TodoTreeIn) => Promise<TodoTreeAdded>
  /** A new chat in the project, with this as its first message, opened. Throws ApiError. */
  onPlan?: (message: string) => Promise<void>
  onChange: (taskId: string, change: BacklogTaskChange) => Promise<void>
  onDelete: (taskId: string) => Promise<void>
  onDecide: (taskId: string, decision: SpawnDecision) => Promise<void>
  /** Do in chat: the ticked tasks wait in this chat's queue (null: a new chat's), which opens. Throws ApiError. */
  onDoInChat?: (taskIds: string[], conversationId: string | null) => Promise<void>
  onOpen: (conversationId: string) => void
  /** 0.1.8: the project's stories (null until read), its chats' titles by id, and its id (☾ Away's chat is of it). */
  stories?: Story[] | null
  chats?: Record<string, string>
  projectId?: string
  /** A story changed or deleted, or a new one made; each throws ApiError. None: the page changes none. */
  tree?: TreeTools
}

type TreeTools = TreeActions & { onNewStory: (title: string) => Promise<Story> }
const unwired = async (): Promise<never> => {
  throw new Error('stories are not changed here')
}
const NO_TREE: TreeTools = {
  onStory: unwired,
  onDeleteStory: unwired,
  onNewStory: unwired,
}

/** What a task's form needs to choose its story: the project's stories, and a new one made by its title. */
type StoryChoice = { stories: Story[]; onNewStory: (title: string) => Promise<string> }

type FieldsProps = { id: string; task: NewBacklogTask; onTask: (task: NewBacklogTask) => void }

/** Priority, detail and criteria: what a task says beyond its title, new or edited. */
function MoreFields({ id, task, onTask }: FieldsProps) {
  return (
    <>
      <div className="field">
        <label htmlFor={`${id}-priority`}>Priority</label>
        <select
          id={`${id}-priority`}
          className="input backlog-status"
          value={task.priority}
          onChange={e => onTask({ ...task, priority: e.target.value as Priority })}
        >
          {PRIORITIES.map(p => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor={`${id}-detail`}>Detail</label>
        <textarea
          id={`${id}-detail`}
          className="input"
          rows={2}
          maxLength={4000}
          value={task.detail ?? ''}
          onChange={e => onTask({ ...task, detail: e.target.value })}
        />
      </div>
      <div className="field">
        <label htmlFor={`${id}-criteria`}>Done when (optional)</label>
        <textarea
          id={`${id}-criteria`}
          className="input"
          rows={2}
          maxLength={4000}
          value={task.criteria ?? ''}
          onChange={e => onTask({ ...task, criteria: e.target.value })}
        />
      </div>
    </>
  )
}

/** A task's story and whether it is a task or a bug (0.1.8). */
function StoryFields({ id, task, onTask, stories, onNewStory }: FieldsProps & StoryChoice) {
  return (
    <>
      <StoryPicker
        id={id}
        value={task.story_id ?? null}
        stories={stories}
        onChange={story_id => onTask({ ...task, story_id })}
        onNew={onNewStory}
      />
      <div className="field">
        <label htmlFor={`${id}-kind`}>Type</label>
        <select
          id={`${id}-kind`}
          className="input backlog-status"
          value={task.kind}
          onChange={e => onTask({ ...task, kind: e.target.value as NewBacklogTask['kind'] })}
        >
          <option value="task">task</option>
          <option value="bug">bug</option>
        </select>
      </div>
    </>
  )
}

/** The fields of a task being edited. */
function TaskFields({ id, task, onTask }: FieldsProps) {
  return (
    <>
      <div className="field">
        <label htmlFor={`${id}-title`}>Title</label>
        {/* (Opened from ⋯: the focus comes here - or to Waits for, focused after it, when that opened it.) */}
        <input
          id={`${id}-title`}
          className="input"
          autoFocus
          required
          maxLength={200}
          value={task.title}
          onChange={e => onTask({ ...task, title: e.target.value })}
        />
      </div>
      <MoreFields id={id} task={task} onTask={onTask} />
    </>
  )
}

const EMPTY: NewBacklogTask = { title: '', detail: '', criteria: '', priority: 'normal', kind: 'task' }
// An empty detail or criteria is none.
const cleaned = (task: NewBacklogTask) => ({
  ...task,
  title: task.title.trim(),
  detail: task.detail?.trim() || null,
  criteria: task.criteria?.trim() || null,
})

/** "Plan it in a chat": the Lead is asked for the Hive keeper, whose tasks wait on cards as any agent's proposal does. */
export const PLAN_ASK = 'Have the Hive keeper break this into To-do tasks: '
/** What the Hive keeper does, under its button: its name does not say it. */
export const HIVE_KEEPER_DOES =
  'The Hive keeper keeps the To-do list: it turns your note into stories and their tasks, each with what makes it done.'
const COSTS: Record<Paid, string> = {
  subscription: 'one request on your plan',
  'API key': 'one request you pay for',
  'this machine': 'one request on this machine, free',
}

type AddProps = Pick<Props, 'onAdd'> & StoryChoice

/** Who writes the drafts and what that costs - or why nobody can, or that it is not read yet. */
const whoWrites = (drafter: BacklogDrafter | null | undefined, asked: Provider | undefined) =>
  drafter?.why ??
  (asked
    ? `${asked.name} (${drafter?.model_id ?? asked.default_model ?? 'its default model'}) writes them: ${COSTS[paidOf(asked)]}. Nothing is saved until you add it.`
    : 'Who writes them is not read yet.')

/** One line: a title, then Enter. The rest of the task opens under it once a title is typed; Esc closes it. */
function AddTask({ onAdd, stories, onNewStory }: AddProps) {
  const { busy, error, ask } = useAsk()
  const [task, setTask] = useState(EMPTY)
  const [folded, setFolded] = useState(false)
  function submit(event: FormEvent) {
    event.preventDefault()
    // Emptied only if nothing was typed since: the list shows the task before the add is through
    // (the board is read too), and the next title may be typed by then.
    void ask(() => onAdd(cleaned(task))).then(done => done && setTask(now => (now === task ? EMPTY : now)))
  }
  const change = (next: NewBacklogTask) => {
    setFolded(false)
    setTask(next)
  }
  return (
    <form
      className="backlog-add"
      aria-label="Add a task"
      onSubmit={submit}
      onKeyDown={e => e.key === 'Escape' && setFolded(true)}
    >
      <div className="backlog-add-line">
        <span aria-hidden="true">＋</span>
        <label className="visually-hidden" htmlFor="new-task-title">
          Title
        </label>
        <input
          id="new-task-title"
          className="backlog-add-input"
          placeholder="Add a task — title, then Enter"
          required
          maxLength={200}
          value={task.title}
          onChange={e => change({ ...task, title: e.target.value })}
        />
      </div>
      {task.title.trim() && !folded && (
        <>
          <MoreFields id="new-task" task={task} onTask={change} />
          <StoryFields id="new-task" task={task} onTask={change} stories={stories} onNewStory={onNewStory} />
          <div className="memory-actions">
            <button type="submit" className="btn btn-small btn-primary" disabled={busy}>
              Add task
            </button>
          </div>
        </>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </form>
  )
}

type NoteProps = Pick<Props, 'onDraft' | 'onPlan' | 'onAddTree' | 'providers'> & {
  drafter: BacklogDrafter | null | undefined
}

/**
 * The rough note (6 Nov; 0.1.8 as a tree; 0.1.10 always in sight, under the cards): what you type is split by the Hive
 * keeper, a model asked once, into stories and their tasks - shown under it to change, each part added by your word;
 * or planned in a chat.
 */
function HiveNote({ onDraft, onPlan, onAddTree, providers, drafter }: NoteProps) {
  const drafting = useAsk()
  const [note, setNote] = useState('')
  const [draft, setDraft] = useState<BacklogDraft | null>(null)
  const asked = providers.find(one => one.id === drafter?.provider_id)
  const text = note.trim()
  const write = (event: FormEvent) => {
    event.preventDefault()
    if (onDraft) void drafting.ask(async () => setDraft(await onDraft(text)))
  }
  return (
    <>
      <form className="backlog-add hive-note" aria-label="Your rough note" onSubmit={write}>
        <div className="field">
          <label htmlFor="hive-note">Your rough note</label>
          <textarea
            id="hive-note"
            className="input"
            rows={3}
            placeholder="Write what you have in mind, roughly: “reports as PDF too, and not stuck on a big file”"
            maxLength={4201}
            value={note}
            onChange={e => setNote(e.target.value)}
          />
        </div>
        <div className="memory-actions">
          {onDraft && (
            <button
              type="submit"
              className="btn btn-small btn-primary"
              aria-describedby="draft-who"
              disabled={!text || !asked || !!drafter?.why || drafting.busy}
            >
              {drafting.busy ? 'Splitting…' : 'Split into tasks'}
            </button>
          )}
          {onPlan && (
            <button
              type="button"
              className="btn btn-small"
              disabled={!text || drafting.busy}
              onClick={() => void drafting.ask(() => onPlan(PLAN_ASK + text))}
            >
              Plan it in a chat
            </button>
          )}
        </div>
        {onDraft && (
          <p id="draft-who" className="muted">
            {HIVE_KEEPER_DOES} {whoWrites(drafter, asked)}
          </p>
        )}
        {drafting.error && (
          <div role="alert" className="alert">
            {drafting.error}
          </div>
        )}
      </form>
      {draft && onAddTree && (
        // (A new draft is a new tree: what was changed in the one before is not carried over.)
        <DraftTree
          key={JSON.stringify(draft)}
          draft={draft}
          onAdd={onAddTree}
          onDrop={() => setDraft(null)}
          taskFields={(id, task, onTask) => <MoreFields id={id} task={task} onTask={onTask} />}
        />
      )}
    </>
  )
}

/** What a task says beyond its title. */
function Said({ task }: { task: Pick<BacklogTask, 'detail' | 'criteria'> }) {
  return (
    <>
      {task.detail && <p className="memory-text backlog-pre">{task.detail}</p>}
      {task.criteria && (
        <div className="memory-text">
          <span className="kicker">Done when</span>
          <p className="backlog-pre">{task.criteria}</p>
        </div>
      )}
    </>
  )
}

/** Where a task stands in a run of the backlog (K-symphony), in a few words; null: its status says it. */
function runState(task: BacklogTask, listed: BacklogTask[]): string | null {
  if (task.status === 'blocked' && task.stuck) return `stuck: ${task.stuck}`
  if (task.status === 'doing') return task.waiting ? 'waiting for you' : 'running'
  // Its work not in the project yet (B-78): nothing to call done before it is taken in or thrown away.
  if (task.status === 'review' && task.not_in)
    return 'Its work is not in the project yet: take it in or discard it in its chat.'
  if (task.status !== 'todo') return null
  const waits = waitsFor(task, listed)
  if (waits.length) return `waits for: ${waitWords(waits)}`
  return task.place != null ? 'queued in its chat' : null
}

/** A task's state at a glance, on the right of its row: its word, and the tag's colour. */
function stateTag(task: BacklogTask): [string, string] {
  if (task.status === 'review' && task.not_in) return ['needs you · Take in', ' tag-warn']
  if (task.status === 'doing') return task.waiting ? ['needs you', ' tag-warn'] : ['running', ' tag-accent']
  if (task.status === 'blocked') return [task.stuck ? 'stuck' : 'blocked', ' tag-del']
  if (task.status === 'done') return ['done', ' tag-ok']
  return [task.status === 'todo' && task.place != null ? 'queued' : STATUS_WORD[task.status], '']
}

// Done, not "done?": work waiting for Take in is not in the project yet.
const waitsFor = (task: BacklogTask, listed: BacklogTask[]) =>
  listed.filter(one => task.after.includes(one.id) && one.status !== 'done')
// B-349: one at "done?" moves on only by your word, so it says so - Done on its row, or first Take in.
const reviewWaits = (one: BacklogTask) =>
  one.not_in ? 'waiting for you - Take in' : 'done? - its Done under Waiting for your word'
const waitWords = (waits: BacklogTask[]) =>
  waits.map(one => (one.status === 'review' ? `${one.title} (${reviewWaits(one)})` : one.title)).join(', ')

// A field's value as the page says it: a status in its words ("done?" for review).
const shown = (field: string, value: unknown) =>
  field === 'status' ? STATUS_WORD[value as Status] : String(value ?? 'none')

/** One of what waits for your word, as it is listed: its kind, its row's name and second line, and its buttons. */
interface Wait {
  key: string
  task: BacklogTask
  kind: 'new task' | 'done?' | 'change'
  name: string
  line: string
  buttons: [label: string, run: () => Promise<void>][]
  /** A proposed task's Edit: its title and detail changed, then it is added. */
  edit?: (fields: { title: string; detail: string | null }) => Promise<void>
}

/** A task the Scout proposed and the Orchestrator said no to at Full auto: under "Decided for you" in its chat, not waiting here. */
const declined = (task: BacklogTask) => task.status === 'proposed' && task.po?.lead === 'no'

/** What waits for your word, one row each, in the page's order: proposed tasks, then "done?", then changes. */
function waitsOf(tasks: BacklogTask[], onDecide: Props['onDecide'], onChange: Props['onChange']): Wait[] {
  const of = (kind: Wait['kind'], task: BacklogTask): Wait => {
    const decide = (decision: SpawnDecision) => () => onDecide(task.id, decision)
    if (kind === 'new task')
      return {
        key: `${task.id}:new`,
        task,
        kind,
        name: `Proposed task: ${task.title}`,
        // (Who proposed it is known only as "an agent", but for the Scout's at a turn's end, with the words it came from.)
        line: [
          task.po
            ? `Proposed by the Scout, from: “${task.po.why}”`
            : task.created_by === 'agent' && 'Proposed by an agent',
          // (As a text that read like orders is told everywhere: the rule, never the text - here the task is the text.)
          task.po?.injection?.length &&
            `Its words look like they try to give the agent orders (rules: ${task.po.injection.map(rule => rule.replaceAll('_', ' ')).join(', ')}); read them before you add it`,
          placeOf(task),
          task.detail,
          task.criteria && `Done when: ${task.criteria}`,
        ]
          .filter(Boolean)
          .join(' · '),
        buttons: [
          // (The spec's verbs, 0.1.10: what it does to To-do, and that you do not want it.)
          ['Add to To-do', decide('approve')],
          ['Not wanted', decide('reject')],
        ],
        edit: async fields => {
          await onChange(task.id, fields)
          await onDecide(task.id, 'approve')
        },
      }
    if (kind === 'done?')
      return {
        key: `${task.id}:done`,
        task,
        kind,
        name: `Done? ${task.title}`,
        line: [
          task.assessment && `An agent’s view (an opinion): ${task.assessment}`,
          task.criteria && `Done when: ${task.criteria}`,
        ]
          .filter(Boolean)
          .join(' · '),
        buttons: [
          ['Done', () => onChange(task.id, { status: 'done' })],
          ['Not yet', () => onChange(task.id, { status: 'todo' })],
        ],
      }
    return {
      key: `${task.id}:change`,
      task,
      kind,
      name: `Proposed change: ${task.title}`,
      // (The agent's words, shown as such.)
      line: Object.entries(task.pending ?? {})
        .map(
          ([field, value]) =>
            `${FIELD_WORD[field] ?? field} ${shown(field, task[field as keyof BacklogTask])} → ${shown(field, value)}`,
        )
        .join(' · '),
      buttons: [
        ['Change', decide('approve')],
        ['Reject', decide('reject')],
      ],
    }
  }
  return [
    ...tasks.filter(task => task.status === 'proposed' && !declined(task)).map(task => of('new task', task)),
    // One whose work is not in the project yet is not asked "done?": it says so on its row in the list.
    ...tasks.filter(task => task.status === 'review' && !task.not_in).map(task => of('done?', task)),
    ...tasks.filter(task => task.pending).map(task => of('change', task)),
  ]
}

/** The Scout's proposals the Orchestrator rejected at Full auto, folded: still yours to add. */
function Declined({ backlog, onDecide }: Pick<Props, 'backlog' | 'onDecide'>) {
  const tasks = (backlog ?? []).filter(declined)
  if (tasks.length === 0) return null
  return (
    <details className="memory-section backlog-declined">
      <summary className="kicker">Rejected by the Orchestrator ({tasks.length})</summary>
      <div className="backlog-rows">
        {tasks.map(task => (
          <DeclinedRow key={task.id} task={task} onDecide={onDecide} />
        ))}
      </div>
    </details>
  )
}

function DeclinedRow({ task, onDecide }: { task: BacklogTask } & Pick<Props, 'onDecide'>) {
  const { busy, error, ask } = useAsk()
  return (
    <div role="group" aria-label={`Rejected: ${task.title}`} className="backlog-row">
      <div className="backlog-row-text">
        <strong>{task.title}</strong>
        {task.po?.lead_why && <div className="backlog-sub">“{task.po.lead_why}”</div>}
        {error && (
          <div role="alert" className="alert">
            {error}
          </div>
        )}
      </div>
      <button
        type="button"
        className="btn btn-small"
        disabled={busy}
        onClick={() => void ask(() => onDecide(task.id, 'approve'))}
      >
        Add
      </button>
    </div>
  )
}

/** A row's title, which unfolds the rest of it; the rest is the row's own (it opens to show it whole). */
function Fold({
  id,
  open,
  onOpen,
  children,
}: {
  id?: string
  open: boolean
  onOpen: (open: boolean) => void
  children: ReactNode
}) {
  return (
    <button type="button" className="backlog-fold" aria-expanded={open} onClick={() => onOpen(!open)}>
      <strong id={id}>{children}</strong>
    </button>
  )
}

/** One decision's row. Its second line is never cut: what is decided is read whole before its button. */
function Decision({
  wait,
  off,
  failed,
  onOpen,
}: {
  wait: Wait
  off?: boolean
  failed?: string
  onOpen: Props['onOpen']
}) {
  const { busy, error, ask } = useAsk()
  const [editing, setEditing] = useState(false)
  const { task } = wait
  const said = error ?? failed
  return (
    // Several rows stand on the page: each is a group named by its task, so their buttons are told apart.
    <div role="group" aria-label={wait.name} className="backlog-row">
      <span className={`tag${wait.kind === 'done?' ? ' tag-ok' : wait.kind === 'change' ? ' tag-accent' : ''}`}>
        {wait.kind}
      </span>
      <div className="backlog-row-text">
        <strong>{task.title}</strong>{' '}
        <span className={`tag mono${task.priority === 'high' ? ' tag-warn' : ''}`}>{task.priority}</span>
        {wait.line && <div className="backlog-sub">{wait.line}</div>}
        {said && (
          <div role="alert" className="alert">
            {said}
          </div>
        )}
      </div>
      {wait.kind === 'done?' && task.conversation_id && (
        <button type="button" className="btn btn-small" onClick={() => onOpen(task.conversation_id ?? '')}>
          Open chat
        </button>
      )}
      {editing && wait.edit ? (
        <ProposalEdit
          task={task}
          busy={busy}
          onAdd={fields => ask(() => wait.edit!(fields))}
          onCancel={() => setEditing(false)}
        />
      ) : (
        wait.buttons.map(([label, run], i) => (
          <Fragment key={label}>
            <button
              type="button"
              className={`btn btn-small${i === 0 ? ' btn-primary' : ''}`}
              disabled={busy || off}
              onClick={() => void ask(run)}
            >
              {label}
            </button>
            {i === 0 && wait.edit && (
              <button type="button" className="btn btn-small" disabled={busy || off} onClick={() => setEditing(true)}>
                Edit
              </button>
            )}
          </Fragment>
        ))
      )}
    </div>
  )
}

/** A proposed task's Edit (6 Nov): its title and detail as you want them, then Add to To-do. */
function ProposalEdit({
  task,
  busy,
  onAdd,
  onCancel,
}: {
  task: BacklogTask
  busy: boolean
  onAdd: (fields: { title: string; detail: string | null }) => Promise<boolean>
  onCancel: () => void
}) {
  const [title, setTitle] = useState(task.title)
  const [detail, setDetail] = useState(task.detail ?? '')
  const id = `proposal-${task.id}`
  return (
    <form
      className="backlog-proposal-edit"
      onSubmit={event => {
        event.preventDefault()
        void onAdd({ title: title.trim(), detail: detail.trim() || null })
      }}
    >
      <div className="field">
        <label htmlFor={`${id}-title`}>Title</label>
        <input
          id={`${id}-title`}
          className="input"
          autoFocus
          required
          maxLength={200}
          value={title}
          onChange={e => setTitle(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor={`${id}-detail`}>Detail</label>
        <textarea
          id={`${id}-detail`}
          className="input"
          rows={2}
          maxLength={4000}
          value={detail}
          onChange={e => setDetail(e.target.value)}
        />
      </div>
      <button type="submit" className="btn btn-small btn-primary" disabled={busy || !title.trim()}>
        Add to To-do
      </button>{' '}
      <button type="button" className="btn btn-small" disabled={busy} onClick={onCancel}>
        Cancel
      </button>
    </form>
  )
}

interface WaitRowProps {
  task: BacklogTask
  onDecide: Props['onDecide']
  onChange: Props['onChange']
  onOpen: Props['onOpen']
  /** Only this one of its decisions (the list orders them by kind); left out, each of them. */
  only?: Wait['kind']
  /** Approve all is at work: its buttons wait. */
  off?: boolean
  /** Approve all's refusal of it. */
  failed?: string
}

/**
 * What waits for your word on a task, a row each - as many as the rail's badge counts for it: a task an
 * agent proposed, a change it proposed, and a task whose turn ended ("done?").
 */
export function WaitRow({ task, onDecide, onChange, onOpen, only, off, failed }: WaitRowProps) {
  return waitsOf([task], onDecide, onChange)
    .filter(wait => !only || wait.kind === only)
    .map(wait => <Decision key={wait.key} wait={wait} off={off} failed={failed} onOpen={onOpen} />)
}

interface RowProps {
  task: BacklogTask
  /** The tasks on the list: what it may wait for, and what it waits for. */
  listed: BacklogTask[]
  /** The task above and below it in the list, when they have its priority: where it can move. */
  above?: BacklogTask
  below?: BacklogTask
  /** The task being dragged, if one is. */
  dragged: BacklogTask | null
  onDrag: (task: BacklogTask | null) => void
  onChange: Props['onChange']
  onDelete: Props['onDelete']
  onOpen: Props['onOpen']
  /** 0.1.8: whether it is ticked, and its story to choose. */
  ticked: boolean
  onTick: (on: boolean) => void
  choice: StoryChoice
}

/** Whether the task being dragged may be dropped on this one: another of the same story (its story is set in Edit). */
const dropsOn = (dragged: BacklogTask | null, task: BacklogTask): dragged is BacklogTask =>
  dragged !== null && dragged.id !== task.id && dragged.story_id === task.story_id

/** A task's second line: how it stands, where its tag does not say that already, and that a change to it waits. */
const subLine = (state: ReturnType<typeof runState>, tag: string, pending: BacklogTask['pending']) =>
  [state !== tag && state, pending && 'A change to it waits under Waiting for your word'].filter(Boolean).join(' · ')

function TaskRow({ task, listed, above, below, dragged, onDrag, onChange, onDelete, onOpen, ...tree }: RowProps) {
  const { busy, error, ask } = useAsk()
  const { open: menuOpen, setOpen: setMenuOpen, close: closeMenu, button: menuButton, panel: menuPanel } = usePanel()
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<NewBacklogTask | null>(null)
  // Edit opened from "Waits for": its list takes the focus.
  const [toWaits, setToWaits] = useState(false)
  const [waits, setWaits] = useState<string[]>([])
  const others = listed.filter(one => one.id !== task.id)
  const state = runState(task, listed)
  const [tag, tone] = stateTag(task)
  // Its second line: what the tag does not say already.
  const sub = subLine(state, tag, task.pending)
  const [deleting, setDeleting] = useState(false)
  // "Keep it" was pressed: the ⋯ it brings back takes the focus.
  const [kept, setKept] = useState(false)
  const id = `task-${task.id}`
  const change = (c: BacklogTaskChange) => void ask(() => onChange(task.id, c))
  const edit = (waitsFirst: boolean) => {
    setEditing({
      title: task.title,
      detail: task.detail ?? '',
      criteria: task.criteria ?? '',
      priority: task.priority,
      kind: task.kind,
      story_id: task.story_id,
    })
    setWaits(task.after)
    setToWaits(waitsFirst)
  }
  // A menu item closes the menu first: the focus goes back to ⋯, unless what it does takes it.
  const items: [string, boolean, () => void][] = [
    ['Edit', false, () => edit(false)],
    ['Waits for', others.length === 0, () => edit(true)],
    ['Move up', !above, () => above && change({ position: above.position })],
    ['Move down', !below, () => below && change({ position: below.position + 1 })],
    ['Delete', false, () => setDeleting(true)],
  ]
  // Dropped on: the dragged task takes this one's place - and its priority, as the list is by priority first.
  const dropHere = dropsOn(dragged, task)
  /** The task being changed: its fields, what it waits for, Save and Cancel. */
  const editForm = (editing: NewBacklogTask) => (
    <form
      className="memory-edit"
      aria-label={`Edit ${task.title}`}
      // (Esc leaves it as it was, as Cancel does.)
      onKeyDown={event => event.key === 'Escape' && setEditing(null)}
      onSubmit={event => {
        event.preventDefault()
        void ask(() => onChange(task.id, { ...cleaned(editing), after: waits })).then(done => done && setEditing(null))
      }}
    >
      <TaskFields id={id} task={editing} onTask={setEditing} />
      <StoryFields id={id} task={editing} onTask={setEditing} {...tree.choice} />
      {others.length > 0 && (
        <div className="field">
          <label htmlFor={`${id}-after`}>Waits for (it starts once these are done)</label>
          <select
            id={`${id}-after`}
            className="input"
            multiple
            autoFocus={toWaits}
            size={Math.min(4, others.length)}
            value={waits}
            onChange={e => setWaits(Array.from(e.target.selectedOptions, option => option.value))}
          >
            {others.map(one => (
              <option key={one.id} value={one.id}>
                {one.title}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="memory-actions">
        <button type="submit" className="btn btn-small btn-primary" disabled={busy || !editing.title.trim()}>
          Save
        </button>
        <button type="button" className="btn btn-small" onClick={() => setEditing(null)}>
          Cancel
        </button>
      </div>
    </form>
  )
  /** Under an opened task: what it says, an agent's view of it, and its status to set. */
  const opened = () => (
    <div className="backlog-more">
      <Said task={task} />
      {task.assessment && (
        <div className="memory-side">
          {/* An opinion, never a status: done is yours to say. */}
          <span className="kicker">An agent’s view — an opinion, not a status</span>
          <q className="memory-text backlog-pre">{task.assessment}</q>
        </div>
      )}
      <div className="memory-actions">
        <label className="visually-hidden" htmlFor={`${id}-status`}>{`Status of ${task.title}`}</label>
        <select
          id={`${id}-status`}
          className="input backlog-status"
          value={task.status}
          disabled={busy || task.status === 'proposed'}
          onChange={e => change({ status: e.target.value as (typeof STATUSES)[number] })}
        >
          {task.status === 'proposed' && <option value="proposed">proposed</option>}
          {STATUSES.map(s => (
            <option key={s} value={s}>
              {STATUS_WORD[s]}
            </option>
          ))}
        </select>
      </div>
    </div>
  )

  return (
    <li
      className={`backlog-task${open ? ' backlog-open' : ''}`}
      aria-labelledby={`${id}-title`}
      onDragOver={event => dropHere && event.preventDefault()}
      onDrop={event => {
        event.preventDefault()
        if (dropHere) {
          const position =
            dragged.priority === task.priority && dragged.position < task.position ? task.position + 1 : task.position
          void ask(() => onChange(dragged.id, { position, priority: task.priority }))
        }
        onDrag(null)
      }}
    >
      {editing ? (
        editForm(editing)
      ) : (
        <div className="backlog-row">
          <TaskMarks task={task} ticked={tree.ticked} onTick={tree.onTick} />
          {/* Only the grip drags (by mouse); from the keyboard, ⋯'s Move up and Move down. */}
          <span
            className="backlog-grip muted"
            aria-hidden="true"
            draggable
            onDragStart={event => {
              event.dataTransfer.effectAllowed = 'move'
              onDrag(task)
            }}
            onDragEnd={() => onDrag(null)}
          >
            <DotsSixVertical size={14} />
          </span>
          <span className={`tag mono${task.priority === 'high' ? ' tag-warn' : ''}`}>{task.priority}</span>
          <div className="backlog-row-text">
            <Fold id={`${id}-title`} open={open} onOpen={setOpen}>
              {task.title}
            </Fold>
            {sub && (
              <div className="backlog-sub" onClick={() => setOpen(!open)}>
                {sub}
              </div>
            )}
          </div>
          <span className={`tag${tone}`}>{tag}</span>
          <NotebookButton story={{ title: task.title, notes: task.notes ?? [] }} of="task" />
          {task.conversation_id && (
            <button
              type="button"
              className="btn btn-small"
              aria-label={`Open chat · ${task.title}`}
              onClick={() => onOpen(task.conversation_id ?? '')}
            >
              Open chat
            </button>
          )}
          {deleting ? (
            <>
              {/* The second word is asked for where the first was given: it takes the focus. */}
              <button
                type="button"
                className="btn btn-small btn-danger"
                autoFocus
                disabled={busy}
                onClick={() => void ask(() => onDelete(task.id))}
              >
                {`Delete “${task.title}”`}
              </button>
              <button
                type="button"
                className="btn btn-small"
                onClick={() => {
                  setDeleting(false)
                  setKept(true)
                }}
              >
                Keep it
              </button>
            </>
          ) : (
            // After "Keep it" the focus comes back here.
            <button
              ref={menuButton}
              type="button"
              className="icon-btn"
              autoFocus={kept}
              aria-label={`${task.title}: more`}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              onClick={() => (menuOpen ? closeMenu() : setMenuOpen(true))}
            >
              ⋯
            </button>
          )}
          {menuOpen && (
            <div
              ref={menuPanel}
              tabIndex={-1}
              className="allow-list-panel msg-menu"
              role="menu"
              aria-label={`${task.title}: more`}
            >
              {items.map(([label, off, run]) => (
                <button
                  key={label}
                  type="button"
                  role="menuitem"
                  disabled={off || busy}
                  onClick={() => {
                    closeMenu()
                    run()
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      {open && !editing && opened()}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </li>
  )
}

/** Where To-do was asked to open (0.1.10): at a task's row - its card's panel open at it -, else at its own heading. */
export interface TodoAsked {
  task?: string
  n: number
}

/** An ask to open To-do, taken once its list is read: the card of the task asked opens at its row; else the heading
 *  takes the focus, in view. */
function useAsked(asked: TodoAsked | null | undefined, cards: Card[] | null, open: (key: string, at: string) => void) {
  const [taken, setTaken] = useState(0)
  useEffect(() => {
    if (!asked || asked.n === taken || !cards) return
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTaken(asked.n)
    const card = asked.task ? cards.find(one => one.tasks.some(task => task.id === asked.task)) : undefined
    if (card && asked.task) return open(card.key, asked.task)
    const head = document.getElementById('todo-head')
    head?.scrollIntoView?.({ block: 'start' })
    head?.focus()
  }, [asked, taken, cards, open])
}

/**
 * The card whose panel is open, and where the focus goes as it closes: back on its card - or, the card gone from under
 * it (its story deleted, closed under a filter), on To-do's heading; the panel does not open again of itself. `read`:
 * the list is read, so a card not found is gone. (The focus moves once the panel is gone: what it lay over is inert
 * until then.)
 */
function useOpened(cards: Card[], read: boolean) {
  const [opened, setOpened] = useState<{ key: string; at?: string } | null>(null)
  const [back, setBack] = useState<string | null>(null)
  const card = cards.find(one => one.key === opened?.key)
  const gone = !!opened && read && !card
  useEffect(() => {
    if (!gone) return
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOpened(null)
    setBack('todo-head')
  }, [gone])
  useEffect(() => {
    if (!back || card) return
    document.getElementById(back)?.focus()
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setBack(null)
  }, [back, card])
  const open = useCallback((key: string, at?: string) => setOpened({ key, at }), [])
  const close = () => {
    if (opened) setBack(cardId(opened.key))
    setOpened(null)
  }
  return { card, at: opened?.at, open, close }
}

/** How the ticked tasks run, and what it runs and spends: in sight, never behind an ⓘ. */
function TodoNotes() {
  return (
    <>
      <div className="muted memory-hint">
        Open a story, tick its tasks and press Do in chat: they run in that chat, one by one; you decide when each is
        done.{' '}
        <Hint doc={GUIDE.todoInChat}>
          The ticked tasks wait in the chat’s queue, above its message box, and run there one by one - your own message
          still goes first. Each story goes into a topic of its own, where its tasks go on in one session; a task of no
          story gets a topic of its own. A task runs at its chat’s level, on its chat’s model, and asks on cards there.
          A task that waits for others (⋯, Waits for) starts once they are done. When its work ends, the chat asks
          “Done?”. The Hive keeper and the Scout can propose tasks and changes; they wait under Waiting for your word.
          Going away? ☾ Away works through the tasks you tick, each in a copy of its own, until you are back.
        </Hint>
      </div>
      <div id="backlog-rules" className="muted memory-hint">
        A task not finished gets one fix round; still not, it is stuck and the next goes on. A stop, a restart or the
        month’s budget stops the chat’s queue and says why there. When a task’s work ends, a fast model, if you have
        one, writes the Scout’s view of it - what of what makes it done looks met: one more request, and only an
        opinion. None is written for work that failed, was stopped, only made a plan or went over its turn’s token
        limit.
      </div>
    </>
  )
}

/**
 * The project's To-do (0.1.10: the Work page's To-do tab), kept like a Hive keeper would: each story a card - a cell for
 * each task - and the tasks of no story one more; a card opens its story's panel, with its tasks and all they can do;
 * ticked ones go to a chat's queue (Do in chat). Under the cards, a rough note the Hive keeper splits into tasks. What
 * waits for your word on To-do is on the Ready for you tab, with the rest of it. `pushes`: the tasks whose push the night
 * parked for you.
 */
export function BacklogPage({
  backlog,
  error,
  drafter,
  away,
  providers,
  onAdd,
  onDraft,
  onPlan,
  onAddTree,
  onChange,
  onDelete,
  onDecide,
  onDoInChat,
  onOpen,
  stories,
  chats = {},
  projectId,
  tree = NO_TREE,
  asked,
  pushes = NO_PUSH,
  covered,
}: Props & { asked?: TodoAsked | null; pushes?: Set<string>; covered?: boolean }) {
  const [dragged, setDragged] = useState<BacklogTask | null>(null)
  const listed = backlog?.filter(task => task.status !== 'proposed') ?? []
  const view = useTreeView(listed, stories, tree.onNewStory)
  const cards = cardsOf(view.rows)
  const { card, at, open, close } = useOpened(cards, backlog !== null)
  useAsked(asked, backlog ? cards : null, open)
  /** All of a card's tasks, whatever the filter shows. */
  const whole = (one: Card) => wholeOf(one, listed, view.stories)
  const dock = (
    <TodoDock listed={listed} selected={view.selected} onSelect={view.select} projectId={projectId} onDo={onDoInChat} />
  )
  /** A card's tasks, each with all it can do: its tick, its place, its notebook, its chat and ⋯. */
  const rows = (one: Card) => (
    <ol className="backlog-rows todo-tree" aria-label="Tasks">
      {one.tasks.map(task => (
        <TaskRow
          key={task.id}
          task={task}
          listed={listed}
          above={view.beside(task, -1)}
          below={view.beside(task, 1)}
          dragged={dragged}
          onDrag={setDragged}
          onChange={onChange}
          onDelete={onDelete}
          onOpen={onOpen}
          ticked={view.selected.has(task.id)}
          onTick={on => view.select([task.id], on)}
          choice={view.choice}
        />
      ))}
    </ol>
  )
  return (
    <section className="todo-half" aria-labelledby="todo-head">
      <h2 id="todo-head" tabIndex={-1}>
        To-do{' '}
        <span className="muted ready-count">
          {view.stories.length > 0 && `${count(view.stories.length, 'story', 'stories')}, `}
          {count(listed.length, 'task')}
        </span>
      </h2>
      {error && (
        <div role="alert" className="alert">
          The To-do list could not be read: {error}
        </div>
      )}
      <TodoBar filter={view.filter} onFilter={view.setFilter} projectId={projectId} />
      <AddTask onAdd={onAdd} {...view.choice} />
      <Cards backlog={backlog} error={error} empty={view.empty}>
        <StoryCards
          cards={cards}
          whole={whole}
          openKey={card?.key ?? null}
          onOpen={key => (key ? open(key) : close())}
          pushes={pushes}
        />
      </Cards>
      <Declined backlog={backlog} onDecide={onDecide} />
      {(onDraft || onPlan) && (
        <HiveNote onDraft={onDraft} onPlan={onPlan} onAddTree={onAddTree} providers={providers} drafter={drafter} />
      )}
      {cards.length > 0 && <CellLegend />}
      <TodoNotes />
      {!card && dock}
      {card && (
        <StoryPanel
          key={card.key}
          card={card}
          all={whole(card)}
          at={at}
          listed={listed}
          chats={chats}
          away={away}
          projectId={projectId}
          actions={tree}
          selected={view.selected}
          onSelect={view.select}
          onOpenChat={onOpen}
          onClose={close}
          covered={covered}
        >
          {rows(card)}
          {dock}
        </StoryPanel>
      )}
    </section>
  )
}

const NO_PUSH = new Set<string>()

/** The cards once the list is read; before, that it is being read; with nothing on it, how to start. */
function Cards({
  backlog,
  error,
  empty,
  children,
}: {
  backlog: BacklogTask[] | null
  error: string | null
  empty: boolean
  children: ReactNode
}) {
  if (!backlog) return !error && <p className="muted">Reading the To-do list…</p>
  if (empty)
    return (
      <p className="muted hive-empty">
        No task yet. A task is work for later: type its title in “Add a task” above, or write a rough note below and the
        Hive keeper splits it into stories and tasks.
      </p>
    )
  return children
}
