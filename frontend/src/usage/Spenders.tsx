import type { Project, Usage } from '../api/types'
import { measureOf, STARTERS, started } from './usageText'
import { UsageTable } from './UsageTable'

type Talk = Usage['by_conversation'][number]
const SHOWN = 3

/**
 * The chats that spent most - by their money where any is priced, else by their tokens - each opening its chat; every
 * chat in numbers folded under them, sortable.
 */
export function TopChats({
  rows,
  here,
  nameOf,
  onOpen,
}: {
  rows: Talk[]
  /** The project "This project" is: a chat of another says whose it is. */
  here: Project | null
  nameOf: (projectId: string | null) => string
  onOpen: (conversationId: string) => void
}) {
  const measure = measureOf(rows)
  const first = [...rows].sort((a, b) => (measure.value(b) ?? -1) - (measure.value(a) ?? -1)).slice(0, SHOWN)
  const title = (row: Talk) => (
    <>
      <button type="button" className="usage-open" onClick={() => onOpen(row.conversation_id)}>
        {row.title}
      </button>
      {(!here || row.project_id !== here.id) && <span className="muted"> · {nameOf(row.project_id)}</span>}
    </>
  )
  return (
    <section className="memory-section usage-side-box" aria-label="Chats that spent most">
      <h3>Chats that spent most</h3>
      <ul className="usage-list">
        {first.map(row => (
          <li key={row.conversation_id}>
            <span>{title(row)}</span>
            <span className="mono">{measure.said(row)}</span>
          </li>
        ))}
      </ul>
      <details className="usage-fold usage-more">
        <summary>{rows.length === 1 ? '1 chat, in numbers' : `All ${rows.length} chats, in numbers`}</summary>
        <UsageTable
          label="Usage by conversation"
          first="Conversation"
          cost
          rows={rows.map(row => ({
            key: row.conversation_id,
            text: row.title,
            name: title(row),
            numbers: row,
            cost: row.cost,
          }))}
        />
      </details>
    </section>
  )
}

/**
 * Who started the work - you, KOLONİ itself (its requests in no message), a trigger before 0.1.10 - each a bar of what
 * it spent, its numbers folded under. (No ☾ Away of its own: the record keeps a night's turns as yours.)
 */
export function WhoStarted({ rows }: { rows: Usage['by_start'] }) {
  const measure = measureOf(rows)
  const most = Math.max(0, ...rows.map(row => measure.value(row) ?? 0))
  return (
    <section className="memory-section usage-side-box" aria-label="Who started it">
      <h3>Who started it</h3>
      <ul className="usage-list usage-who">
        {rows.map(row => (
          <li key={row.started_by}>
            <span>{STARTERS[row.started_by]}</span>
            <span className="usage-share" aria-hidden="true">
              <i style={{ width: `${most > 0 ? ((measure.value(row) ?? 0) / most) * 100 : 0}%` }} />
            </span>
            <span className="mono">{measure.said(row)}</span>
          </li>
        ))}
      </ul>
      <p className="muted memory-hint">{rows.map(started).join(' · ')}</p>
      <details className="usage-fold usage-more">
        <summary>In numbers</summary>
        <UsageTable
          label="Usage by who sent the message"
          first="Started by"
          cost
          rows={rows.map(row => ({
            key: row.started_by,
            name: STARTERS[row.started_by],
            text: STARTERS[row.started_by],
            numbers: row,
            cost: row.cost,
            requests: row.started_by === 'koloni',
          }))}
        />
      </details>
    </section>
  )
}
