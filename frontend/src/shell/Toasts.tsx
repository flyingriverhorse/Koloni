import { Bell } from '@phosphor-icons/react'
import { type CSSProperties, useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AGENT_STATUS, titleOf } from '../agents/agentStatus'
import type { Board, Budget } from '../api/types'
import { waitCount } from '../board/waiting'
import { TERMINAL } from '../state/applyEvent'
import { budgetWarning } from '../usage/budgetText'
import type { Near } from '../usage/limitsText'
import { type Policy, type Said, admit, fresh as freshPolicy, settle } from './toastPolicy'
import { usePanel } from './usePanel'

const NONE: Near[] = []
const SAME_WINDOW_MS = 600_000

interface Note extends Said {
  /** One per thing: a conversation's waits (a second one updates it), a turn's end, or the budget. */
  key: string
  /** Null: of the project, not a conversation - Open goes to Usage. */
  conversationId: string | null
  /** When it was last said: said again, it stays its six seconds from then. */
  at: number
}

/** A note as the Recent notifications list keeps it: whether it was shown as a toast. */
type Kept = Note & { shown: boolean }

const SHOWN_MS = 6000
const AT_MOST = 3
// shortcut: the list keeps the last 50 notes, and only until the page is loaded again; keep them on the server if missed.
const KEPT = 50

type Agents = Board['conversations'][number]['agents']
const asks = (agent: Agents[number]) => agent.status === 'waiting_approval' || agent.status === 'proposed'

/** What changed for the user between two readings of the Board: something began to wait, or a turn ended. */
function news(before: Board, after: Board, at: number): Note[] {
  const was = new Map(before.conversations.map(c => [c.conversation_id, c]))
  return after.conversations.flatMap(c => {
    const old = was.get(c.conversation_id)
    const notes: Note[] = []
    if (waitCount(c) > (old ? waitCount(old) : 0)) {
      // Said of what is new: an agent that began to ask, or else changes put before you, or a plan.
      const asked = new Set(old?.agents.filter(asks).map(a => a.id))
      const merged = c.merges_pending > (old?.merges_pending ?? 0)
      const planned = Boolean(c.turn?.plan_waits) && !(old?.turn?.id === c.turn?.id && old?.turn?.plan_waits)
      const who = c.agents.find(a => asks(a) && !asked.has(a.id)) ?? (merged || planned ? undefined : c.agents.find(asks))
      const what = who ? `${titleOf(who.name)} waits` : planned && !merged ? 'A plan waits' : 'Changes wait'
      notes.push({ key: `waits ${c.conversation_id}`, source: c.conversation_id, conversationId: c.conversation_id, text: `${what} for you · ${c.title}`, at })
    }
    const turn = c.turn
    const ended = turn && TERMINAL.has(turn.status) && (old?.turn?.id !== turn.id || !TERMINAL.has(old.turn.status))
    if (ended) {
      notes.push({
        key: `turn ${turn.id}`,
        source: c.conversation_id,
        conversationId: c.conversation_id,
        text: `${AGENT_STATUS[turn.status][0].replace(/^./, first => first.toUpperCase())} · ${c.title}`,
        error: turn.status === 'failed',
        at,
      })
    }
    // A queued turn is the last one on the Board from when it is sent: it starts only once the turn before it ended
    // (how is not read - that turn is no longer on the Board). One that also ended since it was read queued: its own
    // end, just told, says it all (B-200).
    if (!ended && turn?.started_at && old?.turn?.id === turn.id && old.turn.status === 'queued') {
      notes.push({ key: `started ${turn.id}`, source: c.conversation_id, conversationId: c.conversation_id, text: `Your queued message started · ${c.title}`, at })
    }
    return notes
  })
}

interface ToastProps {
  note: Note
  onOpen: (conversationId: string | null) => void
  onGone: (key: string) => void
  onHeld: (key: string, held: boolean) => void
}

function Toast({ note, onOpen, onGone, onHeld }: ToastProps) {
  // Held while the pointer or the focus is on it: what is being read or reached for does not go.
  const [held, setHeld] = useState(false)
  useEffect(() => {
    onHeld(note.key, held)
    if (held) return
    const timer = setTimeout(() => onGone(note.key), SHOWN_MS)
    return () => clearTimeout(timer)
  }, [held, note.key, note.at, onGone, onHeld])
  return (
    <div className="toast" onMouseEnter={() => setHeld(true)} onMouseLeave={() => setHeld(false)} onFocus={() => setHeld(true)} onBlur={() => setHeld(false)}>
      <span>
        {note.text}
        {(note.count ?? 1) > 1 && ` ×${note.count}`}
      </span>
      <button
        type="button"
        className="btn btn-small"
        onClick={() => {
          onOpen(note.conversationId)
          onGone(note.key)
        }}
      >
        Open
      </button>
    </div>
  )
}

