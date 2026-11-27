import { useEffect, useMemo, useState } from 'react'
import type { DecisionLog } from '../api/types'
import { type Period, since, WHEN } from '../usage/period'
import { openDecisions, periodSentence } from './decisionLog'

/**
 * Usage: the period's decisions in one line, and Ready for you, where its Decided for you says each (karar defteri).
 * Nothing until the log is read, nor where it cannot be.
 */
export function DecidedToday({
  onLoad,
  period = 'today',
}: {
  onLoad: (since: string) => Promise<DecisionLog>
  period?: Period
}) {
  const [log, setLog] = useState<DecisionLog | null>(null)
  // (Once for a period: "7 days" back from now is another moment at each render. All of it: from the first.)
  const from = useMemo(() => since(period) ?? new Date(0).toISOString(), [period])
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
      <span>{periodSentence(log, WHEN[period])}</span>{' '}
      <button type="button" className="link-btn" onClick={() => openDecisions(unseen)}>
        Open in Ready for you
      </button>
    </p>
  )
}
