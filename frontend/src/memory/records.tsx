import { type KeyboardEvent, useState } from 'react'
import type { MemoryRecord } from '../api/types'
import { usePanel } from '../shell/usePanel'
import { leftHow, rowId, waitId } from './memoryText'
import { Evidence, RecordBody, RecordCard } from './RecordCard'
import { MAX_ABOUT, MAX_TEXT, useAsk } from './useAsk'

/** Up and down move between a menu's items. */
function moveFocus(event: KeyboardEvent<HTMLDivElement>) {
  const step = ({ ArrowDown: 1, ArrowUp: -1 } as Record<string, number>)[event.key]
  if (!step) return
  event.preventDefault()
  const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'))
  const at = items.indexOf(document.activeElement as HTMLElement)
  items[at < 0 ? (step > 0 ? 0 : items.length - 1) : (at + step + items.length) % items.length]?.focus()
}

/** A row's ⋯: its less frequent actions, as the chat's message menu opens them. `of`: the row's words, for a screen reader. */
export function RowMenu({ of, items, disabled }: { of: string; items: [string, () => void][]; disabled?: boolean }) {
  const { open, setOpen, close, button, panel } = usePanel()
  const label = `More for “${of.length > 60 ? `${of.slice(0, 60)}…` : of}”`
  return (
    <>
      <button
        ref={button}
        type="button"
        className="btn btn-small"
        aria-label={label}
        title="More"
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => (open ? close() : setOpen(true))}
      >
        ⋯
      </button>
      {open && (
        <div ref={panel} tabIndex={-1} className="allow-list-panel msg-menu" role="menu" aria-label={label} onKeyDown={moveFocus}>
          {items.map(([name, act]) => (
            <button
              key={name}
              type="button"
              role="menuitem"
              onClick={() => {
                close()
                act()
              }}
            >
              {name}
            </button>
          ))}
        </div>
      )}
    </>
  )
}

interface CoreProps {
  record: MemoryRecord
  onCorrect: (id: string, changes: { text: string; about: string | null }) => Promise<void>
  onReject: (id: string) => Promise<void>
  /** Of a source that moved: these are the same lines. */
  onConfirm: (id: string) => Promise<void>
}

/**
 * A fact of the core, one row: corrected (a new record takes its place) or removed (it goes to
 * Past). One whose source changed or moved is looked at again: its lines unfold under it. Moved,
 * you can say they are the same lines; changed, the server would refuse that, so it is not offered.
 */
