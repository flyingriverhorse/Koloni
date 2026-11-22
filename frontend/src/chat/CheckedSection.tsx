import { useState } from 'react'
import { errorText } from '../api/client'
import type { Message } from '../api/types'
import { useApp } from '../state/store'
import { FIX_IT } from './checked'

type Row = NonNullable<Message['checked']>[number]

/** Each row's mark by its state; the rest (not run, timed out, a note) "–". */
const MARK: Partial<Record<Row['state'], string>> = { passed: '✓', failed: '✗', running: '…' }

/**
 * Under a turn's answer, once it is over: what KOLONİ checked at its end and what it did not - one line a row, from its
 * records, never the model's words. On the latest turn, where a test run failed, Fix it asks for the fix in a new message.
 */
export function CheckedSection({ message, over, latest }: { message?: Message; over: boolean; latest: boolean }) {
  const rows = message?.checked
  if (!over || !rows?.length) return null
  const failed = latest ? rows.find(row => row.kind === 'tests' && row.state === 'failed' && row.command) : undefined
  return (
    <section className="checked" aria-label="Checked" title="From KOLONİ’s records, not the model’s words">
      <span className="checked-head">Checked</span>
      <ul className="checked-rows">
        {rows.map((row, index) => (
          <li key={index} className="checked-row" data-state={row.state}>
            <span className="checked-mark" aria-hidden>
              {MARK[row.state] ?? '–'}
            </span>
            <span>{row.text}</span>
            {row.guessed && <span className="tag">guessed</span>}
          </li>
        ))}
      </ul>
      {failed?.command && <FixIt command={failed.command} />}
    </section>
  )
}

function FixIt({ command }: { command: string }) {
  const [error, setError] = useState<string | null>(null)
  return (
    <span className="checked-fix">
      <button type="button" className="btn btn-small" onClick={() => useApp.getState().send(FIX_IT(command)).then(() => setError(null), err => setError(errorText(err)))}>
        Fix it
      </button>
      {error && <span role="alert">{error}</span>}
    </span>
  )
}
