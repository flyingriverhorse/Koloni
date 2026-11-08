import { CaretDown, PencilSimple } from '@phosphor-icons/react'
import { type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from 'react'
import { errorText } from '../api/client'
import { StatusLabel } from '../shell/StatusLabel'
import { UndoCard } from '../changes/UndoCard'
import { ENDED_COLOR, type TurnRow, when, workText } from './turns'

/** How many of the newest messages "Recent" lists. */
export const RECENT = 5

interface Props {
  /** The conversation's messages as turns, oldest first. */
  rows: TurnRow[]
  /** The message whose work the canvas draws. */
  current: string | null
  onPick: (runId: string) => void
  /** The conversation: with it, each message can be restored to before. */
  conversationId?: string
  /** The topic of the message drawn, where the user can rename it. */
  topic?: { id: string; title: string } | null
  /** Give a topic another name. Throws with the server's reason. */
  onRename?: (topicId: string, title: string) => Promise<void>
}

/** What a message is restored to before, by its time: "Restore to before your 10:42 message". */
const restoreTitle = (row: Pick<TurnRow, 'unattended' | 'at'>) => `Restore to before ${row.unattended ? 'the' : 'your'} ${when(row.at)} message`

/** A message's row: its time, its first words, its work and how it stands - and Restore to before it. */
function Row({ row, current, onPick, restore }: { row: TurnRow; current: boolean; onPick: () => void; restore: ReactNode }) {
  const work = workText(row)
  return (
    <li className="recent-row">
      <button type="button" className="turn-row" aria-current={current ? 'true' : undefined} onClick={onPick}>
        <span className="turn-row-text">{row.unattended ? row.triggerName || 'A trigger' : row.text || 'No message'}</span>
        <span className="turn-row-meta mono">
          <span>{when(row.at)}</span>
          {work && <span>{work}</span>}
          <StatusLabel color={ENDED_COLOR[row.ended]}>{row.ended}</StatusLabel>
        </span>
        {row.waits && <span className="tag tag-warn turn-row-waits">waits for you</span>}
        {row.kept && <span className="tag turn-row-waits">changes kept</span>}
      </button>
      {restore}
    </li>
  )
}

/** The box a topic's name is changed in: Enter saves, Esc leaves it as it was. */
function Rename({ title, onSave, onClose }: { title: string; onSave: (title: string) => Promise<void>; onClose: () => void }) {
  const [draft, setDraft] = useState(title)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    // (The box's own Esc: the list stays open.)
    if (event.key === 'Escape') {
      event.stopPropagation()
      return onClose()
    }
    if (event.key !== 'Enter' || busy) return
    const name = draft.trim()
    // An empty name, or the one it has, is nothing to send.
    if (!name || name === title) return onClose()
    setBusy(true)
    try {
      await onSave(name)
      onClose()
    } catch (err) {
      setError(errorText(err))
      setBusy(false)
    }
  }

  return (
    <div className="topic-rename-box">
      <input
        className="input"
        aria-label="Topic name"
        value={draft}
        maxLength={200}
        autoFocus
        onChange={e => setDraft(e.target.value)}
        onKeyDown={event => void onKeyDown(event)}
        onBlur={() => !busy && !error && onClose()}
      />
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}

/**
 * "Recent", in the top bar (slice 107): the last few messages of the conversation, newest
 * first. A row picked is the one whose work the canvas draws; each can be restored to before.
 * Older ones are in the chat, from a message's ⋯. Picking a row, Esc, the button or a click
 * elsewhere closes the list.
 */
export function TurnList({ rows, current, onPick, conversationId, topic, onRename }: Props) {
  const [open, setOpen] = useState(false)
  const [restoring, setRestoring] = useState<string | null>(null)
  const [renaming, setRenaming] = useState(false)
  // The list closed: its card and its box are not there when it opens again.
  if (!open && (restoring || renaming)) {
    setRestoring(null)
    setRenaming(false)
  }
  const box = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const recent = rows.slice(-RECENT).reverse()
  // What waits for you further back: listed too, under them - the dot never points at nothing.
  const older = rows.slice(0, -RECENT).filter(row => row.waits).reverse()
  const waiting = rows.some(row => row.waits)

  useEffect(() => {
    if (!open) return
    const onClick = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('click', onClick, true)
    return () => document.removeEventListener('click', onClick, true)
  }, [open])

  // A message picked is drawn: the list closes over it, the focus back on its button.
  function pick(runId: string) {
    onPick(runId)
    setOpen(false)
    button.current?.focus()
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== 'Escape' || !open) return
    event.stopPropagation()
    setOpen(false)
    button.current?.focus()
  }

  // (Not while it is queued or at work: it would race what it writes.)
  const restore = (row: TurnRow) =>
    conversationId &&
    row.ended !== 'queued' &&
    row.ended !== 'working' &&
    (restoring === row.runId ? (
      <UndoCard
        path={`/conversations/${conversationId}/restore?before=${row.runId}`}
        title={restoreTitle(row)}
        confirm="Restore"
        onClose={() => setRestoring(null)}
      />
    ) : (
      <button type="button" className="link-btn recent-restore" onClick={() => setRestoring(row.runId)}>
        Restore to before this
      </button>
    ))

  return (
    <div className="turns" ref={box} onKeyDown={onKeyDown}>
      <button
        ref={button}
        type="button"
        className="btn btn-small turns-button"
        aria-expanded={open}
        aria-controls={open ? 'turn-list' : undefined}
        onClick={() => setOpen(!open)}
      >
        Recent
        {waiting && <span className="dot turn-list-dot" role="img" aria-label="something waits for you" />}
        <CaretDown size={12} />
      </button>
      {open && (
        <aside id="turn-list" className="turn-list" aria-label="Recent">
          <h3 className="kicker">Recent · last {RECENT}</h3>
          {rows.length === 0 && <p className="muted turn-list-empty">No message yet.</p>}
          <ul className="turn-rows">
            {recent.map(row => (
              <Row key={row.runId} row={row} current={row.runId === current} onPick={() => pick(row.runId)} restore={restore(row)} />
            ))}
          </ul>
          {older.length > 0 && (
            <section aria-label="Older, waits for you">
              <h3 className="kicker">Older · waits for you</h3>
              <ul className="turn-rows">
                {older.map(row => (
                  <Row key={row.runId} row={row} current={row.runId === current} onPick={() => pick(row.runId)} restore={restore(row)} />
                ))}
              </ul>
            </section>
          )}
          {rows.length > RECENT && <p className="muted turn-list-hint">Older ones: in the chat, from a message’s ⋯</p>}
          {topic && onRename && (
            <section aria-label="Topic">
              {renaming ? (
                <Rename title={topic.title} onSave={title => onRename(topic.id, title)} onClose={() => setRenaming(false)} />
              ) : (
                <div className="recent-topic">
                  <span className="muted turn-list-hint" title={topic.title}>
                    Topic: {topic.title}
                  </span>
                  <button type="button" className="icon-btn topic-rename" aria-label={`Rename ${topic.title}`} title="Rename this topic" onClick={() => setRenaming(true)}>
                    <PencilSimple size={12} />
                  </button>
                </div>
              )}
            </section>
          )}
        </aside>
      )}
    </div>
  )
}
