import type { ReactNode } from 'react'
import type { MemoryRecord } from '../api/types'
import { day, foundAt, moment, sourceOf, whereOf, whoWhen } from './memoryText'

/** Lines of a file as they are, under where they are. */
function Lines({ label, text }: { label: string; text: string }) {
  return (
    <figure role="group" aria-label={label} className="memory-lines">
      <figcaption className="mono muted">{label}</figcaption>
      <pre className="mono">{text}</pre>
    </figure>
  )
}

/**
 * The evidence for a record you decide on: the lines it rests on as the file has them now,
 * where the same block was found if it is no longer there, and whether the file was last
 * changed while agents were at work.
 */
export function Evidence({ record }: { record: MemoryRecord }) {
  const where = whereOf(record)
  const found = foundAt(record)
  if (!where) return null
  return (
    <div className="memory-evidence">
      {record.excerpt !== null ? (
        <Lines label={`${where} as it reads now`} text={record.excerpt} />
      ) : (
        <div className="memory-meta mono muted">{where} cannot be read now</div>
      )}
      {found && record.found_at && (
        <>
          {record.found_at.excerpt !== null && (
            <Lines label={`the lines as they were noted, found at ${found}`} text={record.found_at.excerpt} />
          )}
          <div className="memory-meta mono memory-state-moved">
            The same lines stand at {found} now. That may be a copy. Given to no agent until you have looked.
          </div>
        </>
      )}
      {record.modified_in_turn && record.source_modified && (
        <div className="memory-meta mono memory-state-changed">
          this file was last changed while agents were at work ({moment(record.source_modified)})
        </div>
      )}
    </div>
  )
}

/** What a record says and what it rests on; no more is claimed than the record holds. */
export function RecordBody({ record, evidence }: { record: MemoryRecord; evidence?: boolean }) {
  const where = whereOf(record)
  const change = record.last_change
  const about = (
    <>
      <div className="memory-text">
        {record.text} {record.about && <span className="tag">{record.about}</span>}{' '}
        {/* Noted in a turn a trigger started: nobody saw it being written. */}
        {record.unattended && <span className="tag tag-warn">written with nobody watching</span>}
      </div>
      <div className="memory-meta mono">
        {where && <span>{where}</span>}
        <span className={`memory-state memory-state-${record.source_state}`}>{sourceOf(record)}</span>
        <span className="muted">{whoWhen(record)}</span>
      </div>
      {/* (Of a fact with no file behind it - put forward from a working state - it says so on its own.) */}
      {record.checked_how && (
        <div className="memory-meta mono muted">{record.source ? `how the file was looked at: ${record.checked_how}` : record.checked_how}</div>
      )}
      {change && record.source && (
        <div className="memory-meta mono muted">
          last recorded change to {record.source.path} by an agent: {change.agent_name} · {day(change.at)}
        </div>
      )}
    </>
  )
  if (!evidence || !where) return about
  // The claim and the lines it is made on, side by side.
  return (
    <div className="memory-claim">
      <div className="memory-said">{about}</div>
      <Evidence record={record} />
    </div>
  )
}

interface Props {
  record: MemoryRecord
  /** Said above the record, e.g. how it left the memory. */
  note?: string
  /** A reason the server gave for refusing something asked of this record. */
  error?: string | null
  /** Show the lines the record rests on: for what the user decides on. */
  evidence?: boolean
  /** For a search hit to go to: the row takes the focus. */
  id?: string
  /** At the row's right end: its few buttons and ⋯. */
  actions?: ReactNode
  children?: ReactNode
}

/** One record on the Memory page, one row: what can be done about it at its end, and what it unfolds under it. */
export function RecordCard({ record, note, error, evidence, id, actions, children }: Props) {
  return (
    <article className="memory-record" id={id} tabIndex={id ? -1 : undefined}>
      {note && <div className="memory-meta mono muted">{note}</div>}
      <div className="memory-row-line">
        <div className="memory-row-body">
          <RecordBody record={record} evidence={evidence} />
        </div>
        {actions}
      </div>
      {children}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </article>
  )
}
