import { useState } from 'react'
import { useNow } from '../agents/useNow'
import { api, errorText } from '../api/client'
import type { Message } from '../api/types'
import { isKept } from '../changes/copies'
import { useApp } from '../state/store'
import { FIX_HELD, fixOf, originUndone, runClock } from './checked'

type Row = NonNullable<Message['checked']>[number]

/** Each row's mark by its state; the rest (not run, timed out, a note) "–". */
const MARK: Partial<Record<Row['state'], string>> = { passed: '✓', failed: '✗', running: '…' }

/**
 * Under a turn's answer, once it is over: what KOLONİ checked at its end and what it did not - one line a row, from its
 * records, never the model's words. On the latest turn, where a test run failed, Fix it asks for the fix in a new message.
 * A whole suite gone on after the answer (S6) ticks its clock, and Stop this check ends it.
 */
export function CheckedSection({ message, over, latest }: { message?: Message; over: boolean; latest: boolean }) {
  const rows = message?.checked
  if (!message || !over || !rows?.length) return null
  return (
    <section
      className="checked"
      id={message.run_id ? `checked-${message.run_id}` : undefined}
      tabIndex={-1}
      aria-label="Checked"
      title="From KOLONİ’s records, not the model’s words"
    >
      <span className="checked-head">Checked</span>
      <ul className="checked-rows">
        {rows.map((row, index) => (
          <CheckedRow key={index} row={row} runId={message.run_id} />
        ))}
      </ul>
      {latest && <LatestActions rows={rows} runId={message.run_id} />}
      {message.run_id && rows.some(row => row.state === 'running') && <StopCheck runId={message.run_id} />}
    </section>
  )
}

/**
 * The latest turn's buttons: Fix it (or, for work not taken in, Take in anyway and Fix it - N3: only while its kept copy
 * waits; taken in, said so, and Fix it as for work in the project), Run these. N10b: no Fix it once the turn its failing
 * lines come from is undone.
 */
function LatestActions({ rows, runId }: { rows: Row[]; runId: string | null }) {
  const undone = useApp(s => Boolean(s.conv && runId && originUndone(s.conv, runId)))
  const fix = undone ? null : fixOf(rows)
  const offer = rows.find(row => row.kind === 'ci_offer')?.offer
  const held = rows.find(row => row.kind === 'not_taken')
  const kept = useKept(held)
  return (
    <>
      {held && kept === 'taken' && <span role="status">Taken in anyway.</span>}
      {fix && (!held || kept === 'taken') && <FixIt asked={fix} />}
      {held && kept === 'waits' && <NotTaken row={held} runId={runId} />}
      {runId && offer && <RunThese runId={runId} offer={offer} />}
    </>
  )
}

/** How a "not_taken" row's kept copy stands now, by its merge (after a reload too): it waits for the user (or is not known here), was taken in, or is gone - discarded, or gone on in a Fix it turn. */
function useKept(row: Row | undefined): 'waits' | 'taken' | 'gone' {
  const merge = useApp(s => s.conv?.merges.find(m => row?.merge_id != null && m.id === row.merge_id))
  if (!merge) return 'waits'
  if (merge.status === 'applied' || merge.files.some(one => one.state === 'applied')) return 'taken'
  return isKept(merge) ? 'waits' : 'gone'
}

function CheckedRow({ row, runId }: { row: Row; runId: string | null }) {
  return (
    <li className="checked-row" data-state={row.state}>
      <span className="checked-mark" aria-hidden>
        {MARK[row.state] ?? '–'}
      </span>
      <span>{row.text}</span>
      {row.state === 'running' && row.started_at && <RunningFor since={row.started_at} />}
      {row.guessed && <span className="tag">guessed</span>}
      {row.kind === 'changed_during' && runId && <PutBack runId={runId} />}
    </li>
  )
}

/** CL-329: files that changed while KOLONİ's own run went on - Put back is the user's click (never KOLONİ's by itself): each as it was before the run, where it is still as the run left it. Each turn's button is its own run's (CL-340: an older turn's too - a file changed since is refused, said). */
const PUT_BACK_TITLE =
  'Puts back the files this line names, as they were before this turn’s run - not one changed since'