interface Props {
  /** The project's Board as last read; null while it is not (a project just opened). */
  board: Board | null
  /** This month's spend against the project's budget, as last read. */
  budget?: Budget | null
  /** The plans' windows near their limit, as last read (`PlanUse`). */
  near?: Near[]
  /** The conversation that is on screen, if one is: nothing is said of it here. */
  shownId: string | null
  onOpen: (conversationId: string) => void
  onUsage?: () => void
  /** Where the bell of Recent notifications stands (in the top bar); none: no bell. */
  bellIn?: HTMLElement | null
}

/**
 * Small notes in the bottom right corner for what happens out of sight: something in another
 * conversation, or on another page, begins to wait for you, or a turn ends. Each once, at most
 * three at a time (one being read or reached for is not the one that goes), for six seconds;
 * read out politely. The same note is not shown again within a minute, nor more than four of one
 * source a minute; an error is counted, never dropped (`toastPolicy`). The bell in the top bar lists
 * every note, shown or not.
 */
export function Toasts({ board, budget = null, near = NONE, shownId, onOpen, onUsage, bellIn = null }: Props) {
  const before = useRef<Board | null>(null)
  const budgetBefore = useRef<Budget | null>(null)
  const held = useRef(new Set<string>())
  const [notes, setNotes] = useState<Note[]>([])
  const drop = useCallback((key: string) => {
    held.current.delete(key)
    setNotes(shown => shown.filter(note => note.key !== key))
  }, [])
  const hold = useCallback((key: string, on: boolean) => void (on ? held.current.add(key) : held.current.delete(key)), [])
  const put = useCallback((fresh: Note[]) => {
    setNotes(shown => {
      const next = [...shown.filter(note => !fresh.some(f => f.key === note.key)), ...fresh]
      // Over three: the oldest that nobody is reading goes.
      while (next.length > AT_MOST) {
        const gone = next.findIndex(note => !held.current.has(note.key))
        if (gone < 0) break
        next.splice(gone, 1)
      }
      return next
    })
  }, [])
  // Every note goes on the Recent list; which are shown as toasts, `toastPolicy` says.
  const policy = useRef<Policy<Note>>(freshPolicy())
  const [kept, setKept] = useState<Kept[]>([])
  const keep = useCallback((said: Kept[]) => setKept(was => [...said.reverse(), ...was].slice(0, KEPT)), [])
  const owedTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  // An error owed is said once its source has room again: looked at then, whether anything else is said or not.
  const settleOwed = useCallback(
    function look() {
      clearTimeout(owedTimer.current)
      const [next, said, again] = settle(policy.current, Date.now())
      policy.current = next
      if (said.length > 0) {
        put(said)
        keep(said.map(note => ({ ...note, shown: true })))
      }
      if (again !== null) owedTimer.current = setTimeout(look, Math.max(0, again - Date.now()))
    },
    [put, keep],
  )
  useEffect(() => () => clearTimeout(owedTimer.current), [])
  const say = useCallback(
    (fresh: Note[]) => {
      const shown: Note[] = []
      const said = fresh.map(note => {
        const [next, show] = admit(policy.current, note)
        policy.current = next
        if (show) shown.push(show)
        return { ...note, shown: show !== null }
      })
      if (shown.length > 0) put(shown)
      keep(said)
      settleOwed()
    },
    [put, keep, settleOwed],
  )

  useEffect(() => {
    const was = before.current
    before.current = board
    // The first reading (of a project just opened) is how things stand, not news.
    if (!was || !board) return
    const fresh = news(was, board, Date.now()).filter(note => note.conversationId !== shownId)
    // (News of a reading of the Board: the notes are what this effect is for.)
    if (fresh.length > 0) say(fresh)
  }, [board, shownId, say])

  // The budget reaching 80% is said once, as it is crossed: a month starts under it again.
  // shortcut: crossed while KOLONİ's page was closed, only the top bar's pill says it; keep the month told if that is missed.
  useEffect(() => {
    const was = budgetBefore.current
    budgetBefore.current = budget
    if (was && budget && budget.warn && !was.warn) say([{ key: 'budget', source: 'budget', conversationId: null, text: budgetWarning(budget), at: Date.now() }])
  }, [budget, say])

  // A plan's window near its limit is said once for each time it resets: when first seen there (no bar warns of it as
  // the budget's pill does), and again for a later window. Its reset said by another of the CLI's ways, minutes apart,
  // is the same window (app/limits.py SAME_WINDOW).
  // shortcut: what was said is forgotten when the page is loaded again, which says it once more; keep it if that annoys.
  const told = useRef(new Map<string, number | null>())
  useEffect(() => {
    const fresh = near.filter(({ key, resets_at }) => {
      const resets = resets_at ? Date.parse(resets_at) : null
      const was = told.current.get(key)
      if (told.current.has(key) && !(resets !== null && was != null && resets - was > SAME_WINDOW_MS)) return false
      told.current.set(key, resets)
      return true
    })
    if (fresh.length > 0) say(fresh.map(({ key, text }) => ({ key: `near ${key}`, source: 'near', conversationId: null, text, at: Date.now() })))
  }, [near, say])

  const open = (id: string | null) => (id ? onOpen(id) : onUsage?.())
  return (
    <div className="toasts" aria-live="polite" style={notes.length > 0 ? clearOfButtons() : undefined}>
      {notes.map(note => (
        <Toast key={note.key} note={note} onOpen={open} onGone={drop} onHeld={hold} />
      ))}
      {/* (Not in the live region: the bell is not news.) */}
      {kept.length > 0 && bellIn && createPortal(<Recent kept={kept} onOpen={open} />, bellIn)}
    </div>
  )
}

