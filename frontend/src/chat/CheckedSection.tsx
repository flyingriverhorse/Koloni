import { useState } from 'react'
import { useNow } from '../agents/useNow'
import { api, errorText } from '../api/client'
import type { Message } from '../api/types'
import { useApp } from '../state/store'
import { fixOf, runClock } from './checked'

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
  const fix = latest ? fixOf(rows) : null
  const offer = rows.find(row => row.kind === 'ci_offer')?.offer
  return (
    <section className="checked" aria-label="Checked" title="From KOLONİ’s records, not the model’s words">
      <span className="checked-head">Checked</span>
      <ul className="checked-rows">
        {rows.map((row, index) => (
          <CheckedRow key={index} row={row} />
        ))}
      </ul>
      {fix && <FixIt asked={fix} />}
      {latest && message.run_id && offer && <RunThese runId={message.run_id} offer={offer} />}
      {message.run_id && rows.some(row => row.state === 'running') && <StopCheck runId={message.run_id} />}
    </section>
  )
}

function CheckedRow({ row }: { row: Row }) {
  return (
    <li className="checked-row" data-state={row.state}>
      <span className="checked-mark" aria-hidden>
        {MARK[row.state] ?? '–'}
      </span>
      <span>{row.text}</span>
      {row.state === 'running' && row.started_at && <RunningFor since={row.started_at} />}
      {row.guessed && <span className="tag">guessed</span>}
    </li>
  )
}

/** " (2:14)": how long it has run, read every second. */
export function RunningFor({ since }: { since: string }) {
  return <span className="muted"> ({runClock(since, useNow(1000))})</span>
}

function FixIt({ asked }: { asked: string }) {
  const [error, setError] = useState<string | null>(null)
  return (
    <span className="checked-fix">
      <button type="button" className="btn btn-small" onClick={() => useApp.getState().send(asked).then(() => setError(null), err => setError(errorText(err)))}>
        Fix it
      </button>
      {error && <span role="alert">{error}</span>}
    </span>
  )
}

/** S8 (decision 3): the CI lines offered under the answer - Run these approves exactly them, once a project; a change to a workflow asks again. */
function RunThese({ runId, offer }: { runId: string; offer: string }) {
  const [said, setSaid] = useState<string | null>(null)
  return (
    <span className="checked-fix">
      <button type="button" className="btn btn-small" onClick={() => api.post(`/runs/${runId}/ci/approve`, { offer }).then(() => setSaid('Approved: they run after the next change.'), err => setSaid(errorText(err)))}>
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
      <button type="button" className="btn btn-small" onClick={() => api.post(`/runs/${runId}/check/stop`).then(() => setError(null), err => setError(errorText(err)))}>
        Stop this check
      </button>
      {error && <span role="alert">{error}</span>}
    </span>
  )
}
