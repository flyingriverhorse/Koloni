import { ArrowClockwise, CaretDown, CaretRight, FolderSimple, ListChecks, Plus } from '@phosphor-icons/react'
import { useEffect, useId, useState } from 'react'
import { WAITS } from '../agents/agentStatus'
import { errorText } from '../api/client'
import type { Board, ConversationsDeleted, ListedConversation, Project, Trigger } from '../api/types'
import { count } from '../board/columns'
import { standingOf, standingSaid, waitCount } from '../board/waiting'
import { useConfirm } from './Confirm'
import { GitHubIssue } from './GitHubIssue'
import { ranOn } from './modelName'
import { tabOf } from './openTabs'
import { StatusLabel } from './StatusLabel'

type BoardConversation = Board['conversations'][number]

interface Props {
  /** Every chat, of every folder and of none. */
  conversations: ListedConversation[]
  /** The folders, by which the chats are grouped. */
  projects?: Project[]
  currentId: string | null
  onOpen: (id: string) => void
  /** A new chat, in the open chat's folder. */
  onNew: () => void
  /** Put a conversation away (true), or bring it back; rejects with the server's reason. */
  onArchive: (id: string, archived: boolean) => Promise<void>
  /** Delete archived conversations for good; answers which were, and why the others were not. */
  onDelete?: (ids: string[]) => Promise<ConversationsDeleted>
  /** The project's Board as last read: how each conversation stands. */
  board?: Board | null
  /** The project's triggers, once read: an archived conversation's still run, and its row says so. */
  triggers?: Trigger[] | null
  /** Every trigger is held back: none of them runs, and no row says one does. */
  triggersPaused?: boolean
  /** Read the list again: by hand, as the page comes back into view, and every 30 s while it is shown. */
  onRefresh?: () => Promise<void>
}

/** A chat made or changed elsewhere (another window, a trigger, the To-do list) shows up without a click. */
function useRefreshing(onRefresh: (() => Promise<void>) | undefined, onError: (said: null) => void) {
  useEffect(() => {
    if (!onRefresh) return
    // (The page read the list as it opened.)
    let last = Date.now()
    let timer: ReturnType<typeof setInterval> | undefined
    const read = () => {
      if (document.visibilityState !== 'visible' || Date.now() - last < 5000) return
      last = Date.now()
      void onRefresh().then(() => onError(null), () => {}) // (a failed one by itself waits for the next; the button says one)
    }
    // No timer while the page is hidden.
    const shown = () => {
      clearInterval(timer)
      timer = document.visibilityState === 'visible' ? setInterval(read, 30_000) : undefined
      read()
    }
    shown()
    window.addEventListener('focus', read)
    document.addEventListener('visibilitychange', shown)
    return () => {
      clearInterval(timer)
      window.removeEventListener('focus', read)
      document.removeEventListener('visibilitychange', shown)
    }
  }, [onRefresh, onError])
}

const Alert = ({ said }: { said: string | null }) =>
  said && (
    <p role="alert" className="alert">
      {said}
    </p>
  )

/** Its own failed read is said with the list's other alerts, and gone once a read works; theirs are not touched. */
function RefreshButton({ onRefresh, onError }: { onRefresh?: () => Promise<void>; onError: (said: string | null) => void }) {
  const [busy, setBusy] = useState(false)
  useRefreshing(onRefresh, onError)
  if (!onRefresh) return null
  async function now() {
    setBusy(true)
    try {
      await onRefresh()
      onError(null)
    } catch (err) {
      onError(`The conversations could not be read again: ${errorText(err)}`)
    } finally {
      setBusy(false)
    }
  }
  return (
    <button type="button" className="icon-btn" aria-label="Refresh conversations" title="Refresh conversations" aria-busy={busy} disabled={busy} onClick={() => void now()}>
      <ArrowClockwise size={14} className={busy ? 'spin' : undefined} aria-hidden />
    </button>
  )
}

