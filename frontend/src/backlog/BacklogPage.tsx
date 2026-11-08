import { DotsSixVertical } from '@phosphor-icons/react'
import { Fragment, useState, type FormEvent, type ReactNode } from 'react'
import { type SpawnDecision } from '../agents/SpawnApproval'
import { LEAD_WORK } from '../shell/ProjectSettings'
import { errorText } from '../api/client'
import type { Away, BacklogAuto, BacklogChoice, BacklogDraft, BacklogTask, BacklogTaskChange, NewBacklogTask, PermissionMode, Provider } from '../api/types'
import { useAsk } from '../memory/useAsk'
import { type LoadModels, ModelNameInput, ProviderOptions } from '../models/ModelNameInput'
import { paidOf, type Paid } from '../models/cards'
import { runsOn } from '../models/ModelPicker'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { usePanel } from '../shell/usePanel'
import { AwayNight } from './Away'

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
const FIELD_WORD: Record<string, string> = { title: 'Title', detail: 'Detail', criteria: 'Done when', priority: 'Priority', status: 'Status' }

interface Props {
  backlog: BacklogTask[] | null
  error: string | null
  /** Whether the backlog runs by itself, and why its run is paused or stopped; null until read. */
  auto: BacklogAuto | null
  onAuto: (on: boolean) => Promise<void>
  /** The level and model the chats the backlog opens start with (B-350), and what to choose from. Throws ApiError. */
  onChoice: (choice: BacklogChoice) => Promise<void>
  providers: Provider[]
  onModels?: LoadModels
  /** The project's night while you're away (slice 106): the one that runs, else its last. */
  away?: Away | null
  /** Each throws ApiError; the backlog is read again after it. */
  onAdd: (task: NewBacklogTask) => Promise<void>
  /** What is typed, written as tasks by a model asked once; nothing is saved. Throws ApiError. */
  onDraft?: (text: string) => Promise<BacklogDraft>
  /** A new chat in the project, with this as its first message, opened. Throws ApiError. */
  onPlan?: (message: string) => Promise<void>
  onChange: (taskId: string, change: BacklogTaskChange) => Promise<void>
  onDelete: (taskId: string) => Promise<void>
  onDecide: (taskId: string, decision: SpawnDecision) => Promise<void>
  /** Run the backlog: every todo task is queued, and they start as there is room. Throws ApiError. */
  onRun: () => Promise<void>
  onOpen: (conversationId: string) => void
}

type FieldsProps = { id: string; task: NewBacklogTask; onTask: (task: NewBacklogTask) => void }

