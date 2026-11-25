import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Away, Waiting } from '../api/types'
import { useAsk } from '../memory/useAsk'
import { useApp } from '../state/store'

/** What a decided row says: your word, never the agent's. */
const DECIDED: Record<string, (row: Waiting) => string> = {
  run: () => 'You said Run',
  reject: () => 'Rejected',
  answer: row => `Answered: ${row.answer ?? ''}`,
  stop: () => 'Stopped',
}

/** Where a command would run as it stands now (a copy taken in since: the project itself). */
const PLACE: Record<string, string> = { copy: 'Runs in its job’s copy', project: 'Runs in the project itself' }

/** The rows of a card, read again whenever the card is (a decision, Stop this task, the night's end). */
function useWaiting(away: Away): Waiting[] {
  const [rows, setRows] = useState<Waiting[]>([])
  useEffect(() => {
    let live = true
    api.get<Waiting[]>(`/away/${away.id}/waiting`).then(
      found => live && setRows(found),
      () => {},
    )
    return () => {
      live = false
    }
  }, [away])
  return rows
}

/**
 * ☾ Away, park and continue (§10): what the jobs parked for you while you were away - a command's card,
 * a question the Orchestrator could not answer - one list, task by task in the night's order. Run, Reject
 * or an answer, only once you are back and the job's turn is over; once a task's are all given, what you
 * said Run runs in its copy and its Orchestrator goes on. Stop this task closes the rest.
 */
export function WaitingForYou({ away }: { away: Away }) {
  const rows = useWaiting(away)
  const { busy, error, ask } = useAsk()
  if (!rows.length) return null
  const tasks = [...new Set(rows.map(row => row.task_id))]
  const decide = (row: Waiting, word: string, answer?: string) =>
    void ask(() => useApp.getState().awayDo(away.id, `waiting/${row.id}`, { word, answer }))
  return (
    <section className="away-sec waiting-for-you" aria-label="Waiting for you">
      <h4>Waiting for you</h4>
      {tasks.map(taskId => {
        const own = rows.filter(row => row.task_id === taskId)
        return (
          <div key={taskId} className="waiting-task">
            <div className="away-job">
              <b className="away-grow">{own[0].task}</b>
              {/* (A push is no decision its job waits on: Reject it.) */}
              {own.some(row => !row.decision && row.kind !== 'push') && (
                <button
                  type="button"
                  className="btn btn-small nodrag"
                  disabled={busy}
                  onClick={() => void ask(() => useApp.getState().awayDo(away.id, `jobs/${taskId}/stop`))}
                >
                  Stop this task
                </button>
              )}
            </div>
            <ol className="waiting-rows">
              {own.map(row =>
                row.kind === 'push' ? (
                  // (made again with a new commit: a new row - the notes seen of the old one go)
                  <PushRow key={`${row.id}:${row.tip}`} row={row} awayId={away.id} />
                ) : (
                  <WaitingRow key={row.id} row={row} busy={busy} decide={decide} />
                ),
              )}
            </ol>
          </div>
        )
      })}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </section>
  )
}

export type Decide = (row: Waiting, word: string, answer?: string) => void

/** What KOLONİ says of a parked row: why, where it would run, its card's words, a file an agent wrote it runs. */
function RowNotes({ row }: { row: Waiting }) {
  return (
    <>
      <div className="muted">
        {row.why}
        {row.cwd && row.cwd !== '.' ? ` · in ${row.cwd}` : ''}
        {row.place && PLACE[row.place] ? ` · ${PLACE[row.place]}` : ''}
      </div>
      {row.danger && row.danger !== row.why && <div className="muted">{row.danger}</div>}
      {row.wrote && <div className="muted">Runs a file an agent wrote: {row.wrote}</div>}
      {row.warn && (
        <div role="note" className="alert">
          {row.warn}
        </div>
      )}
    </>
  )
}