/** Clear of the canvas's buttons where they stand under the notes (bottom right, slice 66): beside them, at the foot as
 * elsewhere (the user's, 6 Nov: above their tall column the notes stood high up), or above them in a window too narrow
 * for a note beside them. 436px is the widest a note stands from the right edge (board.css .toasts).
 * (Read as the notes are drawn: buttons that come or move later are seen with the next note.) Right of the chat too
 * where it floats over the canvas's foot (base.css .chat): not over its message box.
 * shortcut: the notes are taken as at most 200px tall; measure them if three long ones are seen over a chat higher up.
 * Beside the buttons they stay under "What was said" on the canvas's right (canvas/saidSide.ts ends it above them); above
 * the buttons, in a narrow window, they may lie over its foot for their six seconds - move them if that is met. */
function clearOfButtons(): CSSProperties | undefined {
  const buttons = document.querySelector('.react-flow__controls')?.getBoundingClientRect()
  // (display: none draws a box of nothing: nothing to keep clear of.)
  if (!buttons?.width || buttons.right <= window.innerWidth - 436) return undefined
  const chat = document.querySelector('.chat')?.getBoundingClientRect()
  const atFoot = chat && chat.width > 0 && chat.right < buttons.left && chat.bottom > window.innerHeight - 16 - 200
  const room = buttons.left - 8 - (atFoot ? chat.right + 8 : 16)
  if (room < 300) return { bottom: window.innerHeight - buttons.top + 8 }
  return { right: window.innerWidth - buttons.left + 8, maxWidth: Math.min(420, room) }
}

/** The top bar's bell, from the first note on: every note of this page, newest first - also those not shown - with Open. */
function Recent({ kept, onOpen }: { kept: Kept[]; onOpen: (conversationId: string | null) => void }) {
  const { open, setOpen, close, button, panel } = usePanel()
  const hidden = kept.filter(note => !note.shown).length
  const label = `Notifications${hidden > 0 ? `, ${hidden} not shown` : ''}`
  return (
    <>
      <button ref={button} type="button" className="btn btn-small" aria-label={label} title={`Recent notifications${hidden > 0 ? `: ${hidden} not shown` : ''}`} aria-expanded={open} onClick={() => (open ? close() : setOpen(true))}>
        <Bell size={13} />
        {hidden > 0 && hidden}
      </button>
      {open && (
        <div ref={panel} tabIndex={-1} className="allow-list-panel" role="dialog" aria-label="Recent notifications">
          <div className="kicker">Recent notifications</div>
          <ul className="recent-list">
            {kept.map((note, n) => (
              <li key={n}>
                <span className="mono muted">{new Date(note.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                <span className="recent-text">
                  {note.text}
                  {!note.shown && <span className="muted"> · not shown</span>}
                </span>
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => {
                    onOpen(note.conversationId)
                    close()
                  }}
                >
                  Open
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  )
}