export function CoreFact({ record, onCorrect, onReject, onConfirm }: CoreProps) {
  const { busy, error, ask } = useAsk()
  const [editing, setEditing] = useState(false)
  const [looking, setLooking] = useState(false)
  const [text, setText] = useState(record.text)
  const [about, setAbout] = useState(record.about ?? '')
  // No work can name it, so it is never given unasked: it has no subject, or one made of
  // words that say nothing. Which subjects those are is the backend's to say (given_unasked).
  const note = record.given_unasked
    ? undefined
    : record.about
      ? 'this subject is too general to be matched: only found by looking it up'
      : 'no subject: only found by looking it up'
  const stale = record.source_state === 'changed' || record.source_state === 'moved'
  const remove = () => void ask(() => onReject(record.id))
  return (
    <RecordCard
      record={record}
      error={error}
      note={note}
      id={rowId(record.id)}
      actions={
        <div className="memory-actions">
          {stale && (
            <button type="button" className="btn btn-small" aria-expanded={looking} onClick={() => setLooking(!looking)}>
              Look again
            </button>
          )}
          <RowMenu of={record.text} disabled={busy} items={[['Correct', () => setEditing(true)], ['Remove', remove]]} />
        </div>
      }
    >
      {looking && !editing && (
        <div role="group" aria-label="Its lines now" className="memory-look">
          <Evidence record={record} />
          <div className="memory-actions">
            {record.source_state === 'moved' && (
              <button type="button" className="btn btn-small" disabled={busy} onClick={() => void ask(() => onConfirm(record.id))}>
                These are the same lines
              </button>
            )}
            <button type="button" className="btn btn-small" disabled={busy} onClick={() => setEditing(true)}>
              Correct
            </button>
            <button type="button" className="btn btn-small" disabled={busy} onClick={remove}>
              Remove
            </button>
          </div>
        </div>
      )}
      {editing && (
        <form
          className="memory-edit"
          onSubmit={event => {
            event.preventDefault()
            void ask(() => onCorrect(record.id, { text: text.trim(), about: about.trim() || null })).then(
              done => done && setEditing(false),
            )
          }}
        >
          <div className="field">
            <label htmlFor={`fact-${record.id}`}>Fact</label>
            <textarea
              id={`fact-${record.id}`}
              className="input"
              rows={3}
              maxLength={MAX_TEXT}
              value={text}
              onChange={e => setText(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor={`about-${record.id}`}>Subject</label>
            <input
              id={`about-${record.id}`}
              className="input"
              maxLength={MAX_ABOUT}
              value={about}
              onChange={e => setAbout(e.target.value)}
            />
          </div>
          <div className="memory-actions">
            <button type="submit" className="btn btn-small btn-primary" disabled={busy || !text.trim()}>
              Save correction
            </button>
            <button type="button" className="btn btn-small" disabled={busy} onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </RecordCard>
  )
}

interface ProposalProps {
  record: MemoryRecord
  /** The fact of the core it would take the place of, if any. */
  replaces?: MemoryRecord
  onApprove: (id: string, text?: string) => Promise<void>
  onReject: (id: string) => Promise<void>
  /** Of a source that moved: these are the same lines. */
  onConfirm: (id: string) => Promise<void>
}

/** A note that waits for you: into the core as it is, in your words, or not at all. */
export function Proposal({ record, replaces, onApprove, onReject, onConfirm }: ProposalProps) {
  const { busy, error, ask } = useAsk()
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(record.text)
  return (
    <article className="memory-record" id={waitId(record.id)} tabIndex={-1}>
      {replaces ? (
        <div className="memory-pair">
          <div role="group" aria-label="Would replace" className="memory-side">
            <div className="kicker">Would replace</div>
            <RecordBody record={replaces} />
          </div>
          <div role="group" aria-label="Put forward" className="memory-side">
            <div className="kicker">Put forward</div>
            <RecordBody record={record} evidence />
          </div>
        </div>
      ) : (
        <RecordBody record={record} evidence />
      )}
      {editing && (
        <div className="field">
          <label htmlFor={`edit-${record.id}`}>Fact</label>
          <textarea
            id={`edit-${record.id}`}
            className="input"
            rows={3}
            maxLength={MAX_TEXT}
            value={text}
            onChange={e => setText(e.target.value)}
          />
        </div>
      )}
      <div className="memory-actions">
        {record.source_state === 'moved' && (
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => void ask(() => onConfirm(record.id))}>
            These are the same lines
          </button>
        )}
        <button
          type="button"
          className="btn btn-small btn-primary"
          disabled={busy}
          onClick={() => void ask(() => onApprove(record.id, undefined))}
        >
          Approve
        </button>
        {editing ? (
          <button
            type="button"
            className="btn btn-small"
            disabled={busy || !text.trim()}
            onClick={() => void ask(() => onApprove(record.id, text.trim()))}
          >
            Approve as edited
          </button>
        ) : (
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => setEditing(true)}>
            Edit and approve
          </button>
        )}
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => void ask(() => onReject(record.id))}>
          Reject
        </button>
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </article>
  )
}

/**
 * An agent's note in the journal, one row. It is the agent's word: not rewritten, but it can be
 * removed, or taken as the start of a fact of your own.
 */
export function JournalNote({ record, onReject, onMakeFact }: { record: MemoryRecord; onReject: (id: string) => Promise<void>; onMakeFact: (record: MemoryRecord) => void }) {
  const { busy, error, ask } = useAsk()
  return (
    <RecordCard
      record={record}
      error={error}
      id={rowId(record.id)}
      note={record.wants_core ? 'put forward for the core' : undefined}
      actions={<RowMenu of={record.text} disabled={busy} items={[['Remove', () => void ask(() => onReject(record.id))], ['Make it a fact', () => onMakeFact(record)]]} />}
    />
  )
}

/** A line KOLONİ's summariser suggests for your preferences (22b): added by you, or not. Never by itself. */
export function Suggestion({ record, onAdd, onReject }: { record: MemoryRecord; onAdd: (id: string) => Promise<void>; onReject: (id: string) => Promise<void> }) {
  const { busy, error, ask } = useAsk()
  return (
    <RecordCard
      record={record}
      error={error}
      id={rowId(record.id)}
      actions={
        <div className="memory-actions">
          <button type="button" className="btn btn-small btn-primary" disabled={busy} onClick={() => void ask(() => onAdd(record.id))}>
            Add
          </button>
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => void ask(() => onReject(record.id))}>
            Reject
          </button>
        </div>
      }
    />
  )
}

/** A record that is no longer in effect: still on record, and it can be taken back. */
export function PastRecord({ record, onRestore }: { record: MemoryRecord; onRestore: (id: string) => Promise<void> }) {
  const { busy, error, ask } = useAsk()
  return (
    <RecordCard
      record={record}
      error={error}
      id={rowId(record.id)}
      note={`${record.tier === 'fact' ? 'fact' : 'note'} · ${leftHow(record)}`}
      actions={
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => void ask(() => onRestore(record.id))}>
          Take back
        </button>
      }
    />
  )
}
