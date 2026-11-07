import { useState } from 'react'
import { errorText } from '../api/client'
import type { NotesOffer } from '../api/types'

/**
 * K-bilgi 6: "Add to Project notes?" under a turn - what its agents fixed and the docs/ it changed, a tick each, in their
 * words. Answered whenever you like: it never held the turn. Add sends the lines shown and those ticked - an offer a turn
 * added to meanwhile is refused and shown again - Not now none. Once answered, a line says what came of it.
 */
export function NotesOfferCard({ offer, onAnswer }: { offer: NotesOffer; onAnswer: (lines: string[], add: string[]) => Promise<void> }) {
  const [unticked, setUnticked] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  if (offer.status !== 'waiting') return <div className="muted cmd-approval-note">{offer.status === 'added' ? `Project notes: ${offer.answer}.` : 'Not added to Project notes.'}</div>
  const ticked = offer.lines.filter(line => !unticked.includes(line))
  const tick = (line: string, on: boolean) => setUnticked(was => (on ? was.filter(one => one !== line) : [...was, line]))
  const answer = (add: string[]) => {
    setBusy(true)
    setError(null)
    onAnswer(offer.lines, add)
      .catch(err => setError(errorText(err)))
      .finally(() => setBusy(false))
  }
  return (
    <div className="cmd-approval" role="group" aria-label="Add to Project notes?">
      <div className="kicker cmd-approval-kicker">Add to Project notes?</div>
      <p className="card-said">What turns found, as their agents said it - each one ticked becomes a note in this project’s knowledge:</p>
      {offer.lines.map(line => (
        <label key={line} className="choice">
          <input type="checkbox" checked={!unticked.includes(line)} disabled={busy} onChange={e => tick(line, e.target.checked)} /> {line}
        </label>
      ))}
      <div className="question-options">
        <button type="button" className="btn btn-small btn-primary" disabled={busy || ticked.length === 0} onClick={() => answer(ticked)}>
          Add
        </button>
        {/* (Not now, not Reject: it puts the offer off - another act.) */}
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => answer([])}>
          Not now
        </button>
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}
