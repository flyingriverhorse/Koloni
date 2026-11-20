import { type FormEvent, useState } from 'react'
import { errorText } from '../api/client'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { NoteList } from './NoteList'
import { closedReason, noteId, notebookRun, notebookRuns, turnLabel } from './notesText'

interface Props {
  state: ConvState | null
  onWrite: (runId: string, content: string) => Promise<void>
}

type Turns = ReturnType<typeof notebookRuns>
type Turn = Turns[number] | ReturnType<typeof notebookRun>

/** At the top, where more than one turn has a notebook: whose notes are shown, and the way to another's. */
const turnPicker = (state: ConvState | null, run: Turn, turns: Turns, current: Turn, setPicked: (runId: string | null) => void) =>
  state &&
  run &&
  turns.length > 1 && (
    <div className="note-turns">
      <select
        className="input"
        aria-label="Whose notes"
        value={run.id}
        // Picking the turn the tab would show anyway is picking none: it goes on following.
        onChange={e => setPicked(e.target.value === current?.id ? null : e.target.value)}
      >
        {turns.map(turn => (
          <option key={turn.id} value={turn.id}>
            {turnLabel(state, turn)}
          </option>
        ))}
      </select>
    </div>
  )

/** No note can be posted: the notebook is closed, one is on its way, or nothing is written. */
const cannotPost = (closed: ReturnType<typeof closedReason>, busy: boolean, draft: string) => closed !== null || busy || !draft.trim()

/**
 * The shared notebook of a turn: what its agents and you noted for everyone. It shows the
 * turn at work (or the last one) until you pick an earlier turn at the top; the notebook
 * of a turn that is over can be read, not written on. Nobody waits for a note; each agent
 * is handed it before its next step. You can write one while the turn is at work.
 */
export function NotesPanel({ state, onWrite }: Props) {
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // The turn you picked; null to follow the turn at work, as long as you picked none.
  const [picked, setPicked] = useState<string | null>(null)

  const turns = state ? notebookRuns(state) : []
  const current = state ? notebookRun(state) : null
  // A note the canvas asked for (K-shared-bagli): its turn's notebook, whichever turn it is.
  const at = useApp(s => s.chatAt)
  const [seen, setSeen] = useState<string | null>(null)
  if (at !== seen) {
    setSeen(at)
    const asked = state?.boardPosts.find(p => noteId(p.id) === at)
    if (asked) setPicked(asked.run_id === current?.id ? null : asked.run_id)
  }
  const run = turns.find(r => r.id === picked) ?? current
  const empty = !state || !run || !state.boardPosts.some(p => p.run_id === run.id)
  const closed = closedReason(run)

  async function write(event: FormEvent) {
    event.preventDefault()
    const content = draft.trim()
    if (!content || !run) return
    setBusy(true)
    setError(null)
    try {
      await onWrite(run.id, content)
      setDraft('')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {turnPicker(state, run, turns, current, setPicked)}
      {empty ? (
        <div className="msg-list msg-empty muted">
          Notes that agents and you leave for everyone working on a message show here.
        </div>
      ) : (
        <div className="msg-list channel">
          <NoteList state={state} runId={run.id} />
        </div>
      )}
      <form className="discussion-say" onSubmit={write}>
        <input
          className="input"
          aria-label="A note for every agent working on this request"
          placeholder="A note for every agent working on this request"
          maxLength={1500}
          value={draft}
          disabled={closed !== null}
          onChange={e => setDraft(e.target.value)}
        />
        <button type="submit" className="btn btn-small btn-primary" disabled={cannotPost(closed, busy, draft)}>
          Post note
        </button>
      </form>
      {closed && <div className="mono muted note-closed">{closed}</div>}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </>
  )
}