function when(at: number): string {
  return new Date(at).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Its last activity: its own last change, or its last turn's end where that is later. */
const lastAt = (c: ListedConversation, on?: BoardConversation) =>
  Math.max(Date.parse(c.updated_at), on?.turn?.ended_at ? Date.parse(on.turn.ended_at) : 0)

/** Today, the six days before it, or earlier: by this machine's clock. */
export function dayOf(at: number, now = new Date()): 'Today' | 'Last 7 days' | 'Older' {
  const daysAgo = (days: number) => new Date(now.getFullYear(), now.getMonth(), now.getDate() - days).getTime()
  return at >= daysAgo(0) ? 'Today' : at >= daysAgo(6) ? 'Last 7 days' : 'Older'
}

/** What the status filter offers, and which standings each takes. */
const SHOW = [
  ['all', 'All states', []],
  ['failed', 'Failed or stopped', ['failed', 'cancelled', 'interrupted']],
  ['done', 'Done', ['completed']],
] as const
type Show = (typeof SHOW)[number][0]

/** How it stands, in the words the rest of the app uses: it waits for you, works, or how its last turn ended. */
function Standing({ on }: { on?: BoardConversation }) {
  const said = standingSaid(on)
  return said && <StatusLabel color={said[1]}>{said[0]}</StatusLabel>
}

/** A To-do list task's state in a few words (K-backlog-sohbet). */
const TASK_WORD: Record<NonNullable<ListedConversation['backlog_task']>['status'], string> = {
  proposed: 'proposed',
  todo: 'to do',
  doing: 'working',
  review: 'done?',
  done: 'done',
  blocked: 'stuck',
}

/** Where its task stands on the To-do list - unless the chat's own state already says the same words. */
function TaskState({ task, on }: { task: ListedConversation['backlog_task']; on?: BoardConversation }) {
  if (!task) return null
  const word = task.waiting ? WAITS : TASK_WORD[task.status]
  if (standingSaid(on)?.[0].startsWith(word)) return null
  return <span className={`tag${task.waiting || task.status === 'blocked' ? ' tag-warn' : ''}`}>{word}</span>
}

export function ConversationList({ conversations, projects = [], currentId, onOpen, onNew, onArchive, onDelete, board, triggers, triggersPaused = false, onRefresh }: Props) {
  const [by, setBy] = useState<'date' | 'name'>('date')
  // The folders whose group was opened or closed here by hand, by their project's id ('none': the chats with no folder).
  const [turned, setTurned] = useState<string[]>([])
  const toggle = (key: string) => setTurned(was => (was.includes(key) ? was.filter(one => one !== key) : [...was, key]))
  const [show, setShow] = useState<Show>('all')
  const groupId = useId()
  const [query, setQuery] = useState('')
  const [refused, setRefused] = useState<string | null>(null)
  const [stale, setStale] = useState<string | null>(null)
  const on = new Map(board?.conversations.map(c => [c.conversation_id, c]))
  const waits = (id: string) => waitCount(on.get(id) ?? { agents: [], merges_pending: 0, turn: null }) > 0
  const words = query.trim().toLowerCase()
  const found = conversations.filter(c => c.title.toLowerCase().includes(words))
  const [, showLabel, standings] = SHOW.find(([key]) => key === show)!
  const shown = show === 'all' ? found : found.filter(c => (standings as readonly (string | null)[]).includes(standingOf(on.get(c.id))))
  // Those that wait for you first; within them, as chosen (newest first is how the server lists them).
  const sorted = shown
    .sort((a, b) => (by === 'name' ? a.title.localeCompare(b.title) : lastAt(b, on.get(b.id)) - lastAt(a, on.get(a.id))))
    .sort((a, b) => Number(waits(b.id)) - Number(waits(a.id)))
  // One that waits for you is listed even when archived (and says so), as the badge counts it.
  const kept = sorted.filter(c => !c.archived_at || waits(c.id))
  const archived = sorted.filter(c => c.archived_at && !waits(c.id))
  // Each under its folder, by last activity under Today, Last 7 days and Older; one that waits says so on its row - all
  // of them together are Ready for you's (tek-ev §1).
  const rest = kept
  const groups = (list: ListedConversation[]) => ['Today', 'Last 7 days', 'Older'].map(day => [day, list.filter(c => dayOf(lastAt(c, on.get(c.id))) === day)] as const)
  // Each folder's chats under its name (slice 86a): the open tab's folder first and open, the others closed (86e) - the
  // one used last first, the chats with no folder last; with no chat open, all of them open.
  const keyOf = (c: ListedConversation) => tabOf(c.project_id)
  const current = conversations.find(c => c.id === currentId)
  const here = current ? keyOf(current) : null
  const openAtFirst = (key: string) => here === null || key === here
  const newest = (key: string) => Math.max(...rest.filter(c => keyOf(c) === key).map(c => lastAt(c, on.get(c.id))))
  const folders = [...new Set(rest.map(keyOf))].sort((a, b) => Number(b === here) - Number(a === here) || Number(a === 'none') - Number(b === 'none') || newest(b) - newest(a))
  const nameOf = (key: string) => (key === 'none' ? 'No folder' : (projects.find(p => p.id === key)?.name ?? 'A folder'))
  const isOpen = (key: string) => openAtFirst(key) !== turned.includes(key)
  // B-395: the rows on screen - not those under a closed folder.
  const visible = [...rest.filter(c => isOpen(keyOf(c))), ...archived]

  async function archive(c: ListedConversation, away: boolean) {
    setRefused(null)
    try {
      await onArchive(c.id, away)
    } catch (err) {
      setRefused(`${c.title} could not be ${away ? 'archived' : 'brought back'}: ${errorText(err)}`)
    }
  }

  // The rows ticked (slice 76): acted on only while the list shows them.
  const [picked, setPicked] = useState<string[]>([])
  const chosen = visible.filter(c => picked.includes(c.id))
  const toArchive = chosen.filter(c => !c.archived_at)
  const toDelete = chosen.filter(c => c.archived_at)
  async function archiveChosen() {
    for (const c of toArchive) await archive(c, true)
    setPicked([])
  }
  const confirm = useConfirm()
  function deleteChosen() {
    const n = toDelete.length
    const ids = toDelete.map(c => c.id)
    // (Not "for good": backups and a CLI's own transcripts may still hold copies.)
    const asked = `Delete ${n} archived ${n === 1 ? 'chat' : 'chats'} from KOLONİ? This cannot be undone in KOLONİ.`
    const more = 'Their messages, their agents’ work and what they spent on Usage go too; the project’s files and git are not touched.'
    confirm.ask(`${asked} ${more}`, 'Delete', () => void deleteNow(ids), 'Cancel')
  }
  async function deleteNow(ids: string[]) {
    setRefused(null)
    try {
      const told = await onDelete!(ids)
      setPicked(was => was.filter(id => !told.deleted.includes(id)))
      if (told.refused.length) setRefused(told.refused.map(one => `${one.title ?? 'A conversation'} was not deleted: ${one.why}`).join('; '))
    } catch (err) {
      setRefused(`Nothing was deleted: ${errorText(err)}`)
    }
  }

  const rows = (list: ListedConversation[], underArchived = false) => (
    <ul className="conv-list">
      {list.map(c => {
        const running = c.archived_at && !triggersPaused ? (triggers ?? []).filter(t => t.conversation_id === c.id && t.enabled).map(t => t.name) : []
        // Its last turn as the Board has it (of the folders it reads): its agents, model and tokens.
        const turn = on.get(c.id)?.turn
        const ran = turn && [count(turn.agents, 'agent'), ranOn(turn.provider_name, turn.model_id), turn.tokens != null && `${turn.tokens.toLocaleString('en-US')} tokens`]
        return (
          <li key={c.id} className="conv-item">
            <input
              type="checkbox"
              aria-label={`Select ${c.title}`}
              checked={picked.includes(c.id)}
              onChange={e => setPicked(was => (e.target.checked ? [...was, c.id] : was.filter(id => id !== c.id)))}
            />
            <button type="button" className="conv-row" aria-current={c.id === currentId ? 'true' : undefined} onClick={() => onOpen(c.id)}>
              <span className="conv-row-title" title={c.title}>
                {c.backlog_task && (
                  <span className="muted conv-row-todo" role="img" aria-label="From the to-do list" title="From the to-do list">
                    <ListChecks size={14} aria-hidden />
                  </span>
                )}
                {c.backlog_task && ' '}
                {c.title}
              </span>
              <span className="mono muted conv-row-when">
                <Standing on={on.get(c.id)} /> <TaskState task={c.backlog_task} on={on.get(c.id)} />{' '}
                {/* As its turn says in the turn list: over, and its changes still yours to take in or discard. */}
                {c.kept && <span className="tag turn-row-waits">changes kept</span>} {!underArchived && c.archived_at && <span className="tag">archived</span>}{' '}
                {ran && `${ran.filter(Boolean).join(' · ')} · `}
                {when(lastAt(c, on.get(c.id)))}
              </span>
            </button>
            <button type="button" className="btn btn-small" aria-label={`${c.archived_at ? 'Unarchive' : 'Archive'} ${c.title}`} onClick={() => void archive(c, !c.archived_at)}>
              {c.archived_at ? 'Unarchive' : 'Archive'}
            </button>
            {running.length > 0 && (
              <span className="muted conv-trigger">
                {running.length === 1 ? 'Its trigger' : 'Its triggers'} {running.join(', ')} still {running.length === 1 ? 'runs' : 'run'}
              </span>
            )}
          </li>
        )
      })}
    </ul>
  )

  return (
    <div className="conv-page">
      <div className="conv-head">
        <h2>Conversations</h2>
        <RefreshButton onRefresh={onRefresh} onError={setStale} />
        <div className="usage-filters">
          <input type="search" className="input" aria-label="Search conversations" placeholder="Search by name" value={query} onChange={e => setQuery(e.target.value)} />
          <select className="input" aria-label="Show" value={show} onChange={e => setShow(e.target.value as Show)}>
            {SHOW.map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
          <select className="input" aria-label="Sort by" value={by} onChange={e => setBy(e.target.value as 'date' | 'name')}>
            <option value="date">Last activity</option>
            <option value="name">Name</option>
          </select>
          <button type="button" className="btn btn-primary" title="A new chat in this chat’s folder" onClick={onNew}>
            <Plus size={14} />
            New chat
          </button>
          <GitHubIssue onStarted={onOpen} />
        </div>
      </div>
      {shown.length > 0 && (
        <div className="conv-bulk">
          <label className="conv-bulk-all">
            <input
              type="checkbox"
              aria-label="Select all shown"
              checked={visible.length > 0 && visible.every(c => picked.includes(c.id))}
              onChange={e => setPicked(e.target.checked ? visible.map(c => c.id) : [])}
            />
            Select all
          </label>
          <button type="button" className="btn btn-small" disabled={toArchive.length === 0} onClick={() => void archiveChosen()}>
            Archive selected ({toArchive.length})
          </button>
          {onDelete && (
            <button type="button" className="btn btn-small" title="Only archived conversations are deleted" disabled={toDelete.length === 0} onClick={deleteChosen}>
              Delete selected ({toDelete.length})
            </button>
          )}
        </div>
      )}
      {confirm.shown()}
      <Alert said={refused} />
      <Alert said={stale} />
      {conversations.length === 0 ? (
        <p className="muted">No conversations yet. Start one and it will be kept here.</p>
      ) : found.length === 0 ? (
        <p className="muted">No conversation has that in its name.</p>
      ) : shown.length === 0 ? (
        <p className="muted">{board ? `None of them is “${showLabel}”.` : 'How each conversation stands is not read yet.'}</p>
      ) : (
        <>
          {folders.map((key, folder) => {
            const list = rest.filter(c => keyOf(c) === key)
            const open = isOpen(key)
            return (
              <section key={key} className="memory-section" aria-labelledby={`${groupId}-${folder}`}>
                <h3 className="conv-folder">
                  <button type="button" id={`${groupId}-${folder}`} className="conv-folder-button" aria-expanded={open} onClick={() => toggle(key)}>
                    {open ? <CaretDown size={12} aria-hidden /> : <CaretRight size={12} aria-hidden />}
                    {key !== 'none' && <FolderSimple size={14} weight="fill" className="folder-icon" aria-hidden />}
                    {nameOf(key)}
                  </button>
                </h3>
                {open &&
                  (by === 'name'
                    ? rows(list)
                    : groups(list).map(
                        ([day, under], at) =>
                          under.length > 0 && (
                            <section key={day} className="memory-section" aria-labelledby={`${groupId}-${folder}-${at}`}>
                              <h4 id={`${groupId}-${folder}-${at}`} className="kicker">
                                {day}
                              </h4>
                              {rows(under)}
                            </section>
                          ),
                      ))}
              </section>
            )
          })}
          {archived.length > 0 && (
            <section className="memory-section" aria-label="Archived">
              <h3 className="kicker">Archived</h3>
              {rows(archived, true)}
            </section>
          )}
        </>
      )}
    </div>
  )
}
