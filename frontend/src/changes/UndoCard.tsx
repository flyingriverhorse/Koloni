import { ArrowCounterClockwise } from '@phosphor-icons/react'
import { type KeyboardEvent, useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import type { Undo } from '../api/types'
import { TEXT_CHARS } from '../canvas/turns'

interface Props {
  /** `/runs/{id}/undo`, or `/conversations/{cid}/restore?before={id}`: GET looks ahead, POST does it. */
  path: string
  /** What is asked: "Undo these changes", "Restore to before your 10:42 message". */
  title: string
  /** The word on the button that does it. */
  confirm: string
  onClose: () => void
}

function List({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null
  return (
    <section aria-label={label}>
      <div className="kicker">{label}</div>
      <ul className="undo-list mono">
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </section>
  )
}

/** The messages whose work is taken back, each by its own words: “Add a test”. */
function messages(turns: Undo['turns']): string[] {
  return turns.map(({ turn, request }) => {
    const cut = request.length > TEXT_CHARS ? `${request.slice(0, TEXT_CHARS)}…` : request
    return `${cut ? `“${cut}”` : 'A message with no words'}${turn === null ? ' (it never started)' : ''}`
  })
}

/**
 * Before a message's changes are undone (or the conversation put back to before one): whose, what
 * would be reverted, what is skipped and why, the kept working copies whose folders are deleted, and
 * what cannot be taken back (the commands, and what is not on record) - then, once confirmed, what
 * was done. The chat itself stays (slice 107 §6): it says so first.
 */
export function UndoCard({ path, title, confirm, onClose }: Props) {
  const [ahead, setAhead] = useState<Undo | null>(null)
  const [done, setDone] = useState<Undo | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let mine = true
    api.get<Undo>(path).then(
      undo => mine && setAhead(undo),
      err => mine && setError(errorText(err)),
    )
    return () => {
      mine = false
    }
  }, [path])

  async function go(seen: Undo) {
    setBusy(true)
    setError(null)
    // A restore takes back only the turns it showed: one that ended since is refused, to be looked at again.
    const last = seen.turns.at(-1)?.run_id
    const through = path.includes('/restore') && last ? `&through=${encodeURIComponent(last)}` : ''
    try {
      setDone(await api.post<Undo>(path + through))
    } catch (err) {
      setError(errorText(err))
      // What it would do now: some of it may have been done, or more may be there to take back.
      await api.get<Undo>(path).then(setAhead, () => {})
    } finally {
      setBusy(false)
    }
  }

  // The card's own Esc: what it stands in (the list of turns) stays open.
  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key !== 'Escape') return
    event.stopPropagation()
    onClose()
  }

  const shown = done ?? ahead
  const doable = ahead !== null && (ahead.revert.length > 0 || ahead.copies.length > 0)
  // Files were changed whatever was skipped or is not on record: then it is never "nothing".
  const nothing = shown !== null && [shown.revert, shown.skip, shown.copies, shown.stays].every(list => list.length === 0)
  return (
    <section className="cmd-approval undo-card" aria-label={title} onKeyDown={onKeyDown}>
      <div className="kicker cmd-approval-kicker" aria-live="polite">{done ? `${title}: done` : `${title}?`}</div>
      {shown === null && error === null && <p className="muted">Looking at what it would take back…</p>}
      {shown && (
        <>
          <p className="muted">
            The chat stays as it is: no message is deleted. What is taken back is what these messages changed in the files; a
            file changed since, or a change nobody knows who made, is skipped. What commands did, and notes put in memory, are
            not taken back.
          </p>
          <List label={done ? 'Messages whose changes were taken back' : 'Messages whose changes are taken back'} items={messages(shown.turns)} />
          {nothing && <p className="muted">{done ? 'Nothing was taken back.' : 'Nothing to take back.'}</p>}
          <List label={done ? 'Reverted' : 'Will be reverted'} items={shown.revert} />
          <List label={done ? 'Skipped' : 'Will be skipped'} items={shown.skip.map(s => `${s.path} — ${s.why}`)} />
          <List
            label={done ? 'Kept working copy discarded — the folder is deleted' : 'Kept working copy to discard — the folder is deleted'}
            items={shown.copies.map(copy => `${copy.folder} — these files exist only there: ${copy.files.join(', ') || 'none on record'}`)}
          />
          <List label="Commands run — what they did cannot be taken back" items={shown.commands} />
          <List label="Also not taken back" items={shown.stays} />
          {done?.note && (
            <p role="note" className="muted">
              {done.note}
            </p>
          )}
        </>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      <div className="change-actions">
        {ahead && !done && doable && (
          <button type="button" className="btn btn-small btn-primary" disabled={busy} onClick={() => void go(ahead)}>
            <ArrowCounterClockwise size={13} />
            {confirm}
          </button>
        )}
        {/* (The focus is on the card from the start - the button that opened it is gone - and again once it is done: Esc closes it.) */}
        <button key={done ? 'close' : 'cancel'} type="button" className="btn btn-small" autoFocus onClick={onClose}>
          {done ? 'Close' : 'Cancel'}
        </button>
      </div>
    </section>
  )
}
