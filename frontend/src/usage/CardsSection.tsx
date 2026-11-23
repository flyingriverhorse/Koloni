import { useEffect, useState } from 'react'
import { errorText } from '../api/client'
import type { Cards } from '../api/types'
import { type Period, since } from './period'

interface Props {
  /** The project whose cards are shown; null: every project's. */
  projectId: string | null
  /** The page's period: the cards of it are read (`since`). */
  period: Period
  /** Reads the cards. Throws ApiError. */
  onLoad: (projectId: string | null, since: string | null) => Promise<Cards>
  /** The user's click on a suggested rule (its key alone: KOLONİ writes the line). Throws ApiError. */
  onAdd?: (projectId: string, key: string) => Promise<void>
}

/** "12 s", "3 min": the average time to answer a card. */
const waited = (seconds: number) => (seconds < 120 ? `${Math.round(seconds)} s` : `${Math.round(seconds / 60)} min`)

/** Cards measured (0.1.7): the command cards asked in the period, how they were answered, by reason; what Check what I said first did; and, for one project, a rule its approvals suggest - added only by the user's click. */
export function CardsSection({ projectId, period, onLoad, onAdd }: Props) {
  const [cards, setCards] = useState<Cards | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [read, setRead] = useState(0)

  useEffect(() => {
    let latest = true
    onLoad(projectId, since(period)).then(
      found => {
        if (!latest) return
        setCards(found)
        setError(null)
      },
      err => {
        if (!latest) return
        setCards(null)
        setError(errorText(err))
      },
    )
    return () => {
      latest = false
    }
  }, [onLoad, projectId, period, read])

  const add = async (key: string) => {
    if (!onAdd || !projectId) return
    try {
      await onAdd(projectId, key)
      setRead(n => n + 1)
    } catch (err) {
      setError(errorText(err))
    }
  }

  return (
    <section className="memory-section" aria-label="Cards">
      <div className="memory-head">
        <h3>Cards</h3>
      </div>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {cards ? <Numbers cards={cards} /> : !error && <p className="muted">Reading the cards…</p>}
      {cards?.suggestions.map(one => (
        <p key={one.key}>
          You approved <code>{one.command}</code> {one.times} times - add “{one.rule}” to this project’s rules?{' '}
          <button type="button" className="btn btn-small" disabled={!onAdd} onClick={() => void add(one.key)}>
            Add to rules
          </button>
        </p>
      ))}
      <p className="muted memory-hint">
        Counted from 0.1.7, by the reason KOLONİ asked each card for. A line in the project’s rules spares a card only at Full auto with Check what I said first on (Settings › This project › Asking and away).
      </p>
    </section>
  )
}

/** The period's numbers, by reason; "none" where no card was asked. */
function Numbers({ cards }: { cards: Cards }) {
  const { run, refuse, ask } = cards.checked
  const checked = run + refuse + ask > 0 && (
    <p>
      Check what I said first: {run} ran on a line of yours · {refuse} not run · {ask} still asked
    </p>
  )
  if (cards.asked === 0)
    return (
      <>
        <p className="muted">No command card was asked in this period.</p>
        {checked}
      </>
    )
  return (
    <>
      <p>
        {cards.asked} asked: {cards.approved} approved, {cards.rejected} rejected, {cards.unanswered} not answered
        {cards.decide_seconds !== null && ` · ${waited(cards.decide_seconds)} to answer, on average`}
      </p>
      <div className="tools-table">
      <table className="usage-table" aria-label="Cards by reason">
        <thead>
          <tr>
            <th scope="col">Why it was asked</th>
            <th scope="col">Asked</th>
            <th scope="col">Approved</th>
            <th scope="col">Rejected</th>
          </tr>
        </thead>
        <tbody>
          {cards.by_reason.map(one => (
            <tr key={one.reason}>
              <th scope="row">{one.said}</th>
              <td>{one.asked}</td>
              <td>{one.approved}</td>
              <td>{one.rejected}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {checked}
    </>
  )
}