function PutBack({ runId }: { runId: string }) {
  const [said, setSaid] = useState<string | null>(null)
  const put = () =>
    api.post<{ put_back: string[]; refused: { path: string; why: string }[] }>(`/runs/${runId}/check/put-back`).then(
      done =>
        setSaid(
          [
            done.put_back.length ? `Put back: ${done.put_back.join(', ')}.` : '',
            ...done.refused.map(one => `Not put back: ${one.why}.`),
          ]
            .filter(Boolean)
            .join(' '),
        ),
      err => setSaid(errorText(err)),
    )
  return (
    <span className="checked-fix">
      <button type="button" className="btn btn-small" title={PUT_BACK_TITLE} onClick={() => void put()}>
        Put back
      </button>
      {said && <span role="status">{said}</span>}
    </span>
  )
}

/** " (2:14)": how long it has run, read every second. */
export function RunningFor({ since }: { since: string }) {
  return <span className="muted"> ({runClock(since, useNow(1000))})</span>
}

export function FixIt({ asked }: { asked: string }) {
  const [error, setError] = useState<string | null>(null)
  return (
    <span className="checked-fix">
      <button
        type="button"
        className="btn btn-small"
        onClick={() =>
          useApp
            .getState()
            .send(asked)
            .then(
              () => setError(null),
              err => setError(errorText(err)),
            )
        }
      >
        Fix it
      </button>
      {error && <span role="alert">{error}</span>}
    </span>
  )
}

/** S11 (decision 18): failing work not taken in - Take in anyway takes its kept copy in, the user's word; Fix it sends their answer to the stronger model's question. No pop-up card. */
function NotTaken({ row, runId }: { row: Row; runId: string | null }) {
  const [said, setSaid] = useState<string | null>(null)
  const [answering, setAnswering] = useState(false)
  const question = row.question ?? ''
  return (
    <span className="checked-fix">
      {row.merge_id && (
        <button
          type="button"
          className="btn btn-small"
          title="Takes the kept work in as it is, at your word - no Reviewer looks at it first"
          onClick={() =>
            api.post(`/merges/${row.merge_id}/approve`).then(
              () => setSaid('Taken in.'),
              err => setSaid(errorText(err)),
            )
          }
        >
          Take in anyway
        </button>
      )}
      <button type="button" className="btn btn-small" onClick={() => setAnswering(true)}>
        Fix it
      </button>
      {answering && (
        <Answer
          question={question}
          reason={row.reason}
          onError={setSaid}
          held={runId && row.merge_id ? { runId, mergeId: row.merge_id } : null}
        />
      )}
      {said && <span role="status">{said}</span>}
    </span>
  )
}

/** Fix it's answer to the question: a turn that goes on in the kept work's copy where there is one (else a new message of the user's). */
function Answer({
  question,
  reason,
  onError,
  held,
}: {
  question: string
  reason?: Row['reason']
  onError: (said: string) => void
  held: { runId: string; mergeId: string } | null
}) {
  const [reply, setReply] = useState('')
  const sent = () =>
    held
      ? api.post(`/runs/${held.runId}/held/fix`, { merge_id: held.mergeId, reply })
      : useApp.getState().send(FIX_HELD(question, reply, reason))
  return (
    <form
      className="checked-answer"
      onSubmit={e => {
        e.preventDefault()
        void sent().catch(err => onError(errorText(err)))
      }}
    >
      <label>
        {question}
        <input className="input" value={reply} onChange={e => setReply(e.target.value)} />
      </label>
      <button type="submit" className="btn btn-small" disabled={!reply.trim()}>
        Send
      </button>
    </form>
  )
}

/** S8 (decision 3): the CI lines offered under the answer - Run these approves exactly them, once a project; a change to a workflow asks again. */
function RunThese({ runId, offer }: { runId: string; offer: string }) {
  const [said, setSaid] = useState<string | null>(null)
  return (
    <span className="checked-fix">
      <button
        type="button"
        className="btn btn-small"
        onClick={() =>
          api.post(`/runs/${runId}/ci/approve`, { offer }).then(
            () => setSaid('Approved: they run after the next change.'),
            err => setSaid(errorText(err)),
          )
        }
      >
        Run these
      </button>
      {said && <span role="status">{said}</span>}
    </span>
  )
}

/** The user's stop of a running check (plan decision 17): what finished stays; its row says stopped, never passed. */
function StopCheck({ runId }: { runId: string }) {
  const [error, setError] = useState<string | null>(null)
  return (
    <span className="checked-fix">
      <button
        type="button"
        className="btn btn-small"
        onClick={() =>
          api.post(`/runs/${runId}/check/stop`).then(
            () => setError(null),
            err => setError(errorText(err)),
          )
        }
      >
        Stop this check
      </button>
      {error && <span role="alert">{error}</span>}
    </span>
  )
}