/** One parked row: the line or the question whole, why in KOLONİ's words, and your word on it. */
export function WaitingRow({ row, busy, decide }: { row: Waiting; busy: boolean; decide: Decide }) {
  return (
    <li className="waiting-row">
      <pre className="mono waiting-what">{row.what}</pre>
      <RowNotes row={row} />
      {row.decision ? (
        <div className="waiting-said">{(DECIDED[row.decision] ?? (() => row.decision))(row)}</div>
      ) : (
        <>
          {row.closed && <div className="muted waiting-closed">{row.closed}</div>}
          {row.kind === 'question' ? (
            <Answer row={row} busy={busy} decide={decide} />
          ) : (
            <div className="memory-actions">
              <button
                type="button"
                className="btn btn-small btn-primary nodrag"
                disabled={busy || !!row.closed}
                onClick={() => decide(row, 'run')}
              >
                Run
              </button>
              <button
                type="button"
                className="btn btn-small nodrag"
                disabled={busy || row.held}
                onClick={() => decide(row, 'reject')}
              >
                Reject
              </button>
            </div>
          )}
        </>
      )}
    </li>
  )
}

/** A parked question's answer: one of its options, or any line where it has none. */
function Answer({ row, busy, decide }: { row: Waiting; busy: boolean; decide: Decide }) {
  const [said, setSaid] = useState('')
  const off = busy || !!row.closed
  if (row.options.length)
    return (
      <div className="memory-actions">
        {row.options.map(option => (
          <button
            key={option}
            type="button"
            className="btn btn-small nodrag"
            disabled={off}
            onClick={() => decide(row, 'answer', option)}
          >
            {option}
          </button>
        ))}
      </div>
    )
  return (
    <div className="memory-actions">
      <input
        className="input nodrag"
        aria-label="Your answer"
        maxLength={4000}
        value={said}
        disabled={off}
        onChange={event => setSaid(event.target.value)}
      />
      <button
        type="button"
        className="btn btn-small btn-primary nodrag"
        disabled={off || !said.trim()}
        onClick={() => decide(row, 'answer', said.trim())}
      >
        Answer
      </button>
    </div>
  )
}

/** What a 409 of a push says KOLONİ notes first (`detail.notes`); null: another refusal. */
function notesOf(err: unknown): string[] | null {
  const raw = err instanceof ApiError && err.status === 409 ? (err.raw as { notes?: unknown }) : null
  return raw && Array.isArray(raw.notes) ? raw.notes.map(String) : null
}

/** A push row's buttons: its Run, its Run once KOLONİ noted something, its Reject. */
export type PushWords = [run: string, again: string, reject: string]
const PUSH_WORDS: PushWords = ['Run', 'Run anyway', 'Reject']

/**
 * 0.1.9: a job's push - its branch to origin as one commit by KOLONİ, once its other rows are decided and its going-on
 * turn is over. Run; where KOLONİ notes something first (git's config changed, what moved outside the branch), the notes
 * and Run again; why nothing went up where it did not (the row waits again); Reject leaves the branch as it is. `words`:
 * its buttons' (Ready for you's say what they do).
 */
export function PushRow({ row, awayId, words = PUSH_WORDS }: { row: Waiting; awayId: string; words?: PushWords }) {
  const [notes, setNotes] = useState<string[]>([])
  const { busy, error, ask } = useAsk()
  const go = (word: string) =>
    void ask(async () => {
      try {
        // (the commit the row shows: a Run is of that one, never of one made since)
        await useApp.getState().awayDo(awayId, `waiting/${row.id}`, { word, seen: notes, tip: row.tip })
      } catch (err) {
        const noted = notesOf(err)
        if (!noted) throw err
        setNotes(noted)
      }
    })
  return (
    <li className="waiting-row">
      <pre className="mono waiting-what">{row.what}</pre>
      <div className="muted">{row.why}</div>
      {row.result && <div className={row.decision ? 'waiting-said' : 'muted'}>{row.result}</div>}
      {!row.decision && (
        <>
          {row.closed && <div className="muted waiting-closed">{row.closed}</div>}
          {notes.map(note => (
            <div key={note} role="note" className="alert">
              {note}
            </div>
          ))}
          <div className="memory-actions">
            <button
              type="button"
              className="btn btn-small btn-primary nodrag"
              disabled={busy || !!row.closed}
              onClick={() => go('run')}
            >
              {notes.length ? words[1] : words[0]}
            </button>
            <button
              type="button"
              className="btn btn-small nodrag"
              disabled={busy || row.held}
              onClick={() => go('reject')}
            >
              {words[2]}
            </button>
          </div>
        </>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </li>
  )
}
