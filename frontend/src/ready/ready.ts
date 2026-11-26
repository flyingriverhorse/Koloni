import type { Away, AwayJob, BacklogTask, MemoryRecord, ProjectMemory, Waiting as Parked } from '../api/types'
import { type Waiting, waitingOf } from '../chat/waiting'
import type { ConvState } from '../state/applyEvent'

/** Where a row of Ready for you comes from: its filter on the page (tek-ev §1). */
export type ReadySource = 'chat' | 'todo' | 'memory' | 'night' | 'other'

export const SOURCES: [ReadySource, string][] = [
  ['chat', 'Chats'],
  ['todo', 'To-do'],
  ['memory', 'Memory'],
  ['night', 'Last night'],
  ['other', 'Other folders'],
]

/** One thing that waits for your word, with what its card is drawn from; `at`: since when, '' where no record says. */
export type ReadyItem = { key: string; source: ReadySource; at: string } & (
  | { what: 'card'; state: ConvState; row: Waiting }
  | { what: 'task'; task: BacklogTask; kind: TaskWait }
  | { what: 'memory'; record: MemoryRecord; suggestion: boolean }
  | { what: 'night'; away: Away; job: AwayJob }
  | { what: 'parked'; away: Away; row: Parked }
)

/** A To-do decision, as the To-do list's own rows name it (`WaitRow`'s `only`). */
export type TaskWait = 'new task' | 'done?' | 'change'

/** Since when a chat's card waits: its record's own time, else its turn's. */
function atOf(state: ConvState, row: Waiting): string {
  const item = row.what === 'night' ? row.item.away : row.item
  if ('created_at' in item && typeof item.created_at === 'string') return item.created_at
  const runId = 'run_id' in item ? item.run_id : null
  return state.runs.find(run => run.id === runId)?.created_at ?? ''
}

interface Sources {
  /** The open chat, and the other chats where something waits (`readyChats`). */
  conv: ConvState | null
  chats: Record<string, ConvState>
  /** The open chat's folder, and its To-do list, memory and night - and what its night parked for you (§10). */
  projectId: string | null
  backlog: BacklogTask[] | null
  memory: ProjectMemory | null
  away: Away | null
  parked?: Parked[]
}

/**
 * What the night parked for you and you have not decided (§10), as Waiting for you's rows: its push first - the
 * morning's one row of KOLONİ's own -, then the commands and questions, task by task in the night's order. None of a
 * plan, or of no night.
 */
function parkedItems(away: Away | null, parked: Parked[]): ReadyItem[] {
  if (!away || away.status === 'planned') return []
  const open = parked.filter(row => !row.decision)
  return [...open.filter(row => row.kind === 'push'), ...open.filter(row => row.kind !== 'push')].map(row => ({
    what: 'parked',
    // (a push made again with a new commit: a new row - its notes seen go)
    key: `parked:${row.id}:${row.tip ?? ''}`,
    source: 'night',
    at: '',
    away,
    row,
  }))
}

/**
 * Everything that waits for your word, in one list, oldest first (tek-ev §1) - what the night parked for you first, its
 * push first of all: each chat's cards as its chat counts them (`waitingOf`, what can be answered now), the folder's
 * To-do items, Memory's proposals and suggestions, and the night's jobs that wait. Each decision once: a night job whose
 * asks are all cards of its chat already is that card, one that waits only for what it parked is those rows, and a
 * task whose work waits for Take in is its chat's card.
 */
export function readyItems({ conv, chats, projectId, backlog, memory, away, parked = [] }: Sources): ReadyItem[] {
  const states = [
    conv,
    ...Object.values(chats).filter(state => state.conversation.id !== conv?.conversation.id),
  ].filter((state): state is ConvState => state !== null)
  const cards: ReadyItem[] = states.flatMap(state =>
    waitingOf(state)
      .filter(row => row.current)
      .map(row => ({
        what: 'card' as const,
        key: row.key,
        // (A plain chat is in no folder: not "another folder's".)
        // shortcut: a night job drawn from its chat's card opens its job's chat without leaving the page it is on (the
        // chat's JobRow); map it to a 'night' row here, kept in its chat's part of the panel, if that is missed.
        source:
          row.what === 'night'
            ? 'night'
            : state.conversation.project_id && state.conversation.project_id !== projectId
              ? 'other'
              : 'chat',
        at: atOf(state, row),
        state,
        row,
      })),
  )
  const keys = new Set(cards.map(card => card.key))
  const first = parkedItems(away, parked)
  const parkedOf = new Set(first.flatMap(item => (item.what === 'parked' ? [item.row.task_id] : [])))
  const night: ReadyItem[] = (away?.status === 'planned' ? [] : (away?.jobs ?? []))
    .filter(job => job.state === 'waits')
    .filter(
      job =>
        !keys.has(`${away!.id}:${job.task_id}`) &&
        !(job.asks.some(ask => ask.kind) && job.asks.every(ask => !ask.kind || keys.has(ask.id))) &&
        !(job.asks.length === 0 && parkedOf.has(job.task_id ?? '')),
    )
    .map(job => ({
      what: 'night',
      key: `${away!.id}:${job.task_id}`,
      source: 'night',
      at: away!.started_at ?? '',
      away: away!,
      job,
    }))
  // Each decision a row, as on the To-do list: a new task, a "done?" (not one whose work waits for Take in), a change.
  // shortcut: a task says no time, so To-do items stand after those that do; give BacklogTaskOut its created_at if that misleads.
  const tasks: ReadyItem[] = (backlog ?? []).flatMap(task =>
    (
      [
        // (Not one the Orchestrator said no to at Full auto: that is under "Decided for you" in its chat.)
        [task.status === 'proposed' && task.po?.lead !== 'no', 'new task'],
        [task.status === 'review' && !task.not_in, 'done?'],
        [task.pending != null, 'change'],
      ] as const
    )
      .filter(([waits]) => waits)
      .map(([, kind]) => ({
        what: 'task' as const,
        key: `todo:${task.id}:${kind}`,
        source: 'todo' as const,
        at: '',
        task,
        kind,
      })),
  )
  const records: ReadyItem[] = [
    ...(memory?.proposals ?? []).map(record => ({ record, suggestion: false })),
    ...(memory?.suggestions ?? []).map(record => ({ record, suggestion: true })),
  ].map(({ record, suggestion }) => ({
    what: 'memory',
    key: `memory:${record.id}`,
    source: 'memory',
    at: record.created_at,
    record,
    suggestion,
  }))
  // Oldest first; those with no time last, in the order they came.
  const rest = [...cards, ...night, ...tasks, ...records].sort((a, b) =>
    !a.at || !b.at ? Number(!a.at) - Number(!b.at) : a.at.localeCompare(b.at),
  )
  return [...first, ...rest]
}

/** The open chat's own, and the rest: the panel's two parts. */
export const ofChat = (items: ReadyItem[], conversationId: string | undefined) =>
  items.filter(item => item.what === 'card' && item.state.conversation.id === conversationId)

/** The chat a row belongs to, where it has one: "Open chat" goes there. */
export function chatOf(item: ReadyItem): string | null {
  if (item.what === 'card') return item.state.conversation.id
  if (item.what === 'task') return item.task.conversation_id
  if (item.what === 'memory') return item.record.conversation_id
  if (item.what === 'parked') return item.row.conversation_id
  return item.job.conversation_id ?? null
}

/** A row's element, by its key: where the panel is asked to bring one into view. */
export const readyId = (key: string) => `ready-${key}`

/** The panel's element: what the top bar's pill controls. */
export const READY_PANEL = 'ready-panel'
