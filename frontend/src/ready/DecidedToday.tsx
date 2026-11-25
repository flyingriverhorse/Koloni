import { useEffect, useState } from 'react'
import type { DecisionLog } from '../api/types'
import { since } from '../usage/period'
import { openDecisions, todaySentence } from './decisionLog'

/**
 * Usage's Today: the day's decisions in one line, and Ready for you, where its Decided for you says each (karar defteri).
 * Nothing until the log is read, nor where it cannot be.
 */
export function DecidedToday({ onLoad }: { onLoad: (since: string) => Promise<DecisionLog> }) {
  const [log, setLog] = useState<DecisionLog | null>(null)
  const from = since('today')!
  useEffect(() => {
    let live = true
    onLoad(from).then(
      read => live && setLog(read),
      () => live && setLog(null),
    )
    return () => {
      live = false
    }
  }, [onLoad, from])
  if (!log) return null
  const unseen = log.rows.some(row => row.seen === false)
  return (
    <p className="decided-today">
      <span>{todaySentence(log)}</span>{' '}
      <button type="button" className="link-btn" onClick={() => openDecisions(unseen)}>
        Open in Ready for you
      </button>
    </p>
  )
}