/** Priority, detail and criteria: what a task says beyond its title, new or edited. */
function MoreFields({ id, task, onTask }: FieldsProps) {
  return (
    <>
      <div className="field">
        <label htmlFor={`${id}-priority`}>Priority</label>
        <select id={`${id}-priority`} className="input backlog-status" value={task.priority} onChange={e => onTask({ ...task, priority: e.target.value as Priority })}>
          {PRIORITIES.map(p => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor={`${id}-detail`}>Detail</label>
        <textarea id={`${id}-detail`} className="input" rows={2} maxLength={4000} value={task.detail ?? ''} onChange={e => onTask({ ...task, detail: e.target.value })} />
      </div>
      <div className="field">
        <label htmlFor={`${id}-criteria`}>Done when (optional)</label>
        <textarea id={`${id}-criteria`} className="input" rows={2} maxLength={4000} value={task.criteria ?? ''} onChange={e => onTask({ ...task, criteria: e.target.value })} />
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
        <input id={`${id}-title`} className="input" autoFocus required maxLength={200} value={task.title} onChange={e => onTask({ ...task, title: e.target.value })} />
      </div>
      <MoreFields id={id} task={task} onTask={onTask} />
    </>
  )
}

const EMPTY: NewBacklogTask = { title: '', detail: '', criteria: '', priority: 'normal' }
// An empty detail or criteria is none.
const cleaned = (task: NewBacklogTask) => ({ ...task, title: task.title.trim(), detail: task.detail?.trim() || null, criteria: task.criteria?.trim() || null })

/** "Plan it in a chat": the Lead is asked for the Product owner, whose tasks wait on cards as any agent's proposal does. */
export const PLAN_ASK = 'Have the Product owner break this into To-do tasks: '
const COSTS: Record<Paid, string> = {
  subscription: 'one request on your plan',
  'API key': 'one request you pay for',
  'this machine': 'one request on this machine, free',
}

type AddProps = Pick<Props, 'onAdd' | 'onDraft' | 'onPlan' | 'providers'> & { drafter: BacklogAuto['drafter'] }

/** One line: a title, then Enter. The rest of the task opens under it once a title is typed; Esc closes it. What is typed may
 *  instead be written as tasks by a model (6 Nov), shown under it to change: each is added only by your word. */
function AddTask({ onAdd, onDraft, onPlan, providers, drafter }: AddProps) {
  const { busy, error, ask } = useAsk()
  const drafting = useAsk()
  const adding = useAsk()
  const [task, setTask] = useState(EMPTY)
  const [folded, setFolded] = useState(false)
  const [drafts, setDrafts] = useState<NewBacklogTask[]>([])
  const [by, setBy] = useState('')
  const note = [task.title, task.detail].map(part => part?.trim()).filter(Boolean).join('\n')
  const asked = providers.find(one => one.id === drafter?.provider_id)
  const who =
    drafter?.why ??
    (asked
      ? `${asked.name} (${drafter?.model_id ?? asked.default_model ?? 'its default model'}) writes them: ${COSTS[paidOf(asked)]}. Nothing is saved until you add it.`
      : 'Who writes them is not read yet.')
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
  const draft = (write: NonNullable<Props['onDraft']>) =>
    void drafting.ask(async () => {
      const drawn = await write(note)
      setDrafts(drawn.tasks.map(one => ({ ...one, detail: one.detail ?? '', criteria: one.criteria ?? '' })))
      setBy(drawn.by)
    })
  const addDrafts = (some: NewBacklogTask[]) =>
    void adding.ask(async () => {
      // One after the other: each goes at the end of the order as it is added.
      for (const one of some) {
        await onAdd(cleaned(one))
        setDrafts(now => now.filter(kept => kept !== one))
      }
    })
  const setDraft = (one: NewBacklogTask, next: NewBacklogTask) => setDrafts(now => now.map(kept => (kept === one ? next : kept)))
  return (
    <>
      <form className="backlog-add" aria-label="Add a task" onSubmit={submit} onKeyDown={e => e.key === 'Escape' && setFolded(true)}>
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
            <div className="memory-actions">
              <button type="submit" className="btn btn-small btn-primary" disabled={busy}>
                Add task
              </button>
              {onDraft && (
                <button type="button" className="btn btn-small" aria-describedby="draft-who" disabled={!asked || !!drafter?.why || drafting.busy} onClick={() => draft(onDraft)}>
                  {drafting.busy ? 'Writing…' : 'Write it with the Product owner'}
                </button>
              )}
              {onPlan && (
                <button type="button" className="btn btn-small" disabled={drafting.busy} onClick={() => void drafting.ask(() => onPlan(PLAN_ASK + note))}>
                  Plan it in a chat
                </button>
              )}
            </div>
            {onDraft && (
              <p id="draft-who" className="muted">
                {who}
              </p>
            )}
          </>
        )}
        {(error || drafting.error) && (
          <div role="alert" className="alert">
            {error ?? drafting.error}
          </div>
        )}
      </form>
      {drafts.length > 0 && (
        <section className="backlog-add" aria-label="Drafted tasks">
          <p className="muted">Written by {by}: change them as you like. Nothing is saved until you add it.</p>
          {/* Held while adding: a draft changed then would be another, and added twice. */}
          <fieldset className="recipe-rows" disabled={adding.busy}>
            {drafts.map((one, i) => (
              <div key={i} role="group" aria-label={`Draft ${i + 1}`} className="field">
                <div className="field">
                  <label htmlFor={`draft-${i}-title`}>Title</label>
                  <input id={`draft-${i}-title`} className="input" maxLength={200} value={one.title} onChange={e => setDraft(one, { ...one, title: e.target.value })} />
                </div>
                <MoreFields id={`draft-${i}`} task={one} onTask={next => setDraft(one, next)} />
                <div className="memory-actions">
                  <button type="button" className="btn btn-small btn-primary" disabled={!one.title.trim()} onClick={() => addDrafts([one])}>
                    Add
                  </button>
                  <button type="button" className="btn btn-small" aria-label={`Remove draft ${i + 1}`} onClick={() => setDrafts(now => now.filter(kept => kept !== one))}>
                    ✕
                  </button>
                </div>
              </div>
            ))}
            <div className="memory-actions">
              <button type="button" className="btn btn-small" disabled={drafts.some(one => !one.title.trim())} onClick={() => addDrafts(drafts)}>
                Add all
              </button>
            </div>
          </fieldset>
          {adding.error && (
            <div role="alert" className="alert">
              {adding.error}
            </div>
          )}
        </section>
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
  if (task.status === 'review' && task.not_in) return 'Its work is not in the project yet: take it in or discard it in its chat.'
  if (task.status !== 'todo') return null
  const waits = waitsFor(task, listed)
  if (waits.length) return `waits for: ${waitWords(waits)}`
  return task.queued ? 'queued' : null
}

/** A task's state at a glance, on the right of its row: its word, and the tag's colour. */
function stateTag(task: BacklogTask): [string, string] {
  if (task.status === 'review' && task.not_in) return ['needs you · Take in', ' tag-warn']
  if (task.status === 'doing') return task.waiting ? ['needs you', ' tag-warn'] : ['running', ' tag-accent']
  if (task.status === 'blocked') return [task.stuck ? 'stuck' : 'blocked', ' tag-del']
  if (task.status === 'done') return ['done', ' tag-ok']
  return [task.status === 'todo' && task.queued ? 'queued' : STATUS_WORD[task.status], '']
}

// Done, not "done?": work waiting for Take in is not in the project yet.
const waitsFor = (task: BacklogTask, listed: BacklogTask[]) => listed.filter(one => task.after.includes(one.id) && one.status !== 'done')
// B-349: one at "done?" moves on only by your word, so it says so - Done on its row, or first Take in.
const reviewWaits = (one: BacklogTask) => (one.not_in ? 'waiting for you - Take in' : 'done? - press Done above to go on')
const waitWords = (waits: BacklogTask[]) => waits.map(one => (one.status === 'review' ? `${one.title} (${reviewWaits(one)})` : one.title)).join(', ')

// A field's value as the page says it: a status in its words ("done?" for review).
const shown = (field: string, value: unknown) => (field === 'status' ? STATUS_WORD[value as Status] : String(value ?? 'none'))

/** One of what waits for your word, as it is listed: its kind, its row's name and second line, and its buttons. */
interface Wait {
  key: string
  task: BacklogTask
  kind: 'new task' | 'done?' | 'change' | 'added'
  name: string
  line: string
  buttons: [label: string, run: () => Promise<void>][]
  /** A proposed task's Edit: its title and detail changed, then it is added. */
  edit?: (fields: { title: string; detail: string | null }) => Promise<void>
}

/** A task the Assistant PO proposed and the Orchestrator said no to at Full auto: under "Decided for you" in its chat, not waiting here. */
const declined = (task: BacklogTask) => task.status === 'proposed' && task.po?.lead === 'no'
/** One the Orchestrator added at Full auto that you have not OK'd: it starts by your OK only. */
const unseen = (task: BacklogTask) => task.status === 'todo' && task.po?.lead === 'add' && !task.po.seen

/** What waits for your word, one row each, in the page's order: proposed tasks, then "done?", then changes. */
function waitsOf(tasks: BacklogTask[], onDecide: Props['onDecide'], onChange: Props['onChange']): Wait[] {
  const of = (kind: Wait['kind'], task: BacklogTask): Wait => {
    const decide = (decision: SpawnDecision) => () => onDecide(task.id, decision)
    if (kind === 'added')
      return {
        key: `${task.id}:added`,
        task,
        kind,
        name: `Added for you: ${task.title}`,
        line: ['Added by the Orchestrator at Full auto, not seen by you', task.po?.lead_why && `“${task.po.lead_why}”`].filter(Boolean).join(' · '),
        buttons: [
          ['OK', decide('approve')],
          ['Reject', decide('reject')],
        ],
      }
    if (kind === 'new task')
      return {
        key: `${task.id}:new`,
        task,
        kind,
        name: `Proposed task: ${task.title}`,
        // (Who proposed it is known only as "an agent", but for the Assistant PO's at a turn's end, with the words it came from.)
        line: [
          task.po ? `Proposed by the Assistant PO, from: “${task.po.why}”` : task.created_by === 'agent' && 'Proposed by an agent',
          // (As a text that read like orders is told everywhere: the rule, never the text - here the task is the text.)
          task.po?.injection?.length && `Its words look like they try to give the agent orders (rules: ${task.po.injection.map(rule => rule.replaceAll('_', ' ')).join(', ')}); read them before you add it`,
          task.detail,
          task.criteria && `Done when: ${task.criteria}`,
        ]
          .filter(Boolean)
          .join(' · '),
        buttons: [
          ['Add', decide('approve')],
          ['Reject', decide('reject')],
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
        line: [task.assessment && `An agent’s view (an opinion): ${task.assessment}`, task.criteria && `Done when: ${task.criteria}`].filter(Boolean).join(' · '),
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
        .map(([field, value]) => `${FIELD_WORD[field] ?? field} ${shown(field, task[field as keyof BacklogTask])} → ${shown(field, value)}`)
        .join(' · '),
      buttons: [
        ['Change', decide('approve')],
        ['Reject', decide('reject')],
      ],
    }
  }
  return [
    ...tasks.filter(task => task.status === 'proposed' && !declined(task)).map(task => of('new task', task)),
    ...tasks.filter(unseen).map(task => of('added', task)),
    // One whose work is not in the project yet is not asked "done?": it says so on its row in the list.
    ...tasks.filter(task => task.status === 'review' && !task.not_in).map(task => of('done?', task)),
    ...tasks.filter(task => task.pending).map(task => of('change', task)),
  ]
}

/** The Assistant PO's proposals the Orchestrator rejected at Full auto, folded: still yours to add. */
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
      <button type="button" className="btn btn-small" disabled={busy} onClick={() => void ask(() => onDecide(task.id, 'approve'))}>
        Add
      </button>
    </div>
  )
}

/** A row's title, which unfolds the rest of it; the rest is the row's own (it opens to show it whole). */
function Fold({ id, open, onOpen, children }: { id?: string; open: boolean; onOpen: (open: boolean) => void; children: ReactNode }) {
  return (
    <button type="button" className="backlog-fold" aria-expanded={open} onClick={() => onOpen(!open)}>
      <strong id={id}>{children}</strong>
    </button>
  )
}

/** One decision's row. Its second line is never cut: what is decided is read whole before its button. */
function Decision({ wait, off, failed, onOpen }: { wait: Wait; off?: boolean; failed?: string; onOpen: Props['onOpen'] }) {
  const { busy, error, ask } = useAsk()
  const [editing, setEditing] = useState(false)
  const { task } = wait
  const said = error ?? failed
  return (
    // Several rows stand on the page: each is a group named by its task, so their buttons are told apart.
    <div role="group" aria-label={wait.name} className="backlog-row">
      <span className={`tag${wait.kind === 'done?' ? ' tag-ok' : wait.kind === 'change' ? ' tag-accent' : ''}`}>{wait.kind}</span>
      <div className="backlog-row-text">
        <strong>{task.title}</strong> <span className={`tag mono${task.priority === 'high' ? ' tag-warn' : ''}`}>{task.priority}</span>
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
        <ProposalEdit task={task} busy={busy} onAdd={fields => ask(() => wait.edit!(fields))} onCancel={() => setEditing(false)} />
      ) : (
        wait.buttons.map(([label, run], i) => (
          <Fragment key={label}>
            <button type="button" className={`btn btn-small${i === 0 ? ' btn-primary' : ''}`} disabled={busy || off} onClick={() => void ask(run)}>
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

/** A proposed task's Edit (6 Nov): its title and detail as you want them, then Add. */
function ProposalEdit({ task, busy, onAdd, onCancel }: { task: BacklogTask; busy: boolean; onAdd: (fields: { title: string; detail: string | null }) => Promise<boolean>; onCancel: () => void }) {
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
        <input id={`${id}-title`} className="input" autoFocus required maxLength={200} value={title} onChange={e => setTitle(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor={`${id}-detail`}>Detail</label>
        <textarea id={`${id}-detail`} className="input" rows={2} maxLength={4000} value={detail} onChange={e => setDetail(e.target.value)} />
      </div>
      <button type="submit" className="btn btn-small btn-primary" disabled={busy || !title.trim()}>
        Add
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

/** What waits for your word, one row each, in the page's order. The proposed tasks may be added all at once. */
function Waiting({ waits, onDecide, onChange, onOpen }: { waits: Wait[] } & Pick<Props, 'onDecide' | 'onChange' | 'onOpen'>) {
  const [bulk, setBulk] = useState(false)
  // A refusal of Approve all's stays on the row it was of.
  const [failed, setFailed] = useState<Record<string, string>>({})
  const proposals = waits.filter(wait => wait.kind === 'new task')
  async function approveAll() {
    setBulk(true)
    setFailed({})
    // One after another, each the single decision; one refused, the next goes on.
    for (const { task } of proposals) {
      try {
        await onDecide(task.id, 'approve')
      } catch (err) {
        setFailed(now => ({ ...now, [task.id]: errorText(err) }))
      }
    }
    setBulk(false)
  }
  return (
    <section className="memory-section" aria-label="Waiting for you">
      <div className="memory-head">
        <h3 className="kicker">
          Waiting for you <span className="tag tag-warn">{waits.length}</span>
        </h3>
        {proposals.length > 1 && (
          <button type="button" className="btn btn-small" disabled={bulk} onClick={() => void approveAll()}>
            Approve all {proposals.length} proposals
          </button>
        )}
      </div>
      <div className="backlog-rows">
        {waits.map(wait => (
          <WaitRow
            key={wait.key}
            task={wait.task}
            only={wait.kind}
            off={bulk}
            failed={wait.kind === 'new task' ? failed[wait.task.id] : undefined}
            onDecide={onDecide}
            onChange={onChange}
            onOpen={onOpen}
          />
        ))}
      </div>
    </section>
  )
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
}

function TaskRow({ task, listed, above, below, dragged, onDrag, onChange, onDelete, onOpen }: RowProps) {
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
  const sub = [state !== tag && state, task.pending && 'A change to it waits for you above'].filter(Boolean).join(' · ')
  const [deleting, setDeleting] = useState(false)
  // "Keep it" was pressed: the ⋯ it brings back takes the focus.
  const [kept, setKept] = useState(false)
  const id = `task-${task.id}`
  const change = (c: BacklogTaskChange) => void ask(() => onChange(task.id, c))
  const edit = (waitsFirst: boolean) => {
    setEditing({ title: task.title, detail: task.detail ?? '', criteria: task.criteria ?? '', priority: task.priority })
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
  const dropHere = dragged !== null && dragged.id !== task.id

  return (
    <li
      className={`backlog-task${open ? ' backlog-open' : ''}`}
      aria-labelledby={`${id}-title`}
      onDragOver={event => dropHere && event.preventDefault()}
      onDrop={event => {
        event.preventDefault()
        if (dropHere) {
          const position = dragged.priority === task.priority && dragged.position < task.position ? task.position + 1 : task.position
          void ask(() => onChange(dragged.id, { position, priority: task.priority }))
        }
        onDrag(null)
      }}
    >
      {editing ? (
        <form
          className="memory-edit"
          aria-label={`Edit ${task.title}`}
          onSubmit={event => {
            event.preventDefault()
            void ask(() => onChange(task.id, { ...cleaned(editing), after: waits })).then(done => done && setEditing(null))
          }}
        >
          <TaskFields id={id} task={editing} onTask={setEditing} />
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
      ) : (
        <div className="backlog-row">
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
          {task.conversation_id && (
            <button type="button" className="btn btn-small" aria-label={`Open chat · ${task.title}`} onClick={() => onOpen(task.conversation_id ?? '')}>
              Open chat
            </button>
          )}
          {deleting ? (
            <>
              {/* The second word is asked for where the first was given: it takes the focus. */}
              <button type="button" className="btn btn-small btn-danger" autoFocus disabled={busy} onClick={() => void ask(() => onDelete(task.id))}>
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
            <div ref={menuPanel} tabIndex={-1} className="allow-list-panel msg-menu" role="menu" aria-label={`${task.title}: more`}>
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
      {open && !editing && (
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
            <select id={`${id}-status`} className="input backlog-status" value={task.status} disabled={busy || task.status === 'proposed'} onChange={e => change({ status: e.target.value as (typeof STATUSES)[number] })}>
              {task.status === 'proposed' && <option value="proposed">proposed</option>}
              {STATUSES.map(s => (
                <option key={s} value={s}>
                  {STATUS_WORD[s]}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </li>
  )
}

/** The switch that has the backlog run by itself, its rules behind ⓘ. */
function AutoSwitch({ auto, onAuto }: { auto: BacklogAuto; onAuto: Props['onAuto'] }) {
  const { busy, error, ask } = useAsk()
  return (
    <>
      {/* (Off stays possible: only turning it on is refused while no task can run.) */}
      <label className="choice" htmlFor="backlog-auto" title={auto.cannot_run ?? undefined}>
        <input
          id="backlog-auto"
          type="checkbox"
          role="switch"
          aria-describedby="backlog-auto-line backlog-rules"
          checked={auto.on}
          disabled={busy || (!auto.on && !!auto.cannot_run)}
          onChange={e => void ask(() => onAuto(e.target.checked))}
        />
        Runs by itself
      </label>
      {/* (Beside the label, not in it: the switch's name stays its own.) */}
      <Hint doc={GUIDE.todoRunning} id="backlog-auto-line">
        {auto.on
          ? 'On: todo tasks start by themselves when fewer than two are at work and no turn of yours is running.'
          : 'Off: tasks start only from Run the backlog.'}
      </Hint>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </>
  )
}

/** B-350: the level and the model the chats the backlog opens start with, kept for the project; as a chat's own. */
function ChatChoice({ auto, providers, onChoice, onModels }: { auto: BacklogAuto } & Pick<Props, 'providers' | 'onChoice' | 'onModels'>) {
  const { busy, error, ask } = useAsk()
  const [model, setModel] = useState(auto.model_id ?? '')
  const picked = providers.find(p => p.id === auto.provider_id)
  const full = auto.permission_mode === 'full_auto'
  const save = (change: Partial<BacklogChoice>) =>
    void ask(() =>
      onChoice({ permission_mode: auto.permission_mode, provider_id: auto.provider_id, model_id: auto.model_id, lead_work: auto.lead_work, ...change }),
    )
  return (
    <>
      <div className="memory-row">
        <div className="field">
          <label htmlFor="backlog-level">Its chats’ level</label>
          <select
            id="backlog-level"
            className="input"
            // (Its warning is beside Run settings, outside this panel: the Full auto tag's ⓘ.)
            aria-describedby={full ? 'backlog-level-note' : undefined}
            value={auto.permission_mode}
            disabled={busy}
            onChange={e => save({ permission_mode: e.target.value as PermissionMode })}
          >
            <option value="ask">Ask before changes</option>
            <option value="auto_edit">Auto-edit files</option>
            <option value="full_auto">Full auto</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="backlog-lead-work">Who changes the files</label>
          <select
            id="backlog-lead-work"
            className="input"
            value={auto.lead_work}
            disabled={busy}
            title={LEAD_WORK.find(([value]) => value === auto.lead_work)?.[2]}
            onChange={e => save({ lead_work: e.target.value as BacklogAuto['lead_work'] })}
          >
            {LEAD_WORK.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="backlog-provider">Provider</label>
          <select
            id="backlog-provider"
            className="input"
            value={auto.provider_id ?? ''}
            disabled={busy}
            onChange={e => {
              setModel('')
              save({ provider_id: e.target.value || null, model_id: null })
            }}
          >
            <option value="">Default ({providers[0]?.name ?? 'none'})</option>
            <ProviderOptions providers={providers} />
          </select>
        </div>
        {auto.provider_id && (
          // Kept as the field is left: not at each letter typed.
          <div className="field memory-grow" onBlur={() => model.trim() !== (auto.model_id ?? '') && save({ model_id: model.trim() || null })}>
            <label htmlFor="backlog-model">Model name</label>
            <ModelNameInput
              id="backlog-model"
              value={model}
              // (The Anthropic API has no default of its own: with none set, a run is refused.)
              placeholder={runsOn(picked) ?? (picked?.kind === 'anthropic' ? 'Needed: this provider has no default model' : "The provider's default")}
              providerId={auto.provider_id}
              loadModels={onModels}
              onChange={setModel}
            />
            <span className="choice-note">A role with its own model keeps it.</span>
          </div>
        )}
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </>
  )
}

/**
 * The project's backlog, kept like a product owner would: what waits for your word on top, one row
 * each; your tasks in order (priority first, then the order you give); and "Run the backlog", which
 * starts the todo tasks - two at a time, each in a new conversation - and how the run stands.
 */
export function BacklogPage({ backlog, error, auto, away, providers, onAuto, onChoice, onModels, onAdd, onDraft, onPlan, onChange, onDelete, onDecide, onRun, onOpen }: Props) {
  const { busy, error: workError, ask } = useAsk()
  const [dragged, setDragged] = useState<BacklogTask | null>(null)
  const [settings, setSettings] = useState(false)
  const waits = waitsOf(backlog ?? [], onDecide, onChange)
  const listed = backlog?.filter(task => task.status !== 'proposed') ?? []
  const todo = listed.some(task => task.status === 'todo')
  const working = listed.filter(task => task.status === 'doing').length
  // (By itself it takes the todo tasks never worked on; Run the backlog queues them all.)
  const queued = listed.filter(task => task.status === 'todo' && (task.queued || (auto?.on && !task.conversation_id)))
  // B-349: nothing at work and every queued task waits, some for one in review: that is why.
  const held = working || !queued.every(task => waitsFor(task, listed).length) ? [] : listed.filter(one => one.status === 'review' && queued.some(task => task.after.includes(one.id)))
  const run =
    auto?.halt ??
    (held.length
      ? `Nothing running: waits for ${waitWords(held)}`
      : working || queued.length
        ? `Running ${working} of ${working + queued.length}`
        : auto?.on
          ? 'On, waiting: no new task is todo'
          : 'Off')
  const same = (a: BacklogTask, b?: BacklogTask) => (b && b.priority === a.priority ? b : undefined)

  return (
    <div className="memory-page">
      <div className="conv-head">
        <h2>To-do</h2>
        <div className="memory-actions">
          {/* Why Run the backlog is grey, said where it is seen. */}
          <span id="backlog-next" className="muted">
            {run}
            {auto?.cannot_run && (
              <>
                {' · '}
                <span className="backlog-warn">{auto.cannot_run}</span>
              </>
            )}
          </span>
          {auto && <AutoSwitch auto={auto} onAuto={onAuto} />}
          {auto && (
            <button type="button" className="btn btn-small" aria-expanded={settings} aria-controls="backlog-settings" onClick={() => setSettings(!settings)}>
              Run settings <span aria-hidden="true">▾</span>
            </button>
          )}
          {auto?.permission_mode === 'full_auto' && (
            <span>
              <span className="tag tag-warn">Full auto</span>{' '}
              <Hint doc={GUIDE.todoRunSettings} id="backlog-level-note">
                Full auto: its chats change files and run commands without asking. Commands that run other programs, and anything it
                would ask you, still wait for you - it never answers for you.
              </Hint>
            </span>
          )}
          <button
            type="button"
            className="btn btn-primary"
            aria-describedby="backlog-next"
            title={auto?.cannot_run ?? undefined}
            disabled={busy || !todo || !!auto?.cannot_run}
            onClick={() => void ask(onRun)}
          >
            Run the backlog
          </button>
        </div>
      </div>
      {auto && settings && (
        <section id="backlog-settings" className="memory-side" aria-label="Run settings">
          <p className="choice-note">The To-do list’s chats only, instead of the project’s (Settings › This project).</p>
          <ChatChoice auto={auto} providers={providers} onChoice={onChoice} onModels={onModels} />
        </section>
      )}
      <div className="muted memory-hint">
        Each task runs in its own chat; you decide when it is done.{' '}
        <Hint doc={GUIDE.todoRunning}>
          Run the backlog starts the todo tasks, two at a time, each in a new conversation where the Orchestrator hands it to the right
          role. Its first message is the task’s title, detail and what makes it done. A task that waits for others (⋯, Waits for) starts
          once they are done. When the work ends, the task shows “done?”: you decide whether it is done; what needs your word still waits
          for it. With Runs by itself on, todo tasks start as there is room. A Product owner or an Assistant product owner can propose
          tasks and changes; they wait here for your word. Going away? Tell the Orchestrator in a chat (“I'm going to sleep, finish this
          and that”): it puts the jobs on a card, and they start only when you press Start.
        </Hint>
      </div>
      {/* What it runs and spends stays in sight, never behind an ⓘ. */}
      <div id="backlog-rules" className="muted memory-hint">
        A task not finished gets one fix round; still not, it is stuck and the next goes on. A stop, a restart or a limit pauses the run and
        says why. When a task’s work ends, a fast model, if you have one, writes the Assistant product owner’s view of it: one more
        request, and only an opinion. None is written for work that failed, was stopped, only made a plan or went over its turn’s token
        limit.
      </div>
      {away && <AwayNight away={away} onOpen={onOpen} />}
      {(error || workError) && (
        <div role="alert" className="alert">
          {error ? `The To-do list could not be read: ${error}` : workError}
        </div>
      )}
      <AddTask onAdd={onAdd} onDraft={onDraft} onPlan={onPlan} providers={providers} drafter={auto?.drafter} />
      {waits.length > 0 && <Waiting waits={waits} onDecide={onDecide} onChange={onChange} onOpen={onOpen} />}
      <Declined backlog={backlog} onDecide={onDecide} />
      {!backlog ? (
        !error && <p className="muted">Reading the To-do list…</p>
      ) : listed.length === 0 ? (
        <p className="muted hive-empty">No task yet.</p>
      ) : (
        <section className="memory-section" aria-label="Your tasks">
          <h3 className="kicker">
            Your tasks <span className="muted">· {listed.length}</span>
          </h3>
          <ol className="backlog-rows" aria-label="Tasks">
            {listed.map((task, i) => (
              <TaskRow
                key={task.id}
                task={task}
                listed={listed}
                above={same(task, listed[i - 1])}
                below={same(task, listed[i + 1])}
                dragged={dragged}
                onDrag={setDragged}
                onChange={onChange}
                onDelete={onDelete}
                onOpen={onOpen}
              />
            ))}
          </ol>
        </section>
      )}
    </div>
  )
}
